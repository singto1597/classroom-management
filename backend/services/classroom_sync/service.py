"""Facade ที่ประกอบ mixin ทั้งหมดกลับเป็น ClassroomService (public API เดิม)."""
from .room import RoomMixin
from .tasks import TasksMixin
from .schedule import ScheduleMixin


class ClassroomService(
    RoomMixin,
    TasksMixin,
    ScheduleMixin,
):
    pass
