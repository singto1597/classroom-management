# Classroom-Sync Knowledge Base (skill.md)

## 🛠 Lessons Learned & Audits

### 📝 [2026-05-16] Initial Project Audit Findings
จากการสำรวจโครงสร้างและกฎของโปรเจกต์ พบจุดที่ต้องระวังและปรับปรุงดังนี้:

1.  **Client No-Database Policy:** 
    *   **Lesson:** ทั้ง Discord Bot และ PHP Web ห้ามต่อ Database โดยตรงเด็ดขาด 
    *   **Finding:** พบว่าใน `readme.md` ของฝั่ง Client ยังมีคำแนะนำการติดตั้ง Database อยู่ ซึ่งอาจทำให้ Developer เข้าใจผิด ต้องยึดการใช้งานผ่าน API API เท่านั้น

2.  **Soft Delete Implementation:**
    *   **Rule:** ข้อมูลสำคัญ (เช่น นักเรียน, การเงิน) ต้องใช้ Soft Delete (`deleted_at`)
    *   **Finding:** พบโค้ดใน `student_service.py` ยังใช้ Hard Delete (`DELETE FROM students ...`) ซึ่งผิดกฎ ต้องเปลี่ยนเป็น Update `deleted_at` แทน

3.  **Code Organization (Backend):**
    *   **Lesson:** `main.py` ควรทำหน้าที่เป็นแค่จุดเริ่มระบบ (Entry Point) ไม่ควรมี SQL DDL (Create Table) เยอะเกินไป
    *   **Finding:** `main.py` รกด้วย Schema SQL ควรแยกออกไปไว้ในไฟล์จัดการ Schema หรือ Service เฉพาะทาง

4.  **Audit Logs Requirement:**
    *   **Rule:** ทุก Action ที่เปลี่ยนข้อมูล (POST, PUT, PATCH, DELETE) ต้องบันทึก `audit_logs` ใน Transaction เดียวกันเสมอ

---
*หมายเหตุ: ทุกครั้งที่แก้บั๊กซับซ้อน หรือเจอ Logic ใหม่ ให้บันทึกเพิ่มลงในไฟล์นี้*

### 🛠️ Auth Service - OAuth Linking Validation & Idempotency Patterns
- **Context/Problem:** Tests for `link_oauth_account` revealed that new edge-case tests failed because:
  - Discord profiles must use the `id` key while Google uses `sub`; using `sub` for Discord caused `KeyError: 'id'`.
  - Duplicate linking with the same provider but a *different* ID was silently allowed (only the same provider+same ID was treated as idempotent).
  - Unknown provider values weren't rejected via `ValidationError`; `ValidationError.from_exception_data()` also required an `error` field in the context, causing `TypeError: ValueError: 'error' required in context`.
- **Root Cause:** The `link_oauth_account` function didn't validate the provider before building the column name, didn't read the current user's existing provider ID (previously it only fetched `id, email, ...` without the provider column), and the `ValidationError` construction used an incorrect Pydantic v2 API.
- **Correct Pattern/Solution:**
  1. Always fetch the provider-specific column for the current user: `curr_user = await conn.fetchrow(f"SELECT id, email, phone_number, birthday, {provider_id_col} FROM users WHERE id = $1", current_user_id)`.
  2. After obtaining the new provider ID, compare it with the current user's existing value; if they differ, raise `ForbiddenError`.
  3. Validate `provider` early by using a sub-model with `Literal["google", "discord"]` instead of manually constructing `ValidationError.from_exception_data()`.
  4. In tests, give Discord the `id` key and Google the `sub` key in the profile dict, because the service expects those exact keys.
- **Date Added:** 2026-08-01

### 🛠️ Auth Test Suite - Patterns for 100% Pass
- **Context/Problem:** All tests in `backend/tests/test_auth.py` are now passing (100%). The main challenge was ensuring OAuth endpoints could be tested without external side effects (Discord/Google API calls, Redis) while still validating the database mutations.
- **Root Cause:** Earlier tests either attempted to call real OAuth providers, missed required fields in test user inserts, or used synchronous fixtures that didn't integrate with `pytest-asyncio`.
- **Correct Pattern/Solution:**
  1. Always use `@pytest.mark.asyncio` and async fixtures (`db_pool`, `client`, `admin_headers`).
  2. Mock every external network call (e.g., `exchange_code_for_token`, `get_discord_user_profile`, `get_google_user_info`) with `AsyncMock` and set proper return values.
  3. Insert users with explicit `google_id` and `discord_id` fields to control provider linking, and verify that provider-specific columns are read correctly.
  4. Use `clean_database` fixture for absolute state isolation; never hardcode IDs or rely on existing rows.
  5. After each HTTP call, query the database directly to assert the mutation (e.g., `users.provider_id` updated, `deleted_at` set).
  6. For RBAC-dependent endpoints, rely on a fixture that mocks the `require_permission` dependency, so permission checks don't depend on real RBAC logic.
