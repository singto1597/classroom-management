#!/bin/bash
# =============================================================================
# check_disk.sh — ตรวจสุขภาพดิสก์/backup/volume ของไฟล์หลักฐานการเงิน
# =============================================================================
#
# cron แนะนำ: ทุกชั่วโมง `17 * * * *` (เลี่ยง :00 ให้ไม่ชน backup)
#
# exit: 0 = ปกติ · 1 = มีสัญญาณวิกฤต (ดิสก์ ≥ CRIT หรือ backup เก่าเกิน)
# =============================================================================
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_DIR=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_DIR"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

[ -f .env ] || { log "❌ ไม่พบไฟล์ .env"; exit 1; }
set -a
# shellcheck disable=SC1091
. ./.env
set +a

BACKUP_ROOT="${BACKUP_ROOT:-$HOME/backups/classroom}"
ENV_NAME="${ENV_NAME:-}"
DISK_WARN_PCT="${DISK_WARN_PCT:-80}"
DISK_CRIT_PCT="${DISK_CRIT_PCT:-90}"
BACKUP_MAX_AGE_HOURS="${BACKUP_MAX_AGE_HOURS:-30}"

status=0

# ---------- 1) ดิสก์ ----------
USE_PCT=$(df -P / | awk 'NR==2 {gsub("%","",$5); print $5}')
log "💽 ดิสก์ / ใช้ ${USE_PCT}%"
if [ "$USE_PCT" -ge "$DISK_CRIT_PCT" ]; then
    log "🔴 วิกฤต: ดิสก์ ≥ ${DISK_CRIT_PCT}%"
    status=1
elif [ "$USE_PCT" -ge "$DISK_WARN_PCT" ]; then
    log "🟡 เตือน: ดิสก์ ≥ ${DISK_WARN_PCT}%"
fi

# ---------- 2) backup ล่าสุด ----------
if [ -n "$ENV_NAME" ]; then
    LATEST=$(find "$BACKUP_ROOT/$ENV_NAME/db" -maxdepth 1 -name '*.dump' -printf '%T@ %p\n' 2>/dev/null \
        | sort -nr | head -n1 | cut -d' ' -f2- || true)
    if [ -z "${LATEST:-}" ]; then
        log "🟡 ยังไม่พบ backup DB ของ $ENV_NAME ($BACKUP_ROOT/$ENV_NAME/db)"
    else
        AGE_H=$(( ( $(date +%s) - $(stat -c %Y "$LATEST") ) / 3600 ))
        log "🗄️ backup ล่าสุด: $(basename "$LATEST") · อายุ ${AGE_H} ชม."
        if [ "$AGE_H" -gt "$BACKUP_MAX_AGE_HOURS" ]; then
            log "🔴 backup เก่าเกิน ${BACKUP_MAX_AGE_HOURS} ชม. — ตรวจ cron"
            status=1
        fi
    fi

    # ---------- 3) media volume ----------
    MEDIA_VOL="${ENV_NAME}_media_data"
    if docker volume inspect "$MEDIA_VOL" >/dev/null 2>&1; then
        SIZE=$(docker run --rm -v "$MEDIA_VOL":/media:ro alpine:3.20 du -sh /media 2>/dev/null | cut -f1 || echo "?")
        log "📎 volume $MEDIA_VOL ขนาด $SIZE"
    else
        log "🟡 ยังไม่พบ volume $MEDIA_VOL"
    fi
fi

# ---------- 4) docker df ----------
log "🐳 docker system df:"
docker system df 2>/dev/null | sed 's/^/   /' || true

# ---------- 5) rclone quota (ถ้ามี) ----------
RCLONE_CONFIG="${RCLONE_CONFIG:-$HOME/.config/rclone/rclone.conf}"
if [ -f "$RCLONE_CONFIG" ] && [ -n "${RCLONE_REMOTE:-gdrive}" ]; then
    log "☁️ rclone quota (${RCLONE_REMOTE}):"
    docker run --rm --user "$(id -u):$(id -g)" \
        -v "$(dirname "$RCLONE_CONFIG")":/config/rclone \
        -e RCLONE_CONFIG=/config/rclone/rclone.conf -e HOME=/tmp \
        "${RCLONE_IMAGE:-rclone/rclone:1.68.1}" about "${RCLONE_REMOTE}:" 2>/dev/null \
        | sed 's/^/   /' || log "⚠️ อ่าน quota ไม่ได้"
fi

exit "$status"
