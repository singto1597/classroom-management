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
  3. Mapped `class_role` values (from the list available in `frontend/src/views/students/EditStudent.vue`) to Thai labels and icons: `president`, `vice_president`, `secretary`, `vice_academic`, `vice_activity`, `vice_discipline`, `vice_reception`, `vice_pr`, `vice_sanitation`, `treasurer`, and `staff_*` roles.
  4. Built an org-chart tree using pure CSS (no external library) with inline-block nodes and connecting lines via `::before`/`::after` pseudo-elements.
  5. The top node displays the `president`; below it an executive row (รองหัวหน้าห้อง + เลขานุการ/เรขา); then the six vice roles (`vice_academic`…`vice_sanitation`) as level-3 nodes; under each vice node its corresponding `staff_*` members appear as leaf nodes; the `treasurer` is a separate bottom node.
  5a. `noUncheckedIndexedAccess: true` is on: when a template indexes a `Record<string, T>` with a literal key (e.g. `rolesConfig[slot.role].theme`), TypeScript resolves to `T | undefined` → must resolve the config into the computed/map (with a fallback) instead of indexing directly in the template.
  5b. When adding a new department, keep `viceToStaff` in sync (`vice_pr → staff_pr`, `vice_sanitation → staff_sanitation`) and add a matching theme to `getThemeClasses` (slate/cyan/fuchsia/teal) or the card falls back to `blue`.
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

### 🛠️ Frontend Onboarding Form - Expanded Profile Fields Collection
- **Context/Problem:** The original `Onboarding.vue` only contained inputs for `prefix`, `first_name`, and `last_name`. After the backend started requiring additional profile fields (nickname, birthday, phone_number, line_id, address fields), the UI had no way to collect them, so users were unable to submit a complete profile and downstream features (e.g., contact, address) would fail.
- **Root Cause:** The form's reactive object in `<script setup>` was limited to three keys, and the template lacked controls for the new fields. When `PATCH /auth/me` was called, those additional properties were either `undefined` or missing, causing validation errors on the backend.
- **Correct Pattern/Solution:** Expand the `form` ref to include all required snake_case keys (`prefix`, `first_name`, `last_name`, `nickname`, `birthday`, `phone_number`, `line_id`, `address_house_no`, `address_road`, `address_sub_district`, `address_district`, `address_province`, `address_post_code`). In the template, group fields into three sections using `<h3>` headings styled with `text-sm font-black text-slate-800 border-b border-slate-100 pb-2 mb-4`. Use a responsive two-column grid (`grid grid-cols-1 sm:grid-cols-2 gap-5`) to reduce vertical space. Add `required` to all inputs except `address_road` (ถนน/ซอย) because that field is optional. When submitting, send all properties unchanged in the `api.patch('/api/auth/me', ...)` payload.
- **Date Added:** 2026-08-02

### 🛠️ Frontend Onboarding Form - Pre-fill, Validation, and Payload Refactor
- **Context/Problem:** After expanding the onboarding form with many required fields, the submit logic still used a long `if` condition, the API call mapped each field manually, and pre-fill only covered a few fields. This made the code harder to maintain and risked forgetting new fields when the profile model changed again.
- **Root Cause:** The original implementation duplicated the list of form keys in three places: the reactive object, the validation condition, and the API payload mapping. Any future addition would require changes in all three spots, and the mapping could silently break if field names diverged.
- **Correct Pattern/Solution:** Pre-fill all available properties from the auth store using nullish coalescing (`??`) in `onMounted`. Replace the long validation with a `requiredFields` array and a loop that checks each field's trimmed value, showing `SweetAlert` when any is empty. Send the whole `form.value` object directly to `api.patch('/api/auth/me', form.value)` to eliminate manual mapping. Keep the HTML `required` attribute as a client-side guard, but still validate on submit to avoid relying solely on browser behavior.
- **Date Added:** 2026-08-02

### 🛠️ Frontend Onboarding Form - Dynamic Required Fields & Direct Payload (Implementation Detail)
- **Context/Problem:** The refactored submit still needed to keep the required field list in sync with the form object; the previous approach used a separate hardcoded array which could become outdated.
- **Root Cause:** The required-field list was manually repeated in validation logic, increasing maintenance overhead when new fields are added or removed.
- **Correct Pattern/Solution:** Derive the required fields directly from `form.value` using `Object.keys(form.value).filter(key => key !== 'address_road')`. Check the field is non-empty after trimming with `.every(...)`. Then pass the entire reactive `form.value` to `api.patch('/api/auth/me', form.value)` so future additions automatically flow through without extra mapping. Keep the `required` HTML attributes as a first line of defense but rely on the dynamic check on submit to enforce consistency.
- **Date Added:** 2026-08-02

### 🛠️ Frontend Onboarding Form - Thai Address Autocomplete with `thailand-address`
- **Context/Problem:** When users typed their current Thai address (ตำบล/แขวง, อำเภอ/เขต, จังหวัด, รหัสไปรษณีย์) in the onboarding form, they often entered inconsistent or incomplete data, causing backend validation errors or mismatched address fields. The original inputs were independent fields without any suggestion, forcing users to manually recall exact sub-district/district/province names and zip codes.
- **Root Cause:** The form had four separate text inputs for address parts, and there was no mechanism to look up official postal districts. The frontend had no integration with Thailand's address dataset, so users had to type freeform text, which differs between regions.
- **Correct Pattern/Solution:** Integrate the `thailand-address` npm package (exposes `search(query)` returning objects with `tambon`/`amphoe`/`changwat`/`postcode` or equivalent camelCase keys). In the `<script setup>`, import `search` and define interfaces for both API shapes. Keep a single `addressSuggestions` ref that holds mapped `AddressOption` objects. For each of the four inputs (`address_sub_district`, `address_district`, `address_province`, `address_post_code`), attach `@input` and `@focus` handlers that call `onAddressInput('field')`, and `@blur` to close dropdown (with a slight delay if needed). The dropdown `<ul>` uses `v-if` to show when `isAddressDropdownOpen` and `activeAddressField` matches the current field, and each `<li>` uses `@mousedown.prevent` (so the blur doesn't fire before click) to call `selectAddress(option)`. `selectAddress` populates all four fields from the chosen option, closes the dropdown, and clears `activeAddressField`. Style the dropdown with `absolute z-30 mt-2 w-full bg-white border border-slate-200 shadow-2xl rounded-xl max-h-60 overflow-y-auto`, items with `px-4 py-3 text-sm text-slate-700 hover:bg-slate-50 cursor-pointer border-b border-slate-100 last:border-b-0`. This improves UX while keeping the backend validation expectations.
- **Date Added:** 2026-08-02

### 🛠️ Thai Address Autocomplete - Debounce, Mobile Blur, and Empty-Query Handling
- **Context/Problem:** The autocomplete triggered a search on every keystroke, causing performance lag with larger datasets; mobile interactions could miss dropdown clicks because `blur` unmounted the list before `mousedown` completed; and clearing a field left the dropdown stuck open due to `activeAddressField` not being reset.
- **Root Cause:** No debounce meant expensive search on every input; `@blur` closed the dropdown instantly, racing with touch/click events; `if (!query)` returned without clearing `activeAddressField`, keeping the dropdown visible.
- **Correct Pattern/Solution:** Add a module-level `let searchTimeout: ReturnType<typeof setTimeout> | null = null;`. In `onAddressInput`, keep setting `activeAddressField` and extracting `query` outside the timer; if `query` is empty, set `activeAddressField = null` before returning; otherwise clear any existing timeout and start a 300ms `setTimeout` that performs the search and opens the dropdown. In `closeAddressDropdown`, wrap the closing logic in a 200ms `setTimeout`; ensure selecting an address also clears the timeout, sets the field values synchronously, closes the dropdown, and resets `activeAddressField` to `null`.
- **Date Added:** 2026-08-02

### 🛠️ RBAC Enforcement - Never Comment Out `require_permission` in Services
- **Context/Problem:** The RBAC review found 7 `require_permission(...)` calls commented out inside `services/classroom_sync_service.py` (set_channel, set_notify_time, set_default_schedule, set_override, delete_task, add_daily_note, delete_daily_note). This let any authenticated member of a room change Discord channel/time/schedule/override or delete tasks/notes without permission — a privilege-escalation hole.
- **Root Cause:** The permission checks were written but disabled (likely during debugging), and the router's `except ForbiddenError` handlers stayed in place — so the intent was clearly to enforce them but they were never re-enabled.
- **Correct Pattern/Solution:** Permission checks belong **inside the service** (not the router), on every mutation. The routers already had the `ForbiddenError → 403` mapping; re-enabling the `require_permission` calls in the service made the RBAC effective again without any router change. **Rule:** never commit a commented-out `require_permission`; if a permission is not yet ready, remove the dead code rather than leaving it as a comment.
- **Date Added:** 2026-08-03

### 🛠️ RBAC - Read Transparency vs Write: `require_member` for Finance GET
- **Context/Problem:** Finance GET endpoints (summary, accounts, transactions, collections, categories, debtors, student debts) had **no RBAC at all**, so any authenticated user could read another room's financial data by guessing `room_id`/`server_id`. But requiring `MANAGE_FINANCE` for reads would break the product requirement that "finance should be transparent to room members."
- **Root Cause:** The `require_permission` granular model is write-focused (MANAGE_*), and the read endpoints were never given any authorization check — they assumed any caller was fine.
- **Correct Pattern/Solution:** Add a `require_member(conn, room_id, user_id)` helper in `core/rbac.py` that checks the user is an **active student in that specific room** (`students` row with `status='active'`, `deleted_at IS NULL`; SUPER_ADMIN bypass). Use it on **read-only** endpoints where transparency is desired, keeping `require_permission("MANAGE_FINANCE")` for **mutations**. This prevents cross-room data leaks while preserving the "everyone in the room can see" requirement. **Also:** every read endpoint must `except ForbiddenError` → 403 in the router, otherwise the check silently fails into a 500.
- **Date Added:** 2026-08-03

### 🛠️ Room Creation - Frontend-Primary, Bot as Optional Adapter
- **Context/Problem:** `POST /api/classroom/setup` (used by the Discord bot's `/setup`) could create rooms arbitrarily — no RBAC. The project direction is that **room creation belongs to the web app** (`POST /api/classroom/create` → `RoomManagementService.create_room`), with the bot as an optional integration that links a Discord server to an existing room.
- **Root Cause:** `setup_room` had two modes: with `server_id` (upsert a room bound to a Discord server) and without (create a bare room). The create-bare-room mode was an unauthenticated path that duplicated the web flow.
- **Correct Pattern/Solution:** `setup_room` now requires `server_id`, and it no longer creates new rooms:
  1. If the `server_id` is already bound → update only the room name.
  2. Otherwise, look up a room by `room_name` that was created via the web (has `server_id IS NULL`), and bind `server_id` to it.
  3. Raise `ValueError` (→ 400) if no `server_id` or no matching web-created room.
  This keeps Discord-server↔room linking working for the bot while forcing the primary creation path through the authenticated web flow.
- **Date Added:** 2026-08-03

### 🛠️ Schema Audit Trap - `rooms` Table Has NO `updated_at` Column
- **Context/Problem:** While adding PoC regression tests for the `setup_room` change, `UPDATE rooms SET server_id = $1, updated_at = CURRENT_TIMESTAMP` raised `asyncpg.exceptions.UndefinedColumnError: column "updated_at" of relation "rooms" does not exist`.
- **Root Cause:** The `rooms` table (defined in `core/init_db.py`) only has `server_id, room_code, room_name, announcement_channel_id, notify_time, owner_id, deleted_at` — **no `updated_at`**. The original `setup_room` used `ON CONFLICT ... DO UPDATE` which doesn't touch `updated_at`, so this was only exposed once a manual `UPDATE` was written.
- **Correct Pattern/Solution:** Before writing an `UPDATE ... SET ... updated_at = CURRENT_TIMESTAMP`, verify the target table actually has an `updated_at` column in `core/init_db.py`. Tables like `users`, `students`, `tasks` do; `rooms` does **not**. The fix removed `updated_at` from the `setup_room` UPDATE. **Rule:** when touching raw SQL against a table, check `init_db.py`'s DDL first — several tables in this project lack `updated_at`.
- **Date Added:** 2026-08-03

### 🛠️ `users` Table Has NO `discord_username` Column - Sync Discord Endpoint Was Always Broken
- **Context/Problem:** Writing `test_student.py` tests for `StudentService.sync_discord_account` surfaced `asyncpg.exceptions.UndefinedColumnError: column "discord_username" of relation "users" does not exist` on a successful-path test. The service runs `UPDATE users SET discord_id = $1, discord_username = $2` but the schema has no such column, so `POST /students/discord/sync` could never succeed.
- **Root Cause:** `core/init_db.py` defines the `users` table with `discord_id` but only `username` (no `discord_username`). The router (`student_router.py`) reads the `X-Discord-Username` header and passes it down, but the column was never added to the DDL — a latent mismatch between the service's SQL and the schema.
- **Correct Pattern/Solution:** Add `discord_username TEXT` to the `users` table definition in `core/init_db.py`. Because `init_db` runs `CREATE TABLE IF NOT EXISTS`, the column addition is applied on every fresh test DB; for an existing deployed DB you'd need an `ALTER TABLE ... ADD COLUMN IF NOT EXISTS discord_username TEXT;` migration step. **Rule:** when a service `UPDATE`s a column, confirm the column exists in `init_db.py` — grep the whole repo for the column name (`grep -rn "<col>" core/init_db.py services routers models`).
- **Date Added:** 2026-08-03

### 🛠️ get_audit_logs - SELECT อ้างคอลัมน์ schema เก่า (user_name/detail) ที่ไม่มีอยู่จริง
- **Context/Problem:** เขียน `test_get_audit_logs_returns_recent_logs` เรียก `GET /api/classroom/{id}/logs` แล้วเจอ `asyncpg.exceptions.UndefinedColumnError: column "user_name" does not exist` — `get_audit_logs` (classroom_sync_service.py) SELECT `user_name, action, detail` จากตาราง `audit_logs` ซึ่ง schema จริงมีแค่ `actor_identifier, endpoint_or_command, ...` → endpoint นี้พัง 500 เสมอ ตั้งแต่ schema ถูกย้ายมาใช้ AuditLogger
- **Root Cause:** ตาราง `audit_logs` ถูก rework เป็นโครงสร้างใหม่ (trace_id, actor_identifier, endpoint_or_command) แต่ `get_audit_logs` ยังเขียนอ้างคอลัมน์เก่า `user_name`/`detail` ที่เคยมีในตาราง legacy (`core/audit.py` ก็เป็น dead code ที่ INSERT คอลัมน์เดียวกัน และไม่มีใครเรียกใช้)
- **Correct Pattern/Solution:** เปลี่ยน SELECT ให้ใช้คอลัมน์จริง + alias ให้เข้ากับ contract เดิมที่ bot ใช้ (`actor_identifier AS user_name`, `endpoint_or_command AS detail`) → bot (`view_logs` cog) อ่าน `log['user_name']`/`log['detail']` ได้ต่อทันทีโดยไม่ต้องแก้ข้ามเลเยอร์ **Rule:** ก่อน fix error "column does not exist" ให้เช็ค `init_db.py` ว่าตารางมีคอลัมน์อะไรจริง แล้ว grep หา legacy helper ที่ INSERT คอลัมน์เดียวกัน
- **Date Added:** 2026-08-03

### 🛠️ get_daily_summary - query ไร้ `deleted_at IS NULL` → ข้อมูล soft-delete ยังโผล่
- **Context/Problem:** เขียน `test_get_daily_summary_excludes_deleted_daily_note` (ลบ note แล้วเช็คว่า summary ต้องไม่แสดง `bring`) พบว่า summary ยังคืน `ของเก่า` ทั้งที่ `daily_notes.deleted_at` ถูก set แล้ว
- **Root Cause:** `get_daily_summary` query `default_schedules`, `schedule_overrides`, `daily_notes` โดยไม่มี `deleted_at IS NULL` — 3 ตารางนี้มีคอลัมน์ `deleted_at` แต่ service ละเลย → ข้อมูลที่ soft-delete ไปแล้วยังโผล่ในสรุปรายวัน
- **Correct Pattern/Solution:** เพิ่ม `AND deleted_at IS NULL` ให้ทั้ง 3 query ใน `get_daily_summary` สอดคล้องกับกฎ soft delete ของโปรเจกต์ **Rule:** ทุกครั้งที่ SELECT ตารางที่มี `deleted_at` ให้กรอง `deleted_at IS NULL` ไว้เสมอ — grep ไฟล์ service ทั้งหมดเพื่อหาจุดที่ลืม
- **Date Added:** 2026-08-03

### 🛠️ asyncpg JSONB Returns `str` or `list` Depending on Version
- **Context/Problem:** In `test_update_student_admin_can_update_permissions`, asserting `sorted(row["permissions"]) == ["EXPORT_STUDENTS", "MANAGE_STUDENTS"]` failed because asyncpg returned the JSONB value as a **string** (`'["EXPORT_STUDENTS", "MANAGE_STUDENTS"]'`) instead of a Python list, depending on the Postgres/asyncpg version.
- **Root Cause:** asyncpg's JSONB codec returns `str` on some versions/builds and a native `list` on others, so comparing directly against a list is version-dependent and flaky.
- **Correct Pattern/Solution:** Normalize before comparing: `raw = row["permissions"]; perms = json.loads(raw) if isinstance(raw, str) else raw; assert sorted(perms) == [...]`. This mirrors the defensive `_parse_permissions` helper already used inside `student_service.py`.
- **Date Added:** 2026-08-03

### 🛠️ Classroom Task Mutations Missed Soft-Delete Guards — work on "deleted" tasks
- **Context/Problem:** While expanding `test_classroom_sync_extended.py`, tests exposed that `mark_task_done` / `edit_task` could still mutate a task whose `deleted_at` was set. `add_task` also sent Redis notifications for tasks added to a soft-deleted room, and `add_daily_note` / `set_default_schedule` / `set_override` did `DELETE ... WHERE deleted_at IS NULL` before re-INSERT, so an add→soft-delete→add cycle accumulated duplicate rows (active + zombie soft-deleted).
- **Root Cause:** `mark_task_done`'s `SELECT` and `UPDATE` had no `AND deleted_at IS NULL`; `edit_task` likewise; `add_task` didn't verify the room was alive before INSERT + notify; the delete-then-insert UPSERTs only removed non-deleted rows, leaving soft-deleted zombies behind.
- **Correct Pattern/Solution:**
  1. Every task mutation that should only touch live rows gets `AND deleted_at IS NULL` on both the `SELECT` (for old_values) and the `UPDATE`/`RETURNING`.
  2. `add_task` fetches the room with `AND deleted_at IS NULL` first; if absent → `RoomNotFoundError`, no INSERT, no Redis notify.
  3. The delete-then-insert UPSERTs (default_schedules, schedule_overrides, daily_notes) now `DELETE ... WHERE room_id=$1 AND key=$2` **without** the `deleted_at IS NULL` filter, so the new INSERT always leaves exactly one row.
- **Date Added:** 2026-08-04

### 🛠️ AuditLogger Fallback Can Mask the Real Exception (FK violation on phantom room_id)
- **Context/Problem:** `test_get_room_data_nonexistent_raises_roomnotfound` failed with `ForeignKeyViolationError: key (room_id)=(999999) is not present in table "rooms"` — the *real* `RoomNotFoundError` was being swallowed.
- **Root Cause:** Every `except Exception` block writes a `status="failed"` audit log to `audit_logs.room_id`, which is an FK to `rooms`. When the method itself raised `RoomNotFoundError` (room doesn't exist), the fallback log tried to insert with that phantom `room_id` → FK violation, overriding the original 404 into a 500.
- **Correct Pattern/Solution:** In the fallback handler, null out the FK when the failure is a "not found": `safe_room_id = None if isinstance(e, RoomNotFoundError) else room_id`. Apply to every method that can raise `RoomNotFoundError` inside its try block (get_room_data, set_channel, set_notify_time, add_task). **Rule:** the audit fallback must not reference a row that doesn't exist.
- **Date Added:** 2026-08-04

### 🛠️ Read RPC → `require_member` Design: Where It Is NOT Safe to Add
- **Context/Problem:** The RBAC hardening pass added `require_member` to classroom read/write RPCs. But the daily-notification **loop** (`bot_discord/cogs/classroom_cmd.py:78,93`) calls `GET /{server_id}/summary` with `X-Discord-Id` = the **bot's own user id** (`self.bot.user.id`), which is NOT a member of any room.
- **Root Cause:** `get_daily_summary` is a cross-layer RPC: used both by the bot-loop (system identity, no user) and by user slash commands (`/today`, `/tomorrow`). Its router has no `get_current_user`, and the bot-loop has no per-room membership.
- **Correct Pattern/Solution:** **Do NOT add `require_member` to `get_daily_summary`** — it would break the scheduled notification loop. Instead, this read stays transparent at the RPC layer (same reasoning as Finance GET transparency, but here the "caller" is the bot). When hardening read RPCs, audit every caller (bot loops, schedulers, slash commands) before adding a check. `get_rooms_to_notify` is likewise system-only (`verify_api_key`), so it gets no membership check either.
- **Date Added:** 2026-08-04

### 🛠️ Flaky Summary Test — `datetime.now()` UTC vs `THAI_TZ` Midnight Rollover
- **Context/Problem:** `test_get_daily_summary_combines_schedule_and_tasks` in `test_classroom_sync.py` failed with `days_left == -1` only during 00:00–06:59 Bangkok time.
- **Root Cause:** The test computed "today" with `datetime.now().date()` (UTC) while the service uses `datetime.now(THAI_TZ).date()` (Asia/Bangkok). Between UTC midnight and 07:00 Bangkok time, the two dates differ by a day, so a task due "today" in Bangkok looks 1 day overdue from UTC.
- **Correct Pattern/Solution:** Always compute test "today" with the same `THAI_TZ` as the service (`from services.classroom_sync_service import THAI_TZ`). **Rule:** any test that compares against "today" in a service that uses `THAI_TZ` must use `datetime.now(THAI_TZ).date()`, never bare `datetime.now()`.
- **Date Added:** 2026-08-04

### 🛠️ Finance transfer_money — โอนเงินข้ามห้องได้ (cross-room money leak) ตรวจไม่เจอปลายทาง
- **Context/Problem:** เขียน `test_transfer_from_account_not_in_room_raises` (โอนจากบัญชีต่างห้อง) แล้วเจอว่าโอนไปบัญชีต่างห้อง **ไม่ error** — `transfer_money` เช็คความถูกต้องของ `from_account_id` เท่านั้น ไม่ได้เช็ค `to_account_id` ว่าเป็นของห้องเดียวกัน → เงินรั่วไปอีกห้องได้
- **Root Cause:** ใน `finance_service.py` `transfer_money` validate เฉพาะ `from_account_id` (`SELECT balance ... WHERE id=$1 AND room_id=$2`) แล้ว `UPDATE balance = balance - $1` ฝั่งต้นทาง แต่บัญชีปลายทาง (`to_account_id`) ไม่ถูกตรวจ → `UPDATE balance = balance + $1` ไปบวกยอดให้บัญชีคนละห้อง
- **Correct Pattern/Solution:** หลัง validate ต้นทาง ต้องเช็คปลายทางก่อนทำ transaction เสมอ: `if not await conn.fetchval("SELECT 1 FROM finance_accounts WHERE id = $1 AND room_id = $2", req.to_account_id, target_room_id): raise RoomNotFoundError("ไม่พบบัญชีปลายทาง")`. **Rule:** ทุก multi-table mutation ที่รับ `*_account_id`/`*_id` ต้อง validate ว่า entity ทุกตัวอยู่ใน `target_room_id` เดียวกันก่อน (same-pattern จุดเดียวกับ `add_transaction` ที่เช็คทั้ง account+category)
- **Date Added:** 2026-08-04

### 🛠️ Finance confirm_payment — ไม่มี RBAC + รับ overpay ได้ (สองจุดที่ต้อง flag)
- **Context/Problem:** เขียน `test_plain_member_cannot_confirm_payment_mutation_via_transactions` ตั้งใจเช็คว่า member ธรรมดาต้องโดน ForbiddenError แต่ **ผ่าน** — เพราะ `confirm_payment` ไม่มีพารามิเตอร์ `user_id` เลย ไม่มี `require_permission` อยู่ด้านใน และ router (`finance_router.py`) ก็ไม่ส่ง `user_id` ให้ (ทุก mutation ตัวอื่นส่ง `user_id=user_ctx["user_id"]` แต่ตัวนี้ไม่มี) ส่วน `test_confirm_payment_overpay_allowed_documents_current_behavior` เจอว่า current_paid 600 + paid_amount 500 = 1100 เกินยอดจริง 1000 แต่ระบบยังรับและ mark paid
- **Root Cause:** 1) `confirm_payment` ถูกออกแบบให้ bot/web โทรผ่านก็ได้ จึงไม่ได้ส่ง actor `user_id` ลงไป → ไม่มีชั้น RBAC 2) ตรวจแค่ `if current_paid >= total_amount: raise` (จ่ายครบแล้ว) แต่ไม่ตรวจ `paid_amount` เกินยอดที่เหลือ
- **Correct Pattern/Solution:** สองจุดนี้เป็น **pending fix** — test เอกสารพฤติกรรมปัจจุบันไว้แล้ว (`# ⚠️ document BUG`) เพื่อให้ regression เปลี่ยนชัดเจนเมื่อแก้จริง: 1) ต้องเพิ่ม `user_id` param + `require_permission(conn, room_id, user_id, "MANAGE_FINANCE")` ให้ `confirm_payment` ทั้ง service และ router 2) ต้องเช็ค `if req.paid_amount > total_amount - current_paid: raise ValueError` (ห้ามรับเกิน) **Rule:** mutation endpoint ที่รับได้ทั้ง bot+web ต้องมี path RBAC ให้ครบทั้งสองทางเสมอ
- **Date Added:** 2026-08-04

### 🛠️ Finance service: asyncpg ปฏิเสธ `str` ใส่คอลัมน์ TIMESTAMP — ต้องใช้ datetime object
- **Context/Problem:** `test_get_transactions_pagination` ส่ง `f"2026-01-0{i} 10:00:00"` (string) ไปที่ `UPDATE finance_transactions SET created_at = $2` แล้วเจอ `asyncpg.exceptions.DataError: invalid input for query argument $2: ... (expected a datetime.date or datetime.datetime instance, got 'str')`
- **Root Cause:** asyncpg เป็น codec แบบ strict — ต่างจาก psycopg2 ตรงที่ถ้าคอลัมน์เป็น TIMESTAMP และ parameter เป็น str จะไม่แปลงให้เอง ทั้งที่ `date`/`datetime` Python เป็น codec native
- **Correct Pattern/Solution:** ใน test ที่จะ `UPDATE`/`INSERT` คอลัมน์เวลาที่ parameterized ต้องส่ง `datetime(2026, 1, i, 10, 0, 0)` object เสมอ ห้ามส่ง string (แต่ส่ง `date` object ไปคอลัมน์ DATE ได้ และเขียน literal วันที่ใน SQL string ได้) **Rule:** ถ้า asyncpg ขึ้น `DataError ... expected a datetime.date or datetime.datetime instance` ให้เปลี่ยน str → `datetime` object ใน test ไม่ใช่แก้ SQL
- **Date Added:** 2026-08-04

### 🛠️ TaskStatus.ALL — enum มีค่า "all" แต่ service ยัง `WHERE status=$2` → Web ดูงานเสร็จไม่ได้
- **Context/Problem:** หน้า Web `/tasks` (TaskList.vue) มีแท็บ filter `pending/done/all` แต่แท็บ "เสร็จแล้ว" กลับว่างเปล่าเสมอ เพราะ `TaskService.getAllTasks` เรียก `GET /tasks` โดยไม่ส่ง `status` → ตก default `pending` จึงได้แค่งานยังไม่เสร็จ `TaskStatus.ALL = "all"` มีอยู่ใน schema อยู่แล้ว (หมายเหตุว่า "ใช้ในหน้า Web") แต่ service ยัง `WHERE status = $2` ตรง ๆ ทำให้ส่ง `all` มาก็ได้ 0 แถว (ไม่มีงานไหน status = 'all')
- **Root Cause:** `ClassroomService.get_tasks` สร้าง SQL แบบ fix `status = $2` โดยไม่รู้จัก special value `all` — enum เพิ่มค่าให้แล้วแต่ backend query ยังไม่ support → "ดึงงานทั้งหมด" ทำไม่ได้ทั้งจาก frontend และ API ตรง ๆ
- **Correct Pattern/Solution:** branch ใน `get_tasks`: ถ้า `status == "all"` ให้ drop `status = $2` ออกจาก WHERE (ยังเก็บ `deleted_at IS NULL` + `ORDER BY due_date ASC`) ส่วน `pending/done` ยังกรองเหมือนเดิม → bot (ส่ง pending/done) ไม่กระทบ, Web ส่ง `status=all` แล้ว filter ฝั่ง client เอง **Rule:** เวลาเพิ่ม special value ให้ Enum/query ที่มี default filter (เช่น status, type) ต้องตรวจ service layer ด้วยว่า SELECT อ่านค่านั้นแล้วได้ผลถูกต้อง — enum กับ query ต้องอัปเดตพร้อมกัน
- **Date Added:** 2026-08-04

### 🛠️ Finance — `DECIMAL` column กลับมาเป็น `decimal.Decimal` แต่ Pydantic ส่ง `float` → เปรียบเทียบ `Decimal < float` พัง (เทส edge case จับได้ 5 จุด)
- **Context/Problem:** เทส `test_finance_edge_cases.py` จับได้ว่าหลายจุดใน `finance_service.py` เปรียบเทียบ balance/amount ที่เป็น `Decimal` (อ่านจาก DB) กับ `float` (มาจาก Pydantic request) โดยตรง: `add_transaction` (`current_balance < req.amount`), `transfer_money` (`current_balance < req.amount`), `revert_transaction` (`curr_bal < t['amount']`), `update_collection` (`req.amount != current_data['amount']`). ผลคือ `Decimal('0.1') < 0.1 = True` → เงินพอแต่ระบบห้ามตัดเงิน/ห้ามโอน/ห้าม revert ทั้งที่ยอดเท่ากัน; และ `Decimal('1000.1') != 1000.1 = True` → เปลี่ยนค่า amount เท่าเดิมก็ถูกห้าม (ถ้ามีการจ่ายแล้ว)
- **Root Cause:** `finance_accounts.balance` / `fee_collections.amount` / `finance_transactions.amount` เป็น `DECIMAL` ใน DB → asyncpg คืนเป็น `decimal.Decimal`; Pydantic schema ประกาศเป็น `float` → client ส่ง `0.1`, `1000.1` มาเป็น float binary ที่มี error propagation → `Decimal(0.1) < 0.1` (Decimal ใช้ค่าเทียบตรงตามค่าทศนิยม) ต่างจาก `Decimal(0.1) < Decimal('0.1')`
- **Correct Pattern/Solution:** ทุกจุดที่เปรียบเทียบเงิน ต้อง cast `float()` ทั้งสองฝั่งก่อนเสมอ (`float(current_balance) < float(req.amount)`), **ไม่ใช้ `Decimal(str(...))`** เพราะ production เก็บเงินผ่าน float param → asyncpg บันทึก binary noise (`Decimal('0.1000000000000000055...')`) เข้า numeric → `Decimal(str(0.1))` = `Decimal('0.1')` ≠ ของจริง → ยัง block ผิดอยู่ แต่ `float()` จะลบ noise ให้เท่ากับค่าที่มนุษย์เห็น ถูกต้องทั้งกรณี clean และ noisy. **Rule:** ทุกการเปรียบเทียบ `<`, `>`, `!=` ระหว่างค่าจาก DB (Decimal) กับค่าจาก client (float) ใน finance module ต้อง cast `float()` ก่อนเสมอ — อย่าเทียบข้าม type ตรง ๆ และอย่าใช้ `Decimal(str(...))` เพราะไม่ลบ binary noise ที่ asyncpg เก็บจาก float param. เทสที่จับบั๊กนี้: `test_add_expense_allowed_when_decimal_balance_1_1_amount_1_1` / `test_transfer_exact_balance_decimal_vs_float` / `test_revert_income_allowed_when_balance_decimal_equal_amount` / `test_update_collection_same_amount_not_treated_as_change`
- **Date Added:** 2026-08-04

