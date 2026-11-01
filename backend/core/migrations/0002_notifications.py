"""0002 — แพลตฟอร์มแจ้งเตือน: in-app + Web Push + ประกาศของห้อง

บริบท:
- ก่อนหน้านี้ระบบแจ้งเตือนมีทางเดียวคือ Discord (`ActionService._publish` →
  Redis `classroom_events` → bot) ⇒ คนที่ไม่เปิด Discord ไม่เห็นอะไรเลย
- รอบนี้เพิ่ม "แจ้งเตือนในแอป" สำหรับนักเรียนทุกคนที่ล็อกอินจริง:

    notifications            แถวต่อ "ผู้รับหนึ่งคน" (fan-out ทำตอนสร้าง ไม่ใช่ตอนอ่าน)
    push_subscriptions       อุปกรณ์ที่กดยอมรับ push (1 คนมีได้หลายเครื่อง)
    push_outbox              คิวส่ง push ต่อ (แจ้งเตือน × อุปกรณ์) — transactional outbox
    notification_preferences สวิตช์เปิด/ปิดต่อ "กลุ่ม" (ไม่ใช่ต่อแถว)
    app_settings             ตั้งค่าของห้อง (quiet hours ฯลฯ) แบบ key-value
    announcements            ประกาศของห้อง (แทนที่ Discord-only เดิม)

═══════════════════════════════════════════════════════════════════════════════
🔑 สองประตูที่ต้องแยกให้ชัด
═══════════════════════════════════════════════════════════════════════════════
1. **ประตูตอนเข้าคิว (trigger นี้)** — "งานที่ไม่มีทางสำเร็จ ห้ามเข้าคิวเลย"
   ถ้าผู้ใช้ปิด push ของกลุ่มนั้น หรือไม่มีอุปกรณ์ที่ยัง active ⇒ **ไม่เขียน push_outbox**
   เหตุผล: ถ้าปล่อยเข้าคิวแล้วค่อยทิ้งตอน claim คิวจะโตตามจำนวนแจ้งเตือน × คนทั้งห้อง
   ทั้งที่รู้คำตอบได้ตั้งแต่แรก (บทเรียนจาก PiriVoice — ดู docs/skills.md)

2. **ประตูตอนส่ง (worker)** — quiet hours + สถานะอุปกรณ์ที่เปลี่ยนไปหลังเข้าคิว
   quiet hours **ห้ามเช็คที่นี่** เพราะประกาศ `urgent` ต้องทะลุ และการเลื่อนส่ง
   ไม่ได้แปลว่า "ทิ้ง" (worker เลื่อน next_attempt_at ไปถึงเวลาที่คิวเปิดแทน)

═══════════════════════════════════════════════════════════════════════════════
📣 การแจ้งเตือนสด (SSE)
═══════════════════════════════════════════════════════════════════════════════
trigger ยิง `pg_notify('classroom_notify', {"user_id","room_id","id"})` หลัง INSERT
⇒ backend ทุก replica ได้รับ (LISTEN) แล้ว fan-out ต่อ connection ที่เปิด SSE อยู่
**payload มีแค่ตัวชี้** ไม่มีข้อความ — ถ้าส่งเนื้อหาไปด้วยจะค้างใน memory ของ
pg_notify 8000 ไบต์/ข้อความ และเปิดช่องให้ข้อมูลข้ามผู้ใช้ถ้า routing ผิด
ฝั่ง client จะ fetch รายการจริงจาก API ซึ่งมีการตรวจสิทธิ์อยู่แล้ว

หมายเหตุ: ไฟล์นี้ apply แล้วห้ามแก้ (checksum ตรึง) — เปลี่ยนสคีมาในอนาคตให้เขียนไฟล์ใหม่
"""

