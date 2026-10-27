import { useRouter } from 'vue-router';
import Swal from 'sweetalert2';
import { StudentService } from '@/services/student';
import { useAuthStore } from '@/stores/auth';
import { UI_COLOR } from '@/constants/theme';

/**
 * 🪪 กล่องโต้ตอบเกี่ยวกับโปรไฟล์/บัญชีที่ header และ sidebar ใช้ร่วมกัน
 *
 * แยกออกจาก `useAppShell` เพราะเป็น "เนื้อหาหน้าต่าง" ไม่ใช่สถานะเปลือกแอป
 * และทำให้การทดสอบในอนาคตไม่ต้อง mount layout ทั้งตัว
 */
export function useProfileDialogs() {
  const authStore = useAuthStore();
  const router = useRouter();

  /** เปิดโปรไฟล์นักเรียนของตัวเอง — admin ที่ไม่มีแถวในห้องนี้จะเห็นคำอธิบายแทน */
  const goToMyProfile = async () => {
    try {
      Swal.fire({
        title: 'กำลังโหลดข้อมูล...',
        allowOutsideClick: false,
        didOpen: () => Swal.showLoading(),
      });
      const myProfile = await StudentService.getMyProfile(authStore.currentRoomId!);
      Swal.close();
      router.push(`/students/${myProfile.student_no}`);
    } catch {
      Swal.fire({
        icon: 'warning',
        title: 'ไม่สามารถเข้าถึงได้',
        text: 'คุณอาจเป็นผู้ดูแลระบบ (Admin) ที่ไม่มีข้อมูลในรายชื่อนักเรียนห้องนี้',
        confirmButtonColor: UI_COLOR.brand,
      });
    }
  };

  /** ข้อมูลบัญชีแบบอ่านอย่างเดียว (Discord ID + บทบาทในห้อง) */
  const showAccountInfo = () => {
    Swal.fire({
      title: '<span style="font-family:Anuphan;font-weight:700">ข้อมูลบัญชีระบบ</span>',
      html: `
        <div style="text-align:left;margin-top:18px;display:flex;flex-direction:column;gap:14px">
          <div style="display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid ${UI_COLOR.border};padding-bottom:12px">
            <span style="font-size:13px;color:${UI_COLOR.neutral};font-weight:600">Discord ID</span>
            <span style="font-family:ui-monospace,monospace;font-size:13px;font-weight:700;color:${UI_COLOR.ink}">${authStore.discordId || 'ยังไม่ระบุ'}</span>
          </div>
          <div style="display:flex;align-items:center;justify-content:space-between">
            <span style="font-size:13px;color:${UI_COLOR.neutral};font-weight:600">บทบาทในห้อง</span>
            <span style="font-size:12px;font-weight:700;color:${UI_COLOR.brand};background:${UI_COLOR.brandSoft};padding:4px 10px;border-radius:8px">${authStore.currentRoleLabel}</span>
          </div>
        </div>
      `,
      icon: 'info',
      confirmButtonText: 'ปิดหน้าต่าง',
      confirmButtonColor: UI_COLOR.brand,
    });
  };

  /** หน้าต่างจัดการผูกบัญชี Google/Discord */
  const goToProfileSettings = async () => {
    Swal.fire({
      title: 'กำลังโหลดข้อมูล...',
      allowOutsideClick: false,
      didOpen: () => Swal.showLoading(),
    });
    await authStore.fetchProfile();
    Swal.close();

    const isDiscordLinked = !!authStore.discordId;
    const isGoogleLinked = !!authStore.googleId;

    const discordScope = encodeURIComponent('identify email');
    const discordUrl = `https://discord.com/api/oauth2/authorize?client_id=${import.meta.env.VITE_DISCORD_CLIENT_ID}&redirect_uri=${encodeURIComponent(import.meta.env.VITE_DISCORD_REDIRECT_URI)}&response_type=code&scope=${discordScope}`;

    const googleScope = encodeURIComponent('openid email profile');
    const googleUrl = `https://accounts.google.com/o/oauth2/v2/auth?client_id=${import.meta.env.VITE_GOOGLE_CLIENT_ID}&redirect_uri=${encodeURIComponent(import.meta.env.VITE_GOOGLE_REDIRECT_URI)}&response_type=code&scope=${googleScope}`;

    const row = (linked: boolean, label: string, sub: string, icon: string, href: string) => `
      <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px;border-radius:14px;border:1px solid ${linked ? UI_COLOR.okBorder : UI_COLOR.border};background:${linked ? UI_COLOR.okSoft : UI_COLOR.white}">
        <div style="display:flex;align-items:center;gap:12px;min-width:0">
          <div style="width:40px;height:40px;border-radius:12px;background:${UI_COLOR.surface};display:flex;align-items:center;justify-content:center;flex-shrink:0">
            <i class="${icon}" style="font-size:18px"></i>
          </div>
          <div style="text-align:left;min-width:0">
            <p style="font-weight:700;color:${UI_COLOR.ink};margin:0;font-size:14px">${label}</p>
            <p style="font-size:11px;font-weight:700;margin:2px 0 0;color:${linked ? UI_COLOR.ok : UI_COLOR.subtle}">${linked ? 'เชื่อมต่อแล้ว' : sub}</p>
          </div>
        </div>
        ${!linked ? `<a href="${href}" style="flex-shrink:0;padding:8px 16px;background:${UI_COLOR.brand};color:${UI_COLOR.white};font-size:12px;font-weight:700;border-radius:10px;text-decoration:none">ผูกบัญชี</a>` : ''}
      </div>
    `;

    Swal.fire({
      title: '<span style="font-family:Anuphan;font-weight:700;font-size:19px">จัดการบัญชีและการเชื่อมต่อ</span>',
      html: `
        <div style="text-align:left;display:flex;flex-direction:column;gap:12px;margin-top:16px">
          <p style="font-size:13px;color:${UI_COLOR.neutral};margin:0">เชื่อมต่อแพลตฟอร์มต่างๆ เพื่อรวมข้อมูลของคุณให้เป็นหนึ่งเดียว ป้องกันการสูญหาย</p>
          ${row(isGoogleLinked, 'Google Account', 'ยังไม่ได้เชื่อมต่อ', 'bi bi-google', googleUrl)}
          ${row(isDiscordLinked, 'Discord Account', 'ยังไม่ได้เชื่อมต่อ', 'bi bi-discord', discordUrl)}
        </div>
      `,
      showConfirmButton: true,
      confirmButtonText: 'ปิดหน้าต่าง',
      confirmButtonColor: UI_COLOR.brand,
    });
  };

  return { goToMyProfile, showAccountInfo, goToProfileSettings };
}
