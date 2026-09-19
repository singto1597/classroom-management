"""จัดกลุ่มผู้เข้าร่วมเป็น 'ภูมิภาค' ของแผนภาพเวน — บริสุทธิ์ ไม่มี DB ไม่มี async

ภูมิภาค (region) = เซตของคนที่มี **ลายเซ็นการเข้าร่วมเหมือนกัน** เช่น "อยู่ทั้งกิจกรรม 3
และ 7" หรือ "อยู่เฉพาะกิจกรรม 3" ⇒ จำนวนภูมิภาคสูงสุด = 2^N − 1 (N = จำนวนกิจกรรมที่เลือก
จึงเป็น 3 ภูมิภาคเมื่อเลือก 2 กิจกรรม และ 7 ภูมิภาคเมื่อเลือก 3)

คีย์ภูมิภาค = activity id เรียงจากน้อยไปมากต่อด้วย '-' (เช่น `"3-7"`) — **คำนวณจาก DB ทุกครั้ง**
ฝั่ง client ส่งคีย์กลับมาได้ แต่ service ต้อง intersect กับชุดที่คำนวณได้เสมอ
(ห้ามเชื่อคีย์ที่ client คิดมาเอง — ไม่งั้นเลือกดูคนข้ามห้องได้)
"""
from typing import Any, Dict, Iterable, List, Sequence

# ชื่อคอลัมน์แสดงการเป็นสมาชิกในชีต Excel
MEMBERSHIP_YES = "✓"
MEMBERSHIP_NO = "–"

# ฟิลด์ชื่อที่ยอมให้ออกจาก endpoint เปรียบเทียบ (allowlist)
# 🔴 endpoint นั้นเปิดด้วย `require_member` (สมาชิกห้องทุกคนอ่านได้) ⇒ ต้องคืน **เฉพาะชื่อ**
#    ไม่คืนทั้ง participant record แล้วหวังว่า response_model จะกรองให้
COMPARE_MEMBER_FIELDS = (
    "student_id",
    "student_no",
    "first_name",
    "last_name",
    "nickname",
    "first_name_en",
    "last_name_en",
    "nickname_en",
)


def region_key(activity_ids: Iterable[int]) -> str:
    """คีย์ภูมิภาค = activity id เรียงจากน้อยไปมากต่อด้วย '-' ⇒ `"3-7"` / `"3-7-9"`

    เรียงเสมอเพื่อให้คีย์นิ่งไม่ว่าใครจะส่ง id มาในลำดับไหน
    """
    return "-".join(str(a) for a in sorted(int(x) for x in activity_ids))


def _student_no(member: dict) -> int:
    try:
        return int(member.get("student_no"))
    except (TypeError, ValueError):
        return 0


def _sorted_members(members: List[dict]) -> List[dict]:
    """เรียงตามเลขที่ในห้อง แล้วค่อย student_id (กันเลขที่ว่าง/ซ้ำ)"""
    return sorted(members, key=lambda m: (_student_no(m), int(m.get("student_id") or 0)))


def build_regions(activity_ids: Sequence[int], members_by_activity: Dict[int, List[dict]]) -> List[dict]:
    """จัดคนเป็นภูมิภาคตาม "อยู่กิจกรรมไหนบ้าง"

    - ระบุตัวคนด้วย `student_id` (FK) — ห้ามใช้ชื่อ เพราะชื่อซ้ำ/สะกดต่างกันได้
    - `members` เก็บ record เต็ม (dict จาก DB) ⇒ ผู้เรียกเลือกเองว่าจะส่งออกฟิลด์ไหน
      (endpoint เปรียบเทียบใช้ `slim_region`, export ใช้ของเต็มเพื่ออ่าน metadata)
    - เรียงภูมิภาคตาม mask ⇒ ผลนิ่ง ไม่ขึ้นกับลำดับที่ DB คืนมา
    - คืนเฉพาะภูมิภาคที่มีคนจริง (ภูมิภาคว่างไม่ต้องมีป้ายบนแผนภาพ)
    """
    ordered = sorted({int(a) for a in activity_ids})
    seen: Dict[int, Dict[str, Any]] = {}
    for index, activity_id in enumerate(ordered):
        bit = 1 << index
        for member in members_by_activity.get(activity_id) or []:
            student_id = member.get("student_id")
            if student_id is None:
                continue
            entry = seen.get(student_id)
            if entry is None:
                seen[student_id] = {"mask": bit, "member": member}
            else:
                entry["mask"] |= bit

    buckets: Dict[int, List[dict]] = {}
    for entry in seen.values():
        buckets.setdefault(entry["mask"], []).append(entry["member"])

    regions: List[dict] = []
    for mask in sorted(buckets):
        ids = [aid for index, aid in enumerate(ordered) if mask & (1 << index)]
        regions.append(
            {
                "key": region_key(ids),
                "activity_ids": ids,
                "members": _sorted_members(buckets[mask]),
            }
        )
    return regions