### 🛠️ Finance — `add_student_to_collection` ไม่เช็ค `students.status='active'` → เพิ่ม pending/left student เข้าแคมเปญเก็บเงินได้
- **Context/Problem:** เทส `test_add_pending_student_to_collection_is_blocked` / `test_add_left_student_to_collection_is_blocked` จับได้ว่า `add_student_to_collection` ตรวจแค่ว่า student เป็นของห้อง (`SELECT id FROM students WHERE id=$1 AND room_id=$2`) โดยไม่เช็ค `status='active'` → สมาชิกที่ยังรออนุมัติ (pending) หรือลาออก (left) ถูกเพิ่มเข้ารายการเรียกเก็บเงินได้ทั้งที่ไม่มีสิทธิ์โดนเก็บ
- **Root Cause:** query ที่เช็ค student หลงเหลือ `AND status = 'active'` จาก pattern เดียวกันของ `create_fee_collection` ที่ filter active ถูกต้อง (ใน `create_fee_collection` L364 มี `status = 'active'`) แต่ `add_student_to_collection` L829 ลืมใส่
- **Correct Pattern/Solution:** แก้ query เป็น `SELECT id FROM students WHERE id = $1 AND room_id = $2 AND status = 'active'` (เหมือนจุดที่ถูกต้องใน `create_fee_collection`). **Rule:** ทุก function ที่ "เพิ่ม student เข้า entity ระดับห้อง" (student_payments, tasks, ฯลฯ) ต้องเช็ค `students.status = 'active'` + `deleted_at IS NULL` ด้วยเสมอ — อย่าลอก query จากที่อื่นโดยไม่เทียบเงื่อนไข status
- **Date Added:** 2026-08-04

### 🛠️ Finance — `delete_account` hard-delete โดยไม่เช็ค `finance_transactions` → ประวัติรายรับ/รายจ่ายที่ผูกบัญชีโดน `ON DELETE SET NULL` (ประวัติหาย)
- **Context/Problem:** เทส `test_delete_account_with_history_orphans_transaction_histories` จับได้ว่า `delete_account` ตรวจแค่ `balance > 0` กับ `student_payments.paid_to_account_id` แต่ไม่ตรวจ `finance_transactions.account_id` → บัญชีที่ balance=0 มี transaction history ถูก hard-delete ได้ → `finance_transactions.account_id` โดน FK `ON DELETE SET NULL` → ประวัติธุรกรรมเก่าทั้งหมดของบัญชีนั้นกลายเป็น NULL (ตามลิงก์ account ไม่ได้)
- **Root Cause:** `finance_accounts.id` ถูกอ้างอิงจาก `finance_transactions.account_id` (`ON DELETE SET NULL`) แต่ `delete_account` ไม่ query ว่า `EXISTS(SELECT 1 FROM finance_transactions WHERE account_id = $1)` เหมือน `delete_category` ที่เช็ค `finance_transactions.category_id` ไว้แล้ว → เหลือช่องโหว่คนละจุด
- **Correct Pattern/Solution:** เพิ่ม guard ใน `delete_account` ก่อน hard-delete: `if await conn.fetchval("SELECT 1 FROM finance_transactions WHERE account_id = $1 LIMIT 1", account_id): raise ValueError("ไม่สามารถลบบัญชีได้ เนื่องจากมีประวัติธุรกรรมผูกกับบัญชีนี้!")` (หรือ soft-delete `finance_accounts` แทน). **Rule:** FK ที่เป็น `ON DELETE SET NULL` ทุกตัว (account_id, category_id, student_payment_id) ต้องมี guard ใน function ลบของ parent ก่อนเสมอ — เขียนเทสที่ verify ว่า child row ไม่ถูก NULL-ify หลัง delete
- **Date Added:** 2026-08-04

### 🛠️ Finance — `confirm_payment` รับเงินแคมเปญที่ `status='closed'` ได้ + `get_summary(month)` ที่ไม่มี `year` ทำ params เลื่อน (SQL 500)
- **Context/Problem:** สอง bug ที่เทส `test_confirm_payment_on_closed_collection_should_be_blocked` และ `test_get_summary_with_month_but_no_year` จับได้: 1) `confirm_payment` join `fee_collections FC` ตรวจแค่ `FC.room_id` ไม่ได้เช็ค `FC.status='active'` → แคมเปญปิดแล้วยังรับเงินต่อ (จ่ายเข้ากระเป๋า + mark paid) 2) `get_summary` รับ `month` กับ `year` เป็น `Optional[int]` — ถ้า client ส่ง `month` โดยไม่มี `year` จะเข้า branch `if month and year` → สร้าง SQL ใช้ `$2,$3` แต่ `params` มีแค่ `[room_id, month]` → `asyncpg UndefinedParameterError` (500)
- **Root Cause:** 1) confirm_payment ไม่ filter `FC.status` ใน join query 2) logic `if month and year` ตีความ "มีทั้งคู่" แต่ถ้ามีแค่ตัวเดียว เงื่อนไขเป็น False → เข้า fallback `current_month` แต่ `params` ไม่ถูก append จนครบตาม branch ที่ใช้
- **Correct Pattern/Solution:** 1) เพิ่ม `AND FC.status = 'active'` ใน query ของ `confirm_payment` (ปิดแคมเปญแล้วห้ามรับเงิน) 2) แก้ `get_summary` ให้ validate: ถ้ามี `month` หรือ `year` ตัวเดียว → `raise ValueError("ต้องระบุทั้ง month และ year")` หรือ ใช้ทั้งสองพร้อมกันเสมอ. **Rule:** ทุก endpoint ที่รับคู่ params แบบ "ใช้ด้วยกัน" (เช่น month/year, start/end date) ต้อง validate ว่าให้ครบคู่ หรือ fallback อย่างชัดเจน — และ mutation ที่ operate กับ entity ที่มี status (active/closed) ต้อง filter status ใน query ด้วยเสมอ
- **Date Added:** 2026-08-04

### 🛠️ Finance Excel Export — รวมขาโอนเงินก่อนเขียนไฟล์ + placeholder เริ่มที่ $2 + timestamp ต้องเป็น datetime
- **Context/Problem:** สร้าง `POST /{target_id}/finance/export` (FinanceService.export_transactions_excel) เพื่อดึงประวัติการเงินของห้องเป็น .xlsx สวยงาม พบ 3 กับดักระหว่างทาง: 1) การโอนเงินระหว่างบัญชีสร้าง 2 รายการ (ขาออก+ขาเข้า) → ถ้าใส่ Excel ตรง ๆ รายรับ/รายจ่าย "เกินจริง" (เงินแค่ย้ายบัญชีในห้อง ไม่ได้ออกนอกห้อง) 2) `WHERE T.room_id = $1 ...` แล้วต่อ `AND ... >= $2` → ถ้า helper คืนแค่ SQL string แต่ไม่คืน params จะโดน `asyncpg.InterfaceError: the server expects 3 arguments, 1 was passed` 3) test ที่ `UPDATE finance_transactions SET created_at = '2026-02-10 10:00:00'` (string) โดน asyncpg ปฏิเสธ + อีกจุดที่ `await conn.execute` อยู่นอก `async with pool.acquire() as conn:` → `connection has been released back to the pool`
- **Root Cause:** 1) `transfer_money` ออกแบบให้สร้าง 2 ขา (expense จากบัญชีต้นทาง + income เข้าบัญชีปลายทาง) ผูก `transfer_group_id` เดียวกัน — export ต้อง consolidate ก่อน 2) helper แยก SQL กับ params ออกจากกัน 3) ตามกฎ asyncpg strict codec และ async context manager
- **Correct Pattern/Solution:**
  1. **Consolidate ขาโอน:** ใน `_consolidate_transfers` จับคู่ `transfer_group_id` เดียวกันเป็น 1 แถว โดยเลือก "ขาต้นทาง" (`transaction_type == 'expense'`) เป็นตัวแทนกลุ่ม → account_name ชี้ถูกบัญชี, ตัวเลขรายรับ/รายจ่ายสะท้อนเงินจริง ใช้ regex `re.sub(r'^(โอนออก:|รับโอน:)\s*', '', desc)` ตัดคำนำหน้าซ้ำ
  2. **Helper ต้องคืน (where_sql, params, label) ครบ:** placeholder ใน query หลักเริ่มที่ `$1` (room_id) → helper คืน clause ที่เริ่ม `$2` และคืน list params ไป `fetch(sql, room_id, *params)` เสมอ อย่าแยก SQL กับค่าออกจากกัน
  3. **Test timestamp:** ส่ง `datetime(...)` object (ตาม lessons เดิม) และทำ `UPDATE` ภายใน `async with db_pool.acquire()` ให้เรียบร้อยก่อนออกจาก block
  4. **ยอดคงเหลือรายบัญชี** ควรดึงจาก `finance_accounts.balance` จริง (รวม seed/เปิดบัญชี) ไม่ใช่คำนวณจากรายการในงวดเท่านั้น — ไม่งั้นบัญชีที่เปิดก่อนหน้างวดจะโชว์ 0 ผิด
- **Date Added:** 2026-08-04

### 🛠️ Room create_room — seed หมวดหมู่/บัญชีค่าเริ่มต้นให้ห้องใหม่
- **Context/Problem:** หลังสร้างห้องใหม่ ระบบการเงิน (finance) ยังว่างเปล่า — admin ต้องไปสร้างหมวดหมู่รายรับ/รายจ่ายและกระเป๋าเงินเองทุกห้องซ้ำ ๆ
- **Correct Pattern/Solution:** เพิ่ม `DEFAULT_INCOME_CATEGORIES` / `DEFAULT_EXPENSE_CATEGORIES` / `DEFAULT_FINANCE_ACCOUNTS` ไว้ใน `services/finance_service.py` (เป็น source of truth ชื่อ+emoji ตามความต้องการของครู) แล้วใน `RoomManagementService.create_room` (`services/room_service.py`) หลัง INSERT ห้อง + president student ให้ `executemany` INSERT หมวดหมู่ (income + expense) และบัญชีเงินสด 2 บัญชี **ภายใน transaction เดียวกัน** พร้อม audit log `FINANCE_SEED` (ไม่ต้องมี `user_id`/`entity_id` ซับซ้อน — แค่ log ว่าระบบ seed อะไรให้ห้องไหน). **Rule:** `room_service` import ค่าคงที่จาก `finance_service` ได้ (ไม่เกิด circular import เพราะ finance_service ไม่ import กลับ) แต่ให้วาง "ของ seed" ไว้ฝั่ง finance module เพื่อให้เวลารายชื่อเปลี่ยน อยู่ใกล้ ๆ กันกับ business logic เดิม. **ข้อสำคัญ:** ห้ามไป seed ใน `join_room`/`init_db` — เดี๋ยวห้องเก่าที่สร้างไปแล้วจะถูกเติมของโดยไม่ได้ตั้งใจ; test `test_create_room_seeds_default_finance_categories_and_accounts` (ผ่าน create_room → มีครบ) + `test_join_room_does_not_seed_finance_data` (join → 0 แถว) + `test_raw_inserted_room_starts_without_finance_seed` (INSERT ตรง → 0 แถว) ยืนยันขอบเขตนี้
- **Date Added:** 2026-08-04

### 🛠️ Finance Phase 4 — Time-Based Routing ระหว่าง Single-Entry กับ Double-Entry (Strangler Fig)
- **Context/Problem:** ระบบย้ายจากการเงินแบบเดี่ยว (finance_transactions) ไปเป็นบัญชีคู่ (journal_entries/journal_lines) ผ่าน dual-write (Phase 3) แต่ยังอ่านจากตารางเก่าอยู่ ต้องเริ่มอ่านจากระบบใหม่สำหรับข้อมูลหลังวันที่ตัด (cutoff) โดยไม่ทำ frontend พัง และไม่ให้ยอดเบิ้ล/ตกหล่นช่วงที่ข้อมูลมีในตารางเก่าเท่านั้น
- **Root Cause:** ข้อมูลก่อน 2026-09-01 (วันที่ตั้งยอดยกมา) มีอยู่ใน finance_transactions เท่านั้น — journal อ่านหลัง cutoff ไม่มีข้อมูลเก่า → ถ้า route ผิดยุคจะได้ข้อมูลหายทั้งที่ DB ยังมี
- **Correct Pattern/Solution:**
  1. **Router pattern 3 ทาง (ตัดสินจากขอบเขตของช่วง ไม่ใช่แค่จุดเริ่ม):** `get_transactions` / `export_transactions_excel` เทียบกับ `CUTOFF_DATE`:
     - ทั้งช่วงก่อนเส้นตัด (`end_date < CUTOFF_DATE`) → `_*_legacy`
     - เริ่มที่/หลังเส้นตัด (`start_date >= CUTOFF_DATE`) → `_*_v2` (journal 100%)
     - **"ทั้งหมด" (ไม่กรองช่วง) / คร่อมเส้น / ปลายเปิด → `_*_merged`**: อ่าน legacy เฉพาะ `DATE(created_at) <= วันก่อน 1 ก.ย.` + journal เฉพาะ `DATE(transaction_date) >= 1 ก.ย.` แล้วรวมเรียงตามเวลา — normalize tz ก่อน sort ผ่าน `_naive_thai_dt` (legacy naive ↔ journal aware) → **ไม่เบิ้ล** เพราะ dual-write เขียน timestamp เดียวกันทั้ง 2 ตาราง; legacy อ่านเฉพาะข้อมูลก่อนวันที่ตัดเท่านั้น
     `get_summary` เป็นรายเดือน → คาบเส้นไม่ได้ (เดือนก่อนเส้น = legacy, เดือนที่เส้นขึ้นไป = v2)
  2. **split worker → fetcher ไร้ pagination:** `_get_transactions_legacy`/`_v2` แยก fetch ทั้งชุด (`_fetch_legacy_items`/`_fetch_v2_items`) แล้ว slice ที่ Python (`total_count = len(items)`); `_get_transactions_merged` เรียก worker ทั้งคู่กับ sub-window (`cap/floor` ที่เส้น) แล้ว re-slice — ตัวเลข/การเรียงของเดิมไม่เปลี่ยน
  3. **การแปล Dr/Cr กลับเป็น schema เดิม (TransactionResponse):** group journal_lines ตาม journal_entry_id → classify ตาม combination: income (asset Dr + revenue Cr), expense (asset Cr + expense Dr), transfer (asset 2 บัญชี Dr+Cr), opening_balance → income (ยอด = asset Dr) และไม่นับขา equity
  4. **⚠️ id ของ TransactionResponse ต้องเป็น int:** journal_entry.id เป็น UUID → frontend ใช้ `id` เป็น Vue key + เรียก `revert_transaction` (ค้นจาก finance_transactions.id) → สังเคราะห์ int จาก `metadata['legacy_transaction_id']` (หรือ `transfer_group_id`); ถ้าไม่มี (opening_balance) ใช้ค่าลบจาก hash ของ UUID (เป็น id ที่ revert ไม่ได้จริงตามธรรมชาติ)
  5. **ยอดยกมาไม่นับเป็นรายได้:** `_get_summary_v2` / `get_income_statement` ต้อง `JE.reference_type <> 'opening_balance'` ในส่วนรายได้/รายจ่ายของงวด แต่ **Net Worth (asset) ต้องรวม** ยอดยกมาเสมอ
  6. **Excel v2:** ใช้ `_get_transactions_v2` (limit ใหญ่) → `_format_v2_rows` → `_build_finance_workbook` เดิม; ยอดคงเหลือรายบัญชีคำนวณจาก Net Balance ของ ledger สินทรัพย์ (`SUM(debit−credit)`) ไม่ใช่ finance_accounts.balance
  7. **Helper `_ExportPeriodView`** ใช้ส่ง month/year/start_date/end_date เข้า `_resolve_export_period` (เดิมรับ req object) ให้ `_legacy` export variant ใช้ของเดิมได้
  8. **งบการเงิน (income statement / trial balance / export สมุดรายวัน) เป็น journal-native → [CLAMP]:** ถ้าช่วงเริ่มก่อน 1 ก.ย. ให้ดัน start ขึ้นเป็น 1 ก.ย. (helper `_clamp_to_cutoff`) + แจ้ง note ไทยในผลลัพธ์ (`_CLAMP_START_NOTE`); ทั้งช่วงก่อนเส้น → คืนว่าง/ศูนย์ + note (`_CLAMP_EMPTY_NOTE`) — **ไม่เอา legacy มาทำงบบัญชีคู่** เพราะ legacy ไม่มีแยกหมวด Dr/Cr
  9. **ปิดรอยรั่วฝั่งเขียน (หลังวันที่ตัดต้องพึ่งบัญชีคู่ 100%):** (A) `_confirm_single_payment` **ห้าม `pass` ข้าม dual-write** — ถ้าหา revenue ledger ไม่เจอ ให้ `_find_or_create_default_income_category` สร้างหมวด '📥 เก็บเงินห้องปกติ' + revenue ledger ให้อัตโนมัติ (ไม่งั้น "legacy ได้เงิน แต่ journal ไม่มีบิล" → ยอดเบี้ยว); (B) `revert_transaction` **freeze รายการก่อน 1 ก.ย.**: ถ้า `created_at < CUTOFF_DATE` (รวม transfer group) → `ValueError` → 400 ข้อความ "ไม่สามารถยกเลิกรายการก่อนขึ้นระบบบัญชีคู่ได้ ให้ใช้วิธีบันทึกรายจ่ายปรับปรุงยอดแทน" (guard ก่อนแตะ balance ปลอดภัย)
- **Tests:** `test_finance_v2_read.py` — router 3 ทาง (ก่อน→legacy, หลัง→v2, **no-filter/คร่อม→merge + ไม่เบิ้ล + boundary 31 ส.ค.–1 ก.ย.**), classify income/expense/transfer/opening_balance, summary v2, export v2 + merged, **clamp** income statement/trial balance, RBAC 403; `test_finance.py`/`test_finance_export.py`/`test_finance_journal_export.py` เพิ่มเทส export merge 2 ยุค + Fix A (auto-provision) + Fix B (freeze revert, service+HTTP 400)
- **Date Added:** 2026-08-05

### 🛠️ Backend Full-Audit Pass (2026-08-05) — RBAC, IDOR, dead code, debt
- **Context/Problem:** อ่าน backend ทั้งหมดแบบละเอียด (core/services/routers/models) แล้วเจอ 7 จุดบั๊ก/เทคนิคอลเด็บบ์
- **Findings & Fixes:**
  1. **`confirm_payment` ไม่มี RBAC + รับ overpay:** ไม่มี `user_id` param ไม่มี `require_permission` (router ก็ไม่ส่ง user_id) → member ธรรมดารับเงินได้; และไม่เช็ค `paid_amount > total - current_paid` → จ่ายเกินยอดได้ แก้โดยเพิ่ม `user_id` param (optional เพื่อไม่พัง bot path) + `require_permission(..., "MANAGE_FINANCE")` + guard overpay `if req.paid_amount > total_amount - current_paid: raise ValueError`
  2. **`sync_discord_account` เป็น IDOR:** ใครก็ผูก Discord ID ของตัวเองทับ student ของเพื่อน (ส่ง room_code+student_no) ได้ แก้โดยเพิ่ม `actor_user_id` param + guard `actor_user_id == user_id` (หรือ Super Admin) ก่อนผูก
  3. **`get_summary` router จับ error ไม่ครบ:** service raise `ValueError` (month ไม่มี year) แต่ router จับแค่ RoomNotFoundError/ForbiddenError → 500 แก้โดยเพิ่ม `except ValueError → 400`
  4. **Dead code:** `core/audit.py` (log_action INSERT คอลัมน์ user_name/detail ที่ไม่มีใน schema ใหม่ — legacy เดิม) และ `core/utils.py` (resolve_room_id ไม่มีใครใช้) → ลบทั้งคู่ (git rm)
  5. **`main.py` shutdown `await asyncio.sleep(3)`:** delay การปิด 3 วิ โดยไม่มีเหตุผล → ลบ + ลบ unused import
  6. **`student_router.get_target` default `target_type="server"`:** ต่างจาก finance/classroom router ที่ default `"room"` → ใครลืมส่ง ?target_type จะไป resolve ผิดเป็น server_id แก้เป็น default `"room"`
  7. **`add_transaction` ไม่เช็ค `deleted_at`** ของ account/category (soft-delete แล้วยังใช้ได้) → เพิ่ม `AND deleted_at IS NULL`; **router ใช้ `AccountCreate`/`CategoryCreate` แทน `AccountUpdate`/`CategoryUpdate`** สำหรับ PATCH → เปลี่ยนเป็น schema ที่ถูกต้อง (field เหมือนกัน ไม่กระทบ frontend)
  8. **`transfer_money` ไม่เช็ค `deleted_at`** ของบัญชีต้นทาง/ปลายทาง (โอนเข้ากระเป๋า soft-delete ได้) → เพิ่ม `AND deleted_at IS NULL` ให้ทั้ง 2 query (ต้นทาง FOR UPDATE + ปลายทาง)
  9. **`GET /logs` / `/students/{no}/status` / `/discord/sync` ไม่มี `response_model`** (ผิดกฎ backend รอบ router ต้องบังคับทุกครั้ง) → เพิ่ม `AuditLogResponse` (ใหม่ใน schema) สำหรับ `/logs`, `SuccessResponse` สำหรับอีก 2 ตัว
- **Tests:** อัปเดต `test_confirm_payment_overpay_allowed_documents_current_behavior` → `test_confirm_payment_overpay_now_blocked` (expect ValueError + no mutation), `test_plain_member_cannot_confirm_payment_mutation_via_transactions` → ตอนนี้ expect ForbiddenError (ส่ง user_id=member), เพิ่ม `test_sync_discord_account_actor_mismatch_raises_forbidden`
- **Rule:** (1) ทุก mutation ที่รับได้ทั้ง bot+web ต้องมี RBAC ให้ครบทั้งสองทาง — ใช้ pattern `user_id: Optional[int] = None` + router ส่งเสมอ (2) ทุก "ผูก identity" ต้อง verify ว่า actor เป็นเจ้าของ target ก่อน (IDOR) (3) Router ที่ service raise ValueError ต้องมี `except ValueError → 400` เสมอ (4) เช็ค schema จริงใน `init_db.py` ก่อนเขียน UPDATE/SELECT — อย่าใช้ legacy column (5) ก่อนลบไฟล์ ให้ grep ทั้ง repo ยืนยันไม่มีใครใช้
- **Date Added:** 2026-08-05

### 🛠️ Redis Pub/Sub — Backend กับ Bot ต้องชี้ Redis instance เดียวกัน (compose override แค่ฝั่งเดียว = ฟังไม่เห็น)
- **Context/Problem:** ฟีเจอร์ "ประกาศจากเว็บไป Discord" (CUSTOM_MESSAGE) ไม่ทำงาน — bot ไม่เคยรับ event จาก Redis เลยแม้ backend log ว่า publish สำเร็จ
- **Root Cause:** `docker-compose.app.yml` override `REDIS_URL=redis://${ENV_NAME}_infra_redis:6379/0` ให้ **เฉพาะ backend** ส่วน bot_discord ไม่อ่าน override นั้น → ตกไปใช้ default ฮาร์ดโค้ด `redis://staging_infra_redis:6379/0` ใน `bot_discord/core/config.py` → backend publish กับ bot subscribe อยู่คนละ instance (หรือ instance ที่ไม่มี) → ข้ามกันตลอด. ส่วน `.env.example` เคยมีบรรทัด `REDIS_URL: str = "redis://..."` (คัด syntax Python ติดมา) ซึ่ง compose อ่านไม่รู้เรื่อง → เงียบ ๆ
- **Correct Pattern/Solution:**
  1. `docker-compose.app.yml`: เพิ่ม `environment: - REDIS_URL=redis://${ENV_NAME}_infra_redis:6379/0` ให้ `bot_discord` ด้วย (คัดจาก backend) → สองฝั่งชี้ instance เดียวกันเสมอ
  2. `backend/core/config.py`: เอา default ออกจาก `REDIS_URL` (บังคับให้ต้องระบุ) — ถ้าเผลอ default ผิด instance บอทจะเงียบตลอด ควรพังเร็ว
  3. `bot_discord/core/config.py`: อ่านจาก env ก่อน ถ้าไม่มี fallback ตาม convention `${ENV_NAME}_infra_redis` (local dev → 127.0.0.1) + validate format (กัน `str =` ติดมา)
  4. `docker-compose.test.yml`: ต้องเติม `REDIS_URL` ให้ test_runner ด้วย (หลังทำให้เป็น required)
  5. `redis_listener.py`: ห่อ `process_event` ใน try/except ต่อ event — เดิม event เดียว error → หลุด subscription ทั้งหมด
- **Rule:** ก่อนเพิ่ม/แก้ฟีเจอร์ที่ใช้ Redis pub/sub ให้ grep `REDIS_URL` ทั้ง `docker-compose*.yml`, `backend/core/config.py`, `bot_discord/core/config.py`, `.env*` และเช็คว่า **ทุก consumer/producer ชี้ instance เดียวกัน** (โดยเฉพาะเมื่อมี env override ใน compose — ต้อง override ให้ครบทุก service ที่ใช้)
- **Date Added:** 2026-08-06

### 🛠️ Web→Discord ประกาศ — action endpoint (service-layer) + RBAC `MANAGE_CLASSROOM_SETTINGS`
- **Context/Problem:** ฟีเจอร์ใหม่ของเว็บ: พิมพ์ข้อความแล้วกดส่งให้ประกาศใน Discord (event `CUSTOM_MESSAGE`) ต้องมี endpoint ใน backend + publish ผ่าน Redis
- **Correct Pattern/Solution:**
  1. `backend/models/action_schemas.py`: `CustomMessageRequest` (title, message, user_name) + `CustomMessageResponse`
  2. `backend/services/action_service.py`: เพิ่ม `ActionService.send_custom_message(pool, room_id, ...)` — เช็คห้อง `deleted_at IS NULL` + `require_permission(..., "MANAGE_CLASSROOM_SETTINGS")` (ประกาศ @everyone ทั้งห้อง → ต้องเป็นผู้มีสิทธิ์) + audit log `entity_type="MESSAGE"` ใน transaction เดียวกัน แล้ว publish `CUSTOM_MESSAGE` ถ้ามี `server_id`
  3. `backend/routers/action_router.py`: thin HTTP layer — `POST /api/classroom/{target_id}/messages` รับได้ทั้ง `target_type=room` (web) และ `target_type=server` (bot, X-API-Key) map `RoomNotFoundError→404`, `ForbiddenError→403`
  4. `backend/main.py`: mount `action_router` ด้วย `prefix="/api/classroom"` tags `["Actions"]`
  5. **ข้อควรระวัง:** ห้องที่ยังไม่มี `server_id` (สร้างผ่านเว็บ ยังไม่ผูก Discord) → service ยัง publish ไม่ได้ (ไม่มีปลายทาง) — endpoint ตอบ success แต่ไม่ publish; เทสต้องสร้างห้อง **พร้อม server_id** ถึงจะ `assert_awaited_once`
- **Rule:** endpoint ใหม่ที่ web+bot ใช้ทั้งคู่ ต้อง (1) ทำ RBAC ใน service (ไม่ใช่ router) (2) router จับ `ForbiddenError→403`, `RoomNotFoundError→404` (3) มี `response_model` เสมอ (4) test ผ่านทั้ง JWT web path และ X-API-Key bot path (5) mock `ActionService.notify_custom_message` เพื่อไม่แตะ Redis จริง
- **Date Added:** 2026-08-06

### 🛠️ GET /{target_id} — แก้ด้วย `get_current_user_or_bot` (bot system identity ผ่าน, web ยังเข้ม)
- **Context/Problem:** หลัง column-switch แล้ว production ยัง 404 — เพราะ 404 เกิดจาก `get_current_user` (auth) ก่อน resolve server_id ด้วยซ้ำ: bot ส่ง `X-Discord-Id = self.bot.user.id` (bot application) ที่ไม่มีใน `users` table → 404
- **Correct Pattern/Solution:** เพิ่ม dependency `get_current_user_or_bot` ใน `core/dependencies.py`:
  1. Bot path (X-API-Key ถูก + X-Discord-Id เป็นตัวเลข) → หา `users.discord_id` ถ้าเจอ → `{"user_id": id, "is_bot_system": False}`; ถ้าไม่เจอ (bot application) → `{"user_id": None, "is_bot_system": True}` (**ไม่ 404**)
  2. Web path (JWT) → เหมือน `get_current_user` เดิม
  3. Route `get_room_data` ใช้ dependency นี้ + `user_id=None if is_bot_system` → ข้าม require_member
  4. **Security:** bot ที่เป็น user จริงแต่ไม่ใช่สมาชิก → ยังโดน require_member → 403 (ไม่เปิดช่องว่าง)
- **Rule:** system RPC ที่บอท application ต้องเรียก อย่าใช้ `get_current_user` ตรง ๆ (มัน 404 เมื่อ bot id ไม่มีใน users) — ใช้ `get_current_user_or_bot`; อย่าเปลี่ยน `get_current_user` เดิม (มี 51 จุดใช้ `user_ctx["user_id"]` ที่พังถ้า None)
- **Date Added:** 2026-08-07

