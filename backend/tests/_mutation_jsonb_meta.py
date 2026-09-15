"""🧬 Mutation testing สำหรับ [BUG 2026-09-14] — `metadata` (jsonb) อ่านเป็น dict.

ทำไมต้องมีไฟล์นี้: เทสต์ถดถอยที่ "ผ่าน" ไม่ได้พิสูจน์ว่ามันจับบั๊กได้ — ต้อง**ถอดการแก้
ออกแล้วเห็นเทสต์ล้มจริง** (docs/rules/testing.md บังคับ; บทเรียน docs/skills.md)

วิธีรัน (ในคอนเทนเนอร์เทสต์):
    docker compose -f docker-compose.test.yml run --rm -T test_runner \\
        sh -c "export PYTHONDONTWRITEBYTECODE=1 && python /app/tests/_mutation_jsonb_meta.py"

สคริปต์จะ (1) แก้ `services/finance/helpers.py` ทีละ mutation (2) รันเทสต์เป้าหมาย
(3) คืนไฟล์เดิมเสมอแม้ถูก Ctrl-C (4) สรุปว่า mutation ไหน "รอด" = เทสต์ยังผ่านทั้งที่โค้ดพัง
"""
import os
import subprocess
import sys

HELPERS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "services", "finance", "helpers.py")

TARGETS = [
    "tests/test_finance_v2_read.py::test_metadata_to_dict_accepts_both_str_and_dict",
    "tests/test_finance_v2_read.py::test_legacy_id_prefers_legacy_transaction_id_over_transfer_group_id",
    "tests/test_finance_v2_read.py::test_journal_fallback_id_is_stable_across_processes",
    "tests/test_finance_v2_read.py::test_v2_transaction_id_is_the_real_legacy_id",
    "tests/test_finance_v2_read.py::test_v2_transfer_id_points_at_a_real_transaction_row",
    "tests/test_finance_v2_read.py::test_revert_transaction_accepts_the_id_from_the_transaction_list",
]

# (ชื่อ, ค้นหา, แทนด้วย) — แต่ละอันคือ "ถอดการแก้ออก" หรือ "พังแบบใหม่"
MUTATIONS = [
    (
        "คืนบั๊กเดิม: ทิ้ง metadata ที่เป็นสตริง",
        "    metadata = _metadata_to_dict(metadata)\n",
        "    if not isinstance(metadata, dict):\n        metadata = {}\n",
    ),
    (
        "_metadata_to_dict ไม่รับสตริง (สาขา str ตาย)",
        "    if isinstance(raw, str):\n        try:\n            parsed = json.loads(raw)",
        "    if False:\n        try:\n            parsed = json.loads(raw)",
    ),
    (
        "_metadata_to_dict ไม่ยืนยันว่าผลลัพธ์เป็น dict",
        "        return parsed if isinstance(parsed, dict) else {}",
        "        return parsed",
    ),
    (
        "_metadata_to_dict ทิ้งสาขา dict",
        "    if isinstance(raw, dict):\n        return raw",
        "    if isinstance(raw, dict):\n        return {}",
    ),
    (
        "fallback กลับไปใช้ hash() ของ Python (ไม่คงที่ข้ามโปรเซส)",
        'zlib.crc32(str(journal_uuid).encode("utf-8"))',
        "abs(hash(str(journal_uuid)))",
    ),
    (
        "fallback คืนค่าบวก (ชนกับ id จริงได้)",
        "        return -(zlib.crc32(str(journal_uuid).encode(\"utf-8\")) % (2**31 - 1) + 1)",
        "        return (zlib.crc32(str(journal_uuid).encode(\"utf-8\")) % (2**31 - 1) + 1)",
    ),
    (
        "สลับลำดับคีย์: เอา transfer_group_id ขึ้นก่อน",
        'for key in ("legacy_transaction_id", "transfer_group_id"):',
        'for key in ("transfer_group_id", "legacy_transaction_id"):',
    ),
]


def run_pytest() -> tuple:
    """คืน (passed, สรุปบรรทัดท้าย) — passed = เทสต์ผ่านหมด ⇒ mutation 'รอด'."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *TARGETS],
        cwd="/app", capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    summary = lines[-1] if lines else f"(ไม่มี output, exit={proc.returncode})"
    if proc.returncode == 5:
        # ไม่มีเทสต์ถูกเก็บเลย = เครื่องมือพัง ไม่ใช่ "เทสต์จับได้" ⇒ ห้ามนับเป็นการจับ
        # คืน True เพื่อให้ขึ้น ❌ และกองงานค้างให้คนเห็น (พร้อมคำเตือนใน summary)
        return True, f"⚠️ ไม่มีเทสต์ถูกเก็บ (exit=5) — ตรวจ TARGETS: {summary}"
    caught = ("failed" in summary) or ("error" in summary.lower()) or proc.returncode != 0
    return (not caught), summary


def main() -> int:
    with open(HELPERS, encoding="utf-8") as f:
        original = f.read()

    print(f"เทสต์เป้าหมาย {len(TARGETS)} ตัว · mutation {len(MUTATIONS)} แบบ")
    print("=" * 100)
    survived = []
    try:
        for name, old, new in MUTATIONS:
            if original.count(old) != 1:
                print(f"⚠️  ข้าม: '{name}' — เจอ anchor {original.count(old)} ครั้ง (ต้องเป็น 1)")
                survived.append((name, "anchor ไม่ชัด — mutation ไม่ได้ถูกทดสอบจริง"))
                continue
            with open(HELPERS, "w", encoding="utf-8") as f:
                f.write(original.replace(old, new))
            passed, summary = run_pytest()
            mark = "❌ รอด (เทสต์จับไม่ได้!)" if passed else "✅ ถูกจับ"
            print(f"{mark:28} {name}")
            print(f"{'':28} {summary}")
            if passed:
                survived.append((name, summary))
    finally:
        with open(HELPERS, "w", encoding="utf-8") as f:
            f.write(original)
        print("=" * 100)
        print("คืนไฟล์ helpers.py เรียบร้อยแล้ว")

    print(f"\nสรุป: ถูกจับ {len(MUTATIONS) - len(survived)}/{len(MUTATIONS)} · รอด {len(survived)}")
    for name, summary in survived:
        print(f"  ❌ {name} — {summary}")
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
