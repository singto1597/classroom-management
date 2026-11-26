# 📎 ไฟล์หลักฐานการเงิน — backup / verify / purge

ชุดสคริปต์สำหรับเก็บรักษาไฟล์หลักฐาน (รูปภาพ + PDF) ที่อยู่ใน named volume
`${ENV_NAME}_media_data` (mount ที่ `/data/media` ใน backend)

## หลักการ

1. **DB ก่อน media** — `pg_dump` ถ่ายก่อน tar media เสมอ เพราะไฟล์เขียนแบบ atomic
   และแถว DB ถูก INSERT หลังไฟล์ครบ ⇒ dump ไม่มีทางอ้างไฟล์ที่ยังไม่เกิด
2. **ลบแถวก่อนไฟล์** (purge) — crash แล้วเหลือ orphan file ที่เก็บรอบถัดไปได้
   ดีกว่าเหลือแถวชี้ไฟล์ที่ไม่มี (ผู้ใช้เห็นไฟล์เสีย)
3. **default = dry-run** — ต้องใส่ `--apply` ถึงจะลบจริง
4. **ไม่แตะ DB/volume จริงตอนซ้อมกู้** — restore drill สร้าง scratch DB + /tmp

## สคริปต์

| ไฟล์ | ใช้ทำอะไร | รัน |
|---|---|---|
| `backup.sh` | pg_dump + tar media + retention + offsite | `./ops/finance-media/backup.sh` |
| `restore.sh` | ซ้อมกู้ลง scratch DB + /tmp แล้ว `verify_media.py` | `./ops/finance-media/restore.sh --dump … --media …` |
| `purge_media.sh` | ลบแถว soft-deleted เกิน 30 วัน + orphan >24 ชม. | `./ops/finance-media/purge_media.sh --apply` |
| `check_disk.sh` | เตือนดิสก์ 80/90%, backup เก่า, rclone quota | `./ops/finance-media/check_disk.sh` |

ปลายทาง backup: `~/backups/classroom/<env>/{db,media}` (ไม่ชนกับ mc-hourly / db-10min เดิม)
offsite: `rclone copy` → `gdrive:ClassroomBackup/<env>` (ไม่ sync, ไม่ลบฝั่ง remote)

## ตาราง cron ที่แนะนำ

cron ของ user (ไม่ต้อง sudo — user อยู่ในกลุ่ม `docker`):

```cron
# backup ทุกวัน 02:40 (เลี่ยงชน DB backup ราย 10 นาที)
40 2 * * * cd /home/singto1597/program_projects/classroom-management && ./ops/finance-media/backup.sh >> ~/logs/classroom-media-backup.log 2>&1
# purge ทุกวัน 05:20 (>3 ชม. หลัง backup)
20 5 * * * cd /home/singto1597/program_projects/classroom-management && ./ops/finance-media/purge_media.sh --apply >> ~/logs/classroom-media-purge.log 2>&1
# ตรวจดิสก์ทุกชั่วโมง :17
17 * * * * cd /home/singto1597/program_projects/classroom-management && ./ops/finance-media/check_disk.sh >> ~/logs/classroom-media-check.log 2>&1
```

> ⚠️ ถ้าเลือกใช้ `/etc/cron.d` (root cron) ต้องมี sudo — บันทึกไว้ใน `~/ops/TODO-sudo.md`
> ⚠️ cron มี PATH แคบ — สคริปต์ใช้ `docker`, `flock`, `find`, `tar`, `stat` จาก `/usr/bin`
>    ตรวจด้วย `which` ก่อนติดตั้ง

## ขั้นตอนตรวจสุขภาพ / ซ้อมกู้

```bash
# 1) ตรวจไฟล์ vs DB (อ่านอย่างเดียว)
docker exec <backend_cid> python scripts/verify_media.py   # หรือผ่าน restore drill

# 2) ซ้อมกู้จาก backup จริง — ไม่แตะของจริง
./ops/finance-media/restore.sh \
  --dump  ~/backups/classroom/production/db/db-production-<ts>.dump \
  --media ~/backups/classroom/production/media/media-production-<ts>.tgz

# 3) dry-run purge ดูว่าจะลบอะไร
./ops/finance-media/purge_media.sh
```

## หมายเหตุด้าน environment

`verify_media.py` / `purge_media.py` import `core.config` ⇒ container ต้องได้ env ครบ
เหมือน backend (classroom `Settings` บังคับ Discord/Google/Redis/JWT) ⇒ wrapper ใช้
`--env-file .env` + override `DATABASE_URL`/`MEDIA_STORAGE_DIR`

one-off container ใช้ `--network container:<backend_cid>` เพราะ overlay network ของ
Swarm ไม่ใช่ manually attachable (`docker run --network app-internal-...` จะได้
`PermissionDenied`)
