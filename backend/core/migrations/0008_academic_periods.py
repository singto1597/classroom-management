"""ปีการศึกษา + เทอม สำหรับ **กรองสถิติ** เท่านั้น (P5)

═══════════════════════════════════════════════════════════════════════════════
🎯 ขอบเขตที่ตั้งใจให้แคบ
═══════════════════════════════════════════════════════════════════════════════
รอบนี้ทำแค่ "หน้าต่างเวลา" ที่ผู้ใช้เลือกกรองรายงานได้:
  · `academic_years` — ปีการศึกษาของแต่ละห้อง (ปี พ.ศ.)
  · `academic_terms` — เทอมภายใต้ปี (ภาคเรียน ๑/๒ ฯลฯ)

**ไม่แตะตาราง `students` เลย** — ไม่มี `academic_year_id` ไม่มี rollover
ไม่มี `rollover_runs`/`student_moves` ⇒ การตั้งปีใหม่ไม่ย้ายใครไปไหน
ตัวเลข "ของปีนี้" จึงมาจาก *วันที่ของเหตุการณ์* (ใบเสร็จ/วันที่จัดกิจกรรม)
ไม่ใช่จาก "แถวสมาชิกที่ผูกกับปี"

⚠️ ห้ามเพิ่ม unique index ที่ผูกปีกับ `students` ในอนาคตถ้ายังไม่ทำ rollover จริง
   (จะทำให้ทุก query ที่คาดว่า `students` ไม่มีมิติปีพังแบบเงียบ ๆ)

═══════════════════════════════════════════════════════════════════════════════
🏠 ทำไมผูกกับ `room_id` ไม่ใช่ทั้งระบบ
═══════════════════════════════════════════════════════════════════════════════
แผนเดิมเขียน `year_be INT UNIQUE` (ระดับระบบ) แต่ระบบนี้ **หนึ่งบัญชีอยู่ได้หลายห้อง**
และสิทธิ์ `MANAGE_CLASSROOM_SETTINGS` เป็นสิทธิ์ *ของห้อง* ⇒ ถ้าปีเป็นของทั้งระบบ
ผู้ดูแลห้อง A ตั้งปีปัจจุบันแล้วเปลี่ยนปฏิทินของห้อง B ด้วย
⇒ จึงทำ `UNIQUE (room_id, year_be)` และ "ปีปัจจุบัน" มีได้ห้องละหนึ่งปี

═══════════════════════════════════════════════════════════════════════════════
🔒 partial unique index = เพดาน "ปัจจุบันได้คนเดียว" ที่ DB บังคับ
═══════════════════════════════════════════════════════════════════════════════
`uq_academic_years_current` มี `WHERE is_current AND deleted_at IS NULL`
⇒ มีปีปัจจุบันได้ห้องละหนึ่งปี แม้ service พลาด (สองคำขอพร้อมกัน)
การตั้งปีใหม่จึงต้อง **ล้างตัวเก่าก่อนในทรานแซกชันเดียวกัน**
(ถ้า UPDATE ตรง ๆ จะชน unique violation = 500 แทนข้อความที่อ่านรู้เรื่อง)

เทอม: `uq_academic_terms_current` ผูกกับ `academic_year_id` ⇒ หนึ่งเทอมปัจจุบัน
ต่อหนึ่งปี (ไม่ใช่ทั้งระบบ) เพราะปีเก่ามีเทอมของมันเอง และการเปิดดูย้อนหลัง
ไม่ควรถูกปีใหม่แย่งธง "ปัจจุบัน"

═══════════════════════════════════════════════════════════════════════════════
🗑️ ลบ = soft delete เสมอ
═══════════════════════════════════════════════════════════════════════════════
`deleted_at IS NULL` อยู่ในทุก partial index ⇒ ลบปีแล้วชื่อซ้ำกับปีใหม่ได้
และสถิติที่เคยกรองด้วยปีที่ถูกลบยังอ่านย้อนไม่ได้ (ถูกกรองออก) — ตั้งใจให้เป็นแบบนั้น
เพราะการกู้คืนคือการ "ยกเลิก soft delete" ซึ่งไม่มีในรอบนี้
"""

SQL: list[str] = [
    # ── 1. ปีการศึกษา ─────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS academic_years (
        id         SERIAL PRIMARY KEY,
        room_id    INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        year_be    INTEGER NOT NULL,
        name       TEXT,
        start_date DATE NOT NULL,
        end_date   DATE NOT NULL,
        is_current BOOLEAN NOT NULL DEFAULT FALSE,
        deleted_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    # ปี พ.ศ. เดียวกันซ้ำในห้องเดียวไม่ได้ (หลังลบแล้วสร้างใหม่ได้)
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_academic_years_room_year
        ON academic_years (room_id, year_be)
        WHERE deleted_at IS NULL
    """,
    # 🔒 ปีปัจจุบันได้ห้องละหนึ่งปี
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_academic_years_current
        ON academic_years (room_id)
        WHERE is_current AND deleted_at IS NULL
    """,
    # ── 2. เทอม ───────────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS academic_terms (
        id               SERIAL PRIMARY KEY,
        academic_year_id INTEGER NOT NULL REFERENCES academic_years(id) ON DELETE CASCADE,
        name             TEXT NOT NULL,
        start_date       DATE NOT NULL,
        end_date         DATE NOT NULL,
        is_current       BOOLEAN NOT NULL DEFAULT FALSE,
        deleted_at       TIMESTAMPTZ,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    # ชื่อเทอมซ้ำในปีเดียวไม่ได้ แต่สองปีมี "เทอม 1" ทั้งคู่ได้
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_academic_terms_year_name
        ON academic_terms (academic_year_id, name)
        WHERE deleted_at IS NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_academic_terms_current
        ON academic_terms (academic_year_id)
        WHERE is_current AND deleted_at IS NULL
    """,
    # อ่านรายการของห้องเรียงตามปี — ใช้บ่อยที่สุด
    """
    CREATE INDEX IF NOT EXISTS idx_academic_years_room
        ON academic_years (room_id, year_be DESC)
        WHERE deleted_at IS NULL
    """,
]
