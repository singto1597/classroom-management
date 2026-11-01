class RoomNotFoundError(Exception):
    """Raised when a room is not found."""
    pass

class StudentNotFoundError(Exception):
    """Raised when a student is not found."""
    pass

class ForbiddenError(Exception):
    """Raised when a user does not have permission."""
    pass

class ValidationError(Exception):
    """Raised when data validation fails."""
    pass

class TaskNotFoundError(Exception):
    """Raised when a task is not found."""
    pass

class ActivityNotFoundError(Exception):
    """Raised when an activity is not found."""
    pass

class ParticipantNotFoundError(Exception):
    """Raised when an activity participant is not found."""
    pass

class CheckinSheetNotFoundError(Exception):
    """Raised when an activity check-in sheet is not found."""
    pass

class PaymentNotFoundError(Exception):
    """Raised when a payment record is not found."""
    pass

class TransactionNotFoundError(Exception):
    """Raised when a finance transaction is not found."""
    pass

class AnnouncementNotFoundError(Exception):
    """Raised when an announcement is not found."""
    pass

class BookmarkNotFoundError(Exception):
    """Raised when a bookmark is not found (or belongs to someone else)."""
    pass

class AcademicPeriodNotFoundError(Exception):
    """ไม่พบปีการศึกษา/เทอมที่ขอ *ในห้องนี้* (หรือถูกลบไปแล้ว)

    แยกจาก `ForbiddenError` โดยเจตนา: "ไม่มีของ" ต้องได้ 404 ให้หน้าจอแสดง
    "ช่วงเวลานี้ถูกลบแล้ว" ได้ ส่วน "ไม่ใช่สมาชิก" ต้องได้ 403
    """
    pass
