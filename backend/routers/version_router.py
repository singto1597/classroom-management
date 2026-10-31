from fastapi import APIRouter, Response

from core.config import settings
from models.version_schemas import VersionResponse

router = APIRouter()


@router.get(
    "/version",
    response_model=VersionResponse,
    summary="เวอร์ชันที่รันอยู่จริง (version + git sha)",
)
async def get_version(response: Response) -> VersionResponse:
    """ตอบเวอร์ชันจากตัวแปรที่ฝังใน image — ไม่ใช่ค่าที่อ่านจากไฟล์ตอน request

    - `version` มาจาก `PROJECT_VERSION` (sync กับ `VERSION` ที่ root โดย `release.sh`)
    - `git_sha` มาจาก Docker build arg `GIT_SHA` (ส่งโดย `pull_all.sh`)
    - `Cache-Control: no-store` เพื่อไม่ให้ proxy/CDN แคชคำตอบข้าม deploy
    """
    response.headers["Cache-Control"] = "no-store"
    return VersionResponse(
        version=settings.PROJECT_VERSION,
        git_sha=settings.GIT_SHA,
        service="backend",
    )