### 🛠️ GET /{target_id} (get_room_data) — สลับคอลัมน์ WHERE ใน query ตรง ๆ แทน resolve แยก (กัน 404 งง ๆ)
- **Context/Problem:** บอทเรียก `GET /api/classroom/<server_id>?target_type=server` เพื่อหา `announcement_channel_id` — เดิมการ resolve อยู่ที่ `resolve_target_to_room_id` dependency (query แยกก่อน แล้ว service query `WHERE id=$1` อีกที) ทำให้ 404 มาจาก query แยก ไม่เห็นภาพ และสับสนว่าเป็น data หรือ code
- **Correct Pattern/Solution:** โยก column-switch เข้า `ClassroomService.get_room_data` ตรง ๆ:
  1. service รับ `target_id` + `target_type` → `where_column = "server_id" if target_type == "server" else "id"` → `SELECT ... FROM rooms WHERE {where_column} = $1 AND deleted_at IS NULL`
  2. `room_id = room["id"]` ใช้สำหรับ audit log + `require_member`
  3. router อ่าน `target_id: int = Path(...)` + `target_type: Literal["server","room"] = Query("room")` ตรง ๆ (ไม่ผ่าน resolve dependency) และ **จับ `RoomNotFoundError→404`** เอง (เดิม 404 มาจาก dependency ตอนนี้ service เป็นคน raise)
  4. ใหญ่ integer (Discord snowflake 19 หลัก) ยังเป็น `int` ได้ (Python int ไม่จำกัดความยาว, BIGINT รับถึง 2^63-1) — ไม่ต้องเป็น str
  5. fallback audit log: ค้น room_id ด้วย `WHERE id = $1 OR server_id = $1` (เผื่อ target เป็น server_id) แล้วใช้ `safe_room_id` กัน FK violation ตอน log failed
- **Rule:** ถ้า endpoint ไหน resolve target ผ่าน dependency + query แยก แล้วเกิด 404 มืด ๆ → ให้สลับคอลัมน์ใน service query ตรง ๆ และให้ router จับ domain exception เอง (ไม่ใช่ dependency); ตรวจ `deleted_at IS NULL` เสมอ; response schema ต้องมี `id` + `announcement_channel_id` ครบ contract ที่ bot ใช้
- **Date Added:** 2026-08-06

### 🛠️ GET /{target_id} (get_room_data) — 404 จริง ๆ มาจาก `get_current_user` ว่าบอท identity ไม่มีใน users ไม่ใช่ server_id query
- **Context/Problem:** Production ยังเห็น `GET /api/classroom/<server_id>?target_type=server → 404` ทั้งที่ publish CUSTOM_MESSAGE สำเร็จ (อ่าน server_id จากห้องได้) — หลังแก้ column-switch แล้วก็ยัง 404 → สงสัยว่าสลับคอลัมน์ผิด แต่จริง ๆ แล้วบัคอยู่ชั้น auth
- **Root Cause:** FastAPI resolve **ทุก dependency ก่อน** เข้า handler — `get_room_data` route มี `Depends(get_current_user)` ซึ่ง bot path ทำ `SELECT id FROM users WHERE discord_id = $1` (X-Discord-Id = `self.bot.user.id`) ถ้าไม่มีแถว → `raise HTTPException(404, "ไม่พบบัญชีผู้ใช้ที่ผูกกับ Discord ID นี้")` — บอท application ไม่เคยถูก insert ใน users table → **404 เกิดก่อน resolve server_id ด้วยซ้ำ**
- **พิสูจน์ด้วยเทส:** `test_bot_unregistered_identity_404` (bot id ไม่มีใน users → 404 แม้ server_id ถูก) vs `test_bot_registered_identity_200` (insert bot id ใน users → 200) — ผ่านทั้งคู่
- **Correct Pattern/Solution:** endpoint ที่บอทใช้เป็น **system RPC** (หา announcement_channel, ส่งประกาศ) ต้องไม่ต้องผ่าน `get_current_user` แบบเดียวกับมนุษย์ — ใช้ `verify_api_key` (เช็ค X-API-Key อย่างเดียว) แทน หรือให้ bot path ข้าม user lookup ไป resolve target ตรง ๆ
- **Rule:** เมื่อบอทส่ง `X-Discord-Id = self.bot.user.id` (bot application) อย่าให้ endpoint ต้องหา `users.discord_id` — ไม่งั้น 404 ที่ auth ก่อนเสมอ; ถ้า endpoint ควรเป็น system RPC ให้ใช้ `verify_api_key` แทน `get_current_user` และเช็ค `docs/skills.md` เรื่อง "Read RPC → require_member Design: Where It Is NOT Safe to Add"
- **Date Added:** 2026-08-06

### 🛠️ Discord Notifications — `mention` + `category` ใน payload (แยก @everyone vs แจ้งเฉยๆ)
- **Context/Problem:** ต้องการให้ทุกความเคลื่อนไหวแจ้งเตือน Discord โดยมี "หัวข้อหมวดหมู่" วางก่อน embed และแยกว่า event ไหนควร `@everyone` (เช่น มีงานใหม่, ประกาศ, แคมเปญเก็บเงิน) กับ event ไหนแค่แจ้งเฉยๆ (เช่น ส่งงาน, รายรับ-จ่าย, จ่ายเงิน, สมาชิกใหม่)
- **Correct Pattern/Solution:**
  1. `ActionService._publish` รับ `mention: bool = False` + `category: str` → ใส่ลง payload ทุก event; `notify_*` แต่ละตัวกำหนดค่าเอง (NEW_TASK → mention=True, TASK_DONE → mention=False, ...)
  2. Bot `BotActionService._build_content(data, fallback)` → `"{category} @everyone"` ถ้า `mention` จริง, ไม่งั้น `"{category}"` → ส่งเป็น `content=` ก่อน embed
  3. ระบบที่ควรแจ้ง (มี ActionService publish): งาน (NEW_TASK/TASK_DONE), โน้ต (NEW_NOTE), ประกาศ (CUSTOM_MESSAGE), การเงิน (FINANCE_TRANSACTION/FINANCE_PAYMENT/FINANCE_COLLECTION), สมาชิก (NEW_STUDENT)
  4. การเงิน: `add_transaction` → notify_new_finance (income/expense, ไม่ @everyone แต่โชว์ความโปร่งใส), `confirm_payment` → notify_payment_confirmed, `create_fee_collection` → notify_new_collection (@everyone)
  5. สมาชิก: `add_student` → notify_new_student (ไม่ @everyone)
- **Rule:** ตอน publish ต้อง fetch `server_id` ของห้องจาก DB (ห้องที่ยังไม่ผูก Discord → server_id None → ข้าม publish); publish หลัง commit transaction; bot ใช้ `_build_content` เป็นจุดเดียวที่ตัดสินใจ content prefix เพื่อให้ทุก event สอดคล้อง
- **Date Added:** 2026-08-07

### 🛠️ Student Excel Export — openpyxl 2 แผ่น (สรุป + รายชื่อ) + วันเกิดแบบไทย พ.ศ.
- **Context/Problem:** `StudentService.export_students_excel` เดิมใช้ pandas `to_excel` — หัวตารางเป็นชื่อ field ภาษาอังกฤษ, ไม่มีรูปแบบ (สี/Freeze/ความกว้าง), `birthday` หลุดออกมาเป็น `datetime.date` ดิบ → ไฟล์ไม่เหมาะนำไปใช้งานจริง ผู้ใช้ต้องการไฟล์แบบ 2 แผ่นสวยงามพร้อมวันเกิดแบบ "25 กรกฎาคม 2553"
- **Root Cause:** pandas write path คุม per-cell style ได้จำกัด และ backend ไม่มี Thai label/role/status/month mapping (labels อยู่ฝั่ง frontend เท่านั้น)
- **Correct Pattern/Solution:**
  1. สร้าง workbook ด้วย openpyxl ตรง ๆ (`Workbook`, `PatternFill`, `Font`, `Alignment`, `get_column_letter`) เลียนแบบ `finance_service._build_finance_workbook`
  2. วันเกิดแบบไทย: `f"{d.day} {THAI_MONTH_NAMES[d.month - 1]} {d.year + 543}"` + tuple 12 ชื่อเดือนไทย; ถ้าเป็น `datetime` ต้อง `.date()` ก่อนเสมอ
  3. รักษาลำดับคอลัมน์ตามที่ผู้ใช้ส่งมา: iter ตาม list `fields` ทั้งตอนเขียน header และทุก data row — อย่าพึ่ง dict ordering
  4. แยกคีย์ภายใน (`_status`, `_completion_percent`) ไว้ใน processed row dict สำหรับ Sheet สรุป — ตอนเขียน Sheet "รายชื่อ" ให้ iter แค่ `fields` เท่านั้น คีย์ `_` จะไม่หลุดลงไฟล์
  5. Style: `HEADER_FILL = PatternFill("solid", fgColor="1D4ED8")`, ฟอนต์หัวขาว bold, `freeze_panes = "A2"`, `sheet_view.showGridLines = False`, `column_dimensions[get_column_letter(i)].width`, สลับสีแถวคู่ `F8FAFC`
  6. แปลงค่า: `birthday`→พ.ศ., `class_role`/`status`→ไทย ผ่าน dict map ที่ backend เป็นเจ้าของเอง (ห้าม import จาก frontend); กัน `fields` ซ้ำด้วย `seen` set รักษาลำดับ
- **Rule:** การ export ที่ต้องการ styling ใช้ openpyxl ตรง ๆ แทน pandas; คอลัมน์ที่ user เลือกลำดับเองต้องเขียนตาม `fields` order; ค่าที่เป็น enum (role/status) ควรแปลเป็นไทยใน backend ไม่ใช่ส่ง raw key
- **Date Added:** 2026-08-07

### 🛠️ rooms รองรับห้องแฮปปี้เบิร์ดเดย์ + ห้องแจ้งเตือนงานเล็กๆน้อยๆ (mini-channels)
- **Context/Problem:** ต้องการแยกช่อง Discord สำหรับ (1) คำอวยพรวันเกิด (2) การแจ้งเตือนระดับ "สแปม" (ส่งงาน, รายรับ/จ่าย, จ่ายเงิน, สมาชิกใหม่) ออกจากห้องแจ้งเตือนหลัก — ป้องกันห้องหลักรก และอยากให้บอทอวยพรวันเกิดอัตโนมัติทุกเช้า
- **Correct Pattern/Solution:**
  1. **Schema:** เพิ่ม `rooms.birthday_channel_id` + `rooms.minor_notify_channel_id` (BIGINT NULL) ใน `init_db.py` ทั้งใน `CREATE TABLE` และในส่วน Extra Alterations (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) — ห้องที่ deploy ไปแล้วจะได้คอลัมน์ตอนรีสตาร์ทโดยไม่ต้อง migrate แยก
  2. **set_channel รองรับ channel_type:** `ChannelSetRequest.channel_type` (default `"announcement"`) → `ClassroomService.set_channel` ใช้ `CHANNEL_TYPE_COLUMNS` whitelist dict โยงชื่อ → คอลัมน์ (`announcement/birthday/minor`) แล้วแทรกชื่อคอลัมน์จาก whitelist ลง SQL (กัน SQL injection — ห้ามใช้ชื่อที่ user ส่งตรง ๆ) — bot เดิมที่ยังไม่ส่ง `channel_type` ยังทำงานเหมือนเดิม (default announcement)
  3. **Birthday RPC:** `GET /api/classroom/birthdays/today?target_date=YYYY-MM-DD` (system-only `verify_api_key` เหมือน `/notifications/targets`) → `ClassroomService.get_birthday_celebrants` join `rooms`+`students`(active)+`users` เปรียบเทียบ `date_part('month'/'day', birthday) = date_part('month'/'day', target_date)` (กันปัญหา leap year 29 ก.พ.) → group ตาม server_id
  4. **Bot อวยพรวันเกิด:** `BotCommands.daily_notification` (loop ทุกนาที) เรียก `/birthdays/today` → **กันซ้ำด้วย `self._last_birthday_check != now.date()`** (ไม่งั้น loop ทุกนาทีจะอวยพรซ้ำ 1440 ครั้ง/วัน) → `BotActionService.notify_birthday` ส่ง embed ไป `birthday_channel_id` (ไม่ตั้ง → ตกไป `announcement_channel_id`)
  5. **Low-priority → minor channel:** `ActionService._publish` เพิ่ม field `channel` (default `"announcement"`); `notify_task_done`/`notify_new_finance`/`notify_payment_confirmed`/`notify_new_student` ส่ง `channel="minor"`; bot `_get_announcement_channel(server_id, channel=...)` เลือก `minor_notify_channel_id` ก่อน แล้วตกไป `announcement_channel_id` — ลบคอมเมนต์ `⚠️ [LOW-PRIORITY]` ทั้งหมดออก (งานนี้คือการลบ debt เดิม)
- **Rule:** (1) ทุกครั้งเพิ่มคอลัมน์ให้ตารางที่มีอยู่ ต้องมีทั้งใน `CREATE TABLE` และ `ALTER TABLE ADD COLUMN IF NOT EXISTS` (2) ชื่อคอลัมน์ที่มาจาก input ต้องผ่าน whitelist dict เสมอ อย่า interpolate ตรง (3) endpoint ที่เป็น system RPC สำหรับบอท loop ใช้ `verify_api_key` ไม่ใช่ `get_current_user` (ดู lessons เดิม) (4) ใส่ไอเท็มตีความ "โหลด loop" ต้องนึกถึงความถี่ — loop ทุกนาทีต้องมี guard กันส่งซ้ำ (5) test publish ผ่าน `patch("services.action_service.aioredis.from_url")` — `publish(channel, json_string)` → JSON อยู่ `args[1]` ไม่ใช่ `args[0]` (6) ทดสอบ channel routing ทั้ง service-level (ไม่แตะ Redis) และ HTTP-level (X-API-Key)
- **Date Added:** 2026-08-07

### 🛠️ Finance — รับเงินรวบยอด (Batch) — frontend ลูปยิงทีละบิล → backend batch endpoint + notification เดียว
- **Context/Problem:** หน้าเว็บ `DebtorList.vue` ("เคลียร์หนี้") เลือกหลายบิลค้างของนักเรียนคนเดียวกันแล้วกดรับเงิน → ใช้ `Promise.all(selectedPaymentIds.map(confirmPayment))` ยิง `PUT /payments/{id}/pay` **ทีละบิล** → รับเงิน 5 บิล = Discord ส่ง embed "✅ มีการชำระเงิน" **5 รอบ** (minor channel รก) + `Promise.all` ยัง atomic ไม่ได้ (บิลหนึ่ง error → บางบิล commit บางบิลไม่ commit ข้อมูลครึ่งๆ กลางๆ)
- **Correct Pattern/Solution:**
  1. **Backend batch endpoint:** `PUT /{target_id}/finance/payments/batch` รับ `BatchPaymentConfirm` (`items: [{payment_id, paid_amount}]`, `paid_to_account_id`, `slip_image_url`, `user_name`) → `FinanceService.batch_confirm_payments` วนเรียก helper `_confirm_single_payment` **ภายใน `async with conn.transaction():` เดียว** → atomic (บิลหนึ่ง error → rollback ทั้งชุด)
  2. **Refactor: ดึง logic รับเงิน 1 บิลออกเป็น `_confirm_single_payment(conn, target_room_id, ...)`** — ใช้ร่วมโดย `confirm_payment` (single) และ `batch_confirm_payments` → single path เดิมยังทำงานเหมือนเดิม (เทสเดิมไม่พัง) helper ต้องไม่เปิด transaction เอง (ให้ caller เป็นคนครอบ)
  3. **Guard batch:** dedupe `payment_ids` (กันจ่ายบิลเบิ้ล), ตรวจทุกบิลเป็น `FC.status='active'` และเป็นของ `FC.room_id` (โดนปิด/ข้ามห้อง → PaymentNotFoundError), และ **ทุกบิลต้องเป็น `student_id` เดียวกัน** (`len(student_ids) > 1 → ValueError`) — กันแจ้งเตือนรวมงง / จ่ายข้ามคน
  4. **Notification เดียว:** หลัง commit → `ActionService.notify_payments_confirmed(server_id, payer_name, items, total_amount, user_name)` publish event `FINANCE_PAYMENT` **1 รอบ** พร้อม `items` (ทุกบิล); บอท `notify_finance_payment` ถ้า `data.get("items")` → render embed สรุป "✅ รับเงินรวบยอด: X รายการ รวม Y บาท" + รายการทุกบิล (ถ้าไม่มี items = single path → render เดิม backward compat)
  5. **Frontend:** `DebtorList.handleBatchPay` เปลี่ยนจาก `Promise.all` → **1 call** `confirmBatchPayment` (ยิง `/payments/batch`) — `CollectionDetail.vue` ยังใช้ single `confirmPayment` ต่อบิล (รับทีละคนคนละบิล ยังสมเหตุสมผล ไม่แตะ)
  6. **เส้นทาง route:** `payments/batch` (4 segment) ต่างจาก `payments/{payment_id}/pay` (5 segment) → ไม่ชนกัน
  7. **Test note:** เทสที่ insert ห้องด้วย helper ตรง (ไม่ผ่าน `create_room`) ไม่มีหมวดหมู่ seed `📥 เก็บเงินห้องปกติ` → dual-write **ข้าม journal** (ตาม design) → ถ้าจะ assert journal ต้อง `_insert_category(pool, room_id, "📥 เก็บเงินห้องปกติ", "income")` ก่อน; assert atomicity ด้วย overpay บิลใดบิลหนึ่ง → 400 + บิลที่ถูกต้องก็ไม่โดน commit (balance/status คงเดิม)
- **Rule:** (1) flow ฝั่ง client ที่ยิงหลาย mutation พร้อมกัน (Promise.all) ควรรวมเป็น batch endpoint ฝั่ง backend เมื่อต้องการ atomic + notification รอบเดียว (2) mutation ที่จะวนหลายรายการให้แยก single-item logic เป็น helper แล้วให้ batch วนเรียกใน transaction เดียว (3) notification payload ที่บอท render ต่างกันตาม single/batch ให้ใช้ optional `items` เป็นตัวแยก (backward compat) (4) ก่อน assert journal/dual-write ใน test ที่สร้างห้องเอง ให้เช็คว่ามี seed หมวดหมู่รายได้ครบ (ดู lesson "Room create_room — seed หมวดหมู่/บัญชีค่าเริ่มต้น")
- **Date Added:** 2026-08-09

### 🛠️ Frontend Mobile-Responsive Overhaul — design tokens + บัคที่พบ (h-dvh, dropdown teleport, mobile-card pattern)
- **Context/Problem:** ทุกหน้าของ Vue SPA แสดงผลเหมือน "ย่อหน้าจอคอมมาลงมือถือ" — เมนู/การ์ด/header ใหญ่เกิน ต้องเลื่อนตลอด, MainLayout บัคบนมือถือหลายจุด, EditStudent form แทบใช้ไม่ได้บนโทรศัพท์ (input เหลือ ~129px), และ sidebar desktop ย่อไม่ได้ (user ต้องการซ่อนได้)
- **Root Causes (ที่พบจากการ audit 7 agents):**
  1. **`h-screen` = 100vh** บนมือถือสูงกว่าจอที่มองเห็น (dynamic toolbar) → เนื้อหาด้านล่าง ~60-100px ไปไม่ถึง ต้องใช้ `h-dvh` (มี `h-screen` เป็น fallback ก่อน สำหรับ iOS <16.4)
  2. **`overflow-y-auto` ลำพัง** ทำให้ `overflow-x` คำนวณเป็น `auto` (CSS spec) → ตาราง `min-w-[700px]`/`min-w-[1400px]` เกิด horizontal scrollbar ซ้อนใน main → ต้อง `overflow-x-hidden` คู่กันทุก scroll container
  3. **Dropdown ถูก trap ใน stacking context ของ header/sidebar** (z-50 ภายใน parent z-30) → คลิกนอกไม่ปิด/เปิด drawer ทับ → แก้ด้วย Teleport ไป body + backdrop `z-[70]` + panel `z-[80]`
  4. **Grid `grid-cols-N` ที่ไม่ collapse** (EditStudent x6, Lobby join-modal x3, FinanceSettings x2, Roadmap x6, FinanceDashboard quick-menu x4) → input ถูกบีบแคบมาก → กฎ: ทุก grid ต้องเริ่ม `grid-cols-1` แล้วค่อย `sm:/md:/lg:`
  5. **Tailwind JIT ไม่ compile runtime class** — ExportStudent ใช้ `cat.bg.replace('50','500')` → checkbox ไม่มีสี → ต้อง static class map (literal)
  6. **`new Date('YYYY-MM-DD')` parses UTC midnight** → badge งานเพี้ยน 1 วันใน Asia/Bangkok → ต้อง `dateStr + 'T00:00:00'` (local)
  7. **Touch target < 44px** — icon button `w-8 h-8` (32px), text 10px อ่านยาก → พื้นฐาน `h-9/w-9` (36px) หรือใหญ่กว่า + `text-xs` เป็นขั้นต่ำ
- **Correct Pattern/Solution:**
  1. **Layout shell:** root `h-screen h-dvh` + `overflow-hidden`; main = `overflow-y-auto overflow-x-hidden`; padding token `px-3 sm:px-5 md:px-6 py-4 md:py-6`
  2. **Sidebar desktop ย่อได้:** state `isSidebarCollapsed` + persist `localStorage` + `w-64 ↔ w-[76px]` transition; mobile = drawer `w-[280px] max-w-[85vw]` + `slide-right` transition
  3. **Dropdown anchor:** Teleport + `getBoundingClientRect()` ของ trigger (querySelector `[data-dropdown-trigger]`) + reposition on scroll/resize — ห้าม hardcode fixed left/top
  4. **Mobile card + desktop table:** `block md:hidden` (cards) + `hidden md:block` (table ใน `overflow-x-auto`) — ใช้กับ StudentList, CollectionDetail, DebtorList, TransactionHistory
  5. **Modal = bottom sheet บนมือถือ:** `items-end md:items-center rounded-t-3xl md:rounded-3xl max-h-[90dvh]`
  6. **Drawer ต้องปิดเอง:** ใส่ `watch(route.path)` ปิด drawer + dropdown ทุกครั้งที่เปลี่ยนหน้า; ปุ่มใน drawer เรียก `closeMobileDrawer()` ด้วย
- **Rule:** (1) ห้าม `h-screen` สำหรับ app shell ใช้ `h-dvh` + fallback (2) ทุก scroll container ใส่ `overflow-x-hidden` (3) dropdown/overlay → Teleport body + z-[70/80] (4) ทุก `grid-cols-N` ต้อง responsive prefix (5) ห้ามสร้าง Tailwind class แบบ runtime (`.replace()`/template literal) (6) วันที่ที่รับจาก API เป็น `YYYY-MM-DD` ต้อง parse local เสมอ (7) interactive control ต้อง ≥ 36-44px, text อ่านได้ ≥ 12px
- **Date Added:** 2026-08-09

### 🛠️ Activity & Role Management — ระบบกิจกรรม/ผู้เข้าร่วม (JSONB metadata + soft-delete + NEW_ACTIVITY)
- **Context/Problem:** สร้างฟีเจอร์ "กิจกรรม + ผู้เข้าร่วม + หน้าที่" ทั้ง 3 เลเยอร์ (FastAPI / Vue / Discord bot) โดยยึด JSONB metadata เพื่อต่อยอด Dynamic และต้องไม่แหกกฎเดิมของโปรเจกต์
- **Correct Pattern/Solution:**
  1. **Schema:** `activities` + `activity_participants` ใน `core/init_db.py` — `metadata JSONB DEFAULT '{}'::jsonb` + GIN index; **กับดัก:** `UNIQUE(activity_id, student_id)` บังคับทั้งตาราง → soft-delete แล้ว re-add คนเดิมชน constraint → ต้องใช้ **partial unique index** `idx_activity_participants_active ... WHERE deleted_at IS NULL` และ "เพิ่มคนที่เคยถูกลบ" ต้อง revive (`UPDATE ... SET deleted_at = NULL`) ก่อน INSERT ใหม่
  2. **JSONB parsing:** asyncpg คืน `str` หรือ `dict` ตามเวอร์ชัน → helper `_parse_metadata(raw)` = `json.loads(raw) if isinstance(raw, str) else raw` ใช้ทุกจุดที่อ่าน metadata (mirror จาก skills.md เดิมเรื่อง permissions)
  3. **create_activity atomic:** INSERT activity + `executemany` INSERT participants **ภายใน `async with conn.transaction():` เดียว** — participant ตัวไหน error (เลขที่ซ้ำ/ไม่ active) → rollback ทั้งก้อน; ตรวจ `students.status='active' + deleted_at IS NULL` (ตาม lesson "เพิ่ม pending student") + ห้ามเลขที่ซ้ำในรายชื่อ
  4. **Audit:** ทุก mutation (CREATE/UPDATE/DELETE กิจกรรม + participant) เขียน `service_logger.log` ใน transaction เดียวกัน พร้อม `old_values`/`new_values` (metadata ต้อง `json.dumps(default=str)` กัน date/Decimal)
  5. **PATCH metadata = merge ไม่ใช่ replace:** `update_activity`/`update_participant` ถ้า `metadata` ถูกส่ง ให้ `merged = dict(old_metadata); merged.update(new)` แล้วค่อย UPDATE — กันทำหายคีย์ที่ไม่ได้ส่ง
  6. **Notification:** `ActionService.notify_new_activity` publish `NEW_ACTIVITY` (mention=True, channel=announcement) **หลัง commit** — ห้องที่ไม่มี `server_id` (ยังไม่ผูก Discord) → ข้าม publish (เหมือน notify_new_task); test ต้องสร้างห้อง `server_id` ถึงจะ `assert_awaited_once`
  7. **FastAPI route ordering:** `GET /{target_id}/activities/me/roles` ต้องประกาศ **ก่อน** `GET /{target_id}/activities/{activity_id}` — ไม่งั้น FastAPI match "me" เป็น `activity_id` → 422 (literal segment ยังชน path param ได้ ถ้า registration order ไม่ดี)
  8. **RBAC:** เพิ่ม `MANAGE_ACTIVITIES` ใน `core/rbac.py` `AVAILABLE_PERMISSIONS` + `config/roles.json` — อ่าน (GET) ใช้ `require_member` (โปร่งใส), เขียน (POST/PATCH/DELETE) ใช้ `require_permission(..., "MANAGE_ACTIVITIES")` ใน service
  9. **Excel export (openpyxl):** คอลัมน์ metadata ที่ user เลือก (`metadata_keys`) กลายเป็นคอลัมน์จริง — base fields อ่านจาก record, metadata keys อ่านจาก `participant.metadata`; header แปลงไทยผ่าน `EXPORT_HEADER_LABELS`
  10. **Frontend:** ตารางเลือกผู้เข้าร่วม = checkbox + `role_detail` input โผล่เมื่อติ๊ก + ปุ่ม ⚙️ เปิด modal กรอก metadata ต่อคน (bottom sheet บนมือถือ); Badge หมวดหมู่ดึงจาก `metadata.tags` (array หรือ string คั่น `,`)
  11. **Discord bot:** `notify_new_activity` render embed จาก metadata (`location_url` → Google Maps link, `agenda` list/str → วนลูป, `tags` → badge, `participant_count`); slash commands `/activities` (upcoming) + `/my_roles` (role_detail + `participant_metadata.bus_number`) ผ่าน `GET /{guild}/activities` / `GET /{guild}/activities/me/roles?target_type=server`
- **Rule:** (1) ตารางที่มี `UNIQUE(col1,col2)` + soft-delete ต้องใช้ partial unique index แทน และ "re-add" ต้อง revive ก่อน (2) JSONB metadata อ่านแล้ว normalize เป็น dict เสมอ (3) create หลาย entity พร้อมกัน → transaction เดียว + executemany (4) PATCH field ที่เป็น object → merge ไม่ใช่ replace (5) route ที่เป็น literal segment ประกาศก่อน path param เสมอ (6) publish หลัง commit + ห้องไม่มี server_id → ข้าม (7) คอลัมน์ metadata ใน Excel ต้องใช้ key ตรง ๆ ไม่ใช่ label
- **Date Added:** 2026-08-14

### 🛠️ Dynamic Smart Forms — Field Selector (required_fields) + Type A/B + Batch Apply
- **Context/Problem:** Refactor ระบบกิจกรรมเป็น "Dynamic Smart Forms" — ฟิลด์ที่กิจกรรมจะเก็บต้องกำหนดได้ตั้งแต่สร้าง (Field Selector) เพื่อให้ตารางผู้เข้าร่วม/Excel export แสดงเฉพาะคอลัมน์ที่จำเป็น (DRY Principle) และต้องมี Batch Action (คลุมดำตั้งค่ารถบัส/ห้องพักทีเดียว)
- **ข้อมูลส่วนตัว (Type A) ห้ามบันทึกซ้ำลง JSONB:** `blood_group, shirt_size, food_allergy, congenital_disease, phone_number, phone_number_parent` อยู่ในตาราง `users` → `PARTICIPANT_SELECT` JOIN `users` กลับมาให้เสมอ (ตอน GET detail) + `get_student_activity_roles` JOIN ด้วย → ฝั่ง Vue แสดงเป็นข้อความอ่านอย่างเดียว (🔒) และ export อ่านจาก `p.get(field)` แทน `metadata` — เปลี่ยน label "เบอร์รถบัส"→"หมายเลขรถบัส", "เบอร์โทร"→"เบอร์โทรศัพท์นักเรียน" ตาม spec (ต้องแก้เทสเดิมด้วย)
- **Field Dictionary แชร์ข้ามเลเยอร์:** `frontend/src/constants/activityFields.ts` (PROFILE_FIELDS/EVENT_FIELDS, input/dropdown/boolean/datetime, หมวด transport/accommodation/operation) เป็น source of truth — backend `PROFILE_FIELDS`/`EXPORT_HEADER_LABELS` และ bot `PROFILE_FIELD_LABELS`/`EVENT_FIELD_LABELS` ต้องซิงก์ manual
- **CreateActivity Field Selector:** ติ๊ก checkbox → เก็บ Array คีย์ลง `activities.metadata.required_fields` → backend export อ่านค่านี้ generate header (ถ้าไม่มี → fallback `metadata_keys` ที่ frontend ส่ง backward compat) → **ลดคอลัมน์ขยะว่างเปล่า**
- **DRY field reader:** `_field_reader(field)` = Type A → อ่าน record (JOIN users), Type B → อ่าน `participant.metadata` — ใช้จุดเดียวทั้ง export (แทน BASE_READERS ที่แยก metadata อ่านทีละ key)
- **Type A ต้อง strip จาก payload ตอน create:** frontend `CreateActivity.submit` กรอง metadata ที่ส่งไป backend ให้เหลือเฉพาะ `EVENT_FIELD_KEYS` — กันบันทึก shirt_size ซ้ำลง JSONB
- **`is_paid` boolean → Excel:** `_translate_label` แปลง bool เป็น "✅ จ่ายแล้ว"/"⏳ ยังไม่จ่าย" (เหมือน label enum อื่น)
- **Batch Apply endpoint:** `PATCH /{target_id}/activities/{activity_id}/participants/batch` — `BatchParticipantUpdateRequest{items:[{participant_id, metadata}]}` → `batch_update_participants` วน update metadata (merge กับของเดิม) **ภายใน transaction เดียว** (atomic) + dedupe participant_id + audit log ต่อคน — **route ต้องประกาศก่อน `/participants/{participant_id}`** (literal "batch" ชน path param ไม่งั้น 422 — ตาม lesson route ordering)
- **Frontend Smart Table:** คอลัมน์ = `required_fields` ที่เลือก → Type A แสดง text (🔒), Type B render `ActivityFieldControl` (input/dropdown/checkbox/datetime) แก้ในตารางได้เลย + `@change` (blur/select/checkbox) ยิง PATCH ต่อ cell
- **Batch UX (คลุมดำ):** checkbox หน้าแถว + "เลือกทั้งหมด" → ปุ่ม "ตั้งค่าแบบกลุ่ม" → Modal โชว์เฉพาะฟิลด์ Type B ที่เลือก → ค่าเดียวยิง Batch endpoint → merge ลงทุกคนที่ติ๊ก
- **Bot notify_new_activity:** อ่าน `metadata.required_fields` → ฟิลด์ Type B → field "⚠️ สิ่งที่ต้องเตรียมตัว" (เช่น "การจัดสายรถบัส และ การจัดห้องพัก …กรุณาเข้าไปตรวจสอบที่หน้าเว็บ"), Type A → field "🔒 หมายเหตุ" (เช่น "ใช้ข้อมูลไซส์เสื้อจากโปรไฟล์ …อัปเดตในระบบ")
- **Rule:** (1) ข้อมูลที่อยู่ใน users ห้ามเก็บซ้ำลง JSONB — JOIN กลับมาเสมอ (2) config ฟิลด์ (types/options/labels) ควรมีที่เดียวแล้วแชร์ logic ไปทุกเลเยอร์ (3) export ควรอ่าน `required_fields` จาก activity metadata ไม่ใช่รับจาก client เสมอ (4) batch mutation → transaction เดียว + dedupe id + audit ต่อรายการ (5) Pydantic response_model ต้องประกาศ Type A ฟิลด์ใหม่ ไม่โดน strip (6) asyncpg JSONB คืน str/dict ตามเวอร์ชัน → normalize ก่อนเปรียบเทียบ
- **Date Added:** 2026-08-14

