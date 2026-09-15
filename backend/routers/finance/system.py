"""🔓 System RPC สำหรับบอท — ดาวน์โหลด PDF ชุดเอกสารด้วย **สิทธิ์ระบบ** (F5/PR-3)

⚠️ ไฟล์นี้มี **เส้นทางเดียวในระบบที่ข้ามการตรวจสมาชิกของเส้นทาง PDF** ⇒ แยกออกมาจาก
   `routers/finance/receipts.py` โดยเจตนา: ทั้งชื่อไฟล์และชื่อ route (`/finance/system/...`)
   ทำให้ `grep -rn "finance/system" backend/ bot_discord/` เจอทันที ดีกว่าซ่อนไว้ปนกับ
   route ที่บังคับ `require_member` แล้วอ่านไม่ออกว่าตัวไหนข้าม

🔒 ขอบเขตที่ล็อกไว้ (ไม่ครบข้อใด = ห้าม merge):
   1. ใช้ `get_current_user_or_bot` + ternary `is_bot_system` — **คัดลอกรูปจาก
      `routers/classroom_sync_router.py:79-93` เป๊ะ**: บอทจริง (API key ถูกต้อง แต่
      `X-Discord-Id` เป็น id ของ bot application ที่ไม่มีใน `users`) ได้ `user_id=None`
      ⇒ ข้าม `require_member` · ส่วน JWT ของเว็บยังต้องเป็นสมาชิกจริงเหมือนเดิม
   2. **อ่านเท่านั้น 100%** — ไม่มี `INSERT`/`UPDATE` ใด ๆ ในเส้นทางนี้ และไม่แตะ
      `receipt_sequences` เลยแม้แต่คำสั่งเดียว (มีเทสต์เชิงโครงสร้าง grep บังคับ)
   3. ด่านที่สำคัญที่สุดยังอยู่ที่ service: `WHERE R.room_id = $1 AND R.receipt_no = ANY($2)`
      + `missing` ⇒ เลขของห้องอื่นได้ 404 **ไม่ใช่ไฟล์**
   4. **ห้ามเพิ่ม `is_bot_system` ให้ route อื่น** — โดยเฉพาะ route ที่เขียน (ออกใบเสร็จ /
      ใบแจ้งหนี้ / ชุดเอกสาร) ต้องคง `get_current_user` + `MANAGE_FINANCE` ต่อไป
   5. **ห้ามแก้ auth ของ 2 route PDF เดิม** ใน `receipts.py` (ใบเดียว · รวมชุด) —
      หน้าจอเดิมพึ่ง `require_member` อยู่ และแผน F5 ตกลงว่าจะไม่แตะ RBAC ของหน้าจอเดิม

💡 ทำไมยอมให้บอทอ่านได้: **ความสามารถที่เพิ่มขึ้นเป็นศูนย์** — บอทถือ API key ตัวเดียวกัน
   และเรียก `GET /{target_id}?target_type=server` ได้อยู่แล้ว ซึ่งคืน
   `announcement_channel_id` ของทุกห้อง ⇒ มันรู้จัก server_id ที่มันจะขอไฟล์ตั้งแต่ต้น
   ส่วนเลขที่เอกสารก็ได้มาจาก payload ของ event ที่ backend เพิ่ง publish เอง
   (ไม่เลือกทาง "ออก token อายุสั้น" เพราะ `api_client` ใส่ `X-API-Key` ให้ทุก request
   อยู่แล้ว ⇒ token ไม่ได้ลด attack surface จริง แต่เพิ่มโค้ด sign/verify ที่ไม่มีเทสต์คุม
   และต้องใส่ความลับลง payload ของ Redis ที่วันนี้ไม่มีอะไรลับเลย)
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
import asyncpg

from models.finance_schemas import ReceiptCombinedPdfRequest
from core.dependencies import get_db_pool, get_current_user_or_bot
from core.exceptions import RoomNotFoundError, ForbiddenError
from services.finance_service import FinanceService
from services.finance.pdf import PdfRenderError

from routers._common import TargetResolution, get_target, get_audit_context

router = APIRouter()


@router.post("/{target_id}/finance/system/receipts/pdf")
async def download_documents_pdf_for_system(
    req: ReceiptCombinedPdfRequest,
    request: Request,
    target: TargetResolution = Depends(get_target),
    pool: asyncpg.Pool = Depends(get_db_pool),
    user_ctx: dict = Depends(get_current_user_or_bot),
):
    """ดาวน์โหลดเอกสารหลายใบเป็น PDF **ไฟล์เดียว หน้าละใบ** — สำหรับบอทแนบเข้า Discord

    🎯 ใช้คู่กับ event `FINANCE_PAYMENT` ที่มี `receipt_nos`: บอทขอไฟล์จากที่นี่แล้วแนบ
       ไปกับข้อความแจ้งเตือนใบเดิม (หนึ่งข้อความ หนึ่ง ping หนึ่งไฟล์) — ไม่มี event ใหม่
       เพราะเงินก้อนนั้นแจ้งเตือนไปแล้ว การเพิ่ม embed อีกใบคือ ping ซ้ำ

    ⚠️ **คู่แฝดของ `POST /{target_id}/finance/receipts/pdf`** (`routers/finance/receipts.py:126`)
       ต่างกันที่ **ด่านสมาชิก** เท่านั้น — ที่นี่บอทระบบผ่านได้โดยไม่มี `users` row
       ⇒ response, เพดาน 100 ฉบับ, การ dedupe เลขซ้ำ และการตอบ 404 เมื่อมีเลขตกหล่น
       เหมือนกันเป๊ะ เพราะใช้ service ตัวเดียวกัน (`_render_documents_pdf`)

    ⚠️ `POST` ไม่ใช่ `GET` ด้วยเหตุผลเดียวกับคู่แฝด: เลขเอกสาร 100 ใบใส่ query string ไม่ได้
    ⚠️ ไม่ประกาศ `response_model` — response เป็น binary stream (FastAPI จะพยายาม
       serialize `bytes` เป็น JSON ถ้าใส่)
    """
    is_bot_system = user_ctx.get("is_bot_system") is True
    # 🪪 ตัวตนผู้ทำ: บอทระบบไม่มี `user_id` ⇒ ส่ง `None` ให้ `get_audit_context` ตกไปอ่าน
    #    `X-Actor-Id` (บอทส่ง `discord:<id>` มา) แทนที่จะบันทึกเป็นสตริง `"user_id:None"`
    #    ซึ่งอ่านเหมือน "ผู้ใช้ที่ id เป็น None" — audit log ที่บอกตัวตนผิดนั้นแย่กว่าไม่มี
    #    ⚠️ ไม่ใช่ช่องโหว่ใหม่: `X-Actor-Id` ถูกใช้เป็น fallback อยู่แล้วเมื่อไม่มี `user_id`
    #       และเส้นทางนี้ต้องมี API key ที่ถูกต้องก่อนถึงบรรทัดนี้
    client_source, actor = get_audit_context(request, None if is_bot_system else user_ctx)
    try:
        if is_bot_system:
            # 🔓 ทางเดียวที่ปิด `require_member` — มีเมธอดชื่อเฉพาะใน service เพื่อให้ grep เจอ
            pdf_bytes, filename = await FinanceService.render_documents_pdf_for_system(
                pool=pool, receipt_nos=req.receipt_nos, client_source=client_source,
                actor_identifier=actor, server_id=target.server_id, room_id=target.room_id,
            )
        else:
            # บอทที่เป็น user จริง และเว็บ (JWT) → ยังต้องเป็นสมาชิกห้องนี้ (พฤติกรรมเดิม)
            pdf_bytes, filename = await FinanceService.render_documents_pdf(
                pool=pool, receipt_nos=req.receipt_nos, client_source=client_source,
                actor_identifier=actor, server_id=target.server_id, room_id=target.room_id,
                user_id=user_ctx.get("user_id"),
            )
    except RoomNotFoundError as e:
        # รวม "เลขที่ไม่พบในห้องนี้" ของ service ด้วย ⇒ เลขข้ามห้องจบที่ 404 ไม่ใช่ไฟล์
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        # ⚠️ วันนี้สาขานี้ **ไปไม่ถึง** ผ่านเส้นทางนี้ (ด่านสมาชิกคือด่านเดียวที่โยน ForbiddenError
        #    และมันถูกปิดเฉพาะสาขาบอทระบบ) — เก็บไว้โดยเจตนา: วันที่ใครเพิ่มการตรวจสิทธิ์
        #    ระดับอื่น (เช่น revoked) เข้ามา คำตอบที่ถูกคือ 403 ไม่ใช่ 500
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        # 400 = คำขอที่บอทแก้เองได้ (เกินเพดาน 100 ฉบับ / ไม่ได้ส่งเลขมาเลย)
        raise HTTPException(status_code=400, detail=str(e))
    except PdfRenderError as e:
        # 502 = Gotenberg ใช้งานไม่ได้ ไม่ใช่โค้ดเราพัง ⇒ บอทแยกออกได้ว่า "แนบไม่ได้ชั่วคราว"
        #       แล้วยังต้องส่งข้อความแจ้งเตือนต่อ (ดู PDF_FETCH_TIMEOUT_S ฝั่งบอท)
        raise HTTPException(status_code=502, detail=f"สร้างไฟล์ PDF ไม่สำเร็จ: {e}")

    # filename* แบบ RFC 5987 รองรับชื่อไฟล์ที่มีอักขระนอก ASCII — บอท parse ตัวนี้
    # (ชื่อไฟล์มี "ใบเสร็จ" เป็นภาษาไทย ⇒ `filename="..."` เพียว ๆ จะเพี้ยน)
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{filename}',
            "Content-Length": str(len(pdf_bytes)),
        },
    )
