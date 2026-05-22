from fastapi import APIRouter, Depends, HTTPException
import asyncpg

from models.maintenance_schemas import ReportIssueRequest
from core.dependencies import get_db_pool, get_current_user
from services.maintenance_service import MaintenanceService

router = APIRouter(tags=["Maintenance"])

@router.post("/report")
async def report_issue(
    req: ReportIssueRequest, 
    pool: asyncpg.Pool = Depends(get_db_pool),
    discord_id: int = Depends(get_current_user)
):
    try:
        result = await MaintenanceService.create_ticket(pool, req.model_dump())
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))