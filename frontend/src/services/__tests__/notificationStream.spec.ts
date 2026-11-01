import { describe, expect, it, vi } from 'vitest';
import { createSseParser } from '@/services/notificationStream';

/**
 * 📡 ตัวแยก SSE frame — ล็อกกฎที่ backend ใช้จริง
 *
 * backend (`routers/notification_router.py`) ส่ง:
 *   `: ping`            comment/heartbeat ทุก 25 วิ
 *   `event: ready` + `data: {}`
 *   `event: notification` + `data: {"id":..,"user_id":..,"room_id":..}`
 *
 * ⚠️ chunk จาก network ตัดกลาง frame ได้ทุกตำแหน่ง — เทสต์จึงต้องป้อนทีละครึ่ง
 *    ไม่ใช่ป้อนทั้ง frame ทีเดียว (ซึ่งทำให้บั๊ก buffering หลุดไปถึงผู้ใช้)
 */

type Frame = { event: string; data: string };

function collect() {
  const frames: Frame[] = [];
  const parser = createSseParser((event, data) => frames.push({ event, data }));
  return { frames, parser };
}

describe('createSseParser', () => {
  it('แยก frame ที่มาครบใน chunk เดียว', () => {
    const { frames, parser } = collect();
    parser.push('event: notification\ndata: {"id":1}\n\n');
    expect(frames).toEqual([{ event: 'notification', data: '{"id":1}' }]);
  });

  it('ประกอบ frame ที่ถูกตัดกลางคันได้', () => {
    const { frames, parser } = collect();
    parser.push('event: notif');
    parser.push('ication\ndata: {"id"');
    parser.push(':2}\n\n');
    expect(frames).toEqual([{ event: 'notification', data: '{"id":2}' }]);
  });

  it('รองรับ \\r\\n (CRLF) จาก proxy บางตัว', () => {
    const { frames, parser } = collect();
    parser.push('event: ready\r\ndata: {}\r\n\r\n');
    expect(frames).toEqual([{ event: 'ready', data: '{}' }]);
  });

  it('ข้ามบรรทัด heartbeat/comment ที่เริ่มด้วย ":"', () => {
    const { frames, parser } = collect();
    parser.push(': ping\n\nevent: ready\ndata: {}\n\n');
    expect(frames).toEqual([{ event: 'ready', data: '{}' }]);
  });

  it('รวม data หลายบรรทัดด้วย \\n ตามสเปก SSE', () => {
    const { frames, parser } = collect();
    parser.push('data: line1\ndata: line2\n\n');
    expect(frames).toEqual([{ event: 'message', data: 'line1\nline2' }]);
  });

  it('ค่าเริ่มต้นของ event คือ "message"', () => {
    const { frames, parser } = collect();
    parser.push('data: {"id":9}\n\n');
    expect(frames[0]?.event).toBe('message');
  });

  it('flush() เก็บ frame สุดท้ายที่ไม่มีบรรทัดว่างปิดท้าย', () => {
    const { frames, parser } = collect();
    parser.push('event: notification\ndata: {"id":3}');
    expect(frames).toHaveLength(0);
    parser.flush();
    expect(frames).toEqual([{ event: 'notification', data: '{"id":3}' }]);
  });

  it('flush() ไม่เรียก handler เมื่อไม่มีอะไรค้าง', () => {
    const handle = vi.fn<(event: string, data: string) => void>();
    const parser = createSseParser(handle);
    parser.push('\n\n');
    parser.flush();
    expect(handle).not.toHaveBeenCalled();
  });

  it('reset() ทิ้งข้อมูลค้าง (ใช้เมื่อต่อใหม่)', () => {
    const { frames, parser } = collect();
    parser.push('event: notification\ndata: {"id":4}');
    parser.reset();
    parser.push('data: {"id":5}\n\n');
    expect(frames).toEqual([{ event: 'message', data: '{"id":5}' }]);
  });

  it('ไม่เรียก handler สำหรับ frame ที่ไม่มี data', () => {
    const { frames, parser } = collect();
    parser.push('event: ready\n\n');
    expect(frames).toHaveLength(0);
  });
});
