"""Facade ที่ประกอบ mixin ทั้งหมดกลับเป็น ActivityService (public API เดิม)."""
from .base import BaseMixin
from .activities import ActivitiesMixin
from .participants import ParticipantsMixin
from .checkins import CheckinsMixin
from .export import ExportMixin


class ActivityService(
    ExportMixin,
    CheckinsMixin,
    ParticipantsMixin,
    ActivitiesMixin,
    BaseMixin,
):
    pass
