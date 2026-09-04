"""Package routers.activity — แยก activity_router ตาม resource (activities/participants/checkins/export)."""
from fastapi import APIRouter

from .activities import router as activities_router
from .participants import router as participants_router
from .checkins import router as checkins_router
from .export import router as export_router

router = APIRouter()
router.include_router(activities_router)
router.include_router(participants_router)
router.include_router(checkins_router)
router.include_router(export_router)

__all__ = ["router"]
