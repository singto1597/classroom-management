/**
 * Type shim สำหรับ `thai-address-database`
 *
 * แพ็กเกจนี้ไม่ได้แนบไฟล์ .d.ts มาให้ (ดู node_modules/thai-address-database/package.json → main: lib/index.js)
 * โครงสร้างด้านล่างอ้างอิงจาก `exports.*` ตัวจริงใน lib/index.js โดยตรง
 * จึงทำให้เรียกใช้ได้โดยไม่ต้องใช้ @ts-ignore และไม่ต้องใช้ any
 */
declare module 'thai-address-database' {
  /**
   * หนึ่งรายการผลลัพธ์จาก searchAddressBy*
   * ฟิลด์ alias (subdistrict/tambon/changwat/postcode) เป็นการรองรับฐานข้อมูลคนละชุดข้อมูล
   * ซึ่งของจริงอาจส่งชื่อฟิลด์ต่างกัน — จึงประกาศเป็น optional ไว้ตามที่โค้ดผู้เรียกตรวจสอบไว้
   */
  export interface ThaiAddressRecord {
    district?: string;
    subdistrict?: string;
    tambon?: string;
    amphoe?: string;
    province?: string;
    changwat?: string;
    zipcode?: string | number;
    postcode?: string | number;
  }

  /** ลายเซ็นของฟังก์ชันค้นหาที่อยู่ทั้ง 4 ตัว (คืน [] เสมอเมื่อไม่พบ) */
  export type ThaiAddressSearchFn = (searchStr: string, maxResult?: number) => ThaiAddressRecord[];

  /** ผลลัพธ์จากการแยกที่อยู่เต็ม */
  export interface ThaiAddressSplitResult {
    address: string;
    district: string;
    amphoe: string;
    province: string;
    zipcode: string;
  }

  export const searchAddressByDistrict: ThaiAddressSearchFn;
  export const searchAddressByAmphoe: ThaiAddressSearchFn;
  export const searchAddressByProvince: ThaiAddressSearchFn;
  export const searchAddressByZipcode: ThaiAddressSearchFn;
  export function splitAddress(fullAddress: string): ThaiAddressSplitResult | null;

  /** รูปร่างโมดูลทั้งก้อน — ใช้กับ `default` ที่ bundler (Vite) ห่อ CommonJS มาให้ */
  export interface ThaiAddressModule {
    searchAddressByDistrict: ThaiAddressSearchFn;
    searchAddressByAmphoe: ThaiAddressSearchFn;
    searchAddressByProvince: ThaiAddressSearchFn;
    searchAddressByZipcode: ThaiAddressSearchFn;
    splitAddress: (fullAddress: string) => ThaiAddressSplitResult | null;
  }

  const thaiAddressDatabase: ThaiAddressModule;
  export default thaiAddressDatabase;
}
