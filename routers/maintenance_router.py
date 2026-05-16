from fastapi import APIRouter, Depends, HTTPException
import asyncpg

from models.maintenance_schemas import ReportIssueRequest
from core.dependencies import get_db_pool, verify_api_key
from services.maintenance_service import MaintenanceService

router = APIRouter(tags=["Maintenance"], dependencies=[Depends(verify_api_key)])

@router.post("/report")
async def report_issue(req: ReportIssueRequest, pool: asyncpg.Pool = Depends(get_db_pool)):
    try:
        result = await MaintenanceService.create_ticket(pool, req.model_dump())
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))