"""Facade ที่ประกอบ mixin ทั้งหมดกลับเป็น ActivityService (public API เดิม)."""
from .base import BaseMixin
from .activities import ActivitiesMixin
from .capacity import CapacityMixin
from .participants import ParticipantsMixin
from .checkins import CheckinsMixin
from .qr import QrCheckinMixin
from .share import ShareMixin
from .export import ExportMixin
from .export_combined import ExportCombinedMixin


class ActivityService(
    # 🌟 วาง export_combined เป็น base ตัวแรก — มันใช้ helper ของ ExportMixin (_field_reader /
    # _format_typed_value / _translate_label) ซึ่ง resolve ผ่าน MRO ของคลาสที่ประกอบแล้ว
    ExportCombinedMixin,
    ExportMixin,
    # 🎟️ P4.2 — ใช้ helper ของ CapacityMixin (_lock_activity_capacity / _capacity_counts) ผ่าน `cls.`
    QrCheckinMixin,
    # 🔗 P4.3 — ลิงก์แชร์ (ใช้ _resolve_room_id ของ BaseMixin)
    ShareMixin,
    CheckinsMixin,
    # 🪑 P4.1 — วางก่อน ParticipantsMixin/ActivitiesMixin: ทั้งสองเรียกใช้ helper ผ่าน `cls.`
    CapacityMixin,
    ParticipantsMixin,
    ActivitiesMixin,
    BaseMixin,
):
    pass
