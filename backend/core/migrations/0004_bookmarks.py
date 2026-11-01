"""0004 — บุ๊กมาร์ก "บันทึกไว้" (P3.4)

บริบท:
- ประกาศ/กิจกรรมที่ต้องกลับมาอ่านซ้ำ (กำหนดส่งงาน, ประกาศนโยบาย, กิจกรรมที่สนใจ)
  ไม่มีที่เก็บ — ผู้ใช้ต้องจำหน้าหรือค้นใหม่ทุกครั้ง
- เก็บที่ `(user_id, room_id, entity_type, entity_id)` ⇒ บุ๊กมาร์กเป็น **ของคน**
  ไม่ใช่ของห้อง (ต่างจาก `rooms.muted_channel_ids` ใน 0003 ที่เป็นของห้อง)

═══════════════════════════════════════════════════════════════════════════════
🔑 ทำไม unique index เป็น partial + soft delete
═══════════════════════════════════════════════════════════════════════════════
ลบ = `deleted_at = NOW()` (soft delete ตามกฎ backend) และ index unique ครอบเฉพาะ
แถวที่ `deleted_at IS NULL` ⇒ กดบันทึกซ้ำหลังลบได้โดยไม่ชน unique
⚠️ บทเรียนจาก PiriVoice: partial index กรองแค่ `WHERE` — service ต้องกดซ้ำแล้ว
"คืนชีพ" แถวเดิม (UPDATE deleted_at = NULL) ไม่ใช่ INSERT แถวใหม่ที่ค้างเป็นขยะ

entity_type ที่รองรับกำหนดด้วย CHECK — เพิ่มชนิดใหม่ในอนาคต = เขียน migration ใหม่
(ไฟล์นี้ checksum ตรึงแล้ว แก้ไม่ได้)
"""

SQL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS bookmarks (
        id          BIGSERIAL PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        room_id     INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        entity_type TEXT NOT NULL,
        entity_id   BIGINT NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        deleted_at  TIMESTAMPTZ,

        CONSTRAINT bookmarks_entity_type_check
            CHECK (entity_type IN ('announcement', 'activity'))
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_bookmarks_live
        ON bookmarks (user_id, room_id, entity_type, entity_id)
        WHERE deleted_at IS NULL
    """,
    # หน้ารายการเรียงใหม่สุดก่อนและแบ่งหน้าด้วย (created_at, id) — index ต้องตรงกับ ORDER BY
    """
    CREATE INDEX IF NOT EXISTS idx_bookmarks_user_room_created
        ON bookmarks (user_id, room_id, created_at DESC, id DESC)
        WHERE deleted_at IS NULL
    """,
]
