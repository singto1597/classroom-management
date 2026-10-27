import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { ClassroomService } from '@/services/classroom';
import { navSectionName } from '@/constants/nav';
import type { UserRoom } from '@/types/classroom';

/** ชื่อคีย์ localStorage ที่จำสถานะย่อ sidebar */
const COLLAPSE_KEY = 'syncroom_sidebar_collapsed';

export type ShellMenu = 'roomSwitcher' | 'headerSettings';

/**
 * 🧭 สถานะและคำสั่งของเปลือกแอป (sidebar · header · bottom nav · sheet)
 *
 * แยกออกจาก `MainLayout.vue` เพื่อให้ layout เหลือแค่การประกอบชิ้นส่วน
 * (DoD P1: ไฟล์ละ ≤250 บรรทัด) — สถานะยังอยู่ที่เดียว ไม่ใช่กระจายในคอมโพเนนต์ย่อย
 */
export function useAppShell() {
  const authStore = useAuthStore();
  const router = useRouter();
  const route = useRoute();

  const isMoreSheetOpen = ref(false);
  const isSidebarCollapsed = ref(false);
  const activeDropdown = ref<ShellMenu | null>(null);
  const dropdownStyle = ref<{ top: string; left: string; bottom?: string }>({
    top: '0px',
    left: '0px',
  });

  const displayName = computed(() => authStore.currentUserName);

  /** ชื่อเมนูแม่ของหน้าปัจจุบัน — ใช้ทำ breadcrumb */
  const currentSubMenuName = computed(() => navSectionName(route.path));

  // ✨ อักษรย่อจากชื่อเล่น (หรือชื่อจริง) — ตัวแรกของชื่อเท่านั้น
  const avatarChar = computed(() => {
    const name = authStore.nickname || authStore.firstName;
    return name && name !== 'ไม่ระบุชื่อ' ? name.charAt(0).toUpperCase() : 'ส';
  });

  /**
   * ดึงรายการห้องทั้งหมดมาเก็บใน store
   *
   * ทำที่ shell (ไม่ใช่แค่ Lobby) เพราะผู้ใช้ที่เปิด `/dashboard` ตรง ๆ — หรือเปิด
   * แท็บใหม่ — ไม่เคยผ่าน Lobby ในรอบนั้น ⇒ ถ้าไม่ดึงที่นี่จะไม่มีรายการห้องให้สลับเลย
   */
  const loadRooms = async () => {
    if (!authStore.userId) return;
    try {
      const list = await ClassroomService.getUserRooms(authStore.userId);
      authStore.setRooms(list);
    } catch (error: unknown) {
      // ดึงไม่ได้ = ใช้รายการที่แคชไว้ต่อ ดีกว่าเด้งผู้ใช้ออก
      console.error('Failed to load rooms:', error);
    }
  };

  const closeDropdowns = () => {
    activeDropdown.value = null;
  };

  const closeMoreSheet = () => {
    isMoreSheetOpen.value = false;
  };

  const openMoreSheet = () => {
    closeDropdowns();
    isMoreSheetOpen.value = true;
  };

  /** เปิด/ปิด dropdown และวางตำแหน่งให้ไม่ล้นจอ */
  const toggleDropdown = (event: MouseEvent, menu: ShellMenu) => {
    if (activeDropdown.value === menu) {
      closeDropdowns();
      return;
    }

    activeDropdown.value = menu;

    const trigger = event.currentTarget as HTMLElement;
    const rect = trigger.getBoundingClientRect();
    const panelWidth = 240;
    const panelHeight = menu === 'headerSettings' ? 300 : 220;

    let left = rect.right - panelWidth;
    left = Math.max(12, Math.min(left, window.innerWidth - panelWidth - 12));

    const spaceBelow = window.innerHeight - rect.bottom;

    if (spaceBelow < panelHeight) {
      dropdownStyle.value = {
        top: 'auto',
        bottom: `${window.innerHeight - rect.top + 8}px`,
        left: `${left}px`,
      };
    } else {
      dropdownStyle.value = {
        top: `${rect.bottom + 8}px`,
        bottom: 'auto',
        left: `${left}px`,
      };
    }
  };

  const toggleSidebarCollapse = () => {
    isSidebarCollapsed.value = !isSidebarCollapsed.value;
    localStorage.setItem(COLLAPSE_KEY, isSidebarCollapsed.value ? '1' : '0');
  };

  /**
   * ไปหน้าเลือกห้อง — **ไม่ล้างห้องที่เปิดอยู่**
   *
   * Lobby เป็นเพียงหน้าเลือกห้องที่กลับไปดูได้โดยไม่กระทบว่ากำลังทำงานอยู่ห้องไหน
   */
  const handleChangeRoom = () => {
    closeDropdowns();
    closeMoreSheet();
    router.push('/lobby');
  };

  /**
   * สลับไปห้องอื่นโดยไม่ต้องออกจากห้องเดิม
   *
   * ⚠️ ต้องพากลับ `/dashboard` ด้วย — หน้าปัจจุบันอาจอ้างข้อมูลเฉพาะห้องเดิม
   *    (เช่น `/students/12` หรือ `/finance/receipts/REC-...`) ซึ่งพอสลับห้องแล้ว
   *    ข้อมูลนั้นไม่มีอยู่จริง จะกลายเป็นหน้า error ทันที
   */
  const switchRoom = (room: UserRoom) => {
    closeDropdowns();
    closeMoreSheet();
    if (room.room_id === authStore.currentRoomId) return;

    authStore.setActiveRoom(room.room_id);
    if (route.path !== '/dashboard') router.push('/dashboard');
  };

  const logout = () => {
    closeDropdowns();
    closeMoreSheet();
    authStore.logout();
  };

  onMounted(async () => {
    isSidebarCollapsed.value = localStorage.getItem(COLLAPSE_KEY) === '1';
    if (authStore.isAuthenticated) {
      // 🔄 ต่ออายุ session ก่อนเป็นอันดับแรก — ถ้า token ใกล้ครบอายุ คำขอถัด ๆ ไป
      //    ในรอบนี้จะได้ใช้ token ใหม่ (ถูก throttle ไว้ จึงไม่ยิงทุกครั้งที่โหลดหน้า)
      await authStore.refreshSession();
      await authStore.fetchProfile();
      await loadRooms();
    }
    // 🔁 ปิด dropdown เมื่อเลื่อน/ย่อขยายหน้าจอ
    window.addEventListener('scroll', closeDropdowns, true);
    window.addEventListener('resize', closeDropdowns);
  });

  onUnmounted(() => {
    window.removeEventListener('scroll', closeDropdowns, true);
    window.removeEventListener('resize', closeDropdowns);
  });

  watch(
    () => route.path,
    () => {
      closeMoreSheet();
      closeDropdowns();
    },
  );

  return {
    authStore,
    displayName,
    avatarChar,
    currentSubMenuName,
    isMoreSheetOpen,
    isSidebarCollapsed,
    activeDropdown,
    dropdownStyle,
    toggleDropdown,
    closeDropdowns,
    openMoreSheet,
    closeMoreSheet,
    toggleSidebarCollapse,
    handleChangeRoom,
    switchRoom,
    logout,
  };
}
