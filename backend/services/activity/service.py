"""Facade ที่ประกอบ mixin ทั้งหมดกลับเป็น ActivityService (public API เดิม)."""
from .base import BaseMixin
from .activities import ActivitiesMixin
from .participants import ParticipantsMixin
from .checkins import CheckinsMixin
from .export import ExportMixin
from .export_combined import ExportCombinedMixin


class ActivityService(
    # 🌟 วาง export_combined เป็น base ตัวแรก — มันใช้ helper ของ ExportMixin (_field_reader /
    # _format_typed_value / _translate_label) ซึ่ง resolve ผ่าน MRO ของคลาสที่ประกอบแล้ว
    ExportCombinedMixin,
    ExportMixin,
    CheckinsMixin,
    ParticipantsMixin,
    ActivitiesMixin,
    BaseMixin,
):
    pass
