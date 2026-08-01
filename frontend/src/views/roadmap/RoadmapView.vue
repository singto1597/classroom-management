<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useAuthStore } from '@/stores/auth';
import { StudentService } from '@/services/student';
import type { Student } from '@/types/student';
import Swal from 'sweetalert2';

interface TreeNode {
  role: string;
  label: string;
  student: Student | null;
  staff: Student[];
}

const authStore = useAuthStore();
const roomId = authStore.currentRoomId!;
const students = ref<Student[]>([]);
const isLoading = ref(true);

const roleToLabel: Record<string, string> = {
  president: 'หัวหน้าห้อง',
  vice_academic: 'รองฯ วิชาการ',
  vice_activity: 'รองฯ กิจกรรม',
  vice_discipline: 'รองฯ ระเบียบวินัย',
  vice_reception: 'รองฯ ปฏิคม',
  staff_academic: 'กรรมการวิชาการ',
  staff_activity: 'กรรมการกิจกรรม',
  staff_discipline: 'กรรมการระเบียบวินัย',
  staff_reception: 'กรรมการปฏิคม',
  treasurer: 'เหรัญญิก',
};

const roleToIcon: Record<string, string> = {
  president: 'bi-award-fill',
  vice_academic: 'bi-book-fill',
  vice_activity: 'bi-music-note-beamed',
  vice_discipline: 'bi-shield-fill-check',
  vice_reception: 'bi-people-fill',
  staff_academic: 'bi-journal-text',
  staff_activity: 'bi-star-fill',
  staff_discipline: 'bi-shield-fill-exclamation',
  staff_reception: 'bi-emoji-smile-fill',
  treasurer: 'bi-cash-coin',
};

const viceToStaff: Record<string, string> = {
  vice_academic: 'staff_academic',
  vice_activity: 'staff_activity',
  vice_discipline: 'staff_discipline',
  vice_reception: 'staff_reception',
};

const findStudentByRole = (role: string): Student | null =>
  students.value.find((s) => s.class_role === role) ?? null;

const president = computed(() => findStudentByRole('president'));

const viceRoles = ['vice_academic', 'vice_activity', 'vice_discipline', 'vice_reception'] as const;

const viceNodes = computed<TreeNode[]>(() =>
  viceRoles.map((role) => {
    const student = findStudentByRole(role);
    const staffRole = viceToStaff[role];
    const staff = students.value.filter((s) => s.class_role === staffRole);
    return {
      role,
      label: roleToLabel[role] ?? role,
      student,
      staff,
    };
  })
);

const treasurerNode = computed<TreeNode>(() => {
  const student = findStudentByRole('treasurer');
  return {
    role: 'treasurer',
    label: roleToLabel['treasurer'] ?? 'เหรัญญิก',
    student,
    staff: [],
  };
});

const leadershipNodes = computed<TreeNode[]>(() => [...viceNodes.value, treasurerNode.value]);

const fetchStudents = async () => {
  isLoading.value = true;
  try {
    const data = await StudentService.getStudents(roomId);
    students.value = Array.isArray(data) ? data : [];
  } catch (error) {
    Swal.fire({
      icon: 'error',
      title: 'โหลดข้อมูลไม่สำเร็จ',
      text: 'ไม่สามารถดึงข้อมูลรายชื่อนักเรียนได้',
    });
  } finally {
    isLoading.value = false;
  }
};

onMounted(fetchStudents);

const getRoleLabel = (role: string) => roleToLabel[role] ?? role;
const getRoleIcon = (role: string) => roleToIcon[role] ?? 'bi-person-fill';
const getStudentLink = (student: Student) => `/students/${student.student_no}`;
const displayName = (student: Student) => student.nickname || `${student.first_name} ${student.last_name}`;
</script>

