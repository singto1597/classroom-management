/**
 * 🗂️ [FIN-V2 / P5.2] ตรรกะบริสุทธิ์ของ **ทะเบียนเอกสารรวม** — label · badge · query · bundle
 *
 * แยกออกจาก `.vue` เพื่อให้เทสต์ได้โดยไม่ต้อง mount หน้า และเพื่อให้ **แหล่งเดียว**
 * ของป้ายไทย/สี/คีย์ ที่ทั้ง `DocumentRegistry.vue`, `DocumentDetail.vue` และ
 * `DocumentFilters.vue` ใช้ร่วมกัน
 *
 * 🔴 `DOC_TYPES` ต้องตรงกับ `REGISTRY_DOC_TYPES` ฝั่ง backend (`services/finance/constants.py`)
 *    และ `DOC_TYPE_LABELS` ต้องตรงกับ `DOC_TYPE_LABELS` ที่นั่น — เพิ่มชนิดใหม่ =
 *    แก้ 4 ที่: constants ฝั่ง backend, `DocumentType` ใน `types/finance.ts`, tuple นี้
 *    และ map นี้ (มีเทสต์ `documentFilters.spec.ts` ตรวจนับครบ 8 ชนิด)
 */
import type {
  DocumentListItem,
  DocumentListQuery,
  DocumentType,
} from '@/types/finance';

/**
 * กลุ่ม "ทิศทางเงิน" สำหรับตัวกรองเริ่มต้น
 *  - รายรับ = เงินเข้า (ใบเสร็จ · ใบรับเงินล่วงหน้า · ใบรับเงิน)
 *  - รายจ่าย = เงินออก (ใบสำคัญจ่าย · ใบรับรองแทนใบเสร็จ)
 * เอกสารที่เหลือ (ใบแจ้งหนี้ · ACK · RPT) ไม่ใช่การเคลื่อนเงิน ⇒ ไม่ถูกเลือกโดยปริยาย
 */
export const INCOME_DOC_TYPES: readonly DocumentType[] = ['receipt', 'deposit', 'income'];
export const EXPENSE_DOC_TYPES: readonly DocumentType[] = ['payment_voucher', 'certificate'];
export const DEFAULT_DOC_TYPES: readonly DocumentType[] = [
  ...INCOME_DOC_TYPES,
  ...EXPENSE_DOC_TYPES,
];

/** ลำดับ = ลำดับที่ผู้ใช้เห็นในตัวกรอง (ตรงกับ `REGISTRY_DOC_TYPES` ฝั่ง backend) */
export const DOC_TYPES: readonly DocumentType[] = [
  'receipt',
  'invoice',
  'acknowledgement',
  'deposit',
  'payment_voucher',
  'certificate',
  'income',
  'monthly_report',
];

/** ป้ายไทยของชนิดเอกสาร — คำตรง `DOC_TYPE_LABELS` ฝั่ง backend (glossary) */
export const DOC_TYPE_LABELS: Readonly<Record<DocumentType, string>> = {
  receipt: 'ใบเสร็จรับเงิน',
  invoice: 'ใบแจ้งหนี้',
  acknowledgement: 'ใบรับทราบยอดค้าง',
  deposit: 'ใบรับเงินล่วงหน้า',
  payment_voucher: 'ใบสำคัญจ่าย',
  certificate: 'ใบรับรองแทนใบเสร็จ',
  income: 'ใบรับเงิน',
  monthly_report: 'รายงานปิดงบ',
};

/** ไอคอนของแต่ละชนิด (bootstrap-icons) — ใช้คู่กับป้ายบน badge */
export const DOC_TYPE_ICONS: Readonly<Record<DocumentType, string>> = {
  receipt: 'bi-receipt',
  invoice: 'bi-file-earmark-text',
  acknowledgement: 'bi-check2-square',
  deposit: 'bi-piggy-bank',
  payment_voucher: 'bi-cash-coin',
  certificate: 'bi-patch-check',
  income: 'bi-cash-stack',
  monthly_report: 'bi-clipboard-data',
};

/**
 * 🎨 สีของ badge ตาม **สถานะของเงิน** ไม่ใช่ชื่อชนิด (บทเรียนเดียวกับ `ReceiptList.vue`):
 * - `ok`      = เงินเข้ามือแล้ว และนับเป็นรายได้ (`receipt`, `income`)
 * - `info`    = เงินเข้ามือแล้ว แต่ยังไม่นับเป็นรายได้ (`deposit` — หนี้สินเครดิต 2099)
 * - `warn`    = ยังไม่ได้รับเงิน (`invoice`, `acknowledgement`)
 * - `neutral` = เงินออกจากห้อง (`payment_voucher`) — ตั้งใจให้เป็นกลาง ไม่ใช่แดง
 * - `brand`   = เอกสารรับรอง/สรุปของห้อง (`certificate`, `monthly_report`)
 *
 * 🔴 ห้ามใช้แดง (`danger-*`) กับชนิดใดในนี้: แดงสื่อ "ถูกยกเลิก" อยู่แล้วในหน้านี้
 *    ⇒ เอกสารที่ยังใช้ได้จะอ่านเหมือนใบที่ตายแล้ว
 */
