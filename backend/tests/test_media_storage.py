"""🗄️ LocalMediaStorage — write/read/delete, atomicity, key containment (รูป + PDF)"""
import hashlib
import os
import uuid

import pytest

from core.media import LocalMediaStorage, MediaStorageError


@pytest.fixture
def storage(tmp_path):
    return LocalMediaStorage(str(tmp_path / "media"))


def _key(owner_type="transaction", owner_id=7, ext="webp", thumb=False):
    suffix = "_thumb" if thumb else ""
    return f"media/finance/{owner_type}/{owner_id}/{uuid.uuid4()}{suffix}.{ext}"


@pytest.mark.asyncio
async def test_write_read_roundtrip(storage):
    key = _key()
    data = b"RIFF-webp-payload" + os.urandom(4096)
    await storage.write(key, data)
    assert await storage.exists(key)

    chunks = []
    async for c in storage.read_stream(key):
        chunks.append(c)
    got = b"".join(chunks)
    assert got == data
    assert hashlib.sha256(got).digest() == hashlib.sha256(data).digest()

    path = storage.local_path(key)
    assert path is not None and path.is_file()


@pytest.mark.asyncio
async def test_pdf_key_roundtrip(storage):
    key = _key(ext="pdf")
    await storage.write(key, b"%PDF-1.7 ...")
    assert await storage.exists(key)


@pytest.mark.asyncio
async def test_delete_is_idempotent(storage):
    key = _key()
    await storage.write(key, b"x")
    await storage.delete(key)
    await storage.delete(key)  # ไม่มีไฟล์แล้วต้องไม่ error
    assert not await storage.exists(key)


@pytest.mark.asyncio
async def test_atomic_write_leaves_no_partial_file(storage, monkeypatch):
    """ถ้า os.replace ล้ม ต้องไม่เหลือไฟล์ที่ final path และไม่เหลือ .part"""
    key = _key()

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr("core.media.local.os.replace", boom)
    with pytest.raises(MediaStorageError):
        await storage.write(key, b"data")

    assert not await storage.exists(key)
    parts = list(storage.tmp_dir.glob("*.part"))
    assert parts == []


@pytest.mark.asyncio
async def test_overwrite_is_atomic_replace(storage):
    key = _key()
    await storage.write(key, b"first")
    await storage.write(key, b"second")
    chunks = []
    async for c in storage.read_stream(key):
        chunks.append(c)
    assert b"".join(chunks) == b"second"


@pytest.mark.parametrize(
    "key",
    [
        "../../etc/passwd",
        "/etc/passwd",
        "media/finance/transaction/7/not-a-uuid.webp",
        "media/finance/transaction/7/..%2f..%2fetc.webp",
        "media/finance/transaction/x/" + "a" * 36 + ".webp",
        "media/finance/transaction/7/" + "a" * 36 + ".jpg",
        "media/finance/transaction/7/" + "a" * 36 + ".webp.bak",
        "media/finance/transaction/7/" + "a" * 36 + "_thumb.pdf",
        "media/finance/BOARD/7/" + "a" * 36 + ".webp",
        "media/finance/other/7/" + "a" * 36 + ".webp",
        "media/finance/transaction/7/../" + "a" * 36 + ".webp",
        "tmp/evil.webp",
        "",
    ],
)
@pytest.mark.asyncio
async def test_invalid_keys_rejected(storage, key):
    with pytest.raises(MediaStorageError):
        await storage.write(key, b"x")
    with pytest.raises(MediaStorageError):
        storage.local_path(key)


@pytest.mark.asyncio
async def test_symlink_escape_rejected(tmp_path):
    """`media/` ที่เป็น symlink ออกนอก root ต้องถูกปฏิเสธ (containment หลัง resolve)"""
    root = tmp_path / "media"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "media").symlink_to(outside, target_is_directory=True)

    s = LocalMediaStorage(str(root))
    key = _key()
    with pytest.raises(MediaStorageError):
        await s.write(key, b"x")
    assert list(outside.rglob("*.webp")) == []


@pytest.mark.asyncio
async def test_missing_file_read_raises(storage):
    with pytest.raises(MediaStorageError):
        async for _ in storage.read_stream(_key()):
            pass


@pytest.mark.parametrize(
    "key_tpl",
    [
        "media/finance/transaction/7/{u}.webp",
        "media/finance/transaction/7/{u}_thumb.webp",
        "media/finance/student_payment/12/{u}.webp",
        "media/finance/payment_event/3/{u}.webp",
        "media/finance/transaction/7/{u}.pdf",
        "media/finance/student_payment/1/{u}.pdf",
    ],
)
@pytest.mark.asyncio
async def test_finance_keys_accepted_and_roundtrip(tmp_path, key_tpl):
    s = LocalMediaStorage(str(tmp_path))
    key = key_tpl.format(u=uuid.uuid4())
    await s.write(key, b"data")
    path = s.local_path(key)
    assert path is not None and path.is_file()
