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

class PaymentNotFoundError(Exception):
    """Raised when a payment record is not found."""
    pass

class TransactionNotFoundError(Exception):
    """Raised when a finance transaction is not found."""
    pass
