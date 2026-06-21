from fastapi import APIRouter, Depends, HTTPException, Request
import asyncpg
from typing import List

from models.room_schemas import RoomCreateRequest, RoomJoinRequest, RoomResponse, JoinRoomResponse
from services.room_service import RoomManagementService
from core.dependencies import get_db_pool, get_current_user
from core.exceptions import ForbiddenError

router = APIRouter()

@router.post("/create", response_model=RoomResponse, summary="สร้างห้องเรียนใหม่ (Web)")
async def create_room(
    req: RoomCreateRequest,
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    user_id = user_ctx.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User account required to create a room")

    result = await RoomManagementService.create_room(pool, req.room_name, user_id)
    
    return RoomResponse(
        room_id=result["room_id"],
        room_name=result["room_name"],
        room_code=result["room_code"],
        message="สร้างห้องเรียนสำเร็จ นำรหัสห้องไปแชร์ให้นักเรียนได้เลย!"
    )

@router.post("/join", response_model=JoinRoomResponse, summary="เข้าห้องเรียนด้วยรหัส (Web)")
async def join_room(
    req: RoomJoinRequest,
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    user_id = user_ctx.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User account required to join a room")

    result = await RoomManagementService.join_room(pool, req, user_id)
    return JoinRoomResponse(
        room_id=result["room_id"],
        student_id=result["student_id"],
        message=f"ส่งคำขอเข้าสู่ห้อง {result['room_name']} แล้ว กรุณารอครูผู้สอนอนุมัติ"
    )

@router.get("/{room_id}/requests", summary="ดึงรายชื่อนักเรียนที่รออนุมัติ")
async def get_pending_requests(
    room_id: int,
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        return await RoomManagementService.get_pending_requests(pool, room_id, user_ctx["user_id"])
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e)) 

@router.put("/{room_id}/requests/{student_no}/approve", summary="อนุมัตินักเรียนเข้าห้อง")
async def approve_student(
    room_id: int,
    student_no: int,
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        await RoomManagementService.approve_join_request(pool, room_id, student_no, user_ctx["user_id"])
        return {"status": "success", "message": f"อนุมัตินักเรียนเลขที่ {student_no} สำเร็จ"}
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.delete("/{room_id}/requests/{student_no}/reject", summary="ปฏิเสธนักเรียนเข้าห้อง")
async def reject_student(
    room_id: int,
    student_no: int,
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user)
):
    try:
        await RoomManagementService.reject_join_request(pool, room_id, student_no, user_ctx["user_id"])
        return {"status": "success", "message": f"ปฏิเสธนักเรียนเลขที่ {student_no} สำเร็จ"}
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))