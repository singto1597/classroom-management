from pydantic import BaseModel, Field
from datetime import date, datetime
from typing import Optional, List, Literal
from enum import Enum

class DayOfWeek(str, Enum):
    MONDAY = "จันทร์"
    TUESDAY = "อังคาร"
    WEDNESDAY = "พุธ"
    THURSDAY = "พฤหัสบดี"
    FRIDAY = "ศุกร์"
    SATURDAY = "เสาร์"
    SUNDAY = "อาทิตย์"

class TaskStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"

class SuccessResponse(BaseModel):
    status: str = "success"
    message: Optional[str] = None

class RoomSetupRequest(BaseModel):
    server_id: int
    room_name: str = Field(..., max_length=100)
    user_name: str 

class ChannelSetRequest(BaseModel):
    channel_id: int
    user_name: str

class TimeSetRequest(BaseModel):
    notify_time: str = Field(..., pattern=r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$")
    user_name: str

class RoomNotifyResponse(BaseModel):
    server_id: int
    announcement_channel_id: int

class DefaultScheduleRequest(BaseModel):
    day_of_week: DayOfWeek
    attire: str = Field(..., max_length=100)
    subjects: str = Field(..., max_length=255)
    user_name: str

class OverrideScheduleRequest(BaseModel):
    target_date: date
    new_attire: str = Field(..., max_length=100)
    note: str = Field(..., max_length=255)
    user_name: str

class TaskCreateRequest(BaseModel):
    task_name: str = Field(..., max_length=200)
    task_detail: Optional[str] = Field(None, max_length=1000)
    due_date: date
    user_name: str

class TaskEditRequest(BaseModel):
    task_name: str = Field(..., max_length=200)
    task_detail: Optional[str] = Field(None, max_length=1000)
    due_date: date
    user_name: str

class ActionWithUserRequest(BaseModel):
    user_name: str

class TaskResponse(BaseModel):
    id: int
    task_name: str
    task_detail: Optional[str]
    due_date: date
    status: TaskStatus
    created_at: Optional[datetime]

class TaskActionResponse(BaseModel):
    status: str = "success"
    task_name: str

class DailyNoteRequest(BaseModel):
    target_date: date
    bring_items: str = Field(..., max_length=255)
    announcement: str = Field(..., max_length=500)
    user_name: str

class DailyNoteDeletedResponse(BaseModel):
    bring_items: str
    announcement: str

class TaskDueInfo(BaseModel):
    task_name: str
    days_left: int
    display_text: str 

class DailySummaryResponse(BaseModel):
    date: date
    day: str
    attire: str
    subjects: str
    bring: str
    note: str
    tasks_due: List[TaskDueInfo]