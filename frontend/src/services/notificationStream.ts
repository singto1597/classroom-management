/**
 * 📡 สตรีมแจ้งเตือนสด (SSE) — ใช้ `fetch()` ไม่ใช่ `EventSource`
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมไม่ใช้ `EventSource`
 * ═══════════════════════════════════════════════════════════════════════════
 * `EventSource` แนบ header เองไม่ได้ ⇒ ต้องส่ง token ทาง query string
 * ซึ่งจะไปปรากฏใน access log ของ nginx/Cloudflare/ตัวเก็บ log ใดก็ตาม
 * ⇒ ใช้ `fetch()` อ่าน `response.body` แล้วแยก frame เอง (แบบเดียวกับที่ backend
 * เขียนไว้ใน `routers/notification_router.py`)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * สัญญาณทั้งหมดมีแค่ "มีของใหม่" — ไม่มีเนื้อหาแจ้งเตือนในสตรีม
 * ═══════════════════════════════════════════════════════════════════════════
 * backend ส่ง `{id, user_id, room_id}` ⇒ ฝั่งนี้เรียก `refresh()` เพื่อดึงรายการ
 * ผ่าน API ปกติ · การแยกแบบนี้ทำให้ (1) สิทธิ์ตรวจที่ API เดียว (2) ข้อมูลไม่มีทาง
 * ค้างเป็นชุดเก่าในหน่วยความจำของสตรีม
 *
 * ⚠️ ต้องมี fallback: ทุกครั้งที่กลับมาที่แท็บ (`visibilitychange`) ให้ดึงรายการใหม่
 *    เพราะเบราว์เซอร์มือถือระงับ connection ตอนอยู่เบื้องหลังได้ทุกเมื่อ
 */

import { ACCESS_TOKEN_KEY } from '@/constants/storageKeys';
import { NotificationService } from './notification';

export type StreamStatus = 'idle' | 'connecting' | 'open' | 'retrying' | 'stopped';

export interface NotificationSignal {
  id?: number;
  user_id?: number;
  room_id?: number;
}

export interface NotificationStreamOptions {
  roomId: number;
  /** เรียกเมื่อมีแจ้งเตือนใหม่ (หรือเมื่อ reconnect สำเร็จ — เพื่อไม่ให้พลาดของระหว่างหลุด) */
  onSignal: (signal: NotificationSignal) => void;
  onStatus?: (status: StreamStatus) => void;
}

export interface NotificationStreamHandle {
  start: () => void;
  stop: () => void;
  status: () => StreamStatus;
}

/** เว้นช่วงก่อนลองใหม่ — ถอยหลังทวีคูณสูงสุด 30 วิ */
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

/**
 * ตัวแยก SSE frame จาก byte stream
 *
 * แยกเป็นฟังก์ชันบริสุทธิ์เพื่อ **ทดสอบได้โดยไม่ต้องมีเน็ต**
 * รับ chunk ที่อาจตัดกลาง frame แล้วคืนเฉพาะ frame ที่ครบ
 */
export function createSseParser(handle: (event: string, data: string) => void) {
  let buffer = '';

  const drain = () => {
    // frame คั่นด้วยบรรทัดว่าง — รองรับทั้ง \n และ \r\n
    let index = buffer.indexOf('\n\n');
    while (index !== -1) {
      const raw = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      parseFrame(raw, handle);
      index = buffer.indexOf('\n\n');
    }
  };

  return {
    push(chunk: string): void {
      buffer += chunk.replace(/\r\n/g, '\n');
      drain();
    },
    /** เรียกตอนจบสตรีม — frame สุดท้ายที่ไม่มีบรรทัดว่างปิดท้ายก็ยังนับ */
    flush(): void {
      if (buffer.trim() !== '') parseFrame(buffer, handle);
      buffer = '';
    },
    reset(): void {
      buffer = '';
    },
  };
}

function parseFrame(raw: string, handle: (event: string, data: string) => void): void {
  let event = 'message';
  const dataLines: string[] = [];

  for (const line of raw.split('\n')) {
    // บรรทัดเริ่มด้วย ':' = comment/heartbeat (`: ping`) — ไม่ใช่ข้อมูล
    if (line === '' || line.startsWith(':')) continue;
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    const value = colon === -1 ? '' : line.slice(colon + 1).replace(/^ /, '');

    if (field === 'event') event = value;
    else if (field === 'data') dataLines.push(value);
  }

  if (dataLines.length > 0) handle(event, dataLines.join('\n'));
}

/**
 * เปิดสตรีมของห้องหนึ่ง — คืน handle ที่ `stop()` ได้ทันที (ปิด socket จริง)
 *
 * ผู้เรียก (store) เป็นคนตัดสินใจว่าเมื่อไรควร `start()`/`stop()` เช่น
 * สลับห้อง = stop แล้ว start ใหม่ · แท็บถูกซ่อน = stop
 */
export function openNotificationStream(options: NotificationStreamOptions): NotificationStreamHandle {
  const { roomId, onSignal, onStatus } = options;

  let abortController: AbortController | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let attempt = 0;
  let current: StreamStatus = 'idle';
  let disposed = false;

  const setStatus = (status: StreamStatus) => {
    current = status;
    onStatus?.(status);
  };

  const clearTimer = () => {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const scheduleReconnect = () => {
    if (disposed) return;
    attempt += 1;
    const delay = Math.min(RECONNECT_BASE_MS * 2 ** (attempt - 1), RECONNECT_MAX_MS);
    setStatus('retrying');
    clearTimer();
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      void connect();
    }, delay);
  };

  const connect = async (): Promise<void> => {
    if (disposed) return;
    clearTimer();
    abortController = new AbortController();
    setStatus('connecting');

    const token = localStorage.getItem(ACCESS_TOKEN_KEY);
    const parser = createSseParser((event, data) => {
      if (event === 'ready') {
        // ต่อติดแล้ว — ผู้เรียกจะดึงรายการใหม่เอง (กันพลาดช่วงที่หลุด)
        attempt = 0;
        setStatus('open');
        onSignal({});
        return;
      }
      if (event !== 'notification') return;
      try {
        const signal = JSON.parse(data) as NotificationSignal;
        onSignal(signal);
      } catch (error) {
        console.warn('[stream] payload ไม่ใช่ JSON:', error);
      }
    });

    try {
      const response = await fetch(NotificationService.streamUrl(roomId), {
        method: 'GET',
        headers: {
          Accept: 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        signal: abortController.signal,
        // ห้ามให้เบราว์เซอร์ cache สตรีม (คนละคนกันจะได้ของของกัน)
        cache: 'no-store',
      });

      if (response.status === 401 || response.status === 403) {
        // token หมดอายุ/ไม่ใช่สมาชิก — ลองใหม่จะวนไม่มีที่สิ้นสุด
        setStatus('stopped');
        disposed = true;
        return;
      }

      if (!response.ok || !response.body) {
        throw new Error(`สตรีมตอบ ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      attempt = 0;
      // ⚠️ ไม่เรียก `onSignal` ที่นี่ — backend ส่ง `event: ready` ทันทีอยู่แล้ว
      //    ถ้าเรียกทั้งสองที่ ผู้ใช้จะโดนดึงรายการซ้ำสองรอบทุกครั้งที่ต่อใหม่

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        parser.push(decoder.decode(value, { stream: true }));
      }
      parser.flush();
      // สตรีมจบเอง (เช่น redeploy) — ถือเป็นเหตุให้ต่อใหม่ ไม่ใช่ error ถาวร
      if (!disposed) scheduleReconnect();
    } catch (error) {
      if (disposed) return;
      // ยกเลิกเพราะ `stop()` = ไม่ใช่ความผิดพลาด
      if (error instanceof DOMException && error.name === 'AbortError') return;
      console.warn('[stream] การเชื่อมต่อขาด:', error);
      scheduleReconnect();
    }
  };

  return {
    start(): void {
      disposed = false;
      attempt = 0;
      void connect();
    },
    stop(): void {
      disposed = true;
      clearTimer();
      abortController?.abort();
      abortController = null;
      setStatus('stopped');
    },
    status: () => current,
  };
}