export type DocumentTone = 'ok' | 'info' | 'warn' | 'neutral' | 'brand';

const DOC_TYPE_TONES: Readonly<Record<DocumentType, DocumentTone>> = {
  receipt: 'ok',
  income: 'ok',
  deposit: 'info',
  invoice: 'warn',
  acknowledgement: 'warn',
  payment_voucher: 'neutral',
  certificate: 'brand',
  monthly_report: 'brand',
};

const TONE_CLASS: Readonly<Record<DocumentTone, string>> = {
  ok: 'bg-ok-50 text-ok-700',
  info: 'bg-info-50 text-info-700',
  warn: 'bg-warn-50 text-warn-700',
  neutral: 'bg-canvas text-ink-2',
  brand: 'bg-brand-tint text-brand',
};

/** เพดานของ "พิมพ์ชุด" — ตรงกับ `RECEIPTS_PER_PDF_MAX`/`REGISTRY` ฝั่ง backend (100) */
export const DOCUMENT_BUNDLE_MAX = 100;

/** ชนิดเอกสารที่ backend รู้จัก (guard ให้ route param/ข้อมูลที่รับมาจาก URL) */
export const isDocumentType = (value: unknown): value is DocumentType =>
  typeof value === 'string' && (DOC_TYPES as readonly string[]).includes(value);

/**
 * ป้ายไทยของชนิดเอกสาร — **fallback เป็นรหัสดิบ** เมื่อไม่รู้จัก (ไม่ throw)
 * ตรงกับ `doc_type_label()` ฝั่ง backend ⇒ จอกับ API ตอบเหมือนกัน
 */
export const typeLabel = (docType: string): string =>
  isDocumentType(docType) ? DOC_TYPE_LABELS[docType] : docType;

/** ไอคอนของชนิดเอกสาร — fallback เป็นไอคอนกลางเมื่อไม่รู้จัก */
export const typeIcon = (docType: string): string =>
  isDocumentType(docType) ? DOC_TYPE_ICONS[docType] : 'bi-file-earmark';

/** คลาส badge ของชนิดเอกสาร — fallback เป็น neutral */
export const typeBadgeClass = (docType: string): string =>
  isDocumentType(docType) ? TONE_CLASS[DOC_TYPE_TONES[docType]] : TONE_CLASS.neutral;

/**
 * 🆔 คีย์ของแถว/checkbox — **ต้องเป็น composite key**
 *
 * `doc_id` ชนกันข้ามตารางได้จริง (REC id 12 กับ RPT id 12 มีพร้อมกัน) ⇒ ถ้าใช้ id เดี่ยว
 * การติ๊กใบหนึ่งจะไปติ๊กอีกใบโดยไม่มีอะไรฟ้อง และคำขอพิมพ์ชุดจะส่งใบผิด
 */
export const selectionKey = (item: { doc_type: string; doc_id: number }): string =>
  `${item.doc_type}:${item.doc_id}`;

/** ชุดที่เลือกพิมพ์ได้: 1–100 ใบ (backend ยังกันซ้ำด้วย 400 — defense in depth) */
export const canPrintBundle = (count: number): boolean =>
  Number.isInteger(count) && count >= 1 && count <= DOCUMENT_BUNDLE_MAX;

/**
 * แปลง `DocumentListQuery` เป็น query params ของ API
 *
 * - ตัดค่าว่าง/`null`/`undefined` ทิ้ง — axios จะส่ง `student_id=null` เป็นสตริงขยะ
 * - `doc_types` → `doc_types=r1,r2` (backend แยกด้วยจุลภาคเอง)
 * - `status: 'all'` → `include_voided=true` และ **ไม่ส่ง** `status` (backend รับแค่ active/voided)
 * - `limit`/`offset` คงเป็นตัวเลข (0 คือค่าที่มีความหมาย ⇒ ไม่ตัด)
 */
export const buildDocumentQuery = (
  query: DocumentListQuery,
): Record<string, string | number> => {
  const out: Record<string, string | number> = {};

  if (query.doc_types && query.doc_types.length > 0) {
    out.doc_types = query.doc_types.join(',');
  }
  if (query.from) out.from = query.from;
  if (query.to) out.to = query.to;
  if (query.student_id !== undefined && query.student_id !== null) {
    out.student_id = query.student_id;
  }
  if (query.receiver_id !== undefined && query.receiver_id !== null) {
    out.receiver_id = query.receiver_id;
  }
  if (query.channel_id !== undefined && query.channel_id !== null) {
    out.channel_id = query.channel_id;
  }

  if (query.status === 'all') {
    out.include_voided = 'true';
  } else if (query.status === 'active' || query.status === 'voided') {
    out.status = query.status;
  }

  const term = query.q?.trim();
  if (term) out.q = term;

  if (query.limit !== undefined) out.limit = query.limit;
  if (query.offset !== undefined) out.offset = query.offset;

  return out;
};

/** แถวที่ถูกยกเลิก — ใช้ตัดสินป้าย "ยกเลิก" ทั้งในทะเบียนและหน้ารายละเอียด */
export const isVoided = (item: Pick<DocumentListItem, 'status'>): boolean =>
  item.status === 'voided';
