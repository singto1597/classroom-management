import { describe, it, expect } from 'vitest';
import { routes } from '@/router/routes';
import { NAV_ITEMS, NAV_TABS, MORE_NAV_ITEMS, routeTitles } from '@/constants/nav';
import { pageTitle, DEFAULT_TITLE, APP_NAME } from '@/router/meta';

/**
 * 🗺️ ล็อกสัญญาของตาราง route
 *
 * เทสต์ชุดนี้แทน "คนที่ต้องไล่เปิดไฟล์ router ทุกครั้งที่เพิ่มหน้า" —
 * ถ้าเพิ่มหน้าใหม่แล้วลืมตั้งชื่อ/ลืม navTab CI จะพังทันที
 * (เดิมความผิดพลาดแบบนี้เงียบสนิท: แท็บเบราว์เซอร์ค้างชื่อหน้าเก่า)
 */

interface FlatRoute {
  name: string | undefined;
  /** path เต็ม เช่น `/students/:id` */
  path: string;
  title: string | undefined;
  navTab: string | undefined;
  requiresAuth: boolean | undefined;
  isCatchAll: boolean;
}

function joinPath(parent: string, child: string): string {
  if (child.startsWith('/')) return child;
  return `${parent.replace(/\/$/, '')}/${child}`;
}

function flatten(records: unknown[], parentPath = ''): FlatRoute[] {
  return records.flatMap((raw) => {
    const record = raw as {
      path: string;
      name?: string;
      meta?: { title?: string; navTab?: string; requiresAuth?: boolean };
      children?: unknown[];
    };
    const fullPath = joinPath(parentPath, record.path);
    const self: FlatRoute = {
      name: record.name,
      path: fullPath,
      title: record.meta?.title,
      navTab: record.meta?.navTab,
      requiresAuth: record.meta?.requiresAuth,
      isCatchAll: fullPath.includes(':pathMatch'),
    };
    return record.children ? [self, ...flatten(record.children, fullPath)] : [self];
  });
}

const flat = flatten(routes);
const namedRoutes = flat.filter((r): r is FlatRoute & { name: string } => Boolean(r.name));

describe('ทุก route ต้องมีชื่อหน้า (meta.title)', () => {
  it('มี route ที่มีชื่ออยู่จริง (กันเทสต์ผ่านเพราะลิสต์ว่าง)', () => {
    expect(namedRoutes.length).toBeGreaterThan(20);
  });

  it.each(namedRoutes.map((r) => [r.name, r.title] as const))(
    'route "%s" มี title',
    (_name, title) => {
      expect(typeof title).toBe('string');
      expect((title ?? '').trim().length).toBeGreaterThan(0);
    },
  );

  it('ชื่อ route ไม่ซ้ำ', () => {
    const names = namedRoutes.map((r) => r.name);
    expect(new Set(names).size).toBe(names.length);
  });
});

describe('catch-all 404', () => {
  it('เป็น route สุดท้ายเสมอ — ถ้าอยู่ก่อนจะกลืนทุกหน้า', () => {
    expect(flat[flat.length - 1]?.isCatchAll).toBe(true);
  });

  it('ชื่อ not-found และไม่บังคับล็อกอิน', () => {
    const catchAll = flat[flat.length - 1];
    expect(catchAll?.name).toBe('not-found');
    expect(catchAll?.requiresAuth).toBe(false);
  });

  it('มี catch-all แค่ตัวเดียว', () => {
    expect(flat.filter((r) => r.isCatchAll)).toHaveLength(1);
  });
});

describe('เมนู (constants/nav.ts) ต้องชี้ path ที่มีจริง', () => {
  const leafPaths = new Set(flat.map((r) => r.path));

  it.each(NAV_ITEMS.map((item) => [item.name, item.path] as const))(
    'เมนู "%s" (%s) มี route รองรับ',
    (_name, path) => {
      expect(leafPaths.has(path)).toBe(true);
    },
  );

  it('แท็บมือถือทุกแท็บต้องมีอยู่ในเมนูหลักด้วย', () => {
    const menuPaths = new Set(NAV_ITEMS.map((item) => item.path));
    for (const tab of NAV_TABS) {
      expect(menuPaths.has(tab.path)).toBe(true);
    }
  });

  it('ชีต "เพิ่มเติม" = เมนูหลักลบแท็บล่าง', () => {
    const tabPaths = new Set(NAV_TABS.map((tab) => tab.path));
    const expected = NAV_ITEMS.filter((item) => !tabPaths.has(item.path));
    expect(MORE_NAV_ITEMS).toEqual(expected);
  });

  it('ไม่มี path เมนูซ้ำกัน', () => {
    const paths = NAV_ITEMS.map((item) => item.path);
    expect(new Set(paths).size).toBe(paths.length);
  });
});

describe('routeTitles — แหล่งเดียวของชื่อหน้า', () => {
  it('ทุกคีย์ถูกใช้จริง (ไม่มีชื่อค้างหลังลบหน้า)', () => {
    const used = new Set(namedRoutes.map((r) => r.name));
    const unused = Object.keys(routeTitles).filter((key) => !used.has(key));
    expect(unused).toEqual([]);
  });

  it('ทุก route ที่มีชื่อต้องมีคีย์ใน routeTitles', () => {
    const declared = new Set(Object.keys(routeTitles));
    const missing = namedRoutes.filter((r) => !declared.has(r.name)).map((r) => r.name);
    expect(missing).toEqual([]);
  });
});

describe('navTab ใต้ MainLayout', () => {
  const mainLayoutChildren = flat.filter(
    (r) => r.path.startsWith('/') && !r.path.startsWith('/lobby') && r.name && !r.isCatchAll,
  );
  const appPages = mainLayoutChildren.filter(
    (r) =>
      ![
        'login',
        'google-callback',
        'discord-callback',
        'onboarding',
        'lobby',
      ].includes(r.name ?? ''),
  );

  it('ทุกหน้าในแอปประกาศ navTab', () => {
    const missing = appPages.filter((r) => !r.navTab).map((r) => r.name);
    expect(missing).toEqual([]);
  });

  it('navTab ใช้ค่าในชุดที่กำหนด', () => {
    const allowed = new Set(['home', 'students', 'finance', 'more']);
    for (const route of appPages) {
      expect(allowed.has(route.navTab ?? '')).toBe(true);
    }
  });
});

describe('pageTitle', () => {
  it('ต่อท้ายด้วยชื่อแอป', () => {
    expect(pageTitle('นักเรียน')).toBe(`นักเรียน · ${APP_NAME}`);
  });

  it('ไม่มีชื่อหน้า ⇒ ชื่อแอปเต็ม', () => {
    expect(pageTitle(undefined)).toBe(DEFAULT_TITLE);
    expect(pageTitle('   ')).toBe(DEFAULT_TITLE);
  });
});
