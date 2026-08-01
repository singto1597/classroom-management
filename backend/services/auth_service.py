import httpx
import time
from datetime import datetime, timedelta, timezone
from jose import jwt
from fastapi import HTTPException, status
from pydantic import ValidationError
from core.config import settings
import asyncpg
from typing import Optional
from models.auth_schemas import OAuthProfilePayload, UserLoginResult, UserProfileUpdate
from core.exceptions import ForbiddenError
from core.logger import AuditLogger

service_logger = AuditLogger(service_name="AUTH")

DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

async def exchange_code_for_token(code: str) -> str:
    data = {
        "client_id": settings.DISCORD_CLIENT_ID,
        "client_secret": settings.DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.DISCORD_REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    async with httpx.AsyncClient() as client:
        response = await client.post(DISCORD_TOKEN_URL, data=data, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Discord token exchange failed")
        return response.json()["access_token"]

async def exchange_google_code_for_token(code: str) -> str:
    data = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(GOOGLE_TOKEN_URL, data=data)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Google token exchange failed")
        return response.json()["access_token"]

async def get_discord_user_profile(access_token: str) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(DISCORD_USER_URL, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch Discord user")
        return response.json()

async def get_google_user_info(access_token: str) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(GOOGLE_USERINFO_URL, headers=headers)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch Google user")
        return response.json()

async def process_user_login(
    pool: asyncpg.Pool, 
    payload: OAuthProfilePayload,
    client_source: str,
    actor_identifier: str
) -> UserLoginResult:
    start_time = time.time()
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                existing_by_provider = await conn.fetchrow(
                    "SELECT * FROM users WHERE (discord_id = $1 AND $1 IS NOT NULL) OR (google_id = $2 AND $2 IS NOT NULL) LIMIT 1",
                    payload.discord_id, payload.google_id
                )
                
                existing_by_email = await conn.fetchrow(
                    "SELECT * FROM users WHERE email = $1", payload.email
                )

                old_values = {}
                if existing_by_provider:
                    old_values["existing_by_provider"] = dict(existing_by_provider)
                if existing_by_email:
                    old_values["existing_by_email"] = dict(existing_by_email)

                master_id = None

                if existing_by_provider and existing_by_email and existing_by_provider['id'] != existing_by_email['id']:
                    id_to_keep = existing_by_provider['id']
                    id_to_delete = existing_by_email['id']
                    row_to_delete = existing_by_email
                    
                    # รวมข้อมูลห้อง
                    old_students = await conn.fetch("SELECT id FROM students WHERE user_id = $1", id_to_delete)
                    for ost in old_students:
                        try:
                            await conn.execute("UPDATE students SET user_id = $1 WHERE id = $2", id_to_keep, ost['id'])
                        except asyncpg.exceptions.UniqueViolationError:
                            await conn.execute("DELETE FROM students WHERE id = $1", ost['id'])
                    
                    await conn.execute("UPDATE users SET email = NULL, google_id = NULL, discord_id = NULL WHERE id = $1", id_to_delete)
                    await conn.execute("""
                        UPDATE users SET 
                            email = COALESCE($1, email, $2),
                            google_id = COALESCE($3, google_id, $4),
                            discord_id = COALESCE($5, discord_id, $6)
                        WHERE id = $7
                    """, payload.email, row_to_delete['email'], payload.google_id, row_to_delete['google_id'], payload.discord_id, row_to_delete['discord_id'], id_to_keep)
                    
                    await conn.execute("DELETE FROM users WHERE id = $1", id_to_delete)
                    master_id = id_to_keep
                else:
                    master_id = existing_by_provider['id'] if existing_by_provider else (existing_by_email['id'] if existing_by_email else None)
                    
                    if master_id:
                        await conn.execute("""
                            UPDATE users SET 
                                email = COALESCE($1, email), google_id = COALESCE($2, google_id), discord_id = COALESCE($3, discord_id), updated_at = CURRENT_TIMESTAMP
                            WHERE id = $4
                        """, payload.email, payload.google_id, payload.discord_id, master_id)
                    else:
                        master_id = await conn.fetchval("""
                            INSERT INTO users (email, google_id, discord_id, first_name, last_name, username)
                            VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
                        """, payload.email, payload.google_id, payload.discord_id, payload.first_name, payload.last_name, payload.username)

                final_user = await conn.fetchrow("SELECT id, discord_id FROM users WHERE id = $1", master_id)
                result = UserLoginResult(user_id=final_user["id"], discord_id=final_user["discord_id"])
                
                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn,
                    action="PROCESS_USER_LOGIN",
                    actor_identifier=actor_identifier,
                    client_source=client_source,
                    user_id=master_id,
                    entity_type="USER",
                    entity_id=str(master_id),
                    status="success",
                    old_values=old_values if old_values else None,
                    new_values=payload.dict() if hasattr(payload, 'dict') else dict(payload),
                    endpoint_or_command="process_user_login",
                    execution_time_ms=exec_time
                )
                
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as err_conn:
                await service_logger.log(
                    conn=err_conn,
                    action="PROCESS_USER_LOGIN",
                    actor_identifier=actor_identifier,
                    client_source=client_source,
                    entity_type="USER",
                    status="failed",
                    error_detail=str(e),
                    endpoint_or_command="process_user_login",
                    execution_time_ms=exec_time
                )
            raise e

# 🌟 IDENTITY ENGINE: ระบบรวมร่างบัญชีผ่านหน้าเว็บ
async def link_oauth_account(
    pool: asyncpg.Pool, 
    current_user_id: int, 
    provider: str, 
    profile: dict,
    client_source: str,
    actor_identifier: str
) -> dict:
    start_time = time.time()
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                if provider not in ("google", "discord"):
                    raise ValidationError.from_exception_data(
                        "link_oauth_account",
                        [
                            {
                                "loc": ("provider",),
                                "msg": "provider must be 'google' or 'discord'",
                                "type": "value_error",
                            }
                        ],
                    )

                provider_id_col = f"{provider}_id"
                provider_id_val = str(profile.get('sub')) if provider == 'google' else int(profile['id'])
                email = profile.get('email')

                query = f"SELECT id, email, phone_number, birthday FROM users WHERE {provider_id_col} = $1"
                old_user = await conn.fetchrow(query, provider_id_val)
                
                curr_user = await conn.fetchrow("SELECT id, email, phone_number, birthday FROM users WHERE id = $1", current_user_id)

                if curr_user and curr_user.get(provider_id_col) is not None and str(curr_user[provider_id_col]) != str(provider_id_val):
                    raise ForbiddenError(f"บัญชีนี้ผูกกับ {provider} ID {curr_user[provider_id_col]} อยู่แล้ว กรุณาใช้ ID เดิม")
                
                old_values = {}
                if curr_user:
                    old_values["current_user"] = dict(curr_user)

                if old_user:
                    old_user_id = old_user['id']
                    if old_user_id == current_user_id:
                        exec_time = int((time.time() - start_time) * 1000)
                        await service_logger.log(
                            conn=conn,
                            action="LINK_OAUTH_ACCOUNT",
                            actor_identifier=actor_identifier,
                            client_source=client_source,
                            user_id=current_user_id,
                            entity_type="USER",
                            entity_id=str(current_user_id),
                            status="success",
                            endpoint_or_command="link_oauth_account",
                            execution_time_ms=exec_time
                        )
                        return {"status": "success", "message": f"บัญชีนี้ผูกกับ {provider.capitalize()} ของคุณอยู่แล้วครับ"}

                    old_values["merged_user"] = dict(old_user)

                    # 🚀 MERGE: รวมร่างบัญชีเก่าเข้าบัญชีปัจจุบัน!
                    # 1. ย้ายห้องเรียนทั้งหมดมาให้บัญชีปัจจุบัน
                    old_students = await conn.fetch("SELECT id FROM students WHERE user_id = $1", old_user_id)
                    for ost in old_students:
                        try:
                            await conn.execute("UPDATE students SET user_id = $1 WHERE id = $2", current_user_id, ost['id'])
                        except asyncpg.exceptions.UniqueViolationError:
                            await conn.execute("DELETE FROM students WHERE id = $1", ost['id'])

                    # 2. ล้าง provider_id ของบัญชีเก่าก่อน เพื่อไม่ให้ชนกับ Unique constraint
                    await conn.execute(f"UPDATE users SET {provider_id_col} = NULL, email = NULL WHERE id = $1", old_user_id)

                    # 3. ดูดข้อมูลส่วนตัวมาให้บัญชีปัจจุบัน
                    await conn.execute(f"""
                        UPDATE users SET
                            {provider_id_col} = $2,
                            email = COALESCE(email, $3),
                            phone_number = COALESCE(phone_number, $4),
                            birthday = COALESCE(birthday, $5)
                        WHERE id = $1
                    """, current_user_id, provider_id_val, email or old_user['email'], old_user['phone_number'], old_user['birthday'])

                    # 4. ลบบัญชีเก่าทิ้งอย่างถาวร
                    await conn.execute("DELETE FROM users WHERE id = $1", old_user_id)

                    response = {"status": "success", "message": f"รวมประวัติ {provider.capitalize()} เก่าเข้ากับบัญชีปัจจุบันสำเร็จ!"}
                else:
                    # ถ้าไม่มีใครใช้ ก็ผูกตามปกติ
                    await conn.execute(f"""
                        UPDATE users SET {provider_id_col} = $2, email = COALESCE(email, $3) WHERE id = $1
                    """, current_user_id, provider_id_val, email)

                    response = {"status": "success", "message": f"ผูกบัญชี {provider.capitalize()} สำเร็จ!"}

                exec_time = int((time.time() - start_time) * 1000)
                await service_logger.log(
                    conn=conn,
                    action="LINK_OAUTH_ACCOUNT",
                    actor_identifier=actor_identifier,
                    client_source=client_source,
                    user_id=current_user_id,
                    entity_type="USER",
                    entity_id=str(current_user_id),
                    status="success",
                    old_values=old_values,
                    new_values={"provider": provider, "provider_id": provider_id_val, "email": email},
                    endpoint_or_command="link_oauth_account",
                    execution_time_ms=exec_time
                )
                return response
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as err_conn:
                await service_logger.log(
                    conn=err_conn,
                    action="LINK_OAUTH_ACCOUNT",
                    actor_identifier=actor_identifier,
                    client_source=client_source,
                    user_id=current_user_id,
                    entity_type="USER",
                    entity_id=str(current_user_id),
                    status="failed",
                    error_detail=str(e),
                    endpoint_or_command="link_oauth_account",
                    execution_time_ms=exec_time
                )
            raise e

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    tz_bangkok = timezone(timedelta(hours=7))
    expire = datetime.now(tz_bangkok) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

async def update_user_profile(
    pool: asyncpg.Pool, 
    user_id: int, 
    profile_data: UserProfileUpdate,
    client_source: str,
    actor_identifier: str
) -> dict:
    start_time = time.time()
    async with pool.acquire() as conn:
        try:
            # Fetch old record strictly before applying changes
            old_record = await conn.fetchrow("SELECT prefix, first_name, last_name FROM users WHERE id = $1", user_id)
            old_values = dict(old_record) if old_record else None
            
            # ใช้ execute เพื่อรันคำสั่ง UPDATE (คืนค่าเป็น string เช่น 'UPDATE 1')
            result = await conn.execute("""
                UPDATE users
                SET prefix = $1, first_name = $2, last_name = $3, updated_at = CURRENT_TIMESTAMP
                WHERE id = $4
            """, profile_data.prefix, profile_data.first_name, profile_data.last_name, user_id)
            
            # เช็คกรณีที่หา user ไม่เจอ (เผื่อไว้)
            if result == "UPDATE 0":
                raise HTTPException(status_code=404, detail="User not found")
                
            exec_time = int((time.time() - start_time) * 1000)
            await service_logger.log(
                conn=conn,
                action="UPDATE_USER_PROFILE",
                actor_identifier=actor_identifier,
                client_source=client_source,
                user_id=user_id,
                entity_type="USER",
                entity_id=str(user_id),
                status="success",
                old_values=old_values,
                new_values=profile_data.dict() if hasattr(profile_data, 'dict') else dict(profile_data),
                endpoint_or_command="update_user_profile",
                execution_time_ms=exec_time
            )
            
            return {"status": "success", "message": "อัปเดตโปรไฟล์สำเร็จ"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            async with pool.acquire() as err_conn:
                await service_logger.log(
                    conn=err_conn,
                    action="UPDATE_USER_PROFILE",
                    actor_identifier=actor_identifier,
                    client_source=client_source,
                    user_id=user_id,
                    entity_type="USER",
                    entity_id=str(user_id),
                    status="failed",
                    error_detail=str(e),
                    endpoint_or_command="update_user_profile",
                    execution_time_ms=exec_time
                )
            raise e
