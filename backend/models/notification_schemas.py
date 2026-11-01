from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# กลุ่มแจ้งเตือน — ต้องตรงกับ CHECK ของตาราง notifications / notification_preferences
# ⚠️ `announcement` ไม่อยู่ในชุดที่ผู้ใช้ปรับได้ (ประกาศของห้องปิดไม่ได้)
NotificationGroup = Literal["task", "finance", "activity", "member", "announcement"]
MutableNotificationGroup = Literal["task", "finance", "activity", "member"]
NotificationPriority = Literal["normal", "high", "urgent"]


class NotificationItem(BaseModel):
    id: int
    group_type: NotificationGroup
    type: str
    priority: NotificationPriority
    title: str
    body: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    url: Optional[str] = None
    read_at: Optional[datetime] = None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationItem]
    # จำนวนที่ยังไม่อ่าน "ของห้องนี้" — ให้กระดิ่งใช้ตัวเลขเดียวกับที่หน้ารายการแสดง
    unread_count: int
    # ยังมีหน้าเก่ากว่านี้ให้โหลดต่อหรือไม่ (pagination แบบ cursor ด้วย id)
    has_more: bool


class UnreadCountResponse(BaseModel):
    unread_count: int


class MarkReadResponse(BaseModel):
    notification_id: int
    # False = แถวนี้ไม่ใช่ของผู้ขอ (หรือไม่มีอยู่) ⇒ ไม่บอกใบ้ว่ามีแจ้งเตือนคนอื่นไหม
    marked: bool


class MarkAllReadResponse(BaseModel):
    marked_count: int


class PreferenceItem(BaseModel):
    group_type: MutableNotificationGroup
    inapp: bool
    push: bool


class PreferenceUpdate(BaseModel):
    group_type: MutableNotificationGroup
    inapp: bool
    push: bool


class PreferenceListResponse(BaseModel):
    items: list[PreferenceItem] = Field(default_factory=list)


# ── Web Push ────────────────────────────────────────────────────────────────
class PushSubscriptionKeys(BaseModel):
    """คีย์ของอุปกรณ์ (ได้จาก `PushSubscription.toJSON().keys` ในเบราว์เซอร์)"""

    p256dh: str = Field(..., min_length=16, max_length=255)
    auth: str = Field(..., min_length=8, max_length=255)


class PushSubscribeRequest(BaseModel):
    # endpoint เป็น URL เต็มที่ผู้ให้บริการ push ออกให้ — ยาวได้หลายร้อยตัวอักษร
    endpoint: str = Field(..., min_length=10, max_length=2048, pattern=r"^https://")
    keys: PushSubscriptionKeys


class PushUnsubscribeRequest(BaseModel):
    endpoint: str = Field(..., min_length=10, max_length=2048)


class PushConfigResponse(BaseModel):
    """ข้อมูลที่หน้าเว็บต้องใช้ตัดสินใจว่าจะแสดงปุ่ม "เปิดการแจ้งเตือน" ไหม"""

    # ค่าว่าง = ผู้ดูแลยังไม่ได้ตั้งคีย์ ⇒ ซ่อนปุ่มแทนที่จะให้ผู้ใช้กดแล้วล้ม
    public_key: str
    enabled: bool


class PushSubscriptionResponse(BaseModel):
    subscription_id: int
    endpoint: str


class PushUnsubscribeResponse(BaseModel):
    removed: bool


# ── [P6.5] สถิติการส่ง push ───────────────────────────────────────────────────
class PushQueueStats(BaseModel):
    """สถานะคิว **ของห้องนี้** ณ ตอนที่ถาม — อ่านจาก DB โดยตรง

    🔑 แยก "จะลองใหม่" ออกจาก "ยอมแพ้" ตามกฎเหล็กข้อ 5 ของแผน:
    `retry` ยังมีโอกาสสำเร็จ · `dropped`/`stale` คือหมดหวังแล้ว (อุปกรณ์ถูกลบ
    หรือครบจำนวนครั้ง) ⇒ สองกลุ่มนี้ไม่ควรถูกรวมเป็นตัวเลขเดียว
    """

    pending: int = Field(..., description="รอส่ง (ยังไม่ถึงเวลาส่ง)")
    retry: int = Field(..., description="จะลองใหม่ — ยังไม่ยอมแพ้")
    dropped: int = Field(..., description="ยอมแพ้แล้ว — ครบจำนวนครั้งที่ลอง")
    stale: int = Field(..., description="ยอมแพ้แล้ว — อุปกรณ์ถูกลบ/ไม่ถูกต้อง")
    sent_24h: int = Field(..., description="ส่งสำเร็จในช่วง 24 ชม. ล่าสุด (จำกัดช่วงเพื่อให้ตัวเลขไม่โตตลอดกาล)")
    due_now: int = Field(..., description="ถึงกำหนดส่งแล้วแต่ยังไม่ได้ส่ง (pending+retry ที่ next_attempt_at <= NOW())")
    oldest_due_seconds: int = Field(..., description="แถวที่ถึงกำหนดแล้วรอนานที่สุดกี่วินาที (0 = ไม่มีของค้าง)")


class PushLastRoundStats(BaseModel):
    """ผลของรอบล่าสุดของ worker — **ทั้งระบบ ไม่ใช่เฉพาะห้องนี้** (worker ตัวเดียวส่งให้ทุกห้อง)

    `deferred` (เลื่อนเพราะช่วงงดรบกวน) อยู่ในนี้เท่านั้น: มันไม่ใช่สถานะใน DB
    เพราะแถวยังเป็น `pending`/`retry` แค่ถูกเลื่อนเวลา ⇒ ดูจาก DB แยกไม่ได้
    """

    at: datetime
    claimed: int
    sent: int
    retry: int
    gone: int
    dropped: int
    deferred: int
    stale: int
    enabled: bool = Field(..., description="ตอนนั้น worker เปิดส่งอยู่ไหม (false = ยังไม่ได้ตั้ง VAPID)")


class PushDeliveryStatsResponse(BaseModel):
    room_id: int
    queue: PushQueueStats
    # null = ไม่รู้ (worker ยังไม่เคยรัน หรือ key หมดอายุ/Redis ต่อไม่ได้) — ต่างจาก "0"
    last_round: Optional[PushLastRoundStats] = None
    worker_heartbeat_age_seconds: Optional[int] = Field(
        None, description="worker ติดต่อครั้งล่าสุดกี่วินาทีที่แล้ว — null = ไม่รู้"
    )
    generated_at: datetime
