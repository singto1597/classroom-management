import { describe, expect, it } from 'vitest';
import { defineComponent } from 'vue';
import { mount } from '@vue/test-utils';

import VoidReasonModal from '@/components/finance/VoidReasonModal.vue';

/**
 * 🚫 `VoidReasonModal` — โหมดบังคับเหตุผล / ไม่บังคับ (legacy revert)
 *
 * legacy endpoint (`revertTransaction`) ไม่รับ reason ⇒ ต้องซ่อนช่องเหตุผล
 * และยืนยันได้ทันที **โดยไม่ส่งข้อความหลอก ๆ** ไปให้ผู้เรียก
 */
const AppSheetStub = defineComponent({
  name: 'AppSheet',
  props: {
    open: { type: Boolean, default: false },
    title: { type: String, default: '' },
  },
  emits: ['close'],
  template: '<div v-if="open" data-test="sheet"><slot /><slot name="footer" /></div>',
});

const mountModal = (props: Record<string, unknown> = {}) =>
  mount(VoidReasonModal, {
    props: { open: true, title: 'ยกเลิกเอกสาร', ...props },
    global: { stubs: { AppSheet: AppSheetStub } },
  });

const confirmButton = (wrapper: ReturnType<typeof mountModal>) => {
  const buttons = wrapper.findAll('button');
  return buttons[buttons.length - 1]!;
};

describe('VoidReasonModal', () => {
  it('โหมดบังคับ: ปุ่มยืนยันปิดจนกว่าจะพิมพ์เหตุผล แล้ว emit เหตุผลที่ trim', async () => {
    const wrapper = mountModal();
    const textarea = wrapper.find('textarea');
    expect(textarea.exists()).toBe(true);
    expect(confirmButton(wrapper).attributes('disabled')).toBeDefined();

    await textarea.setValue('  บันทึกผิดคน  ');
    expect(confirmButton(wrapper).attributes('disabled')).toBeUndefined();

    await confirmButton(wrapper).trigger('click');
    expect(wrapper.emitted('confirm')?.[0]).toEqual(['บันทึกผิดคน']);
  });

  it('โหมดไม่บังคับ: ซ่อนช่องเหตุผลและยืนยันได้ทันที (ไม่ส่ง reason)', async () => {
    const wrapper = mountModal({ reasonRequired: false, confirmText: 'ยืนยันย้อนกลับรายการ' });
    expect(wrapper.find('textarea').exists()).toBe(false);
    expect(confirmButton(wrapper).attributes('disabled')).toBeUndefined();

    await confirmButton(wrapper).trigger('click');
    expect(wrapper.emitted('confirm')?.[0]).toEqual(['']);
  });

  it('แสดง errorMessage ในกล่องแดงโดยไม่ปิด sheet', () => {
    const wrapper = mountModal({ errorMessage: 'บิลนี้ถูกอ้างถึงโดยใบเสร็จแล้ว' });
    expect(wrapper.find('[role="alert"]').text()).toContain('บิลนี้ถูกอ้างถึง');
    expect(wrapper.find('[data-test="sheet"]').exists()).toBe(true);
  });
});
