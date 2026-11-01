import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AxiosHeaders } from 'axios';
import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { api } from '@/services/api';
import { HomeService } from '@/services/home';
import { FinanceService } from '@/services/finance';
import { AnnouncementService } from '@/services/announcement';

/**
 * 🔒 เทสต์ชุดนี้ล็อก "สัญญาปลายทาง" ของหน้าหลัก (P3.1 + P3.2)
 *
 * กฎที่ต้องกันไม่ให้ถอยหลัง — การ์ดทุกใบบน Dashboard ต้องพาไปลิสต์ที่กรองด้วย
 * ชุดข้อมูลเดียวกับตัวเลขบนการ์ด ถ้าไคลเอนต์ยิงผิด endpoint/ไม่ส่งตัวกรอง
 * ตัวเลขกับลิสต์จะแยกจากกันเงียบ ๆ ("34 กดแล้วเจอ 5")
 *
 * 1. `HomeService.getSummary` → `/home/summary` (ก้อนเดียว ไม่ใช่ยิง 5 คำขอ)
 * 2. `FinanceService.getMyDebts` → `/finance/me/debts` (**ของฉัน** ไม่ใช่ `/students/:id`)
 *    — ถ้าหลุดไป `/finance/debtors` ซึ่งเป็นของทุกคน จำนวนจะไม่ตรงกับการ์ด
 * 3. `AnnouncementService.list` ต้องส่ง `unread_only` **ไปที่ backend** เพราะรายการ
 *    แบ่งหน้า — กรองฝั่งหน้าจะได้ตัวเลขไม่ตรง และ "กรองแล้วได้ 0" ทั้งที่ยังมีของ
 */

interface Captured {
  uri: string;
  method: string;
  body: unknown;
}

const captured: Captured[] = [];

beforeEach(() => {
  captured.length = 0;
  api.defaults.adapter = async (config: InternalAxiosRequestConfig): Promise<AxiosResponse> => {
    captured.push({
      uri: api.getUri(config),
      method: (config.method ?? 'get').toUpperCase(),
      body: config.data,
    });
    return {
      data: {},
      status: 200,
      statusText: 'OK',
      headers: new AxiosHeaders(),
      config,
    };
  };
});

afterEach(() => {
  vi.restoreAllMocks();
});

const firstUri = (): string => {
  const req = captured[0];
  if (!req) throw new Error('ไม่มีการเรียก API เลย — adapter ไม่ถูกเรียก (เทสต์จะเขียวหลอก)');
  return req.uri;
};

describe('HomeService.getSummary — คำขอเดียวของหน้าหลัก', () => {
  it('ยิง GET ไปที่ /api/classroom/{room}/home/summary พร้อม target_type=room', async () => {
    await HomeService.getSummary(42);

    expect(captured).toHaveLength(1);
    expect(captured[0]?.method).toBe('GET');
    expect(firstUri()).toContain('/api/classroom/42/home/summary?');
    expect(firstUri()).toContain('target_type=room');
  });

  it('ไม่มี id ที่เป็น undefined หลุดเข้า URL (ห้องยังไม่ถูกเลือก)', async () => {
    await HomeService.getSummary(0);
    expect(firstUri()).toContain('/api/classroom/0/home/summary');
    expect(firstUri()).not.toMatch(/undefined|null|NaN/);
  });
});

describe('FinanceService.getMyDebts — ของฉัน ไม่ใช่ของทุกคน', () => {
  it('ยิงไปที่ /finance/me/debts (predicate เดียวกับการ์ด "บิลค้างชำระ")', async () => {
    await FinanceService.getMyDebts(42);

    expect(firstUri()).toContain('/api/classroom/42/finance/me/debts?');
    expect(firstUri()).toContain('target_type=room');
    // ⛔ กันหลุดไป `/finance/students/{id}/debts` (ต้องรู้ student_id) หรือ `/finance/debtors`
    expect(firstUri()).not.toContain('/finance/students/');
    expect(firstUri()).not.toContain('/finance/debtors');
  });
});

describe('AnnouncementService.list — "ยังไม่อ่านเท่านั้น" ต้องกรองฝั่ง backend', () => {
  it('ส่ง unread_only=true เมื่อเปิดตัวกรอง', async () => {
    await AnnouncementService.list(42, { limit: 20, unread_only: true });

    expect(firstUri()).toContain('unread_only=true');
  });

  it('ไม่ส่ง unread_only=true เมื่อไม่ได้เปิด (default ของ backend = false)', async () => {
    await AnnouncementService.list(42, { limit: 20 });

    expect(firstUri()).not.toContain('unread_only=true');
  });

  it('ยังส่ง include_archived ไปด้วยเสมอเมื่อระบุ (สองตัวกรองต้องไปด้วยกันได้)', async () => {
    await AnnouncementService.list(42, { limit: 20, unread_only: true, include_archived: true });

    expect(firstUri()).toContain('unread_only=true');
    expect(firstUri()).toContain('include_archived=true');
  });
});
