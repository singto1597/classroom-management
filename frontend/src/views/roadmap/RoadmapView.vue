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
  president: '👑',
  vice_academic: '📚',
  vice_activity: '🎭',
  vice_discipline: '⚖️',
  vice_reception: '🤝',
  staff_academic: '📝',
  staff_activity: '🎪',
  staff_discipline: '🛡️',
  staff_reception: '🎀',
  treasurer: '💰',
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
const getRoleIcon = (role: string) => roleToIcon[role] ?? '🎖️';
</script>

<template>
  <div class="min-h-screen bg-slate-50 py-8 md:py-10">
    <div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
      <header class="mb-8">
        <h1 class="text-2xl md:text-3xl font-black text-slate-800 tracking-tight">
          <i class="bi bi-diagram-3-fill text-blue-600 mr-3"></i>แผนผังห้องเรียน
        </h1>
        <p class="text-slate-500 font-medium text-sm mt-2">แสดงโครงสร้างการบริหารห้องเรียนตามตำแหน่งต่าง ๆ</p>
      </header>

      <div v-if="isLoading" class="flex justify-center py-24">
        <div class="animate-spin rounded-full h-12 w-12 border-4 border-slate-200 border-t-blue-600"></div>
      </div>

      <div v-else class="bg-white rounded-[2.5rem] shadow-sm border border-slate-200 p-6 md:p-10">
        <div class="org-chart overflow-x-auto">
          <ul class="tree">
            <li v-if="president">
              <div class="node node-top">
                <div class="text-4xl mb-2">{{ getRoleIcon('president') }}</div>
                <p class="text-lg font-black text-white">{{ president.first_name }} {{ president.last_name }}</p>
                <p class="text-[10px] uppercase tracking-widest text-blue-100 font-bold">{{ getRoleLabel('president') }}</p>
              </div>

              <ul v-if="leadershipNodes.length" class="tree">
                <li v-for="node in leadershipNodes" :key="node.role">
                  <div class="node node-level-2">
                    <div class="text-3xl mb-1">{{ node.student ? getRoleIcon(node.role) : '➖' }}</div>
                    <p class="font-bold text-slate-700 text-sm">{{ node.student ? `${node.student.first_name} ${node.student.last_name}` : 'ว่าง' }}</p>
                    <p class="text-[10px] uppercase tracking-widest text-slate-400 font-bold">{{ node.label }}</p>
                  </div>

                  <ul v-if="node.staff.length" class="tree">
                    <li v-for="staff in node.staff" :key="staff.id">
                      <div class="node node-sm">
                        <p class="font-bold text-slate-600 text-xs">{{ staff.first_name }} {{ staff.last_name }}</p>
                        <p class="text-[10px] text-slate-400">{{ getRoleLabel(staff.class_role) }}</p>
                      </div>
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
  padding-top: 20px;
  position: relative;
}
.org-chart .tree ul::before {
  content: '';
  position: absolute;
  top: 0;
  left: 50%;
  border-left: 2px solid #cbd5e1;
  width: 0;
  height: 20px;
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
  height: 20px;
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
  min-width: 150px;
}
.org-chart .node:hover {
  box-shadow: 0 12px 30px rgba(59, 130, 246, 0.1);
  border-color: #bfdbfe;
  transform: translateY(-2px);
}
.node-top {
  background: linear-gradient(145deg, #1e293b, #334155);
  color: white;
  border: none;
  box-shadow: 0 12px 30px rgba(30, 41, 59, 0.25);
}
.node-top p {
  color: white !important;
}
.node-level-2 {
  background: #f8fafc;
}
.node-sm {
  padding: 0.75rem 1rem;
  border-radius: 1rem;
  min-width: 120px;
}
</style>
