#!/bin/bash
# =============================================================================
# backup.sh — สำรอง DB (pg_dump) + ไฟล์หลักฐานการเงิน (media volume)
# =============================================================================
#
# ลำดับสำคัญ: **DB ก่อน media เสมอ**
#   ไฟล์เขียนแบบ atomic (tmp → os.replace) และแถว DB ถูก INSERT หลังไฟล์อยู่ครบ
#   ⇒ dump ที่ถ่ายก่อน tar จะไม่มีทางอ้างไฟล์ที่ "ยังไม่เกิด" ตอน tar
#   (แต่ tar ที่ถ่ายก่อน dump อาจขาดไฟล์ที่เพิ่ง commit ระหว่างนั้น)
#
# ใช้:
#   ops/finance-media/backup.sh              # ← แนะนำ: ใช้ ENV_NAME จาก .env
#   ops/finance-media/backup.sh <env_name>   # override เฉพาะกรณีจำเป็น
#
# env ที่อ่าน: ENV_NAME, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB (จาก .env)
# env ที่ปรับได้:
#   BACKUP_ROOT=$HOME/backups/classroom
#   DB_RETENTION_DAYS=30 · MEDIA_RETENTION_DAYS=30
#   RCLONE_CONFIG=$HOME/.config/rclone/rclone.conf
#   RCLONE_REMOTE=gdrive · RCLONE_DEST=ClassroomBackup
#   ALPINE_IMAGE=alpine:3.20 · RCLONE_IMAGE=rclone/rclone:1.68.1
#
# exit code:
#   0 = สำเร็จ (รวมกรณี "ยังไม่มี rclone config")
#   1 = local backup ล้ม
#   3 = local สำเร็จ แต่อัปโหลด offsite ล้ม
#
# ⚠️ ไม่สำรองไฟล์ .env (มีความลับ)
# ⚠️ offsite ใช้ `rclone copy` **ไม่ใช่ sync**
# =============================================================================
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_DIR=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_DIR"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { log "❌ $*"; exit 1; }

[ -f .env ] || die "ไม่พบไฟล์ .env ที่ $REPO_DIR"
set -a
# shellcheck disable=SC1091
. ./.env
set +a

ENV_NAME="${1:-${ENV_NAME:-}}"
[ -n "$ENV_NAME" ] || die "ต้องระบุ env เช่น: backup.sh production"
case "$ENV_NAME" in
    *[!a-z0-9_]*) die "ENV_NAME='$ENV_NAME' ไม่ถูกต้อง (ใช้ a-z 0-9 _ เท่านั้น)" ;;
esac
: "${POSTGRES_USER:?POSTGRES_USER ไม่มีใน .env}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD ไม่มีใน .env}"
: "${POSTGRES_DB:?POSTGRES_DB ไม่มีใน .env}"

BACKUP_ROOT="${BACKUP_ROOT:-$HOME/backups/classroom}"
DB_DIR="$BACKUP_ROOT/$ENV_NAME/db"
MEDIA_DIR="$BACKUP_ROOT/$ENV_NAME/media"
DB_RETENTION_DAYS="${DB_RETENTION_DAYS:-30}"
MEDIA_RETENTION_DAYS="${MEDIA_RETENTION_DAYS:-30}"
ALPINE_IMAGE="${ALPINE_IMAGE:-alpine:3.20}"
RCLONE_IMAGE="${RCLONE_IMAGE:-rclone/rclone:1.68.1}"
RCLONE_CONFIG="${RCLONE_CONFIG:-$HOME/.config/rclone/rclone.conf}"
RCLONE_REMOTE="${RCLONE_REMOTE:-gdrive}"
RCLONE_DEST="${RCLONE_DEST:-ClassroomBackup}"
RCLONE_REMOTE_PATH="${RCLONE_REMOTE_PATH:-${RCLONE_REMOTE}:${RCLONE_DEST}/${ENV_NAME}}"

TS=$(date +%Y%m%d-%H%M%S)
mkdir -p "$DB_DIR" "$MEDIA_DIR"

# กัน cron ซ้อนกัน — ถ้ารอบก่อนยังไม่จบ ให้ข้ามรอบนี้
LOCK_FILE="$BACKUP_ROOT/.backup-${ENV_NAME}.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "⚠️ backup รอบก่อนของ $ENV_NAME ยังไม่จบ — ข้ามรอบนี้"
    exit 0
fi

TMP_DUMP="$DB_DIR/.db-${ENV_NAME}-${TS}.dump.part"
TMP_MEDIA="$MEDIA_DIR/.media-${ENV_NAME}-${TS}.tgz.part"
cleanup() { rm -f "$TMP_DUMP" "$TMP_MEDIA" 2>/dev/null || true; }
trap cleanup EXIT

log "🟢 เริ่ม backup $ENV_NAME → $BACKUP_ROOT/$ENV_NAME"

