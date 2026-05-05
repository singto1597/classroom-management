from fastapi import Request, Security, HTTPException, status
from fastapi.security import APIKeyHeader
import asyncpg
from core.config import settings

api_key_header = APIKeyHeader(name="X-API-Key")

async def get_db_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool

def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid API Key"
        )
    return api_key