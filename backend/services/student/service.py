"""Facade ที่ประกอบ mixin ทั้งหมดกลับเป็น StudentService (public API เดิม)."""
from .base import BaseMixin
from .students import StudentsMixin
from .export import ExportMixin


class StudentService(
    ExportMixin,
    StudentsMixin,
    BaseMixin,
):
    pass