# ---------- 1) Postgres container ----------
# `([.]|$)` — รับทั้ง container ของ Swarm (`x_infra_db.1.abc`) และเดี่ยว (`x_infra_db`)
DB_CID=$(docker ps -q -f "name=^${ENV_NAME}_infra_db([.]|$)" | head -n1)
[ -n "$DB_CID" ] || die "ไม่พบ container ${ENV_NAME}_infra_db ที่รันอยู่"

# ---------- 2) pg_dump ----------
log "🐘 pg_dump ${POSTGRES_DB}…"
if ! docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$DB_CID" \
        pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$TMP_DUMP"; then
    die "pg_dump ล้มเหลว"
fi
[ -s "$TMP_DUMP" ] || die "pg_dump ได้ไฟล์ว่าง"

if ! docker exec -i "$DB_CID" pg_restore --list < "$TMP_DUMP" > /dev/null 2>&1; then
    die "ตรวจ dump ด้วย pg_restore --list ไม่ผ่าน"
fi
DB_FILE="$DB_DIR/db-${ENV_NAME}-${TS}.dump"
mv "$TMP_DUMP" "$DB_FILE"
log "✅ DB: $(basename "$DB_FILE") ($(du -h "$DB_FILE" | cut -f1))"

# ---------- 3) media volume ----------
MEDIA_VOL="${ENV_NAME}_media_data"
MEDIA_FILE=""
if docker volume inspect "$MEDIA_VOL" > /dev/null 2>&1; then
    log "📎 tar volume $MEDIA_VOL…"
    if ! docker run --rm -v "$MEDIA_VOL":/media:ro "$ALPINE_IMAGE" \
            tar -C /media --exclude=./tmp -czf - . > "$TMP_MEDIA"; then
        die "tar media volume ล้มเหลว"
    fi
    MEDIA_FILE="$MEDIA_DIR/media-${ENV_NAME}-${TS}.tgz"
    mv "$TMP_MEDIA" "$MEDIA_FILE"
    # tar ผ่าน pipe อาจ "สำเร็จ" ทั้งที่สตรีมขาด — เปิดอ่านกลับหนึ่งรอบ
    if ! tar -tzf "$MEDIA_FILE" > /dev/null 2>&1; then
        die "tar media อ่านกลับไม่ได้"
    fi
    log "✅ Media: $(basename "$MEDIA_FILE") ($(du -h "$MEDIA_FILE" | cut -f1))"
else
    log "⚠️ ไม่พบ volume $MEDIA_VOL — ข้าม media (ยังไม่เคย deploy ฟีเจอร์หลักฐาน?)"
fi

# ---------- 4) retention (local) ----------
DEL_DB=$(find "$DB_DIR" -maxdepth 1 -type f -name '*.dump' -mtime +"$DB_RETENTION_DAYS" -print -delete | wc -l)
DEL_MEDIA=$(find "$MEDIA_DIR" -maxdepth 1 -type f -name '*.tgz' -mtime +"$MEDIA_RETENTION_DAYS" -print -delete | wc -l)
log "🧹 retention: ลบ dump $DEL_DB ไฟล์ (>${DB_RETENTION_DAYS}d) · media $DEL_MEDIA ไฟล์ (>${MEDIA_RETENTION_DAYS}d)"

# ---------- 5) offsite ----------
if [ ! -f "$RCLONE_CONFIG" ]; then
    log "⚠️ WARN offsite skipped — ไม่พบ $RCLONE_CONFIG (local backup สำเร็จแล้ว)"
    log "🟢 backup $ENV_NAME เสร็จสมบูรณ์ (local only)"
    exit 0
fi

log "☁️ อัปโหลด offsite → $RCLONE_REMOTE_PATH"
RCLONE_DIR=$(dirname "$RCLONE_CONFIG")
RCLONE_RUN=(docker run --rm
    --user "$(id -u):$(id -g)"
    -v "$RCLONE_DIR":/config/rclone
    -v "$BACKUP_ROOT":/backups:ro
    -e RCLONE_CONFIG=/config/rclone/rclone.conf
    -e HOME=/tmp
    "$RCLONE_IMAGE")

OFFSITE_OK=1
if ! "${RCLONE_RUN[@]}" copy /backups/"$ENV_NAME"/db "$RCLONE_REMOTE_PATH/db" --stats-one-line --stats 0; then
    OFFSITE_OK=0
fi
if [ -d "$MEDIA_DIR" ] && ! "${RCLONE_RUN[@]}" copy /backups/"$ENV_NAME"/media "$RCLONE_REMOTE_PATH/media" --stats-one-line --stats 0; then
    OFFSITE_OK=0
fi

if [ "$OFFSITE_OK" -ne 1 ]; then
    log "❌ offsite upload ล้ม (local backup ยังอยู่ครบ) — ตรวจ rclone config/เน็ต/quota"
    exit 3
fi

log "🟢 backup $ENV_NAME เสร็จสมบูรณ์ (local + offsite)"