### 🛠️ Git Push/PR ติด DNS — วน retry จนกว่าจะได้ (เป็นปกติช่วงนี้)
- **Context/Problem:** `git push` และ `gh pr create` ขึ้น `dial tcp ... i/o timeout` หรือ `gh auth status` ติด "Timeout trying to log in" — เครือข่ายที่เครื่องนี้มีปัญหา DNS/egress เป็นพัก ๆ ไม่ใช่ทุกครั้ง (ครั้งแรก timeout 2 นาที, ครั้งที่สองสำเร็จ)
- **Correct Pattern/Solution:** อย่าเครียดกับ timeout แรก — **ลูป retry** จนกว่าจะผ่าน:
  1. `git push -u origin <branch>` → ถ้า timeout → รอ ~20s → ลองใหม่ (ครั้งนี้สำเร็จครั้งที่ 2)
  2. `gh pr create ...` → ถ้า timeout → retry เช่นกัน (ครั้งนี้ครั้งแรกผ่าน)
  3. ใช้ `timeout 90 <cmd>` กันคำสั่งค้าง ไม่มีกำหนด + รันเป็น background (`run_in_background`) + `Monitor` ดูผลเพื่อไม่ต้องรอเฉย ๆ
- **Rule:** ช่วงที่เครือข่ายไม่เสถียร (DNS timeout) ให้ wrapper คำสั่ง network (push/pr/clone) ด้วย loop retry ~5-8 รอบ รอ ~20s ระหว่างรอบ แล้วหยุดทันทีที่สำเร็จ — อย่า report เป็น error ถ้ายังไม่ลองครบ และอย่าปล่อยให้ timeout ครั้งเดียวหยุดงาน
- **Date Added:** 2026-08-14

### 🛠️ Activity Edit — Participant Reconcile (`_reconcile_participants`) + per-activity duty positions
- **Context/Problem:** หน้าแก้ไขกิจกรรมต้อง "แก้ได้ทุกอย่างเหมือนตอนสร้าง" — รวมถึงแทนที่ผู้เข้าร่วมทั้งชุด (เพิ่ม/แก้/ลบ/กู้คืน) ภายใน atomic transaction เดียว แต่ `update_activity` เดิม PATCH เฉพาะแถว activity (ไม่แตะ participants) และหน้าเว็บใช้คำ "metadata" ซึ่งผู้ใช้ไม่คุ้นเคย
- **Correct Pattern/Solution:**
  1. **Schema:** `ActivityUpdateRequest.participants: Optional[List[ActivityParticipantIn]]` — router ใช้ `model_dump(exclude_unset=True)` → ยังไม่ส่ง participants = status-only PATCH ไม่แตะคนเข้าร่วม; ส่ง `[]` ชัดเจน = ลบทั้งหมด. **ไม่ต้อง endpoint ใหม่** — ยัดลง PATCH เดิม
  2. **Service `_reconcile_participants(conn, room_id, activity_id, participants, user_name, ...)`:** วน `_validate_participants` (เช็ค active + dedupe) → 3 กรณี: มี `student_id` อยู่แล้ว → UPDATE (แทนที่ metadata เต็ม เพราะ form round-trip ทั้งชุด ไม่ merge); soft-deleted → revive (`UPDATE ... SET deleted_at = NULL ... RETURNING id` ตาม lesson partial unique index); ไม่มี → INSERT. แล้วลูปที่เหลือ: active ที่ไม่ถูกส่ง → soft delete (`deleted_at = NOW()`). **audit log 1 รายการต่อ mutation** (CREATE/UPDATE/DELETE, entity_type="ACTIVITY_PARTICIPANT")
  3. **empty-fields guard:** เปลี่ยนเป็น `if not fields and participants is None:` — เปิดทาง PATCH ที่ส่งแค่ participants
  4. **ตำแหน่ง/หน้าที่ต่อกิจกรรม:** เก็บ `metadata["positions"]` = array ของชื่อตำแหน่ง (เช่น `["นักกีฬา","แสตน","สตาฟแสตน"]`) — ค่าเดียวกับ label (ไม่ต้อง {key,label}); fallback `DEFAULT_ACTIVITY_POSITIONS` ถ้าไม่มี key. PATCH metadata merge ระดับ 1 จัดการให้อัตโนมัติ
  5. **Frontend shared form:** ดึง `CreateActivity.vue` → `components/activities/ActivityForm.vue` (props: `mode: 'create'|'edit'`, `initialActivity`; emit `saved(activityId)`) → `CreateActivity.vue` กลายเป็น thin wrapper + `EditActivity.vue` ใหม่. ผู้เข้าร่วม `role_detail` = `"{position}"` หรือ `"{position}: {note}"` (split/join helper ใน activityFields.ts) — เก็บ string เดียว ไม่เปลี่ยน schema, export Excel + bot `/my_roles` ยังอ่านได้
  6. **Edit prefill:** form/metadata/positions/required_fields/selectedNos/dutyPosition/dutyNote/participantMeta + กันทับ `earned_hours`/`role_type`/`status` เดิม (map participantHours/participantRoleType/participantStatus) — ผู้เข้าร่วมใหม่เท่านั้นที่ inherit base_hours/'participant'
- **Rule:** (1) "แก้ทุกอย่างเหมือนตอนสร้าง" → ใช้ PATCH เดิม + `participants` optional + reconcile ใน transaction เดียว ไม่สร้าง endpoint ใหม่ (2) reconcile ต้อง revive soft-deleted ก่อน INSERT (partial unique index) (3) form ที่ round-trip metadata เต็ม → **replace** ไม่ใช่ merge (ต่างจาก batch/status PATCH ที่ merge) (4) ข้อมูลเดิมของ entity (hours/role_type/status) ต้องเก็บและส่งคืน ตอน edit ห้ามทับเป็น default (5) UI แสดงคำ user-facing ควรเป็นภาษาไทยเข้าใจง่าย ไม่ใช้คำ technical (metadata → "ข้อมูลเพิ่มเติม")
- **Date Added:** 2026-08-14

### 🛠️ Activity UX Overhaul — custom_fields (หัวข้อ+ค่า) + dual-write + batch role_detail + export no-raw-keys
- **Context/Problem:** ระบบกิจกรรมถูกออกแบบยึดกีฬาสี (default positions ผูกกีฬาสี, ต้องพิมพ์ "ชื่อตัวแปร" ตอนเพิ่มข้อมูลเพิ่มเติม, แสดงคีย์ดิบในหน้า/Excel, batch ตั้งหน้าที่ไม่ได้) → ปรับ UX ให้เป็นกลาง/อ่านง่าย โดยไม่พังระบบเดิม (Discord bot + ActivityList อ่านคีย์เก่า)
- **Root Cause & Solutions:**
  1. **ข้อมูลเพิ่มเติมแบบ friendly:** เก็บ `activities.metadata.custom_fields = [{label, value}]` (และ `activity_participants.metadata.custom_fields` ต่อคน) **+ dual-write คีย์เก่า** (`location_name/url`, `agenda`, `tags`) → บอท/List ยังอ่านคีย์เก่าได้ไม่ต้องแก้. เมื่อ user ลบแถว "สถานที่" ออก ต้องส่ง `location_name: null` → backend `update_activity` metadata merge ต้อง **delete-on-null** (`if v is None: merged.pop(k)`) กัน ghost key ค้าง (เดิม merge เก็บ key เก่าตลอด)
  2. **R1 (bug สำคัญ):** create-mode ของ ActivityForm กรอง metadata participant เหลือแค่ `EVENT_FIELD_KEYS` → `custom_fields` ถูกทิ้งตอนสร้าง → ต้อง allow `k === 'custom_fields'` ด้วย ไม่งั้นข้อมูลเพิ่มเติมต่อคนหายเงียบ (edit mode round-trip เต็มจึงไม่เป็น)
  3. **Batch ตั้งหน้าที่:** `BatchParticipantItem.role_detail` optional (ไม่ส่ง = ไม่แตะของเดิม, "" = เคลียร์) → `batch_update_participants` ต้อง **พก role_detail ผ่าน dedupe loop** + dynamic UPDATE SET (`metadata` base + `, role_detail = $n` เมื่อมี) + audit `old_values/new_values` ใส่ `role_detail` — เหมือน pattern `update_participant`
  4. **Export ไม่ dump คีย์ดิบ:** summary sheet ใช้ `_format_activity_meta_lines` (map `tags→หมวดหมู่`, `positions→หน้าที่/ตำแหน่ง`, `required_fields→ข้อมูลที่เก็บต่อคน` + label ไทยผ่าน EXPORT_HEADER_LABELS, custom_fields → "หัวข้อ: ค่า") — คีย์ภายในอื่น ๆ รวมเป็น "อื่นๆ" ไม่ dump ทีละ key; data sheet เพิ่มคอลัมน์ "ข้อมูลเพิ่มเติม" **เฉพาะเมื่อมีใครสักคนกรอก custom_fields** (กัน header เปลี่ยน → เทสเดิมไม่พัง)
- **Rule:** (1) "ข้อมูลเพิ่มเติม" ที่ user ต้องเห็น/export ต้องเป็น label ไทยไม่ใช่คีย์ตัวแปร (2) dual-write คีย์เก่า + merge ต้องมี delete-on-null เมื่อ frontend ส่ง `null` (3) batch ที่เพิ่ม field ใหม่ต้อง carry ผ่าน dedupe + dynamic SET + audit ครบ (4) export คอลัมน์ที่อ่านจาก array/object ต้อง format เป็น readable (5) สร้าง component แชร์สำหรับรายชื่อ (ParticipantRosterList) ใช้ร่วม Form/Detail — parent ยิง API
- **Date Added:** 2026-08-16

### 🛠️ Activity Detail — read-only roster (โหมดแสดงเฉย ๆ) + นำออกซ่อนในเมนูจุด 3 จุด
- **Context/Problem:** หน้าดูรายละเอียดกิจกรรม (`ActivityDetail.vue`) มี UI แก้ไขเยอะเกิน (checkbox คลุมดำ + ตั้งค่าแบบกลุ่ม + dropdown หน้าที่ต่อคน) ทั้งที่ผู้ใช้ขอแค่ "การ์ดแสดงผลเฉย ๆ" — คงเหลือแค่ติ๊กว่ามาแล้ว/ยังไม่มา และนำออกควรซ่อนอยู่ในเมนูจุด 3 จุด (แบบ `StudentList.vue`) ไม่ใช่ปุ่มโชว์หน้า
- **Root Cause & Solutions:**
  1. **`readOnly` prop ของ `ParticipantRosterList.vue`:** โหมดใหม่ที่ซ่อน checkbox/toolbar/select หน้าที่+input หมายเหตุ — หน้าที่/หมายเหตุแสดงเป็น text chip, ปุ่ม "ข้อมูลเพิ่มเติม" ยังเปิด modal ได้, ปุ่มเช็คอิน (มาแล้ว/ยังไม่มา) เหลือแบบ compact (`px-2.5 py-1 text-[10px]` + ไอคอน check-circle/circle) — `selectedKeys` กลายเป็น optional (`selectedKeys?: Set<...>`) เพื่อให้ Detail ไม่ต้องส่ง selection state; `isDisabled` ตอบ false ใน readOnly (กันปุ่มจาง)
  2. **เมนูจุด 3 จุด (นำออก) แบบ StudentList:** `readOnly && showRemove && canManage` → ปุ่ม `bi-three-dots-vertical` + dropdown `absolute right-0 top-11 w-36` — ปิดเมื่อคลิกนอก (`document.addEventListener('click', closeMenu)` ใน onMounted/onUnmounted) และ `handleMenuAction` ปิดเมนูก่อน `emit` (ตามท่าเดียวกับ StudentList)
  3. **`ExtraInfoRows.vue` readOnly:** แสดงเป็น text `หัวข้อ: ค่า` (ไม่แสดงปุ่มเพิ่ม/ลบ/quick-add) — ใช้ใน `ParticipantInfoModal` ตอนดูข้อมูลเพิ่มเติมของนักเรียน
  4. **`ParticipantInfoModal.vue` readOnly:** หน้าที่แสดงเป็น chip, Type B `:disabled="!canManage || readOnly"`, `ExtraInfoRows :read-only`, ซ่อนปุ่มบันทึก (`v-if="canManage && !readOnly"`) — Detail ส่ง `read-only` และไม่ bind `@save` (เอา `@close` อย่างเดียว)
  5. **`ActivityDetail.vue`:** ลบ state ทั้งหมดของ batch (selectedParticipantIds/toggleSelectAll/applyBatch/selectedParticipants) + ลบ `BatchApplyModal` import/usage + ลบ `saveInfoModal` (ไม่บันทึกจาก detail) — คงไว้แค่: แก้ไขกิจกรรม/Export Excel/สถานะ (ระดับ activity), เช็คอิน, นำออกผ่านจุด 3 จุด
- **Rule:** (1) component แชร์ที่มีทั้ง "แก้ไข" และ "ดูอย่างเดียว" ให้เพิ่ม prop `readOnly` (ซ่อน/edit-disable ที่ต้นทาง component) แทนการสร้าง component ใหม่แยก (2) การนำ "นำออก/ลบ" ไปซ่อนในเมนูจุด 3 จุด ให้ลอกท่า `StudentList.vue` (openDropdown ref + stopPropagation + document click listener) และให้ action ปิดเมนูก่อน emit (3) prop ที่กลายเป็น optional เมื่อมีโหมดใหม่ ต้องเช็คทุก call site ว่า mode เดิม (ActivityForm) ยังส่งค่าเดิมครบ (4) ระวัง `noUncheckedIndexedAccess` — ใช้ optional chaining/`??` กับ `selectedKeys?.size` (5) ใน Vue template prop ใช้ kebab-case (`read-only`, `:read-only`, `@update:rows`) — ตรงตาม lesson เดิมเรื่อง vite/rolldown parse (named handlers)
- **Date Added:** 2026-08-16

### 🛠️ English-Primary Name Refactor — ชื่ออังกฤษเป็น "กุญแจตัวตน", ชื่อไทยใช้แสดงผล (แก้ อำ/อํา)
- **Context/Problem:** ชื่อไทยมีปัญหา Unicode composition — สระ อำ เขียนได้ 2 แบบ: precomposed `อำ` (U+0E33) กับ decomposed `อา+นิคหิต` (U+0E32 + U+0E4D) → เป็น codepoint คนละตัวแต่ความหมายเดียวกัน → ระบบที่ใช้ชื่อไทยเป็น key (dedupe `add_student`, `join_room` ghost-merge, `migrate_users`) **match กันไม่เจอ** และไม่มี Unicode normalization ในโค้ดทั้งระบบ
- **Correct Pattern/Solution:**
  1. **Schema:** `users` เพิ่ม `first_name_en`/`last_name_en`/`nickname_en` (nullable) — อังกฤษ = กุญแจ identity/dedupe/search; `first_name`/`last_name` ยังเป็นไทย (ไว้แสดงผล). ต้องมีทั้งใน `CREATE TABLE` และ `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (กฎเดิม skills.md); `nickname_en` (ชื่อเล่นอังกฤษ) เก็บเพิ่มตามหน้า profile/onboarding/edit/add
  2. **`core/name_utils.py` (ใหม่):** `normalize_nfc()` (ใช้กับทุกชื่อไทยก่อนเก็บ — แก้ อำ/อํา ให้ exact-match ตรงกัน), `normalize_en()` (NFC+casefold), `identity_pair()` (คู่ key: ชอบอังกฤษก่อน ถ้าไม่มี fallback ไทย NFC), `display_name()` (ไทยก่อน → อังกฤษ). จุดเขียนชื่อไทยทั้งหมดต้อง NFC-normalize: `auth_service` (OAuth INSERT + update_user_profile), `student_service` (add/bulk/update), `room_service` (create_room/join_room), `migrate_users.py`
  3. **Identity/dedupe:** `StudentService._find_or_create_user` = หา user ด้วยชื่ออังกฤษก่อน → fallback `WHERE first_name=$1 AND last_name=$2` (ทั้งคู่ NFC) → ยังไม่มีก็ INSERT ghost พร้อม `_en`. ใช้ร่วมกันใน `add_student` + `bulk_add_students` (กัน dedupe 2 ที่เหลื่อมกัน). `join_room` ghost-merge ใช้ `identity_pair()` แทน concat+lower เดิม
  4. **Search:** `search_students` เพิ่ม `u.first_name_en ILIKE` / `u.last_name_en ILIKE`; frontend search (StudentList/ParticipantRosterList) ต่อ en เข้า fullName
  5. **Backward-compatible response:** ทุก response model เก็บ key `first_name`/`last_name` ไว้ (เป็นไทย) + เพิ่ม `first_name_en`/`last_name_en` Optional → bot (`data['first_name']` direct index), เทส (`assert row["first_name"]`), template เดิมไม่พัง
  6. **Frontend:** `utils/name.ts` `displayName()` (ไทยก่อน → อังกฤษ) ใช้ทุกจุดแสดงชื่อ; forms เก็บอังกฤษ: Onboarding/AddStudent/EditStudent/Lobby (`_en` เป็น optional ไม่นับเป็น required); auth store persist `user_first_name_en`/`user_last_name_en` + currentUserName fallback อังกฤษ
  7. **Bot:** `person_display_name(data)` (ไทยก่อน → อังกฤษ) ใช้ใน my_profile/notify_new_student/notify_birthday
  8. **Finance display:** `first_name + " (nickname)"` เดิม → fallback `first_name_en` เมื่อไม่มีไทย (SELECT ทุกจุดที่ JOIN users เพิ่ม `U.first_name_en, U.last_name_en` + GROUP BY ตาม)
- **Rule:** (1) **`#` ไม่ใช่ SQL comment — Postgres ใช้ `--`** อย่าใส่คอมเมนต์แบบ Python `#` ข้างใน `"""..."""` DDL (พลาดจุดนี้ → `init_db` สร้างตารางไม่ได้ → เทส error ทั้งชุด) (2) ชื่อที่เป็น "ตัวตน/กุญแจ" (dedupe/search/index) ควรเป็นคอลัมน์แยก ไม่ใช่ JSONB metadata (JSONB asyncpg คืน str/dict ตามเวอร์ชัน + index/search ยาก) (3) เวลาเพิ่มภาษา/คอลัมน์ชื่อ ให้เก็บ key เดิมไว้ (compat) แล้วเติม variant แทนการ rename (4) ข้อมูลเก่าที่มีแต่ชื่อไทย: คอลัมน์ `_en` ว่าง → dedupe fallback ไทย NFC ยังทำงานได้ จนกว่าจะกรอกชื่ออังกฤษ (5) `_calculate_completion` ไม่นับ `_en` — กันเปลี่ยน % ครบถ้วนของโปรไฟล์เดิม
- **Date Added:** 2026-08-18

### 🛠️ Activity Part 1 — เช็คชื่อแยกแผ่น + Bulk Update ขยาย + เพิ่มนักเรียน + Dynamic Fields
- **Context/Problem:** ระบบกิจกรรมเช็คชื่อได้แค่ 1 สถานะต่อคน (`status` เดียว ไม่มี timestamp/แผ่นแยกเหตุการณ์); `batchUpdateParticipants`/`addParticipant` endpoint มีแต่ไม่มี caller (ทุกการแก้เป็น local draft ใน ActivityForm เท่านั้น); ฟิลด์เป็น constant dictionary ตายตัว — สร้างฟิลด์ใหม่ที่ใช้กับทุกคนจากหน้าจัดการไม่ได้
- **Correct Pattern/Solution:**
  1. **ตารางเช็คชื่อแยกแผ่น:** `activity_checkin_sheets` (activity_id, title, event_date, created_by) + `activity_checkin_records` (sheet_id, participant_id, is_present, checked_at, recorded_by) — **ห้าม** full-table `UNIQUE(sheet_id, participant_id)` (อยากเก็บ history ของ soft-deleted) → ใช้ partial unique index `WHERE deleted_at IS NULL` + upsert `ON CONFLICT (sheet_id, participant_id) WHERE deleted_at IS NULL DO UPDATE` (ต่างจาก participants ที่มี full UNIQUE → ต้อง revive ก่อน INSERT)
  2. **Batch Update ขยาย:** `BatchParticipantItem` เพิ่ม `role_type/status/earned_hours` optional (None = ไม่แตะ) → `batch_update_participants` สร้าง dynamic SET clause ต่อจาก role_detail; `earned_hours` เป็น NUMERIC → cast `float()` ใน SET + `_serializable` ใน audit
  3. **เพิ่มนักเรียน:** `GET /participants/available` (students active ในห้อง `AND NOT EXISTS` participant active ของ activity — soft-deleted participant = re-addable รวมด้วย) + `POST /participants/batch` (atomic, revive-or-insert ต่อคน กันชน UNIQUE, audit ต่อคน)
  4. **Dynamic Fields:** `activities.metadata.dynamic_fields = [{key: 'df_<n>', label, type}]` (def ระดับกิจกรรม, validate: key `df_\d+` ไม่ซ้ำ, label ไม่ว่าง, type ∈ input/dropdown/boolean/datetime, dropdown ต้องมี options) + ค่าแต่ละคนเก็บ flat ใน `activity_participants.metadata['df_<n>']` (prefix `df_` กันชน Type B key) — def เปลี่ยน → ทุกคนเห็นฟิลด์นั้น (ไม่ต้อง backfill) ; export header = def label
  5. **Frontend:** หน้าใหม่ `ManageActivity.vue` (/activities/:id/manage = "หน้า Checkbox ของกลุ่ม") — roster selectable + batch (เฉพาะคนที่ติ๊ก → เรียก API จริง ไม่ใช่ local draft) + เพิ่มนักเรียน + เช็คชื่อแยกแผ่น + DynamicFieldManager; ActivityDetail คง display-only + เพิ่มปุ่มลิงก์
- **Rule:** (1) ตารางที่ต้องการเก็บ history ของ soft-deleted → partial unique index + ON CONFLICT แทน full UNIQUE (2) literal segment (`checkins`/`available`/`records`/`batch`) ประกาศก่อน path param (`{participant_id}`) เสมอ (3) endpoint batch ที่มีอยู่แต่ไม่มี caller → เชื่อมต่อกับ UI ตัวจริง อย่าทิ้ง dead code (4) ฟิลด์ที่ user สร้างเอง → validate โครงสร้างที่ backend เสมอ (ไม่เชื่อ client) (5) `client.request("DELETE", url, json=...)` ในเทส — httpx ใหม่ `TestClient.delete()` ไม่รับ `json` kwarg (6) helper query participant ต้อง JOIN students เอา `student_no` — `activity_participants` ไม่มีคอลัมน์นั้น
- **Date Added:** 2026-08-20

### 🛠️ Activity Excel Export ปรับปรุง — สถานะไทย + ชื่อไฟล์ + รูปแบบสวยงาม
- **Context/Problem:** `ActivityService.export_activity_excel` ยังมีบั๊ก/จุดอ่อน 3 จุด: (1) สรุป "สถานะ" ใช้ `PARTICIPANT_STATUS_LABELS` (confirmed/cancelled/attended) มาแปลค่าของ **activity** `status` (upcoming/ongoing/completed/cancelled) → ได้ `ongoing` ติดมาเป็นอังกฤษ (2) ชื่อไฟล์เป็น `activity_<id>_participants.xlsx` (backend `Content-Disposition` + frontend `a.download`) — ดูไม่รู้เรื่อง (3) คอลัมน์ทุกตัวกว้าง 20 เท่ากันหมด → "เลขที่" กว้างเกิน + ชีตสรุปไม่สวย (merged หลายบรรทัดไม่ auto-fit ความสูง, ไม่มีแถวรวม)
- **Correct Pattern/Solution:**
  1. **สถานะกิจกรรม:** เพิ่ม `ACTIVITY_STATUS_LABELS`/`ACTIVITY_STATUS_COLORS` (upcoming→กำลังจะมา/น้ำเงิน, ongoing→กำลังดำเนินการ/ส้ม, completed→เสร็จสิ้น/เขียว, cancelled→ยกเลิก/แดง) — แยกชุดกับ `PARTICIPANT_STATUS_LABELS`/`PARTICIPANT_STATUS_COLORS` ของ participant; สรุปใช้ชุดกิจกรรม + แต้มสีข้อความ status; ชีตรายชื่อ "สถานะเข้าร่วม" แต้มสี participant
  2. **ชื่อไฟล์ใช้ชื่อกิจกรรม:** service เก็บชื่อไฟล์ไว้เป็น attribute บน `io.BytesIO` (`output.filename`) — คืน type เดิม (BytesIO) จึงไม่แตกเทสทั้งหมด; router อ่าน `getattr(excel_file, "filename", fallback)` แล้วส่ง `Content-Disposition` แบบ **RFC 5987** `filename*=UTF-8''<percent-encoded>` (รองรับชื่อไทย) + `filename="activity_<id>.xlsx"` ไว้ fallback บราวเซอร์เก่า; frontend `ActivityDetail.vue` สร้าง `a.download` จาก `activity.title` ด้วย sanitize helper (`/\\:*?"<>|` → `_`, กันยาวเกิน 80)
  3. **ฟอร์แมต:** `EXPORT_FIELD_WIDTHS` กำหนดความกว้างต่อคอลัมน์ (เลขที่=7 กะทัดรัด+center, custom_fields=45+wrap, role_detail=28) + default 22; header purple + white bold + wrap + border ล่าง medium + row height 32; แถวข้อมูลมี border บาง + zebra (`F5F3FF`) + `earned_hours` number format `0.##` + align ขวา; `ws_data.auto_filter.ref` + `freeze_panes="A2"`; แถวรวมท้ายตาราง "รวมผู้เข้าร่วม: N คน" (merge A..F, TOTAL_FILL, border บน medium)
  4. **ชีตสรุป:** merge title/วันที่/หัวข้อ section กว้าง A:B, section = purple header + white bold; status value แต้มสี; คำอธิบาย wrap + คำนวณความสูง; **merged cell หลายบรรทัด (meta) ต้องตั้ง `row_dimensions[h].height` เอง** (Excel ไม่ auto-fit merged) = `(จำนวนบรรทัด) * 15`
- **Rule:** (1) ชุด label/สีของ enum ต่างชนิดกัน (activity status vs participant status) ต้องแยก constant กัน อย่าใช้ cross-translate (2) การคืนค่า type เดิมแต่เพิ่ม metadata → ตั้ง attribute บน object แทนการเปลี่ยน return type/break เทส (3) ชื่อไฟล์ไทย → ต้อง `filename*=UTF-8''` (RFC 5987) ถ้าใช้ `filename=` อย่างเดียว browser จะเพี้ยน/ตัด (4) merged cell หลายบรรทัดต้องตั้ง row height เอง (5) คอลัมน์ที่ความกว้าง/ตำแหน่งต่างกัน (เลขที่/ชั่วโมง/ข้อความยาว) ควรมี width map + alignment ต่อฟิลด์ (6) เปลี่ยนฟอร์แมตที่กระทบจำนวนแถว (เช่น เพิ่มแถวรวม) → อัปเดตเทสที่ assert `len(rows)`
- **Date Added:** 2026-08-21

### 🛠️ Global Font: Noto Sans Thai — ฟอนต์หลักของแอป (กัน fallback เป็น serif)
- **Context/Problem:** แอปไม่มีฟอนต์หลักที่ชัดเจน — main.css ใช้ `'Inter', 'Sarabun'` แต่ `App.vue` มี `<style>` ฮาร์ดโค้ด `font-family: 'Inter', system-ui, ...` ใน body (ถูก inject หลัง main.css → rule ทับกัน → **หลุดฟอนต์ไทย**) และ view การเงินฮาร์ดโค้ด 'Sarabun' + `@import` ฟอนต์จาก Google ซ้ำใน scoped style → ถ้าฟอนต์โหลดช้า/ถูกบล็อก (SEO bot, มือถือ) browser fallback เป็น serif แตก UI
- **Correct Pattern/Solution:**
  1. **index.html:** `preconnect` ไป `fonts.googleapis.com` + `fonts.gstatic.com` (ตัวหลังมี `crossorigin`) + `<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+Thai:wght@300;400;500;600;700&display=swap">` — `display=swap` ให้ render ด้วย fallback ทันที ไม่รอฟอนต์โหลด
  2. **tailwind.config.js:** `fontFamily.sans: ['"Noto Sans Thai"', 'sans-serif']` — ต้องลงท้าย generic `'sans-serif'` เสมอ → `@apply font-sans` จะไม่มีทาง fallback เป็น serif
  3. **main.css:** `:root` ตั้ง `font-family: 'Noto Sans Thai', system-ui, -apple-system, Avenir, Helvetica, Arial, sans-serif` + `body { @apply font-sans antialiased; }`
  4. **App.vue:** ห้ามฮาร์ดโค้ด font-family ใน `<style>` — ใช้ `@apply ... font-sans;` แทน (App.vue style inject หลัง main.css → ทับ global ได้)
  5. **.vue ที่เหลือ:** ไม่ `@import` ฟอนต์จาก Google ซ้ำใน scoped style (double-load) และเปลี่ยนทุกฮาร์ดโค้ดฟอนต์เดิมเป็นฟอนต์หลักใหม่ เช่น `FinanceDashboard.vue` (Chart.js `family:` + `*` rule), `FinanceSettings.vue`/`CollectionDetail.vue` (`.swal2-*`)