<template>
  <div class="min-h-screen bg-slate-50 py-8 md:py-12">
    <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
      <header class="mb-10">
        <div class="flex items-start sm:items-center gap-4">
          <span class="w-12 h-12 rounded-2xl bg-blue-600/10 text-blue-600 flex items-center justify-center text-3xl shadow-sm">
            <i class="bi bi-diagram-3-fill"></i>
          </span>
          <div>
            <h1 class="text-2xl md:text-3xl font-black text-slate-800 tracking-tight">แผนผังห้องเรียน</h1>
            <p class="text-slate-500 font-medium text-sm mt-1">แสดงโครงสร้างการบริหารห้องเรียนตามตำแหน่งต่าง ๆ</p>
          </div>
        </div>
      </header>

      <div v-if="isLoading" class="flex justify-center py-24">
        <div class="animate-spin rounded-full h-12 w-12 border-4 border-slate-200 border-t-blue-600"></div>
      </div>

      <div v-else class="bg-white rounded-[2.5rem] shadow-sm border border-slate-100 p-6 md:p-10">
        <div class="org-chart overflow-x-auto">
          <ul class="tree">
            <li v-if="president">
              <RouterLink :to="getStudentLink(president)" class="node node-top">
                <div class="node-icon">
                  <i :class="`bi ${getRoleIcon('president')}`"></i>
                </div>
                <p class="node-name">{{ displayName(president) }}</p>
                <p class="node-role">{{ getRoleLabel('president') }}</p>
                <span class="node-number">เลขที่ {{ president.student_no }}</span>
              </RouterLink>

              <ul v-if="leadershipNodes.length" class="tree">
                <li v-for="node in leadershipNodes" :key="node.role">
                  <RouterLink
                    v-if="node.student"
                    :to="getStudentLink(node.student)"
                    class="node node-level-2"
                  >
                    <div class="node-icon">
                      <i :class="`bi ${getRoleIcon(node.role)}`"></i>
                    </div>
                    <p class="node-name">{{ displayName(node.student) }}</p>
                    <p class="node-role">{{ node.label }}</p>
                    <span class="node-number">เลขที่ {{ node.student.student_no }}</span>
                  </RouterLink>

                  <div v-else class="node node-level-2 node-empty">
                    <div class="node-icon">
                      <i :class="`bi ${getRoleIcon(node.role)}`"></i>
                    </div>
                    <p class="node-name">{{ node.label }}</p>
                    <p class="node-role">ว่าง</p>
                  </div>

                  <ul v-if="node.staff.length" class="tree">
                    <li v-for="staff in node.staff" :key="staff.id">
                      <RouterLink :to="getStudentLink(staff)" class="node node-sm">
                        <p class="node-name">{{ displayName(staff) }}</p>
                        <p class="node-role">{{ getRoleLabel(staff.class_role) }}</p>
                        <span class="node-number">เลขที่ {{ staff.student_no }}</span>
                      </RouterLink>
                    </li>
                  </ul>
                </li>
              </ul>
            </li>

            <li v-else>
              <div class="node">
                <p class="text-slate-400 font-bold">ยังไม่มีข้อมูลการบริหารห้อง</p>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.org-chart .tree {
  list-style: none;
  padding: 0;
  margin: 0;
  text-align: center;
}
.org-chart .tree ul {
  padding-top: 24px;
  position: relative;
}
.org-chart .tree ul::before {
  content: '';
  position: absolute;
  top: 0;
  left: 50%;
  border-left: 2px solid #cbd5e1;
  width: 0;
  height: 24px;
}
.org-chart .tree li {
  display: inline-block;
  vertical-align: top;
  text-align: center;
  list-style: none;
  padding: 20px 5px;
  position: relative;
}
.org-chart .tree li::before,
.org-chart .tree li::after {
  content: '';
  position: absolute;
  top: 0;
  right: 50%;
  border-top: 2px solid #cbd5e1;
  width: 50%;
  height: 24px;
}
.org-chart .tree li::after {
  right: auto;
  left: 50%;
  border-left: 2px solid #cbd5e1;
}
.org-chart .tree li:only-child::before,
.org-chart .tree li:only-child::after {
  display: none;
}
.org-chart .tree li:only-child {
  padding: 0;
}
.org-chart .tree li:first-child::before,
.org-chart .tree li:last-child::after {
  border: 0 none;
}
.org-chart .tree li:last-child::before {
  border-right: 2px solid #cbd5e1;
  border-radius: 0 15px 0 0;
}
.org-chart .tree li:first-child::after {
  border-radius: 15px 0 0 0;
}
.org-chart .node {
  display: inline-block;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 1.5rem;
  padding: 1rem 1.5rem;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.04);
  transition: all 0.3s;
  min-width: 160px;
  text-align: center;
  text-decoration: none;
  color: #1e293b;
  cursor: pointer;
}
.org-chart .node:hover {
  box-shadow: 0 12px 30px rgba(59, 130, 246, 0.15);
  border-color: #bfdbfe;
  transform: translateY(-2px);
  background: #f8fafc;
}
.org-chart .node-top {
  background: #f1f5f9;
  border-color: #bfdbfe;
  border-width: 2px;
}
.org-chart .node-top .node-icon {
  color: #2563eb;
}
.org-chart .node-level-2 {
  background: #f9fafb;
}
.org-chart .node-sm {
  padding: 0.75rem 1rem;
  border-radius: 1rem;
  min-width: 130px;
}
.org-chart .node-empty {
  cursor: default;
}
.org-chart .node-empty:hover {
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.04);
  border-color: #e2e8f0;
  transform: none;
  background: #f9fafb;
}
.org-chart .node-icon {
  font-size: 1.9rem;
  line-height: 1;
  color: #64748b;
  margin-bottom: 0.3rem;
}
.org-chart .node-name {
  font-weight: 700;
  color: #1e293b;
  font-size: 0.95rem;
  margin: 0.15rem 0 0;
  line-height: 1.3;
}
.org-chart .node-role {
  font-size: 0.62rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;
  font-weight: 600;
  margin-top: 0.2rem;
}
.org-chart .node-number {
  font-size: 0.7rem;
  color: #94a3b8;
  font-weight: 500;
  margin-top: 0.2rem;
  display: inline-block;
}
</style>
