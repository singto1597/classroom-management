from fastapi import APIRouter, Depends, HTTPException, Request
import asyncpg
from typing import List

from models.room_schemas import RoomCreateRequest, RoomJoinRequest, RoomResponse, JoinRoomResponse, PendingRequestResponse
from models.student_schemas import SuccessResponse, InviteResponse
from services.room_service import RoomManagementService
from core.dependencies import get_db_pool, get_current_user
from core.exceptions import ForbiddenError
from routers._common import get_audit_context

router = APIRouter()

@router.post("/create", response_model=RoomResponse, summary="สร้างห้องเรียนใหม่ (Web)")
async def create_room(
    req: RoomCreateRequest,
    request: Request,
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    client_source, actor = get_audit_context(request, user_ctx)
    user_id = user_ctx.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User account required to create a room")

    result = await RoomManagementService.create_room(
        pool, 
        req.room_name, 
        user_id, 
        client_source=client_source, 
        actor_identifier=actor
    )
    
    return RoomResponse(
        room_id=result["room_id"],
        room_name=result["room_name"],
        room_code=result["room_code"],
        message="สร้างห้องเรียนสำเร็จ นำรหัสห้องไปแชร์ให้นักเรียนได้เลย!"
    )

@router.post("/join", response_model=JoinRoomResponse, summary="เข้าห้องเรียนด้วยรหัส (Web)")
async def join_room(
    req: RoomJoinRequest,
    request: Request,
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    client_source, actor = get_audit_context(request, user_ctx)
    user_id = user_ctx.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User account required to join a room")

    try:
        result = await RoomManagementService.join_room(
            pool, 
            req, 
            user_id,
            client_source=client_source,
            actor_identifier=actor
        )
        return JoinRoomResponse(
            room_id=result["room_id"],
            student_id=result.get("student_id", 0),
            message=result.get("message", "ส่งคำขอเข้าสู่ห้องแล้ว กรุณารอครูผู้สอนอนุมัติ")
        )
    except HTTPException as e:
        raise e

# 🛡️ Consent Model: คำเชิญเข้าร่วมห้องของฉัน (แอดมินแอดชื่อฉันให้) — ฉันต้องกดรับเอง
# ⚠️ ต้องอยู่ใน room_router (mount อันแรกใน main.py) กันชนกับ `GET /{target_id}` ของ classroom_sync_router
@router.get("/invites", response_model=List[InviteResponse], summary="ดึงคำเชิญเข้าร่วมห้องของฉัน (ต้องกดรับก่อน)")
async def get_my_invites(
    request: Request,
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    client_source, actor = get_audit_context(request, user_ctx)
    return await RoomManagementService.list_my_invites(
        pool,
        user_ctx["user_id"],
        client_source=client_source,
        actor_identifier=actor
    )

@router.post("/invites/{invite_id}/accept", response_model=SuccessResponse, summary="รับคำเชิญเข้าร่วมห้อง")
async def accept_invite(
    invite_id: int,
    request: Request,
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        result = await RoomManagementService.accept_invite(
            pool,
            invite_id,
            user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor
        )
        return SuccessResponse(message=result.get("message", "รับคำเชิญแล้ว"))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/{room_id}/requests", response_model=List[PendingRequestResponse], summary="ดึงรายชื่อนักเรียนที่รออนุมัติ")
async def get_pending_requests(
    room_id: int,
    request: Request,
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        return await RoomManagementService.get_pending_requests(
            pool,
            room_id,
            user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor
        )
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.put("/{room_id}/requests/{student_no}/approve", summary="อนุมัตินักเรียนเข้าห้อง")
async def approve_student(
    room_id: int,
    student_no: int,
    request: Request,
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        await RoomManagementService.approve_join_request(
            pool, 
            room_id, 
            student_no, 
            user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor
        )
        return {"status": "success", "message": f"อนุมัตินักเรียนเลขที่ {student_no} สำเร็จ"}
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.delete("/{room_id}/requests/{student_no}/reject", summary="ปฏิเสธนักเรียนเข้าห้อง")
async def reject_student(
    room_id: int,
    student_no: int,
    request: Request,
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        client_source, actor = get_audit_context(request, user_ctx)
        await RoomManagementService.reject_join_request(
            pool, 
            room_id, 
            student_no, 
            user_ctx["user_id"],
            client_source=client_source,
            actor_identifier=actor
        )
        return {"status": "success", "message": f"ปฏิเสธนักเรียนเลขที่ {student_no} สำเร็จ"}
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))