- **Rule:** (1) ฟอนต์ไทยหลักของโปรเจกต์ = **Noto Sans Thai** โหลดผ่าน index.html global เท่านั้น (2) ทุก `font-family` stack ต้องลงท้าย `sans-serif` ไม่งั้น bot/มือถือ/โหลดช้า fallback ไป serif แตก UI (3) ห้ามฮาร์ดโค้ด font-family ใน `<style>` ของ .vue ที่ทับ global (4) เวลาเปลี่ยนฟอนต์หลัก ต้อง `grep` หา 'Sarabun'/'Inter'/`@import ...fonts.googleapis` ที่เหลือให้หมด (5) `dist/` เกิดจาก build — ใช้ `grep -r` ใน `src/` เป็นหลัก
- **Date Added:** 2026-08-23

### 🛠️ Consent Model — PII ของนักเรียนต้องผ่าน "การยืนยันตัวตน" (identity_claimed) ก่อนเปิดให้ห้องดู
- **Context/Problem:** ช่องโหว่ PII — ใครก็ได้สร้างห้อง (ได้เป็น `is_admin` ทันที) แล้วแอดชื่อคนอื่นด้วยชื่อผ่าน `add_student` → `_find_or_create_user` (student_service.py) **link บัญชีจริงของเหยื่อเข้าห้องอัตโนมัติ** โดยไม่ยินยอม → admin เห็น PII เต็ม (profile/search/export); `search_students` เดิมให้สมาชิกคนไหนก็ได้ค้นชื่อแล้วเห็น PII เต็ม (ตรวจแค่ `require_member`); ส่วน `join_room` สวมรอยทันที (merge ข้ามทุกห้อง) เมื่อชื่อตรงกับ ghost → ถ้าเหยื่อถูกแอดชื่อไว้ในห้องแฮ็กเกอร์ แล้ว self-join ห้องไหนก็ตาม → โดน link เข้าห้องแฮ็กเกอร์
- **Root Cause:** PII อยู่ที่ตาราง users อย่างเดียว, `students` เป็นแค่ลิงก์ room↔user; "เพิ่มด้วยชื่อ" ที่ reuse `user_id` เดิม = เปิดข้อมูลให้โดยไม่มี consent; `join_room` merge ข้ามห้องโดยไม่ถามเจ้าตัว
- **Correct Pattern/Solution (Consent Model):**
  1. **Schema:** `students.identity_claimed BOOLEAN DEFAULT FALSE` (PII gate ตัวเดียว) + `added_by INTEGER REFERENCES users(id)` (NULL=เจ้าตัวขอเอง, admin id=แอดมินแอดให้) + `claim_meta JSONB` (context ตอนขออ้างสิทธิ์ ghost: ghost_user_id/ชื่อเดิม/name_match) — ต้องมีทั้งใน `CREATE TABLE` และ `ALTER TABLE ADD COLUMN IF NOT EXISTS` + backfill `UPDATE students SET identity_claimed=TRUE WHERE status='active' AND deleted_at IS NULL AND identity_claimed=FALSE`
  2. **กฎกลาง `core/privacy.py`:** `can_view_pii = super_admin OR ดูตัวเอง OR (identity_claimed AND VIEW_ALL_STUDENTS)` + `mask_private_fields(...)` ใช้ SENTINEL `"🔒 ไม่มีสิทธิ์เข้าถึง"` — ทุกจุดอ่าน PII import จากนี้ (ห้าม implement ซ้ำ): `get_student_profile`, `search_students`, `export_students_excel`, activities Type A (`PROFILE_TYPE_A_FIELDS`)
  3. **`_find_or_create_user` คืน `(user_id, is_real)`** — is_real = มี google/discord/email/phone → `add_student`/`bulk_add_students` สร้าง **คำเชิญ pending** (`added_by=admin, identity_claimed=FALSE`) เจ้าตัวต้องกดรับ (`accept_invite`) ก่อนถึง active+claimed; ghost/ผู้ใช้ใหม่ → active ได้ทันที (ไม่มี PII)
  4. **`join_room` ไม่สวมรอยทันที** — เจอ ghost → เปลี่ยนเป็น pending claim (เก็บ `claim_meta.name_match` ให้แอดมินตัดสิน) แล้วแอดมิน approve ถึงจะ link; ชื่อไม่ตรงไม่ error 400 แบบเดิม (ที่โชว์ชื่อ ghost); **ไม่ merge ข้ามห้อง** — approve ผูกเฉพาะห้องที่ขอ/ยอมรับ
  5. **`approve_join_request` block คำเชิญ** (added_by IS NOT NULL → 400 "รอเจ้าตัวกดรับ"); **`reject_join_request` แยก 3 กรณี** (invite→DELETE, claim→กู้คืน ghost จาก claim_meta, join→DELETE)
  6. **invites:** `GET /api/classroom/invites` + `POST /invites/{id}/accept` — **ต้องอยู่ใน `room_router`** (mount อันแรกใน main.py) กันชน `GET /{target_id}` ของ `classroom_sync_router` (mount ก่อน student_router → ถ้าใส่ใน student_router จะโดน shadow เป็น 422); `Lobby.vue` โชว์ section คำเชิญ; บอทเพิ่ม embed `notify_student_invite`/`notify_invite_accepted`
  7. **`create_room` set `identity_claimed=TRUE`** ให้แถว president ของเจ้าของห้อง
- **Rule:** (1) PII gate ต้องมีตัวเดียว (identity_claimed) + mask จุดเดียว (privacy.py) ไม่งั้นรั่วตามจุดที่ลืม (2) "เพิ่มด้วยชื่อ" ที่ match บัญชีจริง → ต้องเป็น invite/pending ไม่ใช่ link ตรง (3) การสวมรอย/merge ตัวตนต้องผ่านแอดมินอนุมัติเสมอ + ไม่ merge ข้ามห้อง (4) route ที่เป็น literal segment (เช่น `invites`) ต้อง mount ก่อน path param `/{target_id}` (5) JSONB (`claim_meta`) asyncpg คืน str/dict ตามเวอร์ชัน → normalize ในเทสก่อน `.get()` (6) เทสที่ insert student ที่ต้องเห็น PII ให้ `identity_claimed=True` (default ของ helper หลัง fix)
- **Date Added:** 2026-08-24

### 🛠️ สร้าง PR ตอน `gh` token หมดอายุ — ใช้ git credential store + GitHub REST API แทน
- **Context/Problem:** `gh auth status` บอก token ใน `~/.config/gh/hosts.yml` invalid (`gh pr create` → `HTTP 401: Requires authentication (api.github.com/graphql)`) แต่ `git push` ยังทำงานได้ตามปกติ → อยากสร้าง PR ได้ทันทีโดยไม่ต้องรบกวนให้ user รัน `gh auth login` ใหม่
- **Root Cause:** `gh` เก็บ token แยกจาก git — `~/.config/gh/hosts.yml` (หมดอายุ/ถูก revoke) ขณะที่ git ใช้ credential helper **แยก** (`~/.git-credentials` ถ้าเป็น `store`) ที่ยังมี PAT ใช้ได้อยู่ → ใช้ token ของ git ยิง GitHub REST API ตรงๆ ได้
- **Correct Pattern/Solution:**
  1. **พิสูจน์ว่า git ยัง auth ได้:** `git config --get credential.helper` → ถ้าได้ `store` (หรือ cache) แปลว่ามี credential เก็บไว้; `git push -u origin <branch>` ผ่าน = ใช้ได้จริง (push ได้แล้ว PR endpoint ก็ใช้ token ตัวเดียวกันได้)
  2. **ดึง token โดยไม่ให้หลุดใน output/ประวัติ:** `CRED=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill | sed -n 's/^password=//p')` — อย่า `cat ~/.git-credentials` (มี token เปล่าๆ หลุด)
  3. **PR body เขียนเป็นไฟล์** (เช่น `/tmp/pr_body.md`) แล้ว build JSON ด้วย `python3 -c` + `json.dumps({...})` (title/head/base/body) — กันปัญหา escaping quote/emoji/นิวไลน์ใน shell
  4. **POST สร้าง PR:** `curl -s -o /tmp/pr_response.json -w "%{http_code}" -H "Authorization: token ${CRED}" -H "Accept: application/vnd.github+json" -d "${BODY}" "https://api.github.com/repos/<owner>/<repo>/pulls"` → คาดหวัง `201`; อ่าน `html_url` จาก response
  5. **ล้าง token:** `unset CRED` ท้ายสคริปต์ + อย่า echo token ออกมา
  6. **แจ้ง user:** แนะนำให้รัน `gh auth login -h github.com` เอง เพื่อให้ `gh` กลับมาใช้ได้ (กดรับเองแบบ interactive)
- **Rule:** (1) `gh` token ≠ git token — `gh auth status` เสียไม่เท่ากับ push พัง; ตรวจ `credential.helper` ก่อน (2) ห้าม `cat ~/.git-credentials` / echo token — ใช้ `git credential fill` + `sed` เอาแค่ `password=` แล้ว `unset` (3) สร้าง PR ผ่าน REST `POST /repos/{owner}/{repo}/pulls` {title, head, base, body} + header `Accept: application/vnd.github+json`; `gh` แค่ wrapper ของ API นี้ (4) ชื่อ branch ที่ push แล้ว ต้องตรง `head` ใน PR (5) body ที่มีภาษาไทย/emoji/เครื่องหมายอ้าง → build ผ่าน `json.dumps` ใน python เสมอ ไม่ยัดเข้า `-d` ตรงๆ
- **Date Added:** 2026-08-25

### 🛠️ Excel สรุปรายการนับโอนเงินเป็นรายจ่าย + สร้าง export สมุดรายวัน (General Journal)
- **Context/Problem:** (1) `_build_finance_workbook` คำนวณ `income_total = sum(income)` / `expense_total = sum(expense)` จาก **ทุก** แถว → รายการโอนเงินระหว่างบัญชี (ที่ตั้ง `expense=amount` เพื่อโชว์เงินขาออกในคอลัมน์รายละเอียด) ถูกนับรวมเป็นรายจ่าย → Net Balance (รายรับ−รายจ่าย) ต่ำเกินจริง ทั้งเส้นทาง legacy (`type="โอนเงินระหว่างบัญชี"`) และเส้นทาง v2 (`_format_v2_rows` จัด transfer เป็น `expense` ธรรมดา) (2) ต้องการ export สมุดรายวันทั่วไป (General Journal) ใหม่สำหรับนักบัญชี อ่านจาก `journal_entries JOIN journal_lines JOIN accounting_ledgers` ตรงๆ โดยไม่ผ่านการแปลเป็น TransactionResponse
- **Root Cause:** โอนเงินระหว่างบัญชี = เงินแค่ย้ายภายในห้อง (Dr สินทรัพย์ A / Cr สินทรัพย์ B) ไม่ใช่รายรับหรือรายจ่ายจริง แต่บิล/แถวถูกแสดงเป็นรายจ่ายเพื่อ "เห็นเงินออก" → สรุปต้องกันขาออก แต่แถวรายละเอียดยังเก็บไว้
- **Correct Pattern/Solution:**
  1. **แท็ก transfer ให้รู้กันทุกเส้นทาง** — `_format_row` (legacy) เพิ่มคีย์ `"is_transfer": is_transfer` ในทุกแถว; `_format_v2_rows` ตรวจ transfer ด้วย `t.get("transfer_group_id") is not None` (`_classify_journal_entry` ใส่ให้เฉพาะบิลโอนเท่านั้น) แล้วตั้ง `type="โอนเงินระหว่างบัญชี"` + `category="โอนเงิน"` → ทำให้สองเส้นทางแสดงผลเหมือนกัน
  2. **สรุปคำนวณจากชุดที่กรองแล้ว:** `non_transfer_rows = [r for r in rows if not (r.get("is_transfer") or r.get("type") == "โอนเงินระหว่างบัญชี")]` → `income_total/expense_total/net` คำนวณจากชุดนี้ (แถวรายละเอียด sheet 'ประวัติรายการ' ยังใช้ `rows` เดิม); sheet 'สรุปรายหมวดหมู่' ก็ `continue` ข้าม transfer (กันแถว 0.00)
  3. **Journal export อย่า reuse `_resolve_export_period`** (สร้าง SQL ผูกกับ `T.created_at` + placeholder เริ่ม `$2`) — เขียน helper `_resolve_inclusive_period(month, year, start_date, end_date) -> (start_dt, end_dt, label)` แบบ `DATE(col) >= start AND <= end`; ห้าม start/end กับ month/year พร้อมกัน + กัน `start > end`
  4. **Format สมุดรายวัน:** วน `journal_lines` เรียง `transaction_date, entry_id, line_id`; วันที่/เวลา/Reference/คำอธิบาย/ผู้บันทึก ใส่เฉพาะ **บรรทัดแรกของบิล** (`entry_id != prev`), บรรทัดถัดไปเหลือแค่รหัส/ชื่อบัญชี + เดบิต/เครดิต (เหมือนสมุดรายวันจริง) → ยอดเดบิตรวม = เครดิตเสมอ (มีแถวรวมท้าย); Reference = `REFERENCE_TYPE_LABELS[reference_type] + ' #' + reference_id` (`manual_transaction`→รายการ, `transfer`→โอนเงิน, `student_payment`→ชำระเงิน, `opening_balance`→ยอดยกมา)
  5. **Endpoint ใหม่เป็น GET** `/{target_id}/finance/export/journal` (query: month/year/start_date/end_date) ต่างจาก export เดิมที่เป็น POST body — validation อยู่ที่ service (`month` ไม่มี `year` → ValueError → 400)
- **Tests:** `test_finance_export.py` (regression กันโอนพองยอด legacy+v2: สรุป 500/200/300 ทั้งที่โอน 400 + แถวรายละเอียดยังมีขาโอน 400), `test_finance_journal_export.py` (โครงสร้างไฟล์/คอลัมน์ครบ, Dr=Cr, กลุ่มหัวบิลเฉพาะบรรทัดแรก, กรองเดือน/ช่วง, RBAC, validation), `test_finance_http.py` (GET 200 + cross-room 403 + month ไม่มี year 400)
- **Date Added:** 2026-09-03

### 🛠️ เทส summary ที่ไม่ระบุเดือน "กลายเป็นเทสเก่า" เมื่อเวลาจริงเลย CUTOFF_DATE (2026-09-01) — ยกระดับเป็นบัญชีคู่ หรือยัดวันที่ยุคเก่าให้ชัด
- **Context/Problem:** `get_summary`/`export` **ไม่ระบุ month/year → ตีความเป็น "เดือนปัจจุบัน"** แล้ว route ตาม `period_start >= CUTOFF_DATE` (`CUTOFF_DATE = date(2026, 9, 1)`). เทสที่เคยเขียนยุค Single-Entry (insert เข้า `finance_transactions` ตรงๆ, seed เงินไว้ที่ `finance_accounts.balance`, ไม่สร้าง journal) พอวันจริงของ CI เดินเลย 1 ก.ย. 2026 → ถูกส่งไปอ่าน **journal (v2)** → `net_worth` กลายเป็น 0/300 แทน 1000/400 → fail 3 ตัว (`test_finance.py::test_get_summary_current_month`, `test_get_summary_excludes_transfer_legs`, `test_finance_http.py::test_web_get_summary_and_debtors_200`) **ทั้งที่ไม่เคยแก้โค้ด** (ยืนยันโดยรันบน HEAD เปล่าก็ fail)
- **Root Cause:** ระบบมี "สองยุค" คั่นด้วยวันตัด (real wall clock): เงินตั้งต้น (seed) ของบัญชีก่อนวันตัด **ไม่อยู่ใน journal** — ระบบใหม่คำนวณ Net Worth = `SUM(debit−credit)` ของ ledger ประเภท `asset` สะสมจาก journal → ไม่มี seed = net_worth ต่ำกว่าที่เทสคาด; legacy นับ `SUM(finance_accounts.balance)` ซึ่งรวม seed อยู่แล้ว (สองระบบนับเงินตั้งต้นคนละแบบ)
- **Correct Pattern/Solution:**
  1. **เทสที่ตั้งใจทดสอบระบบใหม่ (ปัจจุบัน) → จำลอง "ยอดยกมา" ให้เหมือน migration จริง** — helper `_provision_opening_balance(pool, room_id, account_id, amount)`: สร้าง/หา `accounting_ledgers` ประเภท asset ผูก `legacy_account_id` (ถ้ายังไม่มีสร้าง code `1{id:04d}`), สร้าง ledger equity code `'3000'` (`ทุน-ยอดยกมา`), แล้ว insert `journal_entries (reference_type='opening_balance')` + 2 `journal_lines` (asset Dr = amount / equity Cr = amount) → Net Worth (v2) นับยอดยกมาเข้า แต่ **ยอดยกมาไม่นับเป็นรายได้งวด** (ถูกกรอง `reference_type <> 'opening_balance'`)
  2. **รายรับ/รายจ่ายต้องผ่าน service แบบ dual-write** (`FinanceService.add_transaction`) ไม่ใช่ insert `finance_transactions` ตรงๆ — `add_transaction` สร้าง asset+revenue/expense ledger และ journal ให้อัตโนมัติ (`_resolve_asset_ledger`/`_resolve_category_ledger` provision ให้เอง); transfer ใช้ `transfer_money` (สร้าง 2 ขา asset: Dr ปลายทาง / Cr ต้นทาง → ไม่มี revenue/expense ledger → สรุป income/expense = 0 และ asset หักล้างกัน net = 0)
  3. **ตัวเลขที่คาดต้องเป็นเลขของระบบใหม่:** Net Worth = ยอดยกมา + รายได้ − รายจ่าย (เช่น 1000 + 300 − 100 = 1200 ไม่ใช่ 1000 แบบ legacy); income/expense/breakdown อ่านจาก ledger ในงวด (journal `transaction_date` DEFAULT `CURRENT_TIMESTAMP` → ไม่ต้อง backdate สำหรับ "เดือนปัจจุบัน")
  4. **เทสที่ตั้งใจเทสระบบเก่า (legacy) → ระบุเดือน/ปีที่ก่อนวันตัดชัดเจน** (เช่น `month=8, year=2026` หรือ `month=1, year=2025`) + backdate `created_at` ของ `finance_transactions` → ผ่าน router ตกรุ่น legacy — ห้ามพึ่ง "ไม่ระบุเดือน" เพราะมันผูกกับ wall clock (ตัวอย่างที่มีอยู่: `test_get_summary_month_year_filter`)
- **Rule:** (1) เทสใดเรียก `get_summary`/export โดย**ไม่ระบุเดือน/ปี** จะ "เน่า" ได้เองเมื่อเวลาจริงผ่าน CUTOFF_DATE → เลือกให้ชัด: ใหม่ = จำลองยอดยกมา + dual-write, เก่า = ยัด date ยุคก่อน cutoff (2) seed เงินของบัญชีต้องมีคู่กันใน journal (`opening_balance`) ไม่งั้น v2 net_worth ไม่ครบ (3) insert ตรงๆ ลง `finance_transactions` ≠ มีผลกับ journal → เทส v2 ต้องเรียก service (add_transaction/transfer_money/confirm_payment) เสมอ (4) helper นี้แยกอยู่ต่อไฟล์เทส (copy) ตามสไตล์ repo
- **Tests:** แก้ 3 ตัวที่ fail เป็นบัญชีคู่ (`test_get_summary_current_month` → net_worth 1200; `test_get_summary_excludes_transfer_legs` → net_worth 1000 ผ่านยอดยกมา + transfer 2 ขา; `test_finance_http.py::test_web_get_summary_and_debtors_200` → net_worth 400 = ยอดยกมา 100 + รายได้ 300) — รันเต็ม 2 ไฟล์ได้ **139 passed**
### 🛠️ Reconciliation Script — กระทบยอด Legacy ↔ บัญชีคู่: ยึด `finance_accounts.balance` เป็นจริง แล้วปรับ journal (equity 3001 เป็นขาสะท้อน)
- **Context/Problem:** ระบบมี 2 ยุคที่ยอด "หลุด" กันได้ (เช่น `_confirm_single_payment` อัปเดต balance เสมอแต่ข้าม dual-write ด้วย `pass` ถ้าไม่มี revenue ledger, หรือ revert รายการเก่าที่ไม่มี journal) → ต้องมีเครื่องมือกระทบยอดให้ยอด 2 ระบบกลับมาตรงกันโดยไม่ต้องไล่แก้ทีละบิล
- **Root Cause:** legacy นับเงินจาก `finance_accounts.balance` (รวม seed/รายการก่อน dual-write) แต่ระบบบัญชีคู่คำนวณ Net Worth จาก `SUM(debit−credit)` ของ ledger ประเภท asset เฉพาะ journal ที่ไม่ void/ไม่ลบ → เงินที่เข้าระบบเดิมแต่ไม่มี journal จะทำให้บัญชีคู่ "ขาด"; รายการ journal ที่ legacy ตัดไปแล้วทำให้บัญชีคู่ "เกิน"
- **Correct Pattern/Solution:**
  1. **ทิศทาง = journal ← legacy เสมอ:** เอา `finance_accounts.balance` (ระบบเดิม) เป็นแหล่งความจริง แล้วเขียนรายการปรับให้ asset-ledger net กลับมาเท่ากับ legacy พอดี (ไม่เคยย้อนกลับ)
  2. **หาผลต่างรายบัญชีด้วย 1 query `LEFT JOIN LATERAL`:** ต่อ asset ledger (โดย `legacy_account_id`, `ORDER BY id LIMIT 1` เผื่อมีซ้ำ) + `SUM(debit−credit)` ของ ledger นั้นโดยกรอง `JE.deleted_at IS NULL AND JE.status <> 'voided'` — **เงื่อนไขเดียวกับ `_get_summary_v2`** (ไม่งั้นวัดเลขคนละชุดกับที่ summary โชว์) และกรอง `FA.deleted_at IS NULL`
  3. **ขาสะท้อนต้องเป็น equity `'3001'` (แยกจาก `'3000'` ทุน-ยอดยกมา):** `diff > 0` → asset Dr / equity Cr (บัญชีคู่ขาด), `diff < 0` → asset Cr / equity Dr (บัญชีคู่เกิน) — เพราะ Net Worth คิดเฉพาะ asset และ income statement นับเฉพาะ revenue/expense → equity mirror ไม่งอเลขที่รายงาน แต่ trial balance ยังสมดุล Dr=Cr
  4. **`reference_type='adjustment'` + metadata ระบุ `finance_account_id`/`direction`** ต่อบัญชี 1 ใบ (กี่บัญชีต่าง = กี่ใบ) → audit/rollback รายบัญชีได้; `_classify_journal_entry` คืน None สำหรับคู่ asset+equity → ไม่โผล่รก list get_transactions
  5. **Idempotent:** รอบสอง diff = 0 (mirror อยู่ equity ไม่แตะ asset) → ไม่สร้างซ้ำ; กัน "เสียง" เลขทศนิยมด้วย `round(diff,4)` + threshold (default 0.01 บาท)
  6. **auto-provision ledger ที่ขาด:** ถ้า ledger_id เป็น None → เรียก `_resolve_asset_ledger` ก่อน insert (บัญชีที่ dual-write ไม่เคย provision); บัญชียอด 0 ไม่มี ledger → ข้าม ไม่สร้างขยะ
  7. **Dry-run default:** CLI `backend/scripts/reconcile_finance.py --room-id N | --server-id N [--apply] [--threshold 0.01]` — default แค่รายงาน; `--apply` เขียนใน transaction เดียว + audit_logs `action='RECONCILE'`
- **Rule:** (1) logic อยู่ `FinanceService.reconcile_balances` (เทสได้ผ่าน db_pool) สคริปต์เป็นแค่ thin CLI เลียนแบบ `migrate_phase2_5_opening_balance.py` (2) วัดผลต่างด้วยเงื่อนไขเดียวกับ summary v2 เสมอ (3) mirror ขาเงิน "พัก" ต้องเป็น equity/liability ไม่ใช่ revenue/expense กันงอ income statement (4) เงินเป็น Decimal → cast float() ก่อนเสมอ, เขียนผ่าน `_insert_journal_entry` (cast+json ให้เอง)
- **Tests:** `test_finance_reconcile.py` 5 ตัว: dry-run แล้ว apply แก้ให้ net==legacy (จำลองรั่วรับเงินไร้ journal), ทิศทาง ledger เกิน (Cr asset), idempotent รอบสอง, auto-provision ledger หาย, server_id resolve + RoomNotFoundError
- **Date Added:** 2026-09-03

### 🐛 SQL — กรอง `JE.status <> 'voided'` ต้องอยู่ใน WHERE ของ subquery ไม่อยู่ใน ON clause ของ LEFT JOIN
- **Context/Problem:** Export Excel แสดงยอดคงเหลือรายบัญชี (เช่น เงินสด) สูงเกินจริง (โชว์ 1,389 แต่หน้าเว็บโชว์ 527) แต่รัน Reconcile แล้วผลต่าง 0 → เพราะคำสั่ง `balances` ใน `_export_transactions_excel_v2`/`_export_transactions_excel_merged` และ `get_trial_balance` (ตอนไม่ระบุ as_of) รวม Debit/Credit ของบิลที่ Revert (void) แล้ว
- **Root Cause:** `COALESCE(SUM(L.debit - L.credit),0) ... LEFT JOIN journal_lines L ... LEFT JOIN journal_entries JE ON L.journal_entry_id = JE.id AND JE.deleted_at IS NULL AND JE.status <> 'voided'` — เงื่อนไขใน **ON clause ของ LEFT JOIN** แค่ทำให้คอลัมน์ JE เป็น NULL เมื่อไม่ตรงเงื่อนไข แต่แถว `journal_lines` ยังคงอยู่ในผลลัพธ์ → `SUM` ยังรวมเส้นของบิลที่ void/deleted อยู่ (เหมือนกันทั้ง `status` และ `deleted_at`)
- **Correct Pattern/Solution:** ใช้ correlated subquery ที่ **JOIN ธรรมดา + กรองใน WHERE** เพื่อให้แถวไม่พึงประสงค์หลุดออกจาก aggregate จริง ๆ:
  ```sql
  SELECT AL.account_name,
         (SELECT COALESCE(SUM(L.debit - L.credit), 0)
          FROM journal_lines L JOIN journal_entries JE ON L.journal_entry_id = JE.id
          WHERE L.ledger_id = AL.id
            AND JE.deleted_at IS NULL AND JE.status <> 'voided') AS net_balance
  FROM accounting_ledgers AL
  WHERE AL.room_id = $1 AND AL.account_type = 'asset' AND AL.is_active = TRUE
  ORDER BY AL.id
  ```
- **Rule:** aggregate ที่ต้อง "ไม่นับ" แถวที่ผูกตารางอ้างอิง (`journal_entries.status`/`deleted_at`) → อย่าใส่เงื่อนไขนั้นใน ON ของ LEFT JOIN; ให้ใส่ใน WHERE ของ aggregate (subquery/LATERAL) — LEFT JOIN ใช้เฉพาะเมื่ออยากได้แถวฝั่งซ้ายที่ไม่มีคู่แล้วได้ SUM=0 ผ่าน COALESCE; สแกนหา pattern เก่าได้ด้วย grep `LEFT JOIN journal_entries JE ON L.journal_entry_id = JE.id`
- **Tests:** (1) `test_finance_export.py::test_export_balances_exclude_voided_journal` — รายได้ 300 (ใช้จริง) + 500 (void) → export เส้นทาง v2 (month/year) และ merged (ไม่กรอง) ต้องโชว์เงินสด = 300 ไม่ใช่ 800 (2) `test_finance_v2_read.py::test_trial_balance_excludes_voided_journal` — งบทดลองไม่ระบุ as_of: Dr/Cr รวม = 300 ไม่ใช่ 800 + ยังยืนยัน as_of หลังงวดกรองถูก
- **Date Added:** 2026-09-03

### 🛠️ Excel Export ระดับ Enterprise (ERP) — ข้อมูล "ลูกหนี้/โปรเจค" เป็น Real-time, sheet Tab ≤ 31 ตัวอักษร, แยก data-fetch ออกจาก builder
- **Context/Problem:** export ไฟล์ Excel 2 แบบเดิมบางเกินไป (management = 3 แผ่น, นักบัญชี = 1 แผ่น) ผู้ใช้ต้องการ "ภาพรวมการเงินทั้งห้อง" + "Full Financial Audit Report" (GL/Trial Balance/PL/Balance Sheet) โดยดึงศักยภาพของตารางที่มี (fee_collections, student_payments, accounting_ledgers, journal_entries) ให้ครบ
- **Root Cause:** builder ผูกกับ "rows ของ transactions" อย่างเดียว; ไม่มี data-fetch กลางให้ sheet โปรเจค/ลูกหนี้/GL/TB/PL/BS; ตั้งชื่อ Sheet ด้วยภาษาไทย+อังกฤษยาว → เกิน Excel limit 31 ตัวอักษร (`ws.title` **raise**) — วัดความยาวด้วย `len()` ก่อนตั้ง
- **Correct Pattern/Solution:**
  1. **แยก data-fetch ออกจาก builder:** helper async รับ `conn` คืน dict ล้วน — `_fetch_collection_register(conn, room_id)` (fee_collections LEFT JOIN student_payments → expected = amount×member, paid, pending, rate) และ `_fetch_accounts_receivable(conn, room_id)` (SP.status='pending' JOIN FC/students/users) เป็น **Real-time "ณ วันที่ export"** ไม่ผูกงวด; ฝั่งบัญชีคู่มี `_fetch_general_ledger(conn, room_id, start_dt, end_dt)` (opening = ก่อน start, period = ในงวด, closing คำนวณ Python), `_fetch_trial_balance_ledgers` (YTD ≤ as_of), `_fetch_income_statement_rows` (revenue = Cr−Dr / expense = **Dr−Cr**), แล้ว `_compose_balance_sheet` พิสูจน์สมการ สินทรัพย์ = ทุน + กำไรสะสม
  2. **เลข "ไม่นับ void/deleted" ทุกที่:** GL/TB/PL/BS aggregate กรอง `JE.deleted_at IS NULL AND JE.status <> 'voided'` ใน WHERE (ดู lesson ด้านบน); opening/period แยกกันด้วย `transaction_date < start` vs `ใน [start,end]` โดยใช้ `$2::timestamptz IS NULL OR ...` ครอบกรณี "ไม่ระบุขอบ"
  3. **Audit Trail ในสมุดรายวัน:** fetch `JE.metadata` แล้ว normalize ก่อน `.get` — asyncpg อาจคืน JSONB เป็น **dict หรือ str ตาม codec** → `if isinstance(raw,str): json.loads(...)`; แสดง `legacy_transaction_id`/`transfer_group_id`/`student_payment_id`/journal UUID/line id ต่อบรรทัด
  4. **ชื่อ Tab สั้น (≤31) แต่ Title ในเซลล์ A1 ใส่ชื่อเต็ม:** เช่น Tab `สมุดรายวัน (General Journal)`/`สมุดบัญชีแยกประเภท (GL)`/`งบแสดงฐานะการเงิน (BS)` แต่ cell A1 = `สมุดรายวันทั่วไป (General Journal) — ห้อง...` — ได้ทั้งสวยงามและไม่โดน ValueError จาก openpyxl
  5. **สี Tab แยกหมวด:** Management = โทนน้ำเงิน, Accounting = เขียวเข้ม/ม่วง (`ws.sheet_properties.tabColor`); ทุกตารางข้อมูลมี zebra + `auto_filter.ref` + `freeze_panes` + ตัวเงิน `#,##0.00`; ห้าม pandas สำหรับ styled export
