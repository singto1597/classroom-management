"""Integration test — GET /api/version

ล็อกสัญญา 3 ข้อ:
1. คืน 200 และ version ตรงกับตั้งค่าที่ service โหลด (PROJECT_VERSION)
2. git_sha มีค่าเสมอ (unknown ได้เมื่อรันนอก container — แต่ห้ามว่าง/หาย)
3. Cache-Control: no-store — กัน proxy แคชคำตอบข้าม deploy
"""
import pytest

from core.config import settings

pytestmark = pytest.mark.asyncio


async def test_version_returns_running_version(client):
    resp = client.get("/api/version")

    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == settings.PROJECT_VERSION
    assert body["service"] == "backend"
    assert isinstance(body["git_sha"], str) and body["git_sha"]
    assert resp.headers["cache-control"] == "no-store"
