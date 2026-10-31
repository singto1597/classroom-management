from pydantic import BaseModel, Field


class VersionResponse(BaseModel):
    """ข้อมูลเวอร์ชันที่ service รันอยู่จริง — ใช้ตรวจ provenance หลัง deploy"""

    version: str = Field(..., description="SemVer จาก VERSION / PROJECT_VERSION")
    git_sha: str = Field(..., description="Commit hash ที่ build image นี้ (หรือ unknown)")
    service: str = Field(default="backend", description="ชื่อ service ที่ตอบ")