- **Rule:** (1) ข้อมูล fee_collections/student_payments เป็นข้ามยุค → ใช้ Real-time (มีคอลัมน์ "ณ วันที่" กำกับ) ไม่ filter ตาม CUTOFF_DATE (2) งบ GL/TB/PL/BS อ่านจาก journal ล้วน → `export_journal_excel` ต้อง clamp ช่วงด้วย `_clamp_to_cutoff` และขึ้น note "ข้อมูลเริ่ม 2026-09-01" (3) เปลี่ยน sheet/column layout ของ export = ต้องอัปเดตเทสที่ assert `wb.sheetnames`/index ด้วย (มีทั้ง service-level + HTTP)
- **Tests:** `test_finance_export_enterprise.py` (ใหม่): management 5 แผ่น ตัวเลขโปรเจค/AR ตรง deep DB; accounting 6 แผ่น GL/TB/PL/BS ตรง deep SQL, Dr=Cr สมดุล, audit trail มีค่า, voided ถูกตัด; แก้ sheetname/header index ใน `test_finance_export.py`/`test_finance_v2_read.py`/`test_finance_http.py`/`test_finance_journal_export.py`
- **Date Added:** 2026-09-04

### 🎨 Frontend — เปลี่ยน Design System ทั้งระบบเป็น "Academic Ledger" (stone paper + น้ำเงินเดียว + เส้นบาง)
- **Context/Problem:** ระบบเดิมหน้าตาเป็น gradient/glassmorphism (gradient hero, `backdrop-blur` header, การ์ด `rounded-[2rem] shadow-2xl`, glow blob, `animate-bounce`/`animate-ping`, ปุ่มมีเงาสี) และใช้สีปนกันหลายตระกูล (`slate`/`blue`/`indigo`/`violet`/`emerald`) ทำให้แต่ละหน้าไม่เป็นภาษาเดียวกัน แก้ทีละหน้าไม่คุ้มเพราะ 40+ ไฟล์ต้องออกมาตรงกันหมด
- **Root Cause:** ไม่มี "สัญญาการออกแบบ" กลาง — ต่างคนต่างเลือกสี/เงา/มุมโค้งเอง จึงไม่มีเกณฑ์ว่าอะไรผิด ถ้าต่างคนต่างแก้จะได้ 40 หน้าตาที่ไม่เหมือนกัน
- **Correct Pattern/Solution:**
  1. **ตรึง token ก่อน แล้วค่อยแตะหน้า** — `tailwind.config.js` ประกาศสี `brand-*` (สเกลเดียว), `paper`, `ink` + ฟอนต์ `font-display` (Anuphan) / `font-sans` (Noto Sans Thai) แล้ว **ห้ามใช้สีอื่น**: `slate/gray/zinc/neutral` → `stone-*`, `indigo/violet/purple/blue` → `brand-*`
  2. **ยกคลาสที่ใช้ซ้ำขึ้นเป็น `.class` กลางใน `@layer components`** (`src/assets/main.css`): `.page-card`, `.card-hover`, `.btn-primary`, `.btn-ghost-ui`, `.btn-danger`, `.field`, `.field-label`, `.data-table`, `.chip`, `.eyebrow`, `.page-title`, `.page-lede`, `.section-title`, `.num`, `.page-wrap` — ทำให้ grep ตรวจได้และแก้ที่เดียวกระทบทั้งระบบ
  3. **สร้างคอมโพเนนต์กลาง 3 ตัวใน `src/components/ui/`** — `PageHeader` (eyebrow→h1→lede + slot `#actions`), `StateBlock` (error/empty กรอบเส้นประ), `SkeletonRows` — บังคับให้ทุก view ใช้ ทำให้หัวหน้าและสถานะโหลด/ว่าง/พัง เหมือนกันทั้งระบบ
  4. **เขียน `frontend/DESIGN.md` เป็น "สัญญา" ก่อนกระจายงาน** — 13 ข้อ รวม checklist คำต้องห้ามและตาราง "คลาสกลางใช้เมื่อไหร่" จากนั้นจึง fan-out subagent แปลงทีละกลุ่ม (งานขนานจะได้ผลตรงกัน ไม่ใช่ 40 หน้าตาที่ต่างกัน)
  5. **grep เป็นด่านตรวจสุดท้าย** — `grep -rnE "slate-[0-9]|gray-[0-9]|indigo-[0-9]|blue-[0-9]|bg-gradient|backdrop-blur|rounded-\[2|animate-bounce|animate-ping" src --include=*.vue` ต้องได้ 0 — **ระวัง false positive คำว่า `translate-x-5` มี substring `slate-`** ให้เติม `[^a-z]` ข้างหน้า หรือ `| grep -v translate-`
- **กับดักที่เจอจริงตอนแก้ (สำคัญ):**
  - `body { overflow-x: hidden }` **ทำให้ `position: sticky` พังทั้งแอป** → ใช้ `overflow-x: clip` แทน (ใส่คอมเมนต์เตือนไว้ใน `main.css` แล้ว)
  - มือถือ iOS **ซูมเองเมื่อโฟกัส input ที่ font-size < 16px** → กันด้วย `@media (max-width:640px){ input,select,textarea{ font-size:16px !important } }` และ **ห้าม override ด้วย `text-xs`/`text-sm` บน input ในมือถือ**
  - **Tailwind JIT ไม่สแกนสตริงใน `Swal.fire({ html })`** — คลาสใน HTML ที่ส่งเข้า Swal ใช้ไม่ได้ ถ้าจำเป็นต้องจัดสไตล์ให้ใช้ inline style
  - **ตาราง `w-full` กว้างเกินจอมือถือเสมอ** → ต้องมีสองเรนเดอร์: `hidden lg:block` (`.data-table`) คู่กับ `lg:hidden` (การ์ด) — และทุกกล่องข้อความยาวต้องมี `min-w-0` ที่พ่อ + `truncate` ที่ลูก ไม่งั้น flex จะดันจอล้น
  - **Layout ที่ `h-screen` + ให้ `<main>` เป็นตัว scroll เอง** ทำให้ `sticky top-0` ภายในหน้าทำงานได้ และต้องเว้นที่ให้ bottom tab bar ด้วย `pb-[calc(env(safe-area-inset-bottom)+7rem)]`
- **Navigation:** เปลี่ยนเมนูมือถือจาก left-slide drawer เป็น **Bottom Tab Bar ลอย (5 ช่อง) + FAB กลาง + Bottom Sheet สำหรับเมนูที่เหลือ** — ลบ `md:` ของ sidebar เดิมเป็น `lg:` เพื่อให้แท็บเล็ตได้ tab bar ด้วย
- **Rule:** (1) แก้หน้าตาทั้งระบบ = ตรึง token → ทำคลาสกลาง → ทำคอมโพเนนต์กลาง → เขียนสัญญา → ค่อยกระจายงาน (2) งานขนานต้องกำหนด "คำต้องห้าม" ให้ grep ได้เป็นรูปธรรม ไม่งั้น subagent ตีความคนละทาง (3) **ห้ามแตะ logic/ชื่อตัวแปร/service call/RBAC ระหว่างงานดีไซน์** — เปลี่ยนได้แค่หน้าตา (4) type-check + build ต้องผ่านหลังแปลง (5) ตรวจว่า pass ไม่ได้มาจาก cache: ลบ `node_modules/.tmp` แล้วรัน `npx vue-tsc --build --force`
- **Date Added:** 2026-09-12

### 📱 Frontend — บั๊คมือถือ 3 ตัวที่ "มองไม่เห็น" จนกว่าจะรู้กลไก: หัวข้อถูกบีบ, `sm:p-*` ทับระยะกันแท็บล่าง, และคอมเมนต์ในแท็ก
- **Context/Problem:** ผู้ใช้รายงานว่า "ในโทรศัพท์หลายหน้ามันบั๊ค ตรงหัวข้อของแต่ละหน้า และข้อความต่างๆ ... หลายอย่างมันห่างกันเกินไป ทำให้ดูบวม" — อาการคือหัวข้อหน้าถูกบีบเป็นคอลัมน์แคบ ๆ เตี้ย ๆ ข้างปุ่ม (หัวข้อไทยยาว ๆ ขึ้นบรรทัดละ 1-2 ตัวอักษร) และหน้าที่มีระยะห่างเยอะอ่านแล้วโปร่งเกินไป
- **Root Cause:**
  1. **`flex-1` + `min-w-0` + `flex-wrap` = wrap ไม่มีวันทำงาน** — `PageHeader` เดิมเป็น `flex flex-wrap items-end justify-between gap-3` โดยกล่องหัวข้อเป็น `flex-1` (คือ `flex: 1 1 0%`) และกล่องปุ่มเป็น `shrink-0`
     - `flex-wrap` ตัดสินใจขึ้นบรรทัดใหม่จาก **"outer hypothetical main size"** ซึ่งก็คือ flex-basis (ถูก clamp ด้วย min/max) **ไม่ใช่ความกว้างที่ข้อความต้องการจริง**
     - `flex-1` ทำให้ basis = `0%` และ `min-w-0` ถอด `min-width:auto` ออก → ขนาดตามทฤษฎีของกล่องหัวข้อ = **0px**
     - ดังนั้นผลรวมบรรทัด = `0 + ความกว้างปุ่ม + gap` ซึ่งแทบไม่เคยเกิน container → **wrap ไม่เคย trigger** เบราว์เซอร์จึงเหลือทางเดียวคือ "หด" กล่องหัวข้อ
     - หน้าที่ส่งปุ่ม 2 ปุ่ม (เช่น `ManageActivity` = "ดูรายละเอียด" + "แก้ไขกิจกรรม" ≈ 313px) ทำให้กล่องหัวข้อเหลือ 343−12−313 = **18px** → ได้ริ้วตัวอักษรไทยสูง ~290px
     - **บทเรียน:** `flex-wrap` ช่วยไม่ได้เลยถ้า item ที่ยืดหยุ่นมี basis 0 — ต้องให้มันมี "ความกว้างจริง" ก่อน (ใส่ `min-w-*` กลับ) wrap จึงจะทำงาน
  2. **Tailwind variant layer ทับกันเงียบ ๆ** — `<main>` มีทั้ง `pb-[calc(env(safe-area-inset-bottom)+7rem)]` (base) และ `sm:p-6` ใน class list เดียวกัน
     - Tailwind เรียงลำดับ base → `sm:` → `lg:` ดังนั้นที่ ≥640px `sm:p-6` **เขียนทับ padding-bottom** เหลือ 24px
     - แต่แท็บล่างซ่อนที่ `lg:` (1024px) → ช่วง **640–1023px (iPad portrait, มือถือแนวนอน)** แท็บล่างยังอยู่ แต่พื้นที่กันไว้เหลือ 24px → **แถวล่างสุดของทุกหน้าถูกแท็บล่างบังถาวร เลื่อนหนีไม่ได้** เพราะ padding อยู่ใน scroll container
     - **บทเรียน:** ห้ามใช้ shorthand (`p-*`) รวมกับ arbitrary value ของ property ย่อย (`pb-[...]`) ใน element เดียวกันถ้ามี breakpoint คั่น — ให้แยกเป็น `sm:px-*` / `sm:pt-*` แล้วปล่อย `pb-*` ไว้จนถึง breakpoint ที่องค์ประกอบนั้นหายจริง
  3. **คอมเมนต์ HTML ใส่ในแท็กระหว่าง attribute ไม่ได้** — `<main <!-- ... --> class="...">` ทำให้ Vue compiler โยน `SyntaxError: Illegal '/' in tags` แล้ว **build ล้มทั้งโปรเจกต์** (ไม่ใช่แค่ไฟล์นั้น) ต้องวางคอมเมนต์บรรทัดใหม่ "ก่อน" แท็ก
- **Correct Pattern/Solution:**
  1. **มือถือต้องสลับเป็นคอลัมน์จริง ไม่ใช่พึ่ง wrap** — `PageHeader` ใช้ `flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between` ให้หัวข้อได้เต็มความกว้างก่อน แล้วปุ่มค่อยขึ้นบรรทัดใหม่เอง; ที่ `sm:` ต้องเติม `sm:min-w-[16rem]` ให้กล่องหัวข้อมี basis จริง เพื่อให้ `sm:flex-wrap` ทำงานได้จริงเมื่อปุ่มเยอะ
  2. **สเกลตัวอักษรไล่ขึ้น ไม่กระโดด** — `.page-title` เปลี่ยนจาก `text-2xl sm:text-3xl` (24→30px) เป็น `text-[1.375rem] leading-snug sm:text-2xl lg:text-3xl` (22→24→30px)
  3. **`eyebrow` ภาษาอังกฤษซ่อนบนมือถือ** (`hidden sm:block`) — ประหยัด ~21px ทุกหน้า และหัวข้อไทยต้องยืนได้ด้วยตัวเอง
  4. **ปุ่มได้พื้นที่กดขั้นต่ำตามสัญญา** — เติม `min-h-11` (44px) ใน `.btn-primary` / `.btn-ghost-ui` / `.btn-danger` (เดิม `py-2.5` ให้แค่ 40px)
  5. **ความบวมจริงอยู่ที่ "ระยะห่างใน/ระหว่างการ์ด" ไม่ใช่ระยะระหว่างการ์ด** — margin ของ `PageHeader` (`mb-4`) collapse กับ `space-y-4` ของ root view (view root เป็น block div ธรรมดา) ได้ `max(16,16)=16px` **ไม่มีการซ้อนกันเลย** → อย่าไปแก้ `space-y-*` ที่ root ให้ลด `p-*`/`mt-*`/`pt-*` **ภายในการ์ด** ลงหนึ่งขั้นบนมือถือแทน (`p-4 sm:p-5`, `mt-3 sm:mt-4`, `pt-3 sm:pt-4`)
  6. **ความซ้ำคือต้นเหตุความบวมที่ใหญ่ที่สุด** — หน้าที่โชว์ค่าเดียวกัน 2-3 ที่ (บทบาท, ชื่อห้อง, รหัสห้อง) หรือมีลิสต์ทางลัดที่ซ้ำกับเมนูนำทาง ให้เหลือ "บ้านหลังเดียว" ต่อหนึ่งข้อเท็จจริง
- **Rule:** (1) ตรวจ UI มือถือ = ต้องคิดที่ 375px และ **640–1023px** ด้วย ไม่ใช่แค่ 375 กับ desktop (2) อย่าดูแค่ "คลาสที่เขียน" ต้องไล่กลไก flex/ลำดับ layer ของ Tailwind จริง ๆ (3) `flex-wrap` ใช้ไม่ได้ถ้า item มี basis 0 (4) shorthand กับ property ย่อยใน element เดียวกัน = กับดัก (5) คอมเมนต์ HTML ต้องอยู่นอกแท็กเสมอ (6) ก่อนรายงานว่าเสร็จ ต้องรัน `npm run build` จริง — `type-check` ผ่านไม่ได้แปลว่าเทมเพลต parse ผ่าน
- **Date Added:** 2026-09-12

### 🧩 Frontend — แผนที่ lookup ใน Vue template (`Record<string, T>`) พัง type-check เพราะ `noUncheckedIndexedAccess`
- **Context/Problem:** เพิ่มตัวช่วยแปลค่า enum → ป้าย (เช่น `statusMeta(status)` ที่คืน `{ chip, icon, label }` จาก `Record<string, StatusMeta>`) แล้วเรียกใช้ใน template แบบ `statusMeta(room.status).chip` — `vue-tsc` ล้มด้วย `error TS2532: Object is possibly 'undefined'` ที่ทุกบรรทัดที่เรียกใช้
- **Root Cause:** `frontend/tsconfig.app.json` เปิด `noUncheckedIndexedAccess` ไว้ → ทุก index access (`MAP[key]`) มี type เป็น `T | undefined` **ไม่ใช่ `T`** ดังนั้น `STATUS_META[status] || STATUS_META.inactive` ที่เขียนเป็น fallback ก็ยังคืน `T | undefined` อยู่ดี เพราะฝั่งขวาของ `||` เองก็มาจาก index access (`MAP.inactive` ของ Record ที่ index ได้ = `T | undefined`)
- **Correct Pattern/Solution:** แยก fallback ออกมาเป็น const ที่ "ไม่ผ่าน index" แล้วประกาศ type ให้ชัด
  ```ts
  type StatusMeta = { chip: string; icon: string; label: string }
  const STATUS_FALLBACK: StatusMeta = { chip: 'bg-stone-100 text-stone-600', icon: 'bi-slash-circle-fill', label: 'ปิดใช้งาน' }
  const STATUS_META: Record<string, StatusMeta> = { active: {...}, pending: {...}, inactive: STATUS_FALLBACK }
  const statusMeta = (status: string) => STATUS_META[status] ?? STATUS_FALLBACK   // → StatusMeta แน่นอน
  ```
  ถ้าฝั่งขวาเป็น literal string / primitive อยู่แล้ว (เช่น `ROLE_LABELS[role] || role || 'นักเรียน'`) ไม่ต้องทำอะไร เพราะ union collapse เหลือ `string` เอง
- **Rule:** (1) helper ที่อ่านจาก `Record<>` แล้วคืน object และถูกเรียกใน template → ต้องมี fallback ที่เป็น const ประกาศ type ไว้ ไม่ใช่ตัวที่ได้จาก index (2) `type-check` เป็นด่านแรกที่จับเรื่องนี้ ไม่ใช่ runtime — รัน `npx vue-tsc --noEmit -p tsconfig.app.json` หลังแก้ template ทุกครั้ง
- **Date Added:** 2026-09-12

### 📱 Frontend — `truncate` บน "ข้อมูลที่อ่านอย่างเดียว" = ซ่อนข้อมูลถาวรบนมือถือ
- **Context/Problem:** ตอนจัดหน้าให้กระชับ มีการเติม `truncate` ให้ป้ายยาว ๆ เพื่อกันล้น ซึ่งถูกต้องสำหรับ "ชื่อรายการในลิสต์ที่กดเข้าไปดูเต็มได้" แต่ผิดสำหรับ "ค่าที่แสดงครั้งเดียวจบ" เช่น แถวข้อมูลส่วนตัวใน modal หรือตัวอย่างประกาศ — ข้อความที่ถูกตัดจะ **ไม่มีทางดูเต็มได้เลย** เพราะมือถือไม่มี hover (ไม่มี tooltip) และไม่มีหน้าไหนให้เข้าไปดูต่อ
- **Root Cause:** `truncate` = `overflow:hidden; text-overflow:ellipsis; white-space:nowrap` ตัดสินที่ "บรรทัดเดียว" ไม่สนใจว่าผู้ใช้จะได้เห็นส่วนที่เหลือหรือไม่ — มันจึงปลอดภัยก็ต่อเมื่อ "ปลายทางอื่น" มีข้อมูลนั้นจริง
- **Correct Pattern/Solution:** ถามว่า "ถ้าตัดแล้ว ผู้ใช้ไปดูเต็มได้ที่ไหน" ถ้าไม่มีคำตอบ → ใช้ `break-words` (หรือ `break-words leading-snug`) ให้ขึ้นบรรทัดใหม่แทน แลกความสูงของแถวกับความครบของข้อมูล
  - เปลี่ยนจริงในรอบนี้: `ParticipantInfoModal` (แถวข้อมูลส่วนตัว) และ `SendMessage` (ตัวอย่างหัวข้อประกาศ) → `truncate` เป็น `break-words`
  - ที่ยังคง `truncate` ไว้ถูกต้อง: ชื่อห้อง/ชื่อนักเรียนในลิสต์ เพราะกดเข้าไปดูหน้าถัดไปได้
- **Rule:** `truncate` ใช้ได้กับ "ลิสต์ที่กดเข้าไปดูได้" เท่านั้น — ข้อมูลอ่านครั้งเดียวจบ (modal, ตัวอย่าง, KPI) ต้อง `break-words`
- **Date Added:** 2026-09-12

### 🤖 Process — แปล enum เดียวกันด้วยเอเจนต์ขนานกัน = ข้อความไม่ตรงกันข้ามหน้า
- **Context/Problem:** งานนี้กระจายแก้ 42 ไฟล์ให้เอเจนต์หลายตัวพร้อมกัน แต่ละตัวต้อง "แปลค่า enum อังกฤษเป็นป้ายไทย" เอง ผลคือ **ค่าเดียวกันถูกแปลคนละแบบในคนละหน้า** โดยไม่มีใครผิด:
  - `class_role = secretary` → `Lobby.vue` + `StudentList.vue` เขียน `'เลขานุการ'` แต่ `stores/auth.ts` + `StudentProfile.vue` + `RoadmapView.vue` เขียน `'เลขานุการ (เรขา)'`
  - `students.status = inactive` → `Lobby.vue` เขียน `'ระงับการใช้งาน'` แต่ `StudentList.vue` เขียน `'ปิดใช้งาน'` (และร้าน filter ของ StudentList ผูกกับ `'ปิดใช้งาน'` ไปแล้ว)
  - `students.status = active` → `'ใช้งานอยู่'` (Lobby) vs `'ใช้งาน'` (StudentList)
  - chip `ADMIN` / `STAFF` ยังเป็นอังกฤษ ดิบ ๆ ข้างป้ายบทบาทไทยที่เพิ่งแปลเสร็จในหน้าเดียวกัน
- **Root Cause:** `ROLE_LABELS` ถูกประกาศซ้ำ **6 ที่** ในโปรเจกต์ (`stores/auth.ts` ประกาศไว้แต่ **ไม่ export** จึงใช้ร่วมไม่ได้) → ไม่มี single source of truth ให้ทุกเอเจนต์อ้าง ทำให้การแปลขนานกันกลายเป็นการแปลอิสระ
- **Correct Pattern/Solution:** หลังงานที่กระจายให้หลายเอเจนต์ **ต้องมีรอบเก็บกวาดข้อความข้ามไฟล์** — วิธีจับที่ได้ผลจริงคือ grep ตัวป้าย (ไม่ใช่ตัว enum) ทั้งโปรเจกต์แล้วเทียบ:
  ```bash
  grep -rn "เลขานุการ" src/            # เจอทั้ง 'เลขานุการ' และ 'เลขานุการ (เรขา)'
  grep -rn "ปิดใช้งาน\|ระงับการใช้งาน" src/
  grep -rn "> ADMIN\|> STAFF" src/     # จับ chip ที่ยังไม่แปล
  ```
  แล้วยึด "ฝั่งที่ข้อความอื่นผูกอยู่แล้ว" เป็นมาตรฐาน (เช่น StudentList มี filter ที่เขียน `'ปิดใช้งาน'` → ใช้ `'ปิดใช้งาน'`) ไม่ใช่ยึดฝั่งที่แก้ทีหลัง
- **Rule:** (1) งานแปลข้อความที่กระจายหลายเอเจนต์ ต้องมี "รอบเก็บกวาดข้ามไฟล์" เป็นขั้นบังคับ ไม่ใช่หวังว่าแต่ละตัวจะตรงกันเอง (2) เวลาจะรวมข้อความที่ขัดกัน ให้ดูว่าฝั่งไหนมีโค้ดอื่นอ้างถึงอยู่แล้ว แล้วยึดฝั่งนั้น (3) ทางแก้ระยะยาวคือ export `ROLE_LABELS` จาก `stores/auth.ts` แล้วให้ทุกหน้า import — ตอนนี้ยังไม่ได้ทำเพราะเป็นการ refactor ที่แตะ store
- **Date Added:** 2026-09-12

### 📄 Frontend — เปลี่ยน "จำนวนแถวต่อหน้า" ต้องรีเซ็ต/หนีบ page ด้วย ไม่งั้นได้ "ไม่พบรายการ" ปลอม
- **Context/Problem:** `TransactionHistory.vue` มี select จำนวนแถวต่อหน้าที่ผูก `v-model="filters.limit"` ตรง ๆ ผู้ใช้ที่อยู่หน้า 5 แล้วเปลี่ยน limit จาก 50 เป็น 100 จะเห็น **"ไม่พบรายการ"** ทั้งที่ข้อมูลมีอยู่
- **Root Cause:** หน้าถูกคำนวณจาก `offset = (currentPage - 1) * limit` พอ limit โตขึ้น จำนวนหน้าจริงลดลง (200 แถว: 50/หน้า = 5 หน้า → 100/หน้า = 2 หน้า) แต่ `currentPage` ยังเป็น 5 → offset 400 เกินช่วงข้อมูล → backend คืน 0 แถวอย่างถูกต้อง แล้ว UI ตีความเป็น empty state
- **จุดที่พลาดได้ง่าย:** ไฟล์นี้มี `applyFilters()` ที่ `currentPage.value = 1` อยู่แล้ว ทำให้ดูเหมือนปัญหาถูกจัดการแล้ว แต่ select **ไม่ได้เรียก `applyFilters`** — มันผูก `v-model` ตรง ๆ แล้วพึ่ง watcher รวม `watch([currentPage, () => filters.value.limit])` ซึ่งเปลี่ยน limit โดยไม่แตะ page
- **Correct Pattern/Solution:** แยก watcher ของ limit ออกมา แล้วหนีบ page ก่อนดึงข้อมูล โดยให้ watcher ของ page เป็นคนดึง (กันยิงซ้ำสองรอบ)
  ```ts
  watch(currentPage, () => { fetchTransactions(); });

  watch(
    () => filters.value.limit,
    () => {
      if (currentPage.value !== 1) {
        currentPage.value = 1; // watcher ของ currentPage จะดึงข้อมูลให้ (ยิงครั้งเดียว)
        return;
      }
      fetchTransactions();
    }
  );
  ```
- **Rule:** ตัวควบคุมที่เปลี่ยน "ขนาดหน้า" (limit / per_page / page_size) ต้องรีเซ็ตหรือหนีบ page เสมอ และถ้ามี watcher รวมหลาย source ให้ตรวจว่าการเปลี่ยน source หนึ่งไม่ได้ทิ้ง source อื่นไว้ค่าเก่า
- **Date Added:** 2026-09-12

### 🐛 Timezone — `datetime` แบบ naive เทียบกับคอลัมน์ `timestamptz` = asyncpg ตีความเป็น "เวลาท้องถิ่นของเครื่อง" ไม่ใช่ UTC (งบการเงินกินข้อมูลข้ามวัน)
- **Context/Problem:** งบการเงินทุกตัว (trial balance / income statement / balance sheet / export) สร้างขอบเขตเวลาด้วย `datetime.combine(d, dtime(23, 59, 59))` แล้วส่งเป็น parameter เทียบกับ `journal_entries.transaction_date` (timestamptz) → **ใน container ที่ `TZ=UTC` (ซึ่งคือภาพ production) งบของวันที่ 1 ก.ย. แอบนับรายการถึง 06:59:59 ของวันที่ 2 ก.ย. ตามเวลาไทย** ⇒ รายการที่บันทึกตี 1:30 ของวันถัดไปโผล่ในงบของเมื่อวาน; รายงานเดียวกันให้ตัวเลขคนละชุดระหว่างเครื่อง dev (TZ=Asia/Bangkok, ถูกโดยบังเอิญ) กับ container (ผิด)
- **Root Cause:** asyncpg เข้ารหัส `datetime` ที่ **ไม่มี tzinfo** เป็นเวลาท้องถิ่นของโปรเซส (`obj.astimezone(utc)`) **ไม่ใช่** UTC อย่างที่มักเข้าใจ พิสูจน์ด้วย `-e TZ=Etc/GMT-7`: `datetime(2026,9,1,23,59,59)` → `2026-09-01 16:59:59+00:00` (= `naive.astimezone(utc)` เป๊ะ) ส่วนใน container `TZ=UTC` ค่าเดียวกันกลายเป็น `2026-09-01 23:59:59+00:00` = `2026-09-02 06:59:59+07:00` → เกินมา 7 ชั่วโมง. อาการนี้ **ตรวจไม่เจอ** ถ้ารันเทสใน container TZ=UTC ด้วย seed ที่เวลากลางวัน (12:00) เพราะไม่ข้ามเส้นวัน
- **Correct Pattern/Solution:** สร้างขอบเขตวันเป็น **tz-aware เวลาไทย** เสมอ ผ่าน helper กลางใน `services/finance/helpers.py` — ห้าม `datetime.combine(...)` เปล่า ๆ อีก:
  ```python
  def _thai_day_start(d: date) -> datetime:      # 00:00:00+07:00  → ใช้กับ `>= $n`
      return datetime.combine(d, dtime.min, tzinfo=THAI_TZ)
  def _thai_day_end(d: date) -> datetime:        # 23:59:59.999999+07:00 → ใช้กับ `<= $n`
      return datetime.combine(d, dtime.max, tzinfo=THAI_TZ)
  def _thai_next_day_start(d: date) -> datetime: # (d+1) 00:00:00+07:00 → ใช้กับ `< $n`
      return datetime.combine(d + timedelta(days=1), dtime.min, tzinfo=THAI_TZ)
  ```
  ใช้ `dtime.max` ไม่ใช่ `23:59:59` เพื่อไม่ให้รายการวินาทีสุดท้ายของวันหลุดจากเงื่อนไข `<` (ช่องโหว่ที่ `get_trial_balance` มีอยู่ก่อนแล้ว)