SQL: list[str] = [
    # ── 1. notifications — หนึ่งแถว = หนึ่งผู้รับ ─────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS notifications (
        id           BIGSERIAL PRIMARY KEY,
        room_id      INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

        -- กลุ่มควบคุมสวิตช์ preference (announcement ปิดไม่ได้)
        group_type   TEXT NOT NULL,
        -- ชนิดย่อยสำหรับไอคอน/ข้อความ (task_due, finance_receipt, ...)
        type         TEXT NOT NULL,
        -- urgent ทะลุ quiet hours; high = ปักหมุดบนสุดของกระดิ่ง
        priority     TEXT NOT NULL DEFAULT 'normal',

        title        TEXT NOT NULL,
        body         TEXT NOT NULL DEFAULT '',

        -- ปลายทางเมื่อกด (entity_type/entity_id ใช้ผูกกับปุ่ม "ดูรายละเอียด")
        entity_type  TEXT,
        entity_id    TEXT,
        url          TEXT,

        read_at      TIMESTAMPTZ,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        CONSTRAINT notifications_group_type_check
            CHECK (group_type IN ('task', 'finance', 'activity', 'member', 'announcement')),
        CONSTRAINT notifications_priority_check
            CHECK (priority IN ('normal', 'high', 'urgent'))
    )
    """,
    # กระดิ่ง: นับที่ยังไม่อ่าน (partial index — แถวอ่านแล้วไม่ต้องอยู่ใน index)
    """
    CREATE INDEX IF NOT EXISTS idx_notifications_unread
        ON notifications (user_id, room_id)
        WHERE read_at IS NULL
    """,
    # รายการ: ใหม่สุดก่อน ต่อผู้ใช้
    """
    CREATE INDEX IF NOT EXISTS idx_notifications_user_created
        ON notifications (user_id, created_at DESC)
    """,
    # หน้าประกาศของห้อง (อ่านร่วมกัน ไม่ผูกผู้รับ)
    """
    CREATE INDEX IF NOT EXISTS idx_notifications_room_created
        ON notifications (room_id, created_at DESC)
    """,

    # ── 2. push_subscriptions — อุปกรณ์ที่ยอมรับ push ────────────────────────
    # endpoint เป็นกุญแจธรรมชาติของเบราว์เซอร์: อุปกรณ์เดิมสมัครซ้ำด้วยบัญชีอื่น
    # ⇒ ต้อง "ย้ายเจ้าของ" ไม่ใช่สร้างแถวใหม่ (service ใช้ ON CONFLICT (endpoint))
    """
    CREATE TABLE IF NOT EXISTS push_subscriptions (
        id              BIGSERIAL PRIMARY KEY,
        user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        endpoint        TEXT NOT NULL UNIQUE,
        p256dh          TEXT NOT NULL,
        auth            TEXT NOT NULL,
        user_agent      TEXT,

        last_success_at TIMESTAMPTZ,
        failure_count   INTEGER NOT NULL DEFAULT 0,

        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        deleted_at      TIMESTAMPTZ
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_push_subscriptions_active
        ON push_subscriptions (user_id)
        WHERE deleted_at IS NULL
    """,

    # ── 3. notification_preferences — สวิตช์ต่อกลุ่ม ─────────────────────────
    # ไม่มีแถว = เปิดทั้งคู่ (ค่าเริ่มต้นของคนที่ไม่เคยแตะตั้งค่า)
    """
    CREATE TABLE IF NOT EXISTS notification_preferences (
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        group_type TEXT NOT NULL,
        inapp      BOOLEAN NOT NULL DEFAULT TRUE,
        push       BOOLEAN NOT NULL DEFAULT TRUE,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (user_id, group_type),
        CONSTRAINT notification_preferences_group_type_check
            CHECK (group_type IN ('task', 'finance', 'activity', 'member'))
    )
    """,

    # ── 4. push_outbox — คิวส่ง push (transactional outbox) ──────────────────
    # status แยก "จะลองใหม่" (retry) ออกจาก "ทิ้งแล้ว" (dropped/stale)
    # ⇒ ตัวนับต้องไม่เอา retry ไปปนกับ dropped (บทเรียนตัวนับปิดบังบั๊ก)
    """
    CREATE TABLE IF NOT EXISTS push_outbox (
        id              BIGSERIAL PRIMARY KEY,
        notification_id BIGINT NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
        subscription_id BIGINT NOT NULL REFERENCES push_subscriptions(id) ON DELETE CASCADE,

        status          TEXT NOT NULL DEFAULT 'pending',
        attempts        INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        processing_at   TIMESTAMPTZ,
        sent_at         TIMESTAMPTZ,
        last_error      TEXT,

        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        CONSTRAINT push_outbox_status_check
            CHECK (status IN ('pending', 'sent', 'retry', 'dropped', 'stale')),
        -- หนึ่งแจ้งเตือน × หนึ่งอุปกรณ์ = หนึ่งแถว (trigger ใช้ ON CONFLICT DO NOTHING)
        CONSTRAINT push_outbox_notification_subscription_key
            UNIQUE (notification_id, subscription_id)
    )
    """,
    # worker claim: เฉพาะแถวที่ยังต้องส่ง และถึงเวลาแล้ว
    """
    CREATE INDEX IF NOT EXISTS idx_push_outbox_claimable
        ON push_outbox (next_attempt_at)
        WHERE status IN ('pending', 'retry')
    """,

    # ── 5. app_settings — ตั้งค่าของห้อง (key-value) ─────────────────────────
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        room_id    INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        key        TEXT NOT NULL,
        value      JSONB NOT NULL DEFAULT '{}'::jsonb,
        updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (room_id, key)
    )
    """,

    # ── 6. announcements — ประกาศของห้อง ────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS announcements (
        id          BIGSERIAL PRIMARY KEY,
        room_id     INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
        title       TEXT NOT NULL,
        body        TEXT NOT NULL DEFAULT '',
        priority    TEXT NOT NULL DEFAULT 'normal',
        pinned      BOOLEAN NOT NULL DEFAULT FALSE,
        archived_at TIMESTAMPTZ,
        created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        CONSTRAINT announcements_priority_check
            CHECK (priority IN ('normal', 'high', 'urgent'))
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_announcements_room_created
        ON announcements (room_id, created_at DESC)
        WHERE archived_at IS NULL
    """,

    # ── 7. trigger: NOTIFY + ใส่คิว push (ประตูตอนเข้าคิว) ───────────────────
    """
    CREATE OR REPLACE FUNCTION fn_notifications_fanout() RETURNS trigger AS $$
    BEGIN
        -- 1) บอกทุก replica ว่ามีแจ้งเตือนใหม่ของผู้ใช้คนนี้ (payload = ตัวชี้เท่านั้น)
        PERFORM pg_notify(
            'classroom_notify',
            json_build_object(
                'user_id', NEW.user_id,
                'room_id', NEW.room_id,
                'id', NEW.id
            )::text
        );

        -- 2) เข้าคิว push เฉพาะเมื่อ "มีทางสำเร็จ" ตั้งแต่ต้น
        --    - อุปกรณ์ยัง active
        --    - ผู้ใช้ไม่ได้ปิด push ของกลุ่มนั้น (announcement ปิดไม่ได้)
        INSERT INTO push_outbox (notification_id, subscription_id)
        SELECT NEW.id, s.id
        FROM push_subscriptions s
        WHERE s.user_id = NEW.user_id
          AND s.deleted_at IS NULL
          AND (
                NEW.group_type = 'announcement'
                OR NOT EXISTS (
                    SELECT 1
                    FROM notification_preferences p
                    WHERE p.user_id = NEW.user_id
                      AND p.group_type = NEW.group_type
                      AND p.push = FALSE
                )
              )
        ON CONFLICT (notification_id, subscription_id) DO NOTHING;

        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    # Postgres ไม่มี CREATE TRIGGER IF NOT EXISTS ของ 16 ⇒ DROP ก่อน (ไม่ทำลายข้อมูล)
    """
    DROP TRIGGER IF EXISTS trg_notifications_fanout ON notifications
    """,
    """
    CREATE TRIGGER trg_notifications_fanout
        AFTER INSERT ON notifications
        FOR EACH ROW
        EXECUTE FUNCTION fn_notifications_fanout()
    """,
]
