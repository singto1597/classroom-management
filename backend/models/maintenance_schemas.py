from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class ReportIssueRequest(BaseModel):
    building: str = Field(..., max_length=100)
    room: str = Field(..., max_length=100)
    category: str = Field(..., description="electrical, it, furniture, general")
    description: str = Field(..., max_length=1000)
    image_url: Optional[str] = None
    reporter_name: str

class TicketResponse(BaseModel):
    id: str
    building: str
    room: str
    category: str
    description: str
    priority: str
    status: str
    created_at: datetime