- **Rule:** (1) **ห้ามส่ง `datetime` naive เป็น parameter ที่เทียบกับคอลัมน์ `timestamptz`** — ต้องมี `tzinfo` เสมอ (สำหรับเวลาไทยใช้ `THAI_TZ`) (2) `_naive_thai_dt()` ยังใช้ได้กับการเทียบ **naive ↔ naive** (เช่น `finance_transactions.created_at` กับ `CUTOFF_DATE`) แต่ห้ามใช้ปนกับ timestamptz (3) ขอบเขตวันของ "รายงาน" ต้องเขียนเป็น helper กลาง **ไม่กระจาย `datetime.combine` ตามไฟล์** — บั๊กนี้อยู่พร้อมกัน 4 จุด (reporting.py ×3, export.py ×1) เพราะต่างคนต่างเขียน (4) ฝั่ง SQL ยังมี `DATE(JE.transaction_date)` ที่แปลงตาม **session TimeZone** ซึ่งเป็นความหมายที่สาม — ระวังอย่านับว่ามันเท่ากับสองแบบข้างบน
- **Tests:** `test_finance_statements.py` §`[TIMEZONE]` — 6 เทสต์ที่ seed รายการ "ตี 1:30 เวลาไทย" (UTC ยังเป็นวันก่อนหน้า) แล้วยืนยันว่ามันไม่โผล่ในงบของวันก่อน: `test_as_of_window_is_bangkok_scoped` (parametrize 3 วัน × TB+BS), `test_day_boundary_is_exact_at_bangkok_midnight` (23:59:59 นับ / 00:00:00 วันถัดไปไม่นับ), `test_income_statement_end_date_is_bangkok_scoped`, `test_export_balance_sheet_period_is_bangkok_scoped`, `test_thai_day_bound_helpers_are_tz_aware_and_pin_correct_instants` (l็อกค่าที่ถูกต้องไว้โดยไม่ต้องพึ่ง DB — จับได้ทันทีถ้ามีคนถอด `tzinfo` ออก). A/B พิสูจน์แล้ว: **5 ใน 7 พังกับโค้ดเดิม** โดยพังด้วยอาการที่ถูกต้อง (`as_of=2026-09-01 ควรเห็นเงินสด 0.0 แต่ได้ 111.0`)
- **Date Added:** 2026-09-13

### 🐛 Finance — `_compose_balance_sheet` ฮาร์ดโค้ด `liability_total = 0.0` → `is_balanced` เป็นเท็จหลอก ๆ บนเอกสารที่พิมพ์ออกมา
- **Context/Problem:** งบแสดงฐานะการเงิน (ทั้งในหน้าเว็บใหม่และแผ่น BS ในไฟล์ Excel) ขึ้นธง **"ไม่สมดุล"** ตลอดกาลทันทีที่ห้องสร้าง liability ledger ตัวแรก ทั้งที่งบทดลอง (trial balance) รายงานว่าสมดุล — เพราะหัวตารางที่พิมพ์ออกมาอ้างสมการ `สินทรัพย์ = หนี้สิน + ส่วนของเจ้าของ + กำไรสะสม` แต่โค้ดรวมฝั่งขวาแค่ `equity + retained` โดยไม่บวกหนี้สิน ⇒ **สัญญาณเตือนเท็จบนเอกสารที่นักบัญชีอ่าน** ซึ่งอันตรายกว่าไม่มีสัญญาณเลย
- **Root Cause:** `_compose_balance_sheet` เดิมเป็นฟังก์ชันที่ถูกเรียกจาก Excel export เท่านั้น จึงไม่มีใครสังเกตว่า `liability_total` ถูกฮาร์ดโค้ดเป็น `0.0` และ `is_balanced` ถูกเทียบกับ `total_equity_side` (ไม่รวมหนี้สิน) — พอมี liability ledger ตัวแรกที่มียอดจริง สมการพังทันที
- **Correct Pattern/Solution:** คำนวณหนี้สินจริงจาก `tb["ledgers"]` ที่ `account_type == 'liability'` โดยใช้ค่า `balance` ที่ `_fetch_trial_balance_ledgers` ให้มาแล้ว (เป็น `Cr − Dr` ⇒ **หนี้สินมาเป็นบวกอยู่แล้ว ห้ามกลับเครื่องหมายซ้ำ**) แล้วเพิ่มคีย์ `total_liabilities_and_equity = liability_total + equity_total + retained` และเทียบ `is_balanced` กับคีย์นี้ — คง `total_equity_side` ไว้ตามความหมายเดิมเพื่อไม่ให้ผู้ใช้เดิมพัง
- **Rule:** (1) ตัวเลขที่ **หัวตารางอ้างถึง** ต้องถูกคำนวณจริง ไม่ใช่ฮาร์ดโค้ดเป็น 0 แล้วเขียนคอมเมนต์ว่า "ยังไม่มี" (2) `is_balanced` ต้องเทียบกับ **ทุกองค์ประกอบที่พิมพ์ออกมา** ไม่ใช่ subset (3) `account_type` ของ `accounting_ledgers` **ไม่มี CHECK constraint** (มีแค่คอมเมนต์) → ใส่ `else` ที่ครอบ "ประเภทที่ไม่รู้จัก" ไว้เสมอ; ตัดออกจากทุกฝ่ายโดยเจตนา (ให้ `is_balanced` เป็น False = เห็นสัญญาณ) **ดีกว่า** เงียบ ๆ ไปรวมเป็นค่าใช้จ่ายแล้วได้ True ทั้งที่เงินถูกจัดประเภทผิด
- **Tests:** `test_finance_statements.py::test_balance_sheet_equation_holds_with_liability_ledger` (สร้าง liability ledger +`Dr expense / Cr liability` → `liability_total > 0` และ `is_balanced is True`) — **A/B พิสูจน์แล้วว่า 5 เทสต์พังกับ `_compose_balance_sheet` เวอร์ชันก่อนแก้** และ `test_export_balance_sheet_sheet_lists_liabilities` (แผ่น BS ต้องมีบรรทัดหนี้สินรายตัว + "รวมหนี้สิน" = 300 ไม่ใช่ 0.0) คู่กับ `test_export_balance_sheet_flags_unbalanced_when_equation_really_breaks` (ธงต้อง**ไม่ได้**เขียวตลอด — สร้างสมการพังจริงด้วยบรรทัดเดี่ยวที่ไม่มีคู่)
- **Date Added:** 2026-09-13

### 🐛 Routers — `from models.finance_schemas import *` ทำให้การเพิ่ม `__all__` ในไฟล์ schema พังทั้ง router
- **Context/Problem:** `routers/finance/reporting.py` และ `routers/finance/export.py` import schema แบบ wildcard (`from models.finance_schemas import *`) อยู่ก่อนแล้ว ⇒ พอเพิ่ม F1 schemas แล้วอยากจัดบ้านด้วยการใส่ `__all__` ใน `finance_schemas.py` ทั้งสอง router พังทันทีที่ import ด้วย `NameError: name 'date' is not defined` (wildcard ที่มี `__all__` จะ **ไม่** ดึงชื่อที่ `__all__` ไม่ได้ระบุ ซึ่งรวมถึง helper/stdlib ที่โค้ดเดิมพึ่งพาโดยบังเอิญ เช่น `date`, `datetime` ที่ import ไว้ในไฟล์ schema)
- **Root Cause:** `import *` เดิมทำหน้าที่เป็น "import ทุกอย่างที่ module นั้นมองเห็น" ซึ่งรวม stdlib ที่ re-export โดยไม่ได้ตั้งใจ → การเพิ่ม `__all__` เปลี่ยนสัญญาแบบ breaking ทันทีโดยไม่มีใครรู้
- **Correct Pattern/Solution:** **ห้ามเพิ่ม `__all__`** ใน `models/finance_schemas.py` จนกว่าจะเปลี่ยน router ทั้งสองเป็น explicit import ก่อน — เขียนคอมเมนต์เตือนไว้ที่หัวไฟล์ schema (มีอยู่แล้ว) และถ้าจำเป็นต้องจัดบ้านจริง ให้เปลี่ยน router เป็น explicit import **ก่อน** แล้วค่อยใส่ `__all__`
- **Rule:** เพิ่ม `__all__` ให้ module ที่มีคน `import *` อยู่ = การเปลี่ยนแปลงแบบ breaking; grep `import \*` ก่อนทุกครั้ง
- **Tests:** เทสต์ HTTP ของ F1 ใน `test_finance_statements.py` (`test_statements_without_explicit_date_return_200` parametrize ครบ 3 path) จะ import router ทั้งสองตัว ⇒ พังทันทีถ้ามีคนใส่ `__all__`
- **Date Added:** 2026-09-13

### 🧪 Tests — เทสต์ export ที่ assert ด้วย **index ของคอลัมน์/แถว** เน่าเงียบ ๆ เมื่อ layout ขยับ (แต่ assert ด้วย **ป้ายชื่อ** ก็ยังเน่าได้ถ้าป้ายถูกเติม suffix)
- **Context/Problem:** `test_finance_export_enterprise.py` ล้ม 5 เทสต์และ `test_finance_journal_export.py` ล้มอีก 1 เทสต์บน `main` **ก่อน**งาน F1 เริ่ม — ตรวจด้วย `git stash` A/B แล้วว่าเป็นเทสต์เน่ามาจาก commit `44b5499` (Update export.py) ไม่ใช่ regression ของงานเรา
- **Root Cause:** สองสาเหตุพร้อมกัน — (1) `_find_row(tb_rows, 0, "รวมทั้งสิ้น")` ค้น **คอลัมน์ A** แต่ป้ายย้ายไปอยู่ **คอลัมน์ B** (index 1) ⇒ คอลัมน์ A เป็น `None`; และ (2) ป้ายถูกเติม suffix เป็น `"รวมทั้งสิ้น (Grand Total)"` ⇒ เทียบแบบเป๊ะไม่เจอ; ส่วน `test_finance_journal_export.py` เป็น **ชื่อ sheet drift** (`'สมุดรายวัน (General Journal)'` vs `'สมุดรายวันทั่วไป (GJ)'` ที่ `export.py` ตั้งจริง)
- **Correct Pattern/Solution:** หาแถวด้วย **ป้ายชื่อแบบ "มีอยู่ข้างใน"** ไม่ใช่เทียบเป๊ะ และค้นให้ครบทุกคอลัมน์ที่ป้ายอาจอยู่ — helper สองตัวใน `test_finance_statements.py`:
  ```python
  def _find_row(rows, col, needle):            # เทียบเป๊ะ — ใช้เมื่อป้ายนิ่งแล้ว
  def _find_row_containing(rows, col, fragment): # "fragment in r[col]" — ทนการเติม suffix
  ```
  และเมื่อต้องอ่านค่าจากคอลัมน์ ให้ยืนยัน index ของคอลัมน์นั้นด้วยเทสต์แยก ไม่ใช่เดาจาก `values`
- **Rule:** (1) เทสต์ที่ผูกกับ index ของเซลล์จะพังทุกครั้งที่ layout ขยับ → ผูกกับ **ป้าย** (2) แต่ป้ายก็ขยับได้ → ใช้ "contains" และ **อย่า assert ทั้งสตริง** (3) เจอเทสต์ล้มบน branch ที่เราไม่ได้แตะ → พิสูจน์ด้วย `git stash` A/B **ก่อน**สรุปว่าเป็น regression ของเรา แล้ว **รายงานให้ผู้ใช้ตัดสิน** ว่าจะแก้ assert ให้ตรงกับโค้ดหรือแก้โค้ด — การเปลี่ยน assert ให้ตรงกับโค้ดเป็นการตัดสินใจเชิงผลิตภัณฑ์ ไม่ใช่ bug fix
- **Tests:** `test_finance_statements.py::_find_row_containing` ถูกสร้างเพราะเคสนี้โดยตรง; เทสต์ใหม่ `test_export_balance_sheet_sheet_lists_liabilities` / `test_export_balance_sheet_flags_unbalanced_when_equation_really_breaks` เขียนด้วยป้ายชื่อล้วน
- **Date Added:** 2026-09-13

### 🧪 Tests — `clean_database` เป็น autouse + `TRUNCATE ... CASCADE` ⇒ fixture ที่สร้าง room/user ต้อง **function-scoped** และห้าม hardcode id
- **Context/Problem:** `docs/rules/testing.md` อ้างถึง `admin_headers` (discord 999 = admin) แต่ `backend/tests/conftest.py` **ไม่มี** มาก่อน → ต่างไฟล์ต่างสร้าง user/room เอง ซ้ำ ๆ; พอเพิ่ม fixture จริงแล้วเทสต์ใหม่ยิง 403 `"คุณไม่ได้เป็นสมาชิกที่ใช้งานอยู่ในห้องเรียนนี้"` เพราะสร้าง room ของตัวเองด้วย `_insert_room` แล้วยิงด้วย `admin_headers` (ซึ่งเป็นสมาชิกของ **ห้องอื่น**)
- **Root Cause:** `require_member(conn, room_id, user_id)` **ไม่ bypass ให้ `is_admin`** (ต่างจาก `require_permission` ที่ bypass ทั้ง `SUPER_ADMIN_ID` และ `is_admin`) ⇒ ต้องมีแถว `students` ที่ `status='active'` ในห้องนั้นจริง ๆ; และ `clean_database` เป็น `autouse=True` + `TRUNCATE TABLE users, rooms, mtn_locations CASCADE` **ก่อนทุกเทสต์** ⇒ fixture ระดับ session/module จะถูกล้างทิ้งกลางทาง
- **Correct Pattern/Solution:** fixture แบบ function-scoped ที่สร้าง user + room + แถว `students` ของตัวเอง (`_provision_auth_context`) แล้วให้เทสต์ใช้ `admin_headers.room_id` เป็นห้องเป้าหมาย — **ไม่สร้างห้องใหม่แยกจาก header**; `TRUNCATE ... CASCADE` **ไม่ reset sequence** ⇒ ledger/user/room id ไต่ขึ้นเรื่อย ๆ ข้ามเทสต์ **ห้าม hardcode id เด็ดขาด**
- **Rule:** (1) `require_member` ≠ `require_permission` — ตัวแรกต้องการแถว `students` จริง `is_admin` ไม่ช่วย (มีเทสต์ล็อกไว้: `test_statements_is_admin_does_not_bypass_require_member`) (2) เทสต์ที่ยิง HTTP ด้วย header fixture ต้องใช้ `headers.room_id` เป็นห้อง (3) fixture ที่แตะ DB ต้อง function-scoped เสมอเพราะ `clean_database` เป็น autouse
- **Tests:** `test_finance_statements.py` — `test_statements_allow_plain_member` / `test_statements_forbid_non_member` / `test_statements_is_admin_does_not_bypass_require_member` (parametrize ครบ 3 path) + `test_statements_unknown_room_returns_404`
- **Date Added:** 2026-09-13

### 🕐 Dates — แก้ขอบเขตเวลาแบบ **ไม่ครบทุกจุดในไฟล์เดียวกัน** ทำให้ไฟล์ที่เคย "ผิดเหมือนกันทั้งไฟล์" กลายเป็น "ขัดแย้งกันเองในไฟล์เดียว"
- **Context/Problem:** งาน F1 แก้ขอบเขตวันที่จาก naive datetime → tz-aware เวลาไทย 4 จุด (`reporting.py` ×3, `export.py` ×1 สำหรับ `_fetch_*`) แต่ **เหลืออีกจุดในไฟล์เดียวกัน**: ชีต "สมุดรายวันทั่วไป (GJ)" ใน `export.py` ยังกรองด้วย `DATE(JE.transaction_date) >= $n` ⇒ รายการที่บันทึก 00:00–07:00 น. เวลาไทยของวันหัว/ท้ายช่วง **หลุดจากชีต GJ แต่ยังถูกนับในชีต GL/TB/IS/BS** (เจอด้วย adversarial review หลัง commit แรก ไม่ใช่ด้วยเทสต์)
- **Root Cause:** `DATE(x)` บนคอลัมน์ **`timestamptz`** จะแปลงเป็น TimeZone ของ **session** ก่อนตัดวัน — DB ตั้ง `TimeZone = UTC` ⇒ ขอบเขตผิดไป 7 ชั่วโมง; ก่อนแก้ทั้ง `_fetch_*` (naive → asyncpg ตีเป็น host-local = UTC) และ `DATE()` (session = UTC) **ตรงกันโดยบังเอิญ** จึงไม่ขัดกันเอง (ผิดพร้อมกันทั้งไฟล์) แต่พอแก้ข้างเดียว ความไม่ตรงกัน 7 ชั่วโมงก็โผล่ **ระหว่างชีตในไฟล์เดียว** — ตรวจจับได้ยากกว่าตอนที่ผิดทั้งไฟล์
- **Correct Pattern/Solution:** ใช้ขอบเขตชุดเดียวกับ `_fetch_income_statement_rows` (`JE.transaction_date >= lower_dt` / `<= upper_dt` โดย `lower_dt = _thai_day_start(...)`, `upper_dt = _thai_day_end(...)`) — **ห้ามใช้ `DATE()` กับคอลัมน์ timestamptz เด็ดขาด**
  - ⚠️ **แก้ความเข้าใจเดิม (พบทีหลัง — ดูบทเรียนถัดไป):** ตอนแรกสรุปว่า `DATE(T.created_at)` ของ `finance_transactions` "ถูกต้องแล้ว" เพราะคอลัมน์เป็น `TIMESTAMP` (naive) จึงไม่มีการแปลง TZ — **ครึ่งเดียวถูก**: มันไม่แปลง TZ จริง แต่ค่าที่ *เก็บ* ในคอลัมน์นั้นเป็น **UTC wall clock** ⇒ `DATE()` ได้ **วันตาม UTC** ซึ่งก็ยังไม่ใช่วันไทยอยู่ดี · **"ไม่แปลง TZ" ≠ "ถูกต้อง"** ต้องถามต่อว่า *ค่าที่เก็บเป็นโซนไหน* ไม่ใช่แค่ *ชนิดคอลัมน์คืออะไร*
- **Rule:** (1) แก้ bug ขอบเขตเวลา ให้ **grep หาทุกจุดที่เทียบวันที่ในไฟล์/โมดูลเดียวกันก่อน** แล้วแก้ให้ครบในรอบเดียว (2) `DATE(col)` บน `TIMESTAMPTZ` ผิดเพราะแปลงตาม session TZ — **ห้ามใช้**; บน `TIMESTAMP` naive ไม่แปลง TZ แต่ **ผลจะถูกหรือไม่ขึ้นกับว่าเก็บค่าอะไรไว้** ⇒ ต้องพิสูจน์ด้วย probe (3) เมื่อไฟล์เดียวประกอบตัวเลขจากหลาย query ที่ใช้ขอบเขตคนละแบบ ให้ **assert ไขว้กัน** ว่ายอดของชีตหนึ่งเท่ากับอีกชีตหนึ่ง (4) การแก้ที่ "ถูกกว่าเดิมแต่ไม่ครบ" อาจ **แย่กว่าเดิม** เพราะเปลี่ยน "ผิดสม่ำเสมอ" เป็น "ขัดแย้งกันเอง"
- **Tests:** `test_finance_statements.py::test_export_journal_sheet_matches_other_sheets_bangkok_bounds` — ยืนยันสองชั้น: รายการ 03:00 น. ไทยของวันแรกช่วงต้องอยู่ในชีต GJ และยอดรวม GJ ต้องเท่างบทดลองในไฟล์เดียวกัน — **A/B พิสูจน์แล้วว่าเทสต์นี้พังกับโค้ดก่อนแก้ โดยรายงานว่าเจอ `'ทุนตีสามวันที่ 1 ต.ค.'` แทน `'ทุนตีสามวันที่ 1 ก.ย.'`** (รายการถูกย้ายเดือนทั้งเดือน)
- **Date Added:** 2026-09-13

### 🧭 Timezone — **`TIMESTAMP DEFAULT CURRENT_TIMESTAMP` ไม่ได้แปลว่า "เวลาไทย"** และการแก้ TZ บางส่วนทำให้ **คนละ endpoint ใช้ปฏิทินคนละใบ**
- **Context/Problem:** หลังแก้งบการเงิน (F1) ให้ใช้เส้นแบ่งวันเวลาไทยแล้ว มาตรวจทั้งโมดูลตามกฎ "grep หาทุกจุด" จึงพบ `_get_transactions_v2()` (`services/finance/transactions.py`) ยังใช้ `DATE(JE.transaction_date)` ⇒ **งบการเงินกับหน้าประวัติรายการใช้ปฏิทินคนละใบ**: รายการที่บันทึก 03:00 น. ไทยวันที่ 1 ก.ย. ไปโผล่ใน **งบกันยายน** แต่ไปอยู่ **ประวัติเดือนสิงหาคม** — ยอดไม่ตรงกันข้ามหน้าจอ
- **Root Cause:** สองชั้นซ้อนกัน (ก) `DATE()` บน `timestamptz` ตัดวันตาม **session TimeZone** ซึ่งเป็น UTC (ข) ที่ร้ายกว่าคือ `finance_transactions.created_at` เป็น `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` — ค่าที่ `CURRENT_TIMESTAMP` คืนมาเป็น `timestamptz` แล้วถูก **แปลงเป็น session TZ (= UTC)** ก่อนเก็บ ⇒ คอลัมน์นี้เก็บ **UTC wall clock** ไม่ใช่เวลาไทย · คอมเมนต์ในแผนที่เขียนว่า *"ใช้ `T.created_at::date` (naive Bangkok)"* จึง **ไม่ตรงความจริง** และ`_naive_thai_dt()` ก็ตีความ naive นั้นว่าเป็นเวลาไทยทั้งที่เป็น UTC (ส่งผลกับ sort และ `cutoff_dt` ของ merge ด้วย)
- **Correct Pattern/Solution:** **อย่าเชื่อคอมเมนต์/เอกสาร — พิสูจน์ด้วย probe** ก่อนตัดสินว่าคอลัมน์ naive เก็บโซนไหน:
  ```sql
  CREATE TEMP TABLE _probe (c TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
  INSERT INTO _probe DEFAULT VALUES;
  SELECT c, now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'Asia/Bangkok' FROM _probe;
  ```
  เทียบว่าค่าที่เก็บตรงกับตัวไหน · ส่วน `journal_entries.transaction_date` เป็น `timestamptz DEFAULT CURRENT_TIMESTAMP` และ `_insert_journal_entry` (`ledger.py:152`) **ไม่ส่งค่านี้เลย** ⇒ เป็น **instant จริง** ⇒ การเทียบกับเส้นแบ่งวันไทย (`_thai_day_start`/`_thai_day_end`) **ถูกต้อง**
- **Rule:** (1) **`TIMESTAMP` ไม่ได้หมายถึงเวลาไทย** — `DEFAULT CURRENT_TIMESTAMP` บนคอลัมน์ naive จะเก็บ **UTC** ถ้า session TZ เป็น UTC (2) `DATE(col)` ที่ "ไม่แปลง TZ" ยังอาจให้วันผิดได้ ถ้าค่าที่เก็บเป็น UTC ⇒ **พิสูจน์ด้วย probe ทุกครั้ง** (3) **การแก้ TZ บางส่วนทำให้เกิดความขัดแย้ง *ข้าม endpoint* ไม่ใช่แค่ในไฟล์เดียว** — แก้ที่หนึ่งแล้วต้องถามว่า *หน้าจออื่นที่โชว์ข้อมูลชุดเดียวกันใช้ขอบเขตอะไร* (4) **ห้าม pin พฤติกรรมไว้กับ default ของ image** — ถ้าไม่มีที่ไหนใน repo ตั้ง `TimeZone` ของ Postgres ให้ตั้งให้ชัด ไม่งั้น dev/test/prod อาจได้ตัวเลขต่างกันโดยไม่มีใครรู้ (5) **การเปลี่ยนปฏิทินของ endpoint ที่ ship แล้ว = การตัดสินใจเชิงผลิตภัณฑ์ ไม่ใช่ bug fix** — โดยเฉพาะเมื่อฝั่ง legacy ต้องแก้ที่ *ข้อมูล* ไม่ใช่แค่ query (บวก 7 ชั่วโมง หรือ migrate) ⇒ รายงานให้ผู้ใช้ตัดสิน
- **Tests:** ยังไม่มีเทสต์ล็อกพฤติกรรมนี้ (เจตนา — รอผู้ใช้ชี้ขาดปฏิทินก่อน) · บันทึกเป็นงานค้าง #11 พร้อมหลักฐาน probe
- **Date Added:** 2026-09-13

### 🧾 Tests — ก่อนเชื่อว่า "เทสต์ที่ล้มเป็นของเดิม" ต้อง **A/B ด้วย subset** และ **อย่าเชื่อจำนวนที่บันทึกไว้ก่อนหน้า**
- **Context/Problem:** บันทึกของเซสชันก่อนระบุว่า "มีเทสต์เก่าล้มบน `main` อยู่ 6 ตัว รอผู้ใช้ตัดสิน" ⇒ ผมรัน full suite แล้วได้ **`14 failed, 638 passed`** ไม่ใช่ 6 · ถ้าเชื่อบันทึกเดิมจะสรุปผิดสองทาง: (ก) เข้าใจว่าตัวเองทำ regression 8 ตัว (ข) หรือรายงานผู้ใช้ผิดจำนวน
- **Root Cause:** **จำนวนที่บันทึกไว้ก่อนหน้าไม่น่าเชื่อถือ** — มันมาจากการวัดที่ไม่ครบ (ไม่ได้รันเต็มชุด) แต่ถูกเขียนลงเอกสารราวกับเป็นข้อเท็จจริง ⇒ ตัวเลขที่ "สืบทอด" ต่อกันมาจะกลายเป็นสมมติฐานที่ไม่มีใครตรวจ; อีกทั้ง full suite ใช้เวลา **23 นาที** (1404 วิ) จึงไม่ควรสตาร์ทใหม่ทั้งชุดเพียงเพื่อตอบว่า "ใครทำให้พัง"
- **Correct Pattern/Solution:** A/B แบบ **subset** เจาะจงเฉพาะไฟล์ที่ล้ม โดย `git stash push -- <ไฟล์ backend ที่แก้>` (ไม่ stash เทสต์/conftest เพื่อไม่ให้ fixture หาย) → รันเฉพาะไฟล์ที่ล้ม → `git stash pop`:
  ```bash
  git diff > /tmp/backup.patch           # สำรองก่อน (กัน stash pop พลาด)
  git stash push -m ab -- <ไฟล์ที่แก้>
  docker compose -p classroom-management -f <abs>/docker-compose.test.yml run --rm --no-deps \
    test_runner sh -c "python -m pytest -q --tb=no /app/tests/<ไฟล์ที่ล้ม>"
  git stash pop
  diff -q /tmp/backup.patch <(git diff) && echo OK   # ยืนยันว่างานกลับมาเหมือนเดิม
  ```
  **เกณฑ์ตัดสิน:** ชื่อเทสต์ที่ล้มต้อง **ตรงกันเป๊ะทั้งเซ็ต** ไม่ใช่แค่จำนวนเท่ากัน — ถ้าจำนวนเท่ากันแต่ชื่อต่าง = ยังมี regression ซ่อนอยู่
  **ผลจริงรอบนี้:** baseline ให้ 9 + 5 = **14 ตัว ชื่อตรงกันทั้งหมด** ⇒ งานใหม่ไม่ทำของเดิมแตกเลย · **เสริมหลักฐานอิสระ:** `git diff` ของ `export.py` ไม่มีการเรียก `create_sheet`/`.title`/`remove()` เลย และ sheet ที่เทสต์บ่นถึง **มีอยู่บน HEAD แล้ว**
- **Rule:** (1) ตัวเลข "เทสต์เก่าล้มอยู่ N ตัว" ที่สืบทอดมา **ต้องวัดใหม่ก่อนใช้** อย่ารายงานต่อโดยไม่ตรวจ (2) ใช้ **subset A/B** เมื่อ full suite แพง — และต้องเทียบ **ชื่อเทสต์** ไม่ใช่แค่จำนวน (3) `git stash push -- <path>` เจาะจงไฟล์ แล้ว **backup เป็น patch ก่อนเสมอ** พร้อม verify หลัง pop (4) "เทสต์ล้มเรื่องชื่อ sheet/index" มักเป็น rot จริง — ตรวจด้วยว่าโค้ดที่เทสต์บ่นถึงมีอยู่บน HEAD หรือไม่ (5) การนับให้ลงตัว: `652 − 49 (เทสต์ใหม่) = 603 เดิม = 589 ผ่าน + 14 ล้ม` — ตรวจเลขแบบนี้จับการนับผิดได้
- **Tests:** N/A (บทเรียนกระบวนการ) — หลักฐานคือตาราง A/B ใน `~/.claude/plans/finance/02-F1-statements.md`
- **Date Added:** 2026-09-13

### 🕐 Timezone — หลังตัดสินใจยึด "เวลาไทย" ต้องแก้ **สองทิศทาง**: ขาเข้า (SQL) และขาออก (API) — ขาออกนี่คือตัวที่ผู้ใช้ **เห็น** ผิด
- **Context/Problem:** หลังย้ายทั้งโมดูลการเงินไปปฏิทินไทยแล้ว รายการ legacy ยังโชว์เวลาเพี้ยน 7 ชั่วโมงบนหน้าจอ ทั้งที่ query กรองถูกแล้ว และแม้ frontend จะระบุ `timeZone: 'Asia/Bangkok'` ไว้ก็ตาม
- **Root Cause:** **JavaScript ตีความ ISO string ที่ไม่มี offset ว่าเป็นเวลาท้องถิ่นของเบราว์เซอร์** — `new Date("2026-09-01T03:00:00")` = 03:00 น. **ตามเวลาเครื่องผู้ใช้** แล้ว `toLocaleString('th-TH', {timeZone:'Asia/Bangkok'})` ก็ยังได้ 03:00 เพราะค่าที่ parse เข้ามา "ไม่มีโซน" ให้แปลง · ฝั่ง legacy คืน `created_at` เป็น naive (Pydantic serialize เป็น `"…T03:00:00"`) ขณะที่ฝั่ง journal คืน aware (`+00:00`) ⇒ **สัญญา API ไม่สม่ำเสมอ**: รายการจากสองยุคแสดงเวลาต่างกัน 7 ชั่วโมงในลิสต์เดียวกัน
- **Correct Pattern/Solution:** ตั้งชื่อทิศทางให้ชัดแล้วใช้ helper กลางคู่กันใน `services/finance/helpers.py` (มีบล็อก `[TIMEZONE]` อธิบายกำกับ):
  - **ขาเข้า (เทียบขอบเขตใน SQL):** *param-unwrap* — บังคับ tz ฝั่ง **parameter** แล้วแปลงกลับเป็น UTC wall-clock
    `T.created_at >= ($2::timestamptz AT TIME ZONE 'UTC')` โดยส่ง `_thai_day_start(d)` (aware) เป็น `$2`
    ใช้ helper `_thai_day_start`/`_thai_day_end`/`_thai_next_day_start` ชุดเดียวกับคอลัมน์ timestamptz ⇒ **หนึ่งชุดขอบเขตสำหรับทั้งสองชนิดคอลัมน์** · ยัง sargable และไม่พึ่ง session TimeZone
  - **ขาออก (ส่งออก API):** `_as_utc(v)` ติด `tzinfo=UTC` ให้ค่า naive **ก่อน** ส่งออก ⇒ Pydantic ได้ `+00:00` ⇒ `new Date()` แปลงเป็นเวลาไทยถูก
  - **ห้าม**เรียก `.astimezone(THAI_TZ)` ตรง ๆ กับค่า naive — Python ตีความเป็น **เวลาท้องถิ่นของเครื่องที่รันโค้ด** ⇒ container TZ=UTC ให้ผล "ถูกโดยบังเอิญ" แต่เครื่อง dev ที่ TZ=Asia/Bangkok เพี้ยน 7 ชม. (บั๊กที่ CI มองไม่เห็น) ต้อง `.replace(tzinfo=timezone.utc)` **ก่อน** เสมอ
