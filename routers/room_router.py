from fastapi import APIRouter, Depends, HTTPException, Request
import asyncpg

from models.room_schemas import RoomCreateRequest, RoomJoinRequest, RoomResponse, JoinRoomResponse
from services.room_service import RoomManagementService
from core.dependencies import get_db_pool, get_current_user

router = APIRouter()

@router.post("/create", response_model=RoomResponse, summary="สร้างห้องเรียนใหม่ (Web)")
async def create_room(
    req: RoomCreateRequest,
    pool: asyncpg.Pool = Depends(get_db_pool),
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user.get("user_id")
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
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User account required to join a room")

    result = await RoomManagementService.join_room(pool, req, user_id)
    
    return JoinRoomResponse(
        room_id=result["room_id"],
        student_id=result["student_id"],
        message=f"เข้าสู่ห้อง {result['room_name']} สำเร็จ!"
    )