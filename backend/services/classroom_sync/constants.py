"""ค่าคงที่ + logger ของ classroom service (เวลาไทย)."""
from zoneinfo import ZoneInfo

from core.logger import AuditLogger

THAI_TZ = ZoneInfo("Asia/Bangkok")

service_logger = AuditLogger(service_name="CLASSROOM")