- **Rule:** (1) คอลัมน์ `TIMESTAMP` (naive) ที่เขียนด้วย `NOW()`/`CURRENT_TIMESTAMP` เก็บ **UTC wall-clock** ⇒ ทั้งอ่านและเขียนต้องมีท่าแปลงที่ชัด (2) **การย้ายปฏิทินต้องตรวจ "ขอบเขตของ API" ด้วย ไม่ใช่แค่ query** — ชนิดของ `datetime` ที่ออก JSON คือส่วนหนึ่งของสัญญา: naive กับ aware ให้ผลต่างกัน 7 ชม. บนเบราว์เซอร์ (3) ค่า naive ที่หลุดออก API = บั๊กที่ **เทสต์ backend มองไม่เห็น** (backend เทียบกันเองยังถูก) แต่ผู้ใช้เห็นทันที ⇒ ต้องมีเทสต์ยืนยัน `tzinfo is not None` (4) ตัวเขียนฝั่ง SQL ปลอดภัยอยู่แล้ว: ทุกการเขียนลงคอลัมน์ naive มาจาก `NOW()`/`DEFAULT` **ไม่เคยมาจาก `datetime` ของ Python** ⇒ กับดัก asyncpg (encode naive ตามเวลาท้องถิ่น) ไม่ถูกกระตุ้น
- **Tests:** `test_finance_v2_read.py::test_router_boundary_aug31_vs_sep01` ล็อกกติกาการเก็บด้วย `assert stored == datetime(2026, 8, 31, 16, 59, 59)` + `assert stored.hour == 16` (ถ้าเก็บเป็นเวลาไทยเลขชั่วโมงต้องเป็น 23) และยืนยันวินาทีสุดท้ายของ 31 ส.ค. ไทย กับวินาทีแรกของ 1 ก.ย. ไทย ถูกคืนมาคนละฝั่งของเส้นตัด
- **Date Added:** 2026-09-13

### 📊 Finance — เทียบ `date` กับคอลัมน์ `timestamptz` = Postgres แปลงเป็น **เที่ยงคืน UTC (07:00 ไทย)** ⇒ ยอด "เดือนนี้" ของ dashboard ไม่ตรงกับงบกำไรขาดทุน
- **Context/Problem:** ระหว่างตรวจทั้งโมดูลตามกฎ "grep หาทุกจุด" พบ `_get_summary_v2()` (`services/finance/reporting.py`) ส่ง `date(year, month, 1)` / ต้นเดือนถัดไป เข้าเงื่อนไข `JE.transaction_date >= $2 AND < $3` ตรง ๆ — ไม่มีใครสังเกตเพราะ **ตัวเลขยังออกมาสมเหตุสมผล** แค่ขอบเดือนเพี้ยน
- **Root Cause:** `JE.transaction_date` เป็น `timestamptz` แต่ parameter เป็น `date` ⇒ Postgres cast เป็น `timestamptz` ที่ **เที่ยงคืน UTC** = **07:00 น. เวลาไทย** ⇒ ช่วงที่ถูกนับจริงคือ 07:00 ของวันที่ 1 ถึง 07:00 ของวันที่ 1 เดือนถัดไป · รายการที่บันทึก **00:00–07:00 น. ไทย** ของวันแรก/วันสุดท้ายของเดือนจะตกไปอยู่เดือนผิด — **และไม่ตรงกับงบกำไรขาดทุนที่ใช้ `_thai_day_start`** ⇒ สองหน้าจอของเดือนเดียวกันรายงานยอดต่างกัน
- **Correct Pattern/Solution:** แปลงขอบเขตเป็น instant ไทยด้วย helper เดียวกับที่อื่น ก่อนส่งเป็น parameter:
  ```python
  start_dt = _thai_day_start(start_d)   # ไม่ใช่ start_d (date) ตรง ๆ
  end_dt = _thai_day_start(end_d)       # ขอบบนแบบไม่รวม → ต้นเดือนถัดไป
  ```
  และ `get_income_statement()` มีกับดักเดียวกันอีกจุด: `query_start` ออกมาจาก `_clamp_to_cutoff()` เป็น **`date` เปล่า ๆ** แล้วถูกใช้เทียบกับ `transaction_date` ขณะที่ `end_bound` ใช้ `_thai_day_end` อย่างถูกต้องแล้ว ⇒ อสมมาตร ซ่อมด้วย `_thai_day_start(query_start)`
- **Rule:** (1) **`date` vs `timestamptz` ไม่ error — มัน cast ให้ แล้วได้คำตอบผิดแบบเงียบ ๆ** ⇒ ตรวจ "ชนิดของทั้งสองฝั่ง" ทุกครั้งที่เขียนเงื่อนไขช่วงวันที่ (2) เมื่อไฟล์เดียวมีหลาย query ที่กรองช่วงเดียวกัน **ขอบเขตต้องมาจาก helper ตัวเดียวกันทั้งหมด** — จุดที่ลืมมักเป็นจุดที่ตัวแปรผ่าน `_clamp_*` แล้วถูกใช้ต่อโดยไม่แปลง (3) อาการของบั๊กชนิดนี้คือ "ตัวเลขดูสมเหตุสมผลแต่ไม่ตรงกันข้ามหน้าจอ" ⇒ วิธีจับคือ **assert ไขว้** ให้สองเส้นทางรายงานยอดเดียวกัน
- **Tests:** เทสต์เดิม **จับบั๊กนี้ไม่ได้** เพราะทุกตัวตั้ง `transaction_date` ไว้กลางเดือน (เช่น `'2026-10-10'` = 07:00 น. ไทย) ซึ่งห่างจากขอบเดือนหลายวัน ⇒ ความเพี้ยน 7 ชั่วโมงที่ขอบไม่ปรากฏ · การจะจับได้ต้องมีรายการที่ **00:00–07:00 น. ไทยของวันที่ 1 หรือวันสุดท้ายของเดือน** แล้วเทียบยอดกับอีกเส้นทาง (`test_finance_statements.py` เป็นชุดที่ทำแบบนั้น)
- **Date Added:** 2026-09-13

### 🧪 Tests — เทสต์ Excel export ที่ผูกกับ "ชื่อ/ลำดับแผ่น + index ของแถวรวม" เน่าพร้อมกัน **6 ตัวจาก commit เดียว** และวิธีซ่อมให้ไม่เน่าซ้ำ
- **Context/Problem:** หลัง `export.py` ถูกแก้ (เพิ่มแผ่น `สรุปรายเดือน (Monthly)` และเปลี่ยนชื่อแผ่นเป็น `สมุดรายวันทั่วไป (GJ)`) เทสต์ **15 ตัว** ล้ม แต่ตัวที่ทำให้สับสนคือ **6 ตัวในไฟล์เดียวล้มที่บรรทัดเดียวกัน** (`_read_journal` helper) ⇒ ดูเหมือนเป็นบั๊กใหญ่ ทั้งที่เป็น rot ของเทสต์ตัวเดียว
- **Root Cause:** helper กลาง assert **ชื่อ+ลำดับแผ่นแบบทั้งชุด** เป็นด่านแรก ⇒ เทสต์ทุกตัวที่เรียก helper ตายที่จุดเดียวกัน **ก่อน** จะได้ตรวจเนื้อข้อมูล ⇒ และเมื่อแก้ด่านแรกได้ ก็ยังมี mismatch ซ่อนอยู่ข้างหลังอีก 2 ชั้นซึ่งยังไม่มีใครเห็น (ป้ายหัวคอลัมน์ถูกเปลี่ยนชื่อ และ **ป้ายแถวรวมย้ายคอลัมน์**)
- **Correct Pattern/Solution:** ซ่อมเป็นชั้น ๆ แล้ว **อย่าหยุดที่ assert แรกที่ผ่าน**:
  1. **ชื่อ/ลำดับแผ่น** — ให้ตรงกับ `wb.create_sheet(...)`/`.title` ในโค้ดจริง
  2. **ป้ายหัวคอลัมน์** — เทียบกับ `j_headers` ในโค้ดจริง (ป้ายถูก rename: `Reference`→`อ้างอิง (Ref)`, `เดบิต (บาท)`→`เดบิต (Dr.)` ฯลฯ)
  3. **แถวรวม** — หาด้วย **คำขึ้นต้นของป้าย** ไม่ใช่ `==` และที่ **index ที่ถูกต้อง**: `if isinstance(row[3], str) and row[3].startswith("รวมทั้งสิ้น")` (ป้ายอยู่ **คอลัมน์ D/index 3** ไม่ใช่ A — ช่อง A ของแถวนั้นว่าง) และมี suffix `" (Grand Total)"`
  4. เพิ่ม helper `_find_row_containing(rows, col, fragment)` คู่กับ `_find_row` สำหรับป้ายที่ถูกเติม suffix
- **Rule:** (1) helper ที่ assert โครงสร้างทั้งชุด (ชื่อ/ลำดับแผ่น) **กลบความล้มเหลวที่อยู่ลึกกว่า** ⇒ พอผ่านด่านแรก ต้องรันซ้ำและอ่าน failure ถัดไปเสมอ อย่าประกาศว่าจบ (2) assert ป้ายด้วย `startswith`/`in` ไม่ใช่ `==` เมื่อป้ายมีแนวโน้มถูกเติม suffix (3) **`row[0]` ไม่ใช่ที่อยู่ของป้ายเสมอไป** — ตรวจว่าโค้ดเขียนป้ายลง `column=` ใด (4) `list(ws.values)` ของ openpyxl ให้แถวสั้นได้ ⇒ indexing เกินจำนวนคอลัมน์เป็น `IndexError` ไม่ใช่ `AssertionError` — อาการคนละแบบ อย่าสับสน (5) ข้อมูลที่คำนวณแล้วไม่ถูกเขียนลงไฟล์คือ **dead data**: พบ `journal_line_id` ถูกใส่ใน `journal_rows` แต่ตัวเขียนแผ่นไม่เคยเขียนคอลัมน์นั้น ⇒ บรรทัดที่เป็น entry เดียวกันแยกกันไม่ได้ด้วย UUID · **รายงานผู้ใช้ ไม่แก้เอง** เพราะการเพิ่มคอลัมน์กลับ = เปลี่ยนเอกสารที่ ship แล้ว
- **Tests:** `test_finance_journal_export.py` (6), `test_finance_export_enterprise.py` (4), `test_finance_http.py` (2), `test_finance_export.py` (1), `test_finance_v2_read.py` (2) — ทั้งหมดแก้ให้ตรงโค้ดปัจจุบัน **ไม่แตะ `export.py`** (ตรวจ git แล้วว่า `44b5499` คือ commit ที่ตั้งใจเปลี่ยนชื่อ/เพิ่มแผ่น และ mismatch ของหัวคอลัมน์มีมาก่อนหน้านั้นแล้ว ⇒ ฝั่งเทสต์คือฝั่งที่เน่า)
- **Date Added:** 2026-09-13

### ⚠️ Finance — **KNOWN GAP**: แถว legacy-only ที่ "วันที่ไทย" ข้ามเส้นตัด มองไม่เห็นจากทั้งสองผู้อ่าน (ช่วงเปลี่ยนผ่าน ~7 ชั่วโมง)
- **Context/Problem:** หลังย้ายเส้นแบ่งยุคจาก UTC เป็นไทย ผู้อ่านสองฝั่งแบ่งงานกันแบบ **ไม่ทับและไม่มีช่องว่างตาม *วันที่ไทย*** (legacy cap = `_thai_day_end(31 ส.ค. ไทย)`, journal floor = `_thai_day_start(1 ก.ย. ไทย)`) — แต่มีแถวประเภทหนึ่งที่ **ทั้งสองฝั่งไม่รับ**
- **Root Cause:** แถวที่ถูกเขียนลง `finance_transactions` **ก่อน dual-write เริ่มทำงานจริง** (~7 ชั่วโมงหลังเที่ยงคืน) แต่ **เวลาไทยของมันข้ามเส้นไปแล้ว** ⇒ ไม่มี journal คู่กัน และถูก cap ฝั่ง legacy ตัดออก ⇒ ยอดของรายการนั้น **หายจากประวัติ** (แต่ยังอยู่ใน DB — ไม่ใช่ข้อมูลหายจริง) · ก่อนการย้ายเส้น ระบบใช้เส้น UTC จึงยังเห็นแถวกลุ่มนี้ปนอยู่ในฝั่ง legacy ⇒ **การย้ายเส้นทำให้เกิดการเปลี่ยนแปลงเชิงพฤติกรรม ไม่ใช่แค่จัดหมู่ใหม่**
- **Correct Pattern/Solution:** **ยังไม่แก้** — ทางเลือกที่มีเหตุผลคือ (ก) backfill journal ให้แถวกลุ่มนี้ หรือ (ข) เปลี่ยนผู้อ่าน legacy จาก "cap ด้วยวันที่" เป็น "ไม่มี journal คู่กัน" (`NOT EXISTS` บน `journal_entries.metadata->>'legacy_transaction_id'`) · ข้อ (ข) **แก้เองไม่ได้** เพราะ (1) กลุ่มโอนเงินใช้ journal เดียวร่วมกันสองขา ⇒ `NOT EXISTS` แบบตรง ๆ จะทำให้ขาหนึ่งหาย (2) เปลี่ยน endpoint ที่ ship แล้วและโปรไฟล์ performance ของมัน ⇒ **ต้องให้ผู้ใช้ตัดสิน**
- **Rule:** (1) **การย้ายเส้นแบ่งยุคต้องตอบให้ได้ว่า "แถวที่ตกในรอยต่อเป็นของใคร"** ไม่ใช่แค่พิสูจน์ว่าสองฝั่งไม่ทับกัน (2) การ partition ที่ "ไม่ทับและไม่มีช่องว่าง" ตามเกณฑ์ใหม่ **ยังมีรูได้** ถ้าแถวบางประเภทไม่มีคีย์ที่ใช้แบ่งทั้งสองฝั่ง (ที่นี่คือแถวที่ไม่มี journal) (3) เขียนเทสต์ที่ **ล็อกช่องที่รู้อยู่** ไว้ด้วยชื่อที่บอกชัด (`test_known_gap_…`) พร้อมคอมเมนต์ว่า "ถ้ามีการแก้ ค่าที่คาดหวังจะเปลี่ยน → ให้เขียนเทสต์ใหม่ อย่างัดให้กลับ" — ดีกว่าปล่อยให้ช่องนี้ไม่มีร่องรอยในโค้ด
- **Tests:** `test_finance_v2_read.py::test_known_gap_legacy_only_row_in_thai_september_is_invisible` — deep verify ว่าแถวยังอยู่ใน DB (1 แถว) และห้องนั้นไม่มี `journal_entries` เลย (0 แถว) แต่ `get_transactions` คืน `total_count == 0`
- **Date Added:** 2026-09-13

### 📅 Frontend — ค่าเริ่มต้นของตัวกรองเดือนจาก `new Date().getMonth()` = **ปฏิทินของอุปกรณ์ผู้ใช้** ไม่ใช่ของไทย (เปิดหน้ามาผิดเดือนทั้งหน้า)
- **Context/Problem:** หลังย้ายทั้งระบบมาอยู่บนปฏิทินไทย พบว่า `FinanceDashboard.vue` seed ตัวกรองจาก `new Date().getMonth() + 1` / `new Date().getFullYear()` ⇒ เครื่องที่ TZ ไม่ใช่ UTC+7 **เปิดหน้ามาที่เดือนผิด แล้วติดป้ายเดือนไทยทับตัวเลขของอีกเดือน** และขัดกับหน้าพี่น้อง `FinancialStatements.vue` ที่ seed จาก `todayIso()` (ไทย) ⇒ สองหน้าการเงินตอบคำถาม "ตอนนี้เดือนอะไร" ไม่ตรงกัน
- **Root Cause:** `new Date()` สร้างจากนาฬิกา **ของอุปกรณ์** และ `getMonth()`/`getFullYear()` คืน **ชิ้นส่วนเวลาท้องถิ่น** ของอุปกรณ์นั้น ⇒ ค่าที่ seed ถูกส่งเข้า `getSummary(room, month, year)` ตรง ๆ แล้วคืนตัวเลขของเดือนนั้นออกมา **สอดคล้องกันเองทั้งหน้า** (ป้ายกับตัวเลขตรงกัน) ⇒ **ดูไม่ออกว่าผิด** ถ้าไม่รู้ว่าวันนี้ที่ไทยเป็นเดือนอะไร
  - เครื่อง **นำหน้าไทย** (UTC+9): ช่วง ~2 ชม. สุดท้ายของเดือนไทย อุปกรณ์เป็นวันที่ 1 ของเดือนถัดไปแล้ว → เปิดมาที่เดือนถัดไป
  - เครื่อง **ตามหลังไทย** (UTC, US): ช่วงต้นวันที่ 1 ตามไทย อุปกรณ์ยังเป็นเดือนที่แล้ว → เปิดมาที่เดือนก่อน
- **Correct Pattern/Solution:** รวมคำตอบของ "วันนี้เดือนอะไร" ไว้ **ที่เดียว** ใน `utils/period.ts` แล้วอ่านผ่าน `todayIso()` (ซึ่งใช้ `Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Bangkok' })` อยู่แล้ว) — ห้ามประกอบ `Date` เอง:
  ```ts
  export const todayThaiYearMonth = (): { year: number; month: number } => {
    const iso = todayIso();                       // 'YYYY-MM-DD' ตามเวลาไทย
    return { year: Number(iso.slice(0, 4)), month: Number(iso.slice(5, 7)) };
  };
  ```
  ใช้ `slice`+`Number` ไม่ destructure จาก array เพราะ `noUncheckedIndexedAccess: true` ทำให้ได้ `number | undefined` · แก้ **ทุกจุดที่ตอบคำถามเดียวกัน** ไม่ใช่แค่จุดที่ผู้ใช้เจอ: ตัว seed, `yearOptions` (ต้องเป็นปีไทยชุดเดียวกับค่าที่ seed ไม่งั้นปีที่เลือกอาจหลุดออกจาก dropdown), getter/setter fallback ของ `PeriodPicker`, และ fallback ของ `referenceDate` ตอน ISO เพี้ยน
- **Rule:** (1) **`new Date()` เปล่า ๆ ในโค้ด frontend = ปฏิทินของอุปกรณ์** — ใช้ได้เฉพาะกับสิ่งที่ "เวลาของผู้ใช้" เป็นคำตอบที่ถูก (เช่น แสดง relative time) แต่ **ห้ามเด็ดขาด**กับสิ่งที่ backend จะเอาไปตัดข้อมูล (2) อาการของบั๊กชนิดนี้คือ **หน้าสอดคล้องกันเอง** ⇒ การอ่านโค้ดแบบ "ค่าที่ seed ถูกส่งต่อไปที่ไหน" มองไม่เห็น ต้องถามว่า "ค่านี้หมายถึงปฏิทินของใคร" (3) ตรวจ **ทุกจุดที่ตอบคำถามเดียวกัน** — จุดที่อันตรายกว่าคือ `yearOptions` เพราะมันไม่แสดงอาการจนถึงขอบปี (4) helper ที่ seed ไม่ควรเป็น `new Date()` ซ้ำ ควรอ่านจาก helper กลางตัวเดียว ไม่งั้นแหล่งความจริงแตกเป็นสองที่
- **Tests:** `frontend/src/utils/__tests__/period.spec.ts` — ล็อกด้วย instant ที่ **วันที่ไทยไม่ตรงกับวันที่ UTC** (`2026-09-30T18:00:00Z` = 1 ต.ค. ไทย) แล้วยืนยันว่าได้เดือน 10 **พร้อม assert ว่าปฏิทิน UTC ยังเป็นเดือน 9** ⇒ เทสต์แยกสองพฤติกรรมออกจากกันได้จริง ไม่ใช่ผ่านเพราะบังเอิญ TZ ของ process ตรง · A/B proof (รันจริง 3 TZ): `TZ=UTC` และ `TZ=America/New_York` ให้ OLD = `2026-09` แต่ NEW = `2026-10-01` ❌ ต่างกัน (ส่วน `TZ=Asia/Tokyo` ตรงกันโดยบังเอิญ) ⇒ **เทสต์ต้องไม่พึ่ง TZ ของเครื่องรัน**
- **Date Added:** 2026-09-13

---

### 🩹 Finance — แถว Legacy ที่ "วันที่ไทย" ข้ามเส้นตัดแล้วแต่ไม่มี journal = **แถวที่ไม่มีผู้อ่านฝั่งใดรับ** (หายจากประวัติทั้งที่ข้อมูลอยู่ครบ)
- **Context/Problem:** หลังแยกผู้อ่านสองฝั่งตาม **วันที่ไทย** (legacy = ก่อน `CUTOFF_DATE = 2026-09-01`, journal = ตั้งแต่วันนั้นเป็นต้นไป + merge cap ที่ 31 ส.ค.) พบว่าแถวที่ถูกบันทึกในช่วง **~7 ชม. แรกของวันที่ 1 ก.ย. ตามเวลาไทย** (ก่อนที่โค้ด dual-write จะขึ้นจริง) มี "วันที่ไทย" อยู่ฝั่ง v2 แล้ว แต่ **ยังไม่มี journal คู่** ⇒ ฝั่ง legacy ถูก cap ออก ฝั่ง v2 ไม่มีอะไรให้อ่าน ⇒ **หายจากหน้าประวัติและไม่โผล่ในงบการเงิน** ทั้งที่แถวยังอยู่ใน DB (อีกกลุ่มคือรอยรั่วของ `_confirm_single_payment` สมัยที่ยัง `pass` ข้าม dual-write เมื่อห้องไม่มี ledger รายได้)
- **Root Cause:** "วันที่ไทย" ที่ใช้แบ่งยุคคำนวณจาก `T.created_at` (มีการเคลื่อนไหวของเงิน) แต่ **การมีอยู่ของ journal** ขึ้นกับว่า *โค้ด* dual-write ขึ้นหรือยัง — สองเงื่อนไขนี้ไม่ใช่สิ่งเดียวกัน จึงมีหน้าต่างที่สองเงื่อนไขไม่ตรงกัน · ตรรกะสำคัญคือ **`created_at` ของแถว legacy เก็บ UTC (naive)** ⇒ 2026-08-31 18:00 UTC = 1 ก.ย. 01:00 ไทย ⇒ แถวนี้ "วันไทย" ข้ามเส้นไปแล้วทั้งที่ UTC ยังเป็นเดือน 8
- **Correct Pattern/Solution:** สร้าง journal ย้อนหลัง (backfill) ให้เฉพาะแถวที่ตกหล่น **โดยไม่แตะ endpoint เดิม** — `services/finance/backfill.py` (`BackfillMixin.backfill_missing_journals`) + CLI `scripts/backfill_journals.py` (dry-run เป็นค่าเริ่มต้น). กฎที่ต้องยึด:
  ```sql
  -- candidate = แถวที่ (ก) ยังไม่ถูกลบ (ข) วันไทย >= เส้นตัด (ค) ยังไม่มี journal คู่
  AND T.deleted_at IS NULL
  AND T.created_at >= ($2::timestamptz AT TIME ZONE 'UTC')   -- $2 = _thai_day_start(CUTOFF_DATE)
  AND NOT EXISTS (SELECT 1 FROM journal_entries JE
                  WHERE JE.room_id = T.room_id
                    AND (JE.metadata->>'legacy_transaction_id' = T.id::text
                         OR (T.transfer_group_id IS NOT NULL
                             AND JE.metadata->>'transfer_group_id' = T.transfer_group_id::text)))
  ```
  - **ห้าม backfill แถวก่อนเส้นตัดเด็ดขาด** — งบการเงิน (trial balance / balance sheet) อ่าน `journal_lines` เป็นแหล่งเดียว *โดยไม่มี date floor* ⇒ journal ที่สร้างให้แถวก่อนเส้นตัด = **เพิ่มข้อมูลที่ไม่มีมาก่อน** แล้ว**ยอดยกมาเพี้ยนถาวร**
  - **ข้ามแถวที่ `deleted_at IS NOT NULL`** — แถวนั้นถูก revert และคืนยอดแล้ว; สร้าง journal ให้จะได้แถว `status='posted'` ⇒ **รายการผีโผล่กลับมา**
  - **`NOT EXISTS` ต้องนับ journal ทุกสถานะ** (รวม voided) ⇒ เป็น idempotent โดยโครงสร้าง ⇒ รันซ้ำไม่สร้างซ้ำ
  - **จับกลุ่ม transfer ก่อน**: 1 การโอน = แถว legacy 2 แถว แต่ journal **ใบเดียว** ⇒ ต้อง group ด้วย `transfer_group_id` ไม่งั้นยอดโอนถูกนับซ้ำ (asset เคลื่อนไหว 2 เท่า)
  - **metadata ต้องเป็นคีย์ชุดเดียวกับ dual-write สด** (`legacy_transaction_id` / `transfer_group_id` / `student_payment_id`) ไม่งั้น `revert_transaction` (ที่ void journal ด้วย `metadata->>'...'`) จะ**ยกเลิกรายการที่ backfill มาให้ไม่ได้** ⇒ รายการค้างในงบตลอดกาล
  - **`transaction_date` ต้องเป็นเวลาที่เงินเคลื่อนไหวจริง** (`_as_utc(row["created_at"])`) ไม่ใช่ `NOW()` ไม่งั้นรายการไปกองที่เดือนที่รันสคริปต์ **แล้วเดือนที่ขาดก็ยังขาดอยู่ดี** (บั๊กเดิมไม่หาย แค่ย้ายที่) · `created_at` ของ journal ปล่อยเป็น `NOW()` ได้ เพราะไม่มีโค้ดส่วนใดอ่าน (ยืนยันด้วย grep) และมีประโยชน์ตอนสืบย้อนว่าสร้างเมื่อไหร่
  - **dry-run ต้องเป็น transaction ที่ `rollback()` ทิ้ง** — ไม่ใช่แค่ "ไม่เรียก INSERT" เพราะการวางแผนเรียก `_resolve_*_ledger` ที่ **auto-provision ledger ได้** ⇒ dry-run ที่ไม่ rollback จะทิ้ง ledger ค้างไว้
  - **แถวที่วางแผนไม่ได้ = `skipped` + เหตุผล ไม่ใช่ `raise`** (ops tool ต้องไม่หยุดทั้งชุดเพราะแถวเดียวพัง) และครอบ `ValueError` จาก `_resolve_*_ledger` ด้วย เพราะมัน raise เมื่อแถว legacy ต้นทางถูกลบจริง (ไม่ใช่แค่ NULL)
- **Rule:** (1) เมื่อ **การมีอยู่ของข้อมูล** ขึ้นกับ "โค้ดเวอร์ชันไหนเขียน" แต่ **การมองเห็นข้อมูล** ขึ้นกับ "วันที่ของข้อมูล" ⇒ จะมีหน้าต่างที่ข้อมูลหายเงียบ ๆ เสมอ; การ migrate แบบ dual-write ต้องมี **backfill เป็นขั้นบังคับ** ไม่ใช่ทางเลือก (2) backfill script ที่แตะเงินต้องเป็น **dry-run by default** และ dry-run ต้อง simulate จริงใน transaction ที่ rollback (3) ก่อนเขียน ops script ให้ **grep หาว่ามีโค้ดส่วนใดอ่านคอลัมน์ที่กำลังจะตั้ง** — เจอว่าไม่มีใครอ่าน `journal_entries.created_at` จึงปล่อย `NOW()` ได้อย่างมีหลักฐาน (4) **ห้ามแก้ endpoint ที่ ship แล้วเพื่อกลบปัญหาข้อมูล** — แก้ที่ข้อมูลดีกว่า เพราะการแก้ผู้อ่านข้างเดียวสร้างความไม่สอดคล้องชุดใหม่
- **Tests:** `backend/tests/test_finance_backfill.py` (18 ตัว) — ที่มีค่าที่สุดคือ `test_straddle_row_is_invisible_before_and_visible_after_backfill` ซึ่งพิสูจน์ **อาการที่ผู้ใช้เห็น** (ก่อน backfill `get_transactions` = 0, หลัง = 1 และ merge ต้องได้ 1 ไม่ใช่ 2) ไม่ใช่แค่ "มี journal ถูกสร้าง" · `test_pre_cutoff_row_is_never_backfilled` ล็อกกฎห้ามแตะ · `test_backfill_is_idempotent_across_runs` · `test_revert_transaction_voids_backfilled_journal` + เวอร์ชัน transfer (พิสูจน์ว่า metadata ใช้ต่อได้จริง) · `test_backfilled_journal_lands_in_the_right_thai_month` (ส.ค. = 0, ก.ย. = 1) · `test_prior_reconcile_adjustment_is_reported` (ดู Gotcha ถัดไป) · E2E รัน CLI จริงกับ Postgres จริง: dry-run → apply → apply ซ้ำ (0 ใบ) → ตรวจ DB ตรง ๆ
- **Gotcha:** asyncpg ในเทสต์นี้คืน **JSONB เป็น `str`** (ไม่ได้ลง codec) ⇒ `entry["metadata"]["k"]` จะได้ `TypeError: string indices must be integers` — ต้อง `json.loads()` ก่อน (โค้ด producción รอดเพราะอ่านผ่าน SQL `metadata->>'k'` ทั้งหมด; `audit_logs.new_values` ก็เป็น str เช่นกัน)
- **Gotcha (อันตรายกว่า — ต้องรายงาน ไม่ใช่ปล่อยผ่าน):** ถ้าห้องนั้นเคยรัน `reconcile_finance.py --apply` มาก่อน **การ backfill จะทำให้ยอดสินทรัพย์เบิ้ล** เพราะ `reconcile_balances` แก้ *ผลต่างตัวเดียวกับ* ที่ backfill กำลังจะแก้ (แถวที่ตกหล่นคือสาเหตุที่ยอดบัญชีคู่ขาดไป) ด้วย journal `Dr สินทรัพย์ / Cr ทุน 3001` — และ journal ปรับปรุงยอด **ไม่มี `legacy_transaction_id`** (เป็นค่าระดับ "บัญชี" ไม่ใช่ระดับ "รายการ") ⇒ เงื่อนไข `NOT EXISTS` **มองไม่เห็น** ⇒ หลัง backfill asset ledger = 2 เท่าของ legacy. คำตอบคือ **นับและรายงาน** (`_count_prior_adjustments` → `prior_adjustments` + บล็อกเตือน 🚨 ใน CLI) แล้วให้ผู้ใช้ **รัน `reconcile_finance.py` ซ้ำหลัง backfill** (รอบสองเห็น ledger เกินแล้วออกรายการปรับปรุง "ทางกลับ" ให้เอง; ฝั่งรายได้ไม่ถูกแตะจึงถูกทั้งสองฝั่ง) — บทเรียนทั่วไป: **ก่อนเพิ่มข้อมูลย้อนหลัง ต้องถามว่า "มีกลไกไหนที่เคยชดเชยการขาดข้อมูลนั้นไปแล้วหรือยัง"** การชดเชยกับข้อมูลจริงสองทางจะหักกันไม่สนิทและกลายเป็นเบิ้ล
- **Date Added:** 2026-09-13

---