- **Date Added:** 2026-08-01

### 🛠️ Class Roadmap Org Chart View - Frontend Implementation
- **Context/Problem:** The Dashboard had a placeholder for "Class Roadmap & Committee" but it was empty; we needed to visualize the classroom's organizational hierarchy (head, vice-heads, committees) as a family-tree style org chart.
- **Root Cause:** No dedicated page existed to display the structure based on each student's `class_role`.
- **Correct Pattern/Solution:**
  1. Created `frontend/src/views/roadmap/RoadmapView.vue` as a new view.
  2. Used `StudentService.getStudents(roomId)` from `frontend/src/services/student.ts` (the same API call used in `frontend/src/views/students/StudentList.vue`) to fetch all students in the current room.
  3. Mapped `class_role` values (from the list available in `frontend/src/views/students/EditStudent.vue`) to Thai labels and icons: `president`, `vice_academic`, `vice_activity`, `vice_discipline`, `vice_reception`, `treasurer`, and `staff_*` roles.
  4. Built an org-chart tree using pure CSS (no external library) with inline-block nodes and connecting lines via `::before`/`::after` pseudo-elements.
  5. The top node displays the `president`; below it are the four vice roles as level-2 nodes; under each vice node its corresponding `staff_*` members appear as leaf nodes.
  6. Added a `RouterLink` from the existing roadmap card in `src/views/Dashboard.vue` pointing to `/roadmap`.
  7. Registered a new `roadmap` route inside the root layout's children list in `frontend/src/router/index.ts`, lazy-loading `RoadmapView.vue`.
  8. Followed frontend rules: used `<script setup lang="ts">`, `ref`/`computed`, `Tailwind`, and `SweetAlert2` for errors; kept the design minimal and white (slate-50 background) with a dark gradient top node to match the existing dashboard.
- **Date Added:** 2026-08-01

### 🛠️ User Onboarding Profile Update - SQL Parameter Order Alignment
- **Context/Problem:** The user onboarding flow needed to accept additional required user fields (nickname, birthday, phone_number, line_id, address parts) beyond the original prefix/first/last name. The frontend needed to fetch these fields via GET /me, and the backend needed to persist them via PATCH /me.
- **Root Cause:** Initial schema did not include these fields; the raw SQL SELECT in `auth_router.py` and the UPDATE in `auth_service.py` only covered three fields, leaving new fields unhandled and causing missing data or misaligned placeholders.
- **Correct Pattern/Solution:** Update the `UserProfileUpdate` Pydantic model to include all required fields (`nickname`, `birthday`, `phone_number`, `line_id`, `address_house_no`, `address_road` optional, `address_sub_district`, `address_district`, `address_province`, `address_post_code`) with constraints; expand the GET /me `SELECT` and PATCH /me `UPDATE` to include these columns in the same order as the SQL placeholders, mapping each `$n` to the corresponding attribute.
- **Date Added:** 2026-08-02

### 🛠️ Frontend Onboarding Guard - Required Profile Fields Enforcement
- **Context/Problem:** The app let authenticated users access protected pages without completing the mandatory nickname/phone onboarding step, causing incomplete profile data in downstream features.
- **Root Cause:** The `isOnboarded` computed property only checked `prefix`, and there was no global navigation guard preventing access to non-onboarding pages when the profile was incomplete.
- **Correct Pattern/Solution:** Extend the auth store with `nickname` and `phoneNumber` refs (initialized via `safeGetItem`), update `isOnboarded` to require both `prefix` and `phoneNumber` to be non-empty after trimming, and parse `nickname`/`phone_number` from the `/api/auth/me` response while persisting them to localStorage. In the router, add `beforeEach` that first checks `isAuthenticated`; when authenticated but not onboarded and the target route is not `onboarding`, redirect to `{ name: 'onboarding' }`; when authenticated and onboarded and the target is `onboarding`, redirect to `{ name: 'lobby' }`. Use route names to avoid loops.
- **Date Added:** 2026-08-02