def slim_member(member: dict) -> dict:
    """ตัด participant record เหลือเฉพาะฟิลด์ชื่อที่ปลอดภัย (allowlist)"""
    return {
        "student_id": int(member.get("student_id") or 0),
        "student_no": _student_no(member),
        "first_name": member.get("first_name"),
        "last_name": member.get("last_name"),
        "nickname": member.get("nickname"),
        "first_name_en": member.get("first_name_en"),
        "last_name_en": member.get("last_name_en"),
        "nickname_en": member.get("nickname_en"),
    }


def slim_region(region: dict) -> dict:
    """ภูมิภาคเวอร์ชันส่งออก API — เฉพาะชื่อ ไม่มี PII Type A / metadata"""
    return {
        "key": region["key"],
        "activity_ids": list(region["activity_ids"]),
        "members": [slim_member(m) for m in region["members"]],
    }


def regions_by_key(regions: Iterable[dict]) -> Dict[str, dict]:
    return {region["key"]: region for region in regions}


def select_regions(regions: Iterable[dict], region_keys: Iterable[str]) -> List[dict]:
    """คืนภูมิภาคที่ถูกเลือก โดย **รักษาลำดับจาก `regions`** (ไม่ใช่ลำดับที่ client ส่ง)

    caller ต้องตรวจก่อนว่าทุกคีย์มีอยู่จริง — ฟังก์ชันนี้แค่กรอง (คีย์แปลก ๆ ถูกทิ้งเงียบ ๆ)
    """
    wanted = {str(k).strip() for k in region_keys if str(k).strip()}
    return [region for region in regions if region["key"] in wanted]


def flatten_members(
    regions: Iterable[dict], members_by_activity: Dict[int, List[dict]] | None = None
) -> List[dict]:
    """รวมคนจากทุกภูมิภาคเป็นรายการเดียว (ไม่ซ้ำ) พร้อม metadata ของ **ทุกกิจกรรมที่คนนั้นอยู่**

    ใช้ตอน export — ต้องการ record เต็ม (มี `metadata` ของกิจกรรมนั้น) ไม่ใช่แค่ชื่อ

    🔴 `region["members"]` เก็บได้แค่ record ของ **กิจกรรมแรกที่เจอ** ตัวคนเดียว (คนที่อยู่
    ทั้งกิจกรรม A และ B มี 2 record) ⇒ ถ้าอ่านค่าฟิลด์ `df_1` จาก record ที่ติดมากับ region
    เฉย ๆ คอลัมน์ของกิจกรรม B จะได้ค่าของ A ไปด้วย (คีย์ `df_1` มีในทุกกิจกรรมแต่คนละความหมาย)
    ⇒ ต้อง join กลับกับ `members_by_activity` แล้วเก็บเป็น `records_by_activity[activity_id]`
    """
    records_by_activity = {
        (int(activity_id), int(member["student_id"])): member
        for activity_id, members in (members_by_activity or {}).items()
        for member in members
        if member.get("student_id") is not None
    }
    people: Dict[int, dict] = {}
    for region in regions:
        ids = list(region["activity_ids"])
        for member in region["members"]:
            student_id = member.get("student_id")
            if student_id is None or student_id in people:
                continue
            person = dict(member)
            person["activity_ids"] = ids
            person["records_by_activity"] = {
                activity_id: records_by_activity.get((activity_id, student_id), member)
                for activity_id in ids
            }
            people[student_id] = person
    return sorted(people.values(), key=lambda p: (_student_no(p), int(p.get("student_id") or 0)))
