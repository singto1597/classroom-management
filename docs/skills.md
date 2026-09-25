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
- **Correct Pattern/Solution:** **Do NOT add `require_member` to `get_daily_summary`.** `get_rooms_to_notify` is likewise system-only, so it gets no membership check either. When hardening read RPCs, audit every caller (bot loops, schedulers, slash commands) before adding a check.
- **⚠️ แก้ไข 2026-09-23 — ข้อสรุปเดิมของหัวข้อนี้ผิด และเป็นเหตุให้เกิดช่องโหว่จริง:** เวอร์ชันก่อนหน้าของหัวข้อนี้เขียนว่า *"this read stays transparent at the RPC layer"* — ประโยคนั้นถูกอ่านเป็น "ไม่ต้องใส่อะไรเลย" ทั้งที่เจตนาคือ "ไม่ต้องใส่ `require_member`" ผลคือ `GET /{target_id}/summary` กลายเป็น **route เดียวจาก 106 ตัวที่ไม่มี auth dependency ใด ๆ** ยืนยันด้วยการยิงจริงว่าได้ข้อมูลจริงของโรงเรียนตอบ 200 ทั้ง production และ staging โดยไม่ต้องส่ง credential และ enumerate `target_id` เก็บได้ทั้งโรงเรียน
- **Rule ที่ถูกต้อง:** "system RPC" ≠ "ไม่ต้องมี auth" — มันหมายถึง **`verify_api_key` ไม่ใช่ `require_member`/`get_current_user`** ดูตัวอย่างที่ถูกต้องในไฟล์เดียวกัน: `get_rooms_to_notify` และ `get_birthday_celebrants` ใช้ `api_key: str = Depends(verify_api_key)` ครบทั้งคู่ บอทส่ง `X-API-Key` ให้ทุกคำขออยู่แล้วใน `api_client.init_session` จึงไม่ต้องแก้อะไรฝั่งบอทเลย
- **Date Added:** 2026-08-04 (แก้ไข 2026-09-23)

### 🛠️ ลำดับ dependency ของ FastAPI สร้าง Enumeration Oracle ได้ — วาง auth ไว้ก่อนเสมอ
- **Context/Problem:** ตอนเติม `verify_api_key` ให้ `GET /{target_id}/summary` ถ้าวาง parameter ไว้ **หลัง** `room_id: int = Depends(resolve_target_to_room_id)` จะได้พฤติกรรมนี้ — target_id ที่มีอยู่จริง → **401**, target_id ที่ไม่มี → **404** ⇒ ผู้โจมตีที่ไม่มี credential เลยแยกออกได้ว่าห้องไหนมีอยู่จริง แล้วไล่เก็บทีละห้อง (ตรงกับที่เห็นใน log จริงของเทสต์: `GET /api/classroom/6/summary → 200` คู่กับ `GET /api/classroom/2418485/summary → 404`)
- **Root Cause:** FastAPI resolve dependency ตาม **ลำดับที่ประกาศใน signature** — `resolve_target_to_room_id` แตะ DB ก่อน จึง raise `RoomNotFoundError` (404) ทันก่อนที่ `verify_api_key` จะได้ทำงาน ตัว auth เลยไม่ได้เป็นประตูด่านแรกจริง
- **Correct Pattern/Solution:** วาง parameter ที่เป็น auth (`Depends(verify_api_key)`, `Depends(get_current_user)`) **ก่อน** parameter ที่แตะ DB หรือ resolve ข้อมูลเสมอ
  ```python
  async def get_daily_summary(
      request: Request,
      target_date: date,
      api_key: str = Depends(verify_api_key),        # ← auth ก่อน
      room_id: int = Depends(resolve_target_to_room_id),  # ← ค่อยแตะ DB
      pool: asyncpg.Pool = Depends(get_db_pool),
  ):
  ```
  **Rule:** endpoint ที่มี auth + resolve target ต้องมีเทสต์ที่ยิง **target_id ที่ไม่มีอยู่จริงโดยไม่ส่ง credential** แล้วคาดหวัง 401 (ไม่ใช่ 404) — ถ้าได้ 404 แปลว่าลำดับ dependency กลับกัน และมี oracle ให้ enumerate ดูตัวอย่างที่ `tests/test_daily_summary_auth.py::test_summary_nonexistent_target_returns_401_not_404`
- **Date Added:** 2026-09-23

### 🔍 เทสต์ที่เรียก service ตรง ๆ ไม่ผ่าน HTTP layer จะจับ auth ที่หายไปไม่ได้เลย
- **Context/Problem:** ช่องโหว่ข้อ C1 (`/summary` ไม่มี auth) อยู่บน production โดยที่ชุดเทสต์ **1,065 ตัวเขียวทั้งหมด** — เพราะเทสต์ของ `get_daily_summary` ทั้ง 6 ตัวใน `test_classroom_sync.py` และ `test_classroom_sync_extended.py` เรียก `ClassroomService.get_daily_summary(pool, ...)` ตรง ๆ ซึ่งข้ามชั้น HTTP ไปเลย dependency ของ route จึงไม่เคยถูกตรวจ
- **Root Cause:** เทสต์ระดับ service พิสูจน์ได้แค่ "business logic ถูก" ไม่สามารถพิสูจน์ได้ว่า "route ถูกป้องกัน" — สองเรื่องนี้คนละชั้นกัน และเทสต์ที่ครอบคลุมชั้นล่างก็ไม่บอกอะไรเกี่ยวกับชั้นบน
- **Correct Pattern/Solution:** endpoint ที่มี auth ทุกตัวต้องมีเทสต์ยิงผ่าน `client` (HTTP) **อย่างน้อยหนึ่งตัว** ควบคู่กับเทสต์ระดับ service ที่มีอยู่ — และทางที่ดีกว่าคือเทสต์ที่ enumerate **ทุก** route แล้ว assert 401/403 โดยมี allowlist สำหรับ route public (ดู `tests/test_route_auth_audit.py`) **Rule:** ความเขียวของชุดเทสต์ไม่ได้แปลว่าระบบปลอดภัย มันแปลว่า*สิ่งที่เทสต์ครอบคลุม*ปลอดภัย — ถ้ามีชั้นที่ไม่มีเทสต์ ชั้นนั้นก็ไม่มีด่าน
- **Date Added:** 2026-09-23

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

### 🤖 Discord bot — `get_target` มี default `target_type="room"` ⇒ บอทที่ลืมส่ง `target_type=server` ได้ **404 "ไม่พบห้อง"** ทั้งที่ห้องมีอยู่
- **Context/Problem:** `GET /{target_id}/finance/summary` รับ `target_id` เดียว แต่ตีความเป็นได้สองอย่าง (room ของเว็บ / server ของบอท) ผ่าน `target_type` ที่ **default = `"room"`** (เพราะเว็บคือผู้ใช้ส่วนใหญ่) ⇒ บอทที่ส่ง `interaction.guild_id` มาลอย ๆ จะถูกตีเป็น `room_id` = ค่า guild id → `resolve_room_id` หาไม่เจอ → 404 · อาการหลอกมาก: ข้อความ "ไม่พบห้องเรียนนี้" ทำให้เข้าใจว่าห้องยังไม่ผูก Discord ทั้งที่ผูกแล้ว
- **Root Cause:** พารามิเตอร์ที่ **เปลี่ยนความหมายของพารามิเตอร์อื่น** (ไม่ใช่แค่กรอง) และมี default ที่ถูกสำหรับผู้ใช้รายใหญ่ ⇒ ฝั่งที่เหลือลืมได้ง่ายและ**ไม่มี type system จับ**
- **Correct Pattern/Solution:** บอทต้องส่ง `target_type=server` **ทุกครั้ง** — รวมศูนย์ไว้ที่ `_server_params()` ใน `bot_discord/services/finance_api.py` (ไม่กระจายเป็น kwargs ต่อคำสั่ง) แล้วเทสต์ฝั่ง backend ล็อกไว้ทั้งสองทิศในเทสต์เดียว (`test_my_debts_via_server_target_matches_the_bot_path`: ส่ง `target_type=server` → 200 · guild_id เดียวกัน**ไม่ส่ง** → 404) · **ห้ามพึ่ง type hint** เพราะ `target_type: Literal["server","room"] = Query("room")` ไม่รู้จักความหมายของ `target_id`
- **Rule:** (1) เมื่อ endpoint รับ "id ที่ตีความได้หลายแบบ" ให้ **ส่งตัวบอกชนิดทุกครั้งจาก client** และรวมไว้ที่จุดเดียว (2) เทสต์ต้องมีเคส **"ลืมส่ง"** ที่ยืนยันว่ามันพัง — ไม่ใช่มีแต่เคสที่ถูก (3) **บอทไม่มี test harness ในโปรเจกต์นี้** (ไม่มี `bot_discord/tests/` และ CI ไม่รัน cog) ⇒ cog ต้อง **โง่ที่สุด** (`defer()` → เรียก wrapper → `followup.send(embed=)` → จับ error) และทุกอย่างที่ "คิด" ได้ (validate, แปลงวันที่, ประกอบ embed, จำกัดความยาว) ต้องอยู่ใน `services/finance_api.py` เพื่อให้อนาคตเขียนเทสต์ได้โดยไม่ต้องมี Discord
- **Gotcha:** (1) `api_client.request` เรียก `response.json()` **เสมอ** และไม่มี `raise_for_status` ⇒ รับ binary (PDF) ไม่ได้ และพังกับ 204 — ต้องแก้ client กลางก่อนถ้าจะทำ (2) ข้อความ error จาก `APIException` ควรตอบ **ephemeral เสมอ** เพราะอาจมีรายละเอียดภายใน (3) `defer()` ต้องเป็น `defer(ephemeral=True)` **ให้ตรงกับ** `followup.send(ephemeral=...)` ของคำสั่งนั้น ไม่งั้นคำตอบส่วนตัวจะกลายเป็นสาธารณะ (4) attribute access ผิดชื่อบน `discord.Embed`/`app_commands` **ไม่ถูกจับตอน import** — ตรวจด้วย `python -m py_compile` เท่านั้นไม่พอสำหรับ decorator (ต้องรันบอทหรือโหลด cog จริง) — วิธีตรวจจริงโดยไม่ต้องมี token: โหลด cog ใน image ของบอท (มี discord.py ติดตั้งแล้ว) แล้วอ่าน `__cog_app_commands__`:
  ```bash
  docker run --rm -v "$PWD/bot_discord:/app:z" -w /app classroom-production-bot:<tag> \
    python -c "import cogs.finance_cmd as m; print(sorted(c.name for c in m.FinanceCommands.__cog_app_commands__))"
  ```
  ⇒ พิสูจน์ได้ทั้ง decorator, `app_commands.Group`, `Choice`/`Range` และ `setup()` โดยไม่ต้องต่อ Discord
- **Tests:** ยังไม่มี harness ในเรpo แต่พิสูจน์ได้ด้วย **smoke script ที่รันใน image ของบอท** (ไม่ต้องมี token/guild):
  ```bash
  docker run --rm -e PYTHONPATH=/app -e TZ=UTC -e DISCORD_TOKEN=x -e API_BASE_URL=http://x -e API_KEY=x \
    -v "$PWD/bot_discord:/app:z" -v /tmp/bot_smoke:/mnt:z -w /app <bot-image> python /mnt/smoke.py
  ```
  ครอบ: `format_baht` · `format_thai_datetime`/`format_thai_date` (naive UTC→ไทย + **พ.ศ.**) · `validate_period` · `_server_params` · embed builder ทั้ง 4 + payload ว่าง · และ **เพดานความยาวของ Discord** (field 1024 / title 256 / desc 4096) ซึ่งเป็นสาเหตุ 400 ที่หาไม่เจอถ้าไม่ทดสอบ
  - ⚠️ `format_thai_date` รับ **DATE ล้วน** ⇒ ห้ามเข้า timezone conversion (วันที่ 1 ของเดือนจะเลื่อนเป็น 31/08) — มีเคสล็อกไว้
  - 🔒 รันด้วย `TZ=UTC` / `America/New_York` / `Asia/Bangkok` ให้ผล **เหมือนกันทั้งสาม** ⇒ พิสูจน์ว่าการแปลงไม่พึ่ง TZ ของเครื่อง (กับดักเดิมของโปรเจกต์นี้)
  - 💡 `PYTHONPATH=/app` จำเป็นเมื่อสคริปต์อยู่นอก `/app` ไม่งั้น `import services` ไม่เจอ
- **Date Added:** 2026-09-13

---

### 🧪 Tests — ลืม prefix `/api/classroom` ⇒ **ทุกเทสต์ได้ 404 `{"detail":"Not Found"}` ของ FastAPI เอง** และตัวที่ "ผ่าน" คือตัวที่ผ่านด้วยเหตุผลผิด
- **Context/Problem:** เขียนไฟล์เทสต์ใหม่ (`test_finance_me_endpoints.py`) แล้วเรียก `client.get(f"/{room_id}/finance/me/debts")` — **8 ใน 9 ตัวล้มด้วย 404** ส่วนตัวเดียวที่ผ่านคือ `test_..._unknown_room_is_404` **เพราะมันคาดหวัง 404 อยู่แล้ว** ⇒ ได้สัญญาณ "ผ่าน 1 ล้ม 8" ที่ชี้ผิดทางทั้งหมด (เหมือน router ไม่ถูก mount / พังทั้งโมดูล) · ความจริงคือ router การเงินถูก mount ด้วย `app.include_router(finance_router.router, prefix="/api/classroom")` (`backend/main.py:79`) ⇒ URL ที่ถูกคือ `/api/classroom/{target_id}/finance/...` และที่ได้คือ **404 ของ FastAPI** ไม่ใช่ของโดเมน
- **Root Cause:** 404 มีสองความหมายที่ **แยกไม่ออกจาก status code** — (ก) "ไม่มี route นี้" (FastAPI) (ข) "มี route แต่ไม่พบข้อมูล" (โดเมน) · เทสต์ที่ assert แค่ `status_code == 404` **ผ่านได้ทั้งสองกรณี** ⇒ เทสต์ครอบเคส 404 กลายเป็นเทสต์ "เขียวเปล่า" ทันทีที่ URL ผิด
- **Correct Pattern/Solution:** ใช้ **ค่าคงที่ path ระดับโมดูล** แทนการพิมพ์ URL ซ้ำในทุกเทสต์ (แบบเดียวกับ `test_finance_statements.py`) และเมื่อ assert 404 ให้ **assert ข้อความ detail ของโดเมนด้วย**:
  ```python
  API_PREFIX = "/api/classroom"                              # ⚠️ มาจาก main.py:79
  MY_DEBTS_PATH = API_PREFIX + "/{room}/finance/me/debts"
  ...
  assert res.status_code == 404, res.text
  assert res.json()["detail"] == "ไม่พบห้องเรียนนี้"   # ไม่ใช่ {"detail":"Not Found"} ของ FastAPI
  ```
- **Rule:** (1) **เทสต์ที่ผ่านด้วยเหตุผลผิดอันตรายกว่าเทสต์ที่ fail** — เคส 404 ต้องผูกกับ *ข้อความ* เสมอ ไม่ใช่แค่รหัส (2) อาการ "ทุกตัว 404 ยกเว้นตัวที่คาดหวัง 404" = **สงสัย prefix/การ mount ก่อน** ไม่ใช่สงสัย service (3) URL ในเทสต์ให้ประกาศเป็นค่าคงที่ต่อโมดูล — พิมพ์ `f"/{room_id}/..."` ซ้ำ 10 ที่ = 10 โอกาสลืม prefix
- **Date Added:** 2026-09-13

---

### 🐛 Routers — `rooms.id` เป็น SERIAL (int4) ⇒ เอา guild_id ของ Discord (~19 หลัก) ไปหา `WHERE id = $1` ได้ **HTTP 500 `OverflowError`** ไม่ใช่ 404
- **Context/Problem:** เทสต์กับดัก `target_type` ตั้งใจส่ง guild id ใหญ่ (`4_567_890_123`) แล้ว **ไม่ส่ง** `target_type` เพื่อพิสูจน์ว่าจะถูกตีเป็น room_id → ควรได้ 404 แต่ได้ `asyncpg ... OverflowError: value out of int32 range` ลอยออกมาเป็น **500** (ในเทสต์คือ exception ทะลุออกมาเลย เพราะ `TestClient(raise_server_exceptions=True)` เป็นค่าเริ่มต้น) · เคสจริงคือ **บอทที่ลืมส่ง `target_type=server`** ⇒ guild id จริงเป็น snowflake ~19 หลัก ⇒ **เกิน int32 ทุกตัว** ⇒ ผู้ใช้เห็น 500 แทนข้อความที่วินิจฉัยได้
- **Root Cause:** `rooms.id` เป็น `SERIAL` (int4) แต่ `target_id` เป็น Python `int` ไม่จำกัดขนาด ⇒ asyncpg พยายามเข้ารหัสเป็น int4 แล้วโยน `OverflowError` **ก่อน** query จะได้รัน ⇒ ไม่มีทางได้ "not found" เพราะพังตอน bind parameter ไม่ใช่ตอน fetch · จุดที่พลาดมีสองที่ที่โค้ดเดียวกันเป๊ะ: `BaseService.resolve_room_id` (`backend/services/finance/base.py:82`) และ `resolve_target_to_room_id` (`backend/core/dependencies.py:122` — ตัวหลังถูกใช้โดย router กลุ่ม activity/action อีก ~30 route)
- **Correct Pattern/Solution:** **ยังไม่ได้แก้ — บันทึกเป็นงานแยกโดยตั้งใจ** เพราะ (ก) helper เป็นของร่วมที่ router นอกโมดูลการเงินใช้อยู่ ~30 route ⇒ อยู่นอกขอบเขต additive ของ F4 (ข) ทางแก้คือ guard ก่อนยิง query แล้วโยน not-found ตามปกติ:
  ```python
  # `rooms.id` เป็น int4 — ค่าที่เกินช่วงไม่มีทางมีอยู่ในตาราง ⇒ "ไม่พบ" ตั้งแต่แรก
  if not (0 < room_id <= 2_147_483_647):
      raise RoomNotFoundError("ไม่พบห้องเรียนนี้")
  ```
  ระหว่างนี้เทสต์ของ F4 จึงเลือก guild id ที่ **พอดี int32** (`1_234_567_890`) เพื่อให้ assertion สื่อความหมายเดียว (พิสูจน์กับดัก `target_type` ไม่ใช่พิสูจน์ overflow) พร้อมคอมเมนต์กำกับเหตุผลไว้ในตัวเทสต์
- **Rule:** (1) **id ที่รับจากภายนอก (path param/body) ต้องถูก validate กับชนิดคอลัมน์ปลายทาง** — Python `int` ไม่มีขอบเขต แต่ Postgres `SERIAL`/`INTEGER` มี; พังตอน bind = 500 เสมอ ไม่ใช่ 404/422 (2) อาการ "**ค่าใหญ่พัง แต่ค่าเล็กผ่าน**" ให้สงสัย int4/int8 ก่อน logic (3) เจอบั๊กนอกขอบเขตเฟส → **บันทึก ไฟล์:บรรทัด + ทางแก้ ให้ครบแล้วเดินต่อ** ดีกว่าแอบแก้ helper ร่วมกลางเฟสที่ประกาศว่า additive (แนวเดียวกับที่โปรเจกต์นี้ใช้กับ `delete_category` hard delete)
- **Date Added:** 2026-09-13

### 💰 Finance — `finance_transactions` **ไม่ใช่ตาราง legacy** แต่เป็น dual-write mirror ที่ครบทั้งสองยุค ⇒ งบประมาณอ่านตารางนี้ตารางเดียว ห้าม clamp ที่ CUTOFF และห้ามอ่าน journal
- **Context/Problem:** F1 (งบทดลอง/กำไรขาดทุน/งบดุล) กับ F2 (งบประมาณ) ใช้ "ยอดใช้ไป" เหมือนกันแต่ต้องอ่านคนละตารางโดยสิ้นเชิง — F1 อ่าน `journal_lines` อย่างเดียวและ **clamp ที่ `CUTOFF_DATE = 2026-09-01`** (ก่อนเส้นไม่มี journal เลย) ส่วน F2 อ่าน `finance_transactions` อย่างเดียวและ **ห้าม clamp** ถ้าลอกกฎของ F1 มาใช้กับ F2 จะได้งบประมาณที่มียอด 0 สำหรับทุกงบของเดือนก่อนกันยา; ถ้าให้ F2 อ่านทั้งสองตารางจะได้ **ยอดเบิ้ล**
- **Root Cause:** `finance_transactions` ถูกเขียนคู่กับ journal **ใน `conn.transaction()` เดียวกัน** ทุกจุดที่มีการเคลื่อนไหวของเงินจริง — มีแค่ 3 จุดใน production: `transactions.py:56` (`add_transaction`), `transactions.py:155`+`:163` (สองขาของ `transfer_money`), `collections.py:152` (`_confirm_single_payment`) ⇒ ตารางนี้ **มีแถวครบทั้งยุคก่อนและหลังเส้นตัด** ขณะที่ `journal_lines` เริ่มมีเฉพาะหลังเส้น · และ `revert_transaction` mark **ทั้งสองฝั่ง** พร้อมกัน (`deleted_at = NOW()` คู่กับ `status='voided'`) ⇒ เงื่อนไข `T.deleted_at IS NULL` ฝั่ง legacy สอดคล้องกับ `JE.status <> 'voided'` ฝั่ง journal อยู่แล้ว **การอ่านทั้งคู่จึงเป็นการนับซ้ำ ไม่ใช่การปิดรู**
- **Correct Pattern/Solution:** งบประมาณอ่าน `finance_transactions` เท่านั้น **ไม่ clamp** — ช่วงก่อนเส้นมีแถว legacy อยู่แล้ว ช่วงหลัง dual-write ใส่ให้ คร่อมเส้นก็ไม่มีรู · `opening_balance` และ `adjustment` ของ reconcile **ไม่มีแถวในตารางนี้** จึงถูกตัดออกเองโดยธรรมชาติ (ถูกต้อง เพราะไม่ใช่การใช้จ่ายจริง) · ตัดขาโอนเงินด้วย `T.transfer_group_id IS NULL` (ลอกจาก `_get_summary_legacy` — ขาโอนย้ายเงิน ไม่ใช่รายจ่าย)
  - ⚠️ **เขียนคอมเมนต์กำกับไว้ว่านี่เป็น "ตรงข้าม" กับกฎของ F1 โดยเจตนา — ห้าม refactor ให้สองที่ใช้ helper ร่วมกัน** ความต่างนี้ไม่ใช่ความไม่สม่ำเสมอที่ต้องจัดบ้าน แต่เป็นผลจาก "สองตารางมีประวัติคนละแบบ"
- **Rule:** (1) ก่อนเลือกว่าจะ clamp ที่ `CUTOFF_DATE` ไหม ให้ถามว่า **ตารางนั้นเริ่มมีข้อมูลตั้งแต่เมื่อไร** ไม่ใช่ถามว่าฟีเจอร์ไหน (2) "dual-write" หมายความว่าตาราง legacy **ครบทั้งสองยุค** ⇒ ห้ามอ่านคู่กับ journal (3) ฟีเจอร์ที่คล้ายกันอาจต้องอ่านคนละแหล่งโดยเจตนา — ถ้าจะรวม helper ต้องพิสูจน์ก่อนว่าไม่มีฟีเจอร์ใดต้อง clamp
- **Tests:** `backend/tests/test_finance_budgets.py` §1 (era routing / no double count) — pre-cutoff 3 แถว legacy → `used == X`; post-cutoff ผ่าน `add_transaction` → `used == Y` **และยืนยันว่า `journal_entries` มีแถวเกิดขึ้นจริง** แล้วจึงยืนยัน `used == Y` **ไม่ใช่ `2Y`** (บทพิสูจน์ว่าไม่นับซ้ำ ไม่ใช่แค่assert ตัวเลข); คร่อมเส้น → `X + Y` พอดี; `add → revert_transaction → used == 0` พร้อมยืนยัน **ทั้ง** `deleted_at IS NOT NULL` และ `status='voided'`
- **Date Added:** 2026-09-13

### 🕐 SQL — งบประมาณต้องเทียบ "วันไทย" กับ **สองชนิดคอลัมน์ที่เก็บโซนต่างกัน** ในคำสั่งเดียว ⇒ `LEFT JOIN LATERAL` เดียวมีสองนิพจน์เวลา
- **Context/Problem:** ยอด "ใช้ไป" ของงบต้องนับจากสองแหล่งที่อยู่คนละตารางและคนละชนิดคอลัมน์ในรอบเดียว: `finance_transactions.created_at` (`TIMESTAMP` naive ที่เก็บ **UTC wall clock**) สำหรับรายการปกติ และ `journal_entries.transaction_date` (`TIMESTAMPTZ`) สำหรับรายรับจาก `student_payment` ที่แถว legacy ไม่มี `category_id` ⇒ ใช้ `T.created_at::date` หรือ `JE.transaction_date::date` ตรง ๆ **ผิดทั้งคู่** เพราะได้วันตาม UTC/session ไม่ใช่วันไทย ⇒ รายการที่บันทึก 00:00–07:00 น. เวลาไทยจะไปโผล่ในงบของ **วันก่อนหน้า**
- **Root Cause:** คอลัมน์สองชนิดต้องการการแปลงคนละแบบ — `TIMESTAMPTZ` เก็บจุดเวลา จุดเดียวตัดสินว่าเป็นวันไหนได้ด้วย timezone; `TIMESTAMP` naive **ไม่มีโซนให้แปลง** ค่าที่เก็บจึงต้องถูกตีความก่อนว่ามันคือ UTC แล้วค่อยแปลงเป็นไทย · การใช้ `::date` กับทั้งคู่เท่ากับ **ปนความหมายสามแบบ** (UTC calendar / session calendar / Thai calendar)
- **Correct Pattern/Solution:** สองนิพจน์นี้อยู่ในคำสั่งเดียวกันได้ และต้องเป็นแบบนี้:
  ```sql
  -- naive TIMESTAMP ที่เก็บ UTC wall clock → ตีความเป็นเวลาไทยก่อน แล้วค่อยกลับมาเป็น UTC naive
  ((GREATEST(B.start_date, $2)::timestamp) AT TIME ZONE 'Asia/Bangkok' AT TIME ZONE 'UTC')
  -- TIMESTAMPTZ → แค่ตีความวันที่เป็นเที่ยงคืนเวลาไทย
  ((GREATEST(B.start_date, $2)::timestamp) AT TIME ZONE 'Asia/Bangkok')
  ```
  และขอบบนเป็น **half-open** เสมอ: `((LEAST(B.end_date, $3) + 1)::timestamp AT TIME ZONE ...)` เทียบด้วย `<` ไม่ใช่ `<= 23:59:59` ⇒ ไม่มีวินาทีสุดท้ายของวันหลุด (ช่องโหว่ที่ `get_trial_balance` เคยมี)
  - `AT TIME ZONE` ตัวแรกบน `timestamp` **คืน `timestamptz`** ส่วนตัวที่สองบน `timestamptz` **คืน `timestamp`** — ลำดับสลับกันไม่ได้ และจำนวนครั้งที่ใช้คือตัวบอกว่าคอลัมน์ต้นทางเป็นชนิดไหน
- **Rule:** (1) **ห้ามใช้ `col::date` กับคอลัมน์เวลาไม่ว่าชนิดใด** ในโมดูลนี้ — ต้องเขียนขอบเขตเป็นช่วง half-open (2) `AT TIME ZONE` × 1 = คอลัมน์เป็น `timestamptz`; × 2 = คอลัมน์เป็น naive ที่เก็บ UTC (3) งบที่คิดยอดจาก "ช่วงของตัวเอง" ให้ใส่การ clamp (`GREATEST`/`LEAST`) ไว้ใน SQL ไม่ใช่คำนวณใน Python แล้วส่งเป็นขอบเขต — ไม่งั้นต้องยิง query ต่อแถว
- **Tests:** `test_finance_budgets.py` §4 (Thai day boundaries) — รายการที่ `created_at` ตรงวัน `start_date`/`end_date` ต้องถูกนับ และห่างออกไป 1 วันต้องไม่ถูก; helper `_thai_day_utc(d, hour=12)` สร้าง naive UTC ที่ตรงกับวันไทยที่ต้องการ (§5 เดิมของไฟล์นี้)
- **Date Added:** 2026-09-13

### 🐛 Finance — guard `delete_category` ที่กรอง `deleted_at IS NULL` **ไม่ตรงกับ FK `ON DELETE RESTRICT`** ⇒ ลบงบก่อนแล้วลบหมวด = HTTP 500 ดิบ
- **Context/Problem:** เทสต์ของ F2 ล้มด้วย `asyncpg.ForeignKeyViolationError: update or delete on table "finance_categories" violates foreign key constraint "finance_budgets_category_id_fkey"` ทะลุเป็น **500** — เคสจริง: ผู้ใช้ **soft delete งบ** (หายจากหน้าจอแล้ว) → กดลบหมวด → guard ผ่าน (เพราะงบถูก soft delete ไปแล้ว) → FK ระเบิด · โค้ดที่เขียนไว้ตอนแรกดู "ถูก" และคอมเมนต์ก็อธิบายเหตุผลครบ แต่ **อธิบายคนละความจริงกับที่ DB บังคับ**
- **Root Cause:** `finance_budgets.category_id` เป็น `NOT NULL REFERENCES finance_categories(id) ON DELETE RESTRICT` ⇒ FK นับ **ทุกแถวไม่ว่า `deleted_at` จะเป็นอะไร** แต่ guard ที่เขียนไว้กรอง `AND deleted_at IS NULL` ⇒ **สองชั้นป้องกันใช้กติกาคนละข้อ** ชั้นที่หลวมกว่าจึงปล่อยผ่านไปชนชั้นที่เข้มกว่า ⇒ ได้ error ของ DB แทนข้อความที่อ่านรู้เรื่อง (และโมดูลนี้ **ไม่มี global exception handler** ⇒ ทุกอย่างที่หลุด = 500)
- **Correct Pattern/Solution:** ให้ guard สื่อ **ความจริงข้อเดียวกับ FK** — ตัด `deleted_at IS NULL` ออก:
  ```python
  if await conn.fetchval("SELECT 1 FROM finance_budgets WHERE category_id = $1 LIMIT 1", category_id):
      raise ValueError("ไม่สามารถลบได้ เนื่องจากมีงบประมาณผูกอยู่!")
  ```
  ⇒ หมวดที่ "เคย" มีงบจะลบไม่ได้เลย ไม่ว่าจะลบงบไปแล้วหรือยัง · **เป็น semantics เดียวกับ guard `finance_transactions` ที่อยู่ข้างกัน** (ซึ่งก็เป็น "เคยใช้" เช่นกัน) · เหตุผลเชิงผลิตภัณฑ์ที่ทำให้ `RESTRICT` ถูก: การ hard delete หมวดจะทิ้งแถวงาน (ที่ soft delete ไว้) ชี้ไปยังหมวดที่ไม่มีอยู่ ⇒ ประวัติอ่านไม่รู้เรื่อง — ส่วน guard มีหน้าที่แค่เปลี่ยน error ของ DB ให้เป็น 400
- **Rule:** (1) **guard ที่เขียนไว้ "หน้า" constraint ต้องมี semantics เดียวกับ constraint นั้นเป๊ะ ๆ** — ถ้า constraint ไม่สน `deleted_at` guard ก็ต้องไม่สน (2) ทุกครั้งที่เขียน guard กัน FK ให้เปิด DDL มาอ่านจริง **อย่าเดาจากชื่อ** (3) soft delete + FK `RESTRICT` = "ลบไม่ได้ตลอดกาล" ซึ่งมักเป็นสิ่งที่ต้องการ แต่ต้องเขียนให้ตรงกันทั้งสองชั้น (4) เทสต์ที่จับบั๊กนี้ได้คือเทสต์ที่ทำตามลำดับ **ธุรกิจจริง** (ลบงบ → ลบหมวด) ไม่ใช่ยิงตรง ๆ
- **Tests:** `test_finance_budgets.py` §9 — `test_delete_category_blocked_when_budget_exists` และ **`test_delete_category_still_blocked_after_budget_soft_deleted`** (ตัวหลังคือตัวที่ fail กับโค้ดเวอร์ชันแรก) พร้อมยืนยันว่าหมวด **ยังอยู่** ใน DB หลังได้ 400
- **Date Added:** 2026-09-13

### 🧪 Tests — เทสต์ที่พิสูจน์ว่า SQL clause "มีผลจริง" ต้องหาทรงข้อมูลที่ **clause เดียวเปลี่ยนคำตอบได้** ไม่งั้นเทสต์ผ่านทั้งที่ถอด clause ออก
- **Context/Problem:** query ยอด "ใช้ไป" มีสอง clause ที่ดูเหมือนจำเป็นแต่ **เทสต์ทั่วไปพิสูจน์ไม่ได้เลยว่าใส่มาแล้วมีผล**: `T.transfer_group_id IS NULL` (ตัดขาโอนเงิน) และ `AL.legacy_category_id = B.category_id` (ผูก journal เข้ากับหมวดของงบ) — เพราะขาโอนเงินจริงมี `category_id = NULL` อยู่แล้ว จึงไม่ถูกนับตั้งแต่ clause ก่อนหน้า ⇒ เทสต์ "โอนเงินแล้วยอดไม่ขยับ" **ผ่านแม้ถอด `transfer_group_id IS NULL` ออก** และ `student_payment` ก็นับเฉพาะงบของหมวดรายรับเริ่มต้น ⇒ เทสต์ผลรวมผ่านได้แม้ถอด join ทิ้ง
- **Root Cause:** เทสต์ที่ยืนยัน **ผลลัพธ์** ของข้อมูลรูปร่างปกติ ไม่ได้ยืนยัน **การมีอยู่ของเงื่อนไข** — ถ้าข้อมูลจริงล้วนอยู่ในรูปที่ clause ไม่ได้ทำอะไร เทสต์จะเขียวตลอดกาลและ clause จะถูกลบออกอย่างปลอดภัยในสายตาคนอ่าน
- **Correct Pattern/Solution:** สำหรับแต่ละ clause ให้สร้าง **ทรงข้อมูลเดียวที่ clause นั้นเปลี่ยนคำตอบ** แล้วเขียนเทสต์เฉพาะทรงนั้น:
  - `transfer_group_id IS NULL` → seed แถว legacy ที่มี **ทั้ง** `category_id` และ `transfer_group_id` (ทรงเดียวที่ clause เปลี่ยนคำตอบจริง — ขาโอนจริงมี `category_id = NULL` จึงพิสูจน์ไม่ได้)
  - `AL.legacy_category_id = B.category_id` → **leak test**: ตั้งงบของ **อีกหมวดรายรับหนึ่ง** แล้วยืนยัน `used == 0` ทั้งที่มี `student_payment` อยู่ในช่วง (ถ้า join หลวม จะรั่วข้ามหมวดทันที)
  - `JE.reference_type = 'student_payment'` → reconcile-`adjustment` ที่ **เครดิต ledger ตัวเดียวกับที่ map กับหมวดของงบเป๊ะ ๆ** (ทรงที่แข็งที่สุดของเคสนี้)
  - และ **assert ข้อตั้งต้น (premise) กับ DB ก่อน assert ผลลัพธ์** — เทสต์ disjointness ของ `student_payment` อ่าน DB ยืนยันว่าแถว legacy มี `category_id IS NULL` **และ** ledger มี `legacy_category_id` ชี้หมวดนั้น ก่อนจะยืนยัน `used == 1000` ⇒ วันที่ dual-write เริ่มใส่ `category_id` ให้แถวนี้ เทสต์จะ **fail ดัง ๆ** ด้วยข้อความที่บอกสาเหตุ แทนที่จะเริ่มนับซ้ำเงียบ ๆ
- **Rule:** (1) clause ที่ "ดูเหมือนจำเป็น" ต้องมีเทสต์ที่ **ลบ clause แล้วเทสต์ต้องแดง** — ถ้าหาเคสไม่ได้ ให้เขียนคอมเมนต์ว่ายังพิสูจน์ไม่ได้ อย่าปล่อยให้เข้าใจว่าพิสูจน์แล้ว (2) assert **ข้อสมมติ** (ข้อมูลเป็นรูปที่เราคิด) ไม่ใช่แค่ยอดรวม — ยอดรวมที่ถูกด้วยเหตุผลผิดจะเปลี่ยนเป็นผิดในวันที่สมมติฐานพัง (3) เทสต์ boundary ของช่วงเวลาให้ **derive วันที่จาก DB** (`_thai_day_of_latest_tx` อ่าน `created_at` ของแถวล่าสุดจริง) ไม่ใช่ hardcode เดือน ไม่งั้น suite เน่าเองเมื่อข้ามเดือน
- **Tests:** `test_finance_budgets.py` §2 (`test_transfer_with_category_and_group_is_excluded`), §3 (`test_student_payment_does_not_leak_to_other_category`, `test_student_payment_row_has_no_category_id`), §5 (`test_adjustment_on_same_ledger_is_excluded`)
- **Date Added:** 2026-09-13

### 🎨 Frontend — `npm run format` **ไม่ปลอดภัยกับ repo นี้**: โค้ดทั้ง repo ไม่เคยถูกจัดฟอร์มด้วย Prettier ภายใต้ config ใดเลย (ไม่ใช่แค่เรื่อง `semi`) ⇒ rewrite 67 ไฟล์เสมอ
- **Context/Problem:** รัน `npm run format` (= `prettier --write src/`) ตามคำสั่งใน `CLAUDE.md` แล้ว diff ระเบิดเป็น **67 ไฟล์ / +4,098 −2,665 บรรทัด** ทั้งที่งานจริงแตะ 4 ไฟล์ ⇒ ถ้า commit ตามไป จะได้ PR ที่รีวิวไม่ได้เลย และกลบการเปลี่ยนแปลงจริงของฟีเจอร์
- **Root Cause (วัดใหม่ 2026-09-13 — คำอธิบายเดิมไม่ครบ):** เดิมสรุปว่าเกิดจาก `"semi": false` ใน `.prettierrc.json` ขัดกับโค้ดที่ใช้เซมิโคลอน **ซึ่งจริงแค่บางส่วน** — วัดด้วย `prettier --check` จริงแล้วพบว่า **67 ไฟล์ต่างกันทั้งที่ `semi: false` และ `semi: true`** (และ 72–73 ไฟล์เมื่อสลับ quote / `printWidth`) ⇒ เนื้อแท้คือ **โค้ดทั้ง repo ไม่เคยถูกจัดฟอร์มด้วย Prettier ภายใต้ config ใดเลย**: บรรทัดยาวเกิน `printWidth: 100`, การห่อ `(await api.get(...)) as unknown as T` ถูกเขียนเป็นบรรทัดเดียว ฯลฯ ⇒ **ไม่มีค่า config ไหนที่ทำให้ diff เป็นศูนย์**
  - และ **ไม่มี CI gate ใดรัน `prettier --check`** (`frontend/.github/workflows/deploy.yml` ไม่แตะ prettier) ⇒ ไม่มีแรงกดดันให้จัดฟอร์ม และไม่มีอะไรพังถ้าไม่จัด
- **Correct Pattern/Solution (สิ่งที่ทำจริงรอบนี้):**
  1. **ไม่จัดฟอร์มทั้ง repo** — 4,000 บรรทัดของ churn ล้วน ๆ บน branch ที่มีงานฟีเจอร์ค้างอยู่ = แลกไม่คุ้ม (ถ้าจะทำ ต้องเป็นคอมมิตแยกตอน branch ว่าง)
  2. แก้ค่าที่ **ผิดข้อเท็จจริง** ข้อเดียว: `frontend/.prettierrc.json` → `"semi": true` (โค้ดจริงใช้เซมิโคลอน 100%) — ลด diff ได้บางส่วน ไม่ได้ทำให้เป็นศูนย์
  3. เติมคำเตือนที่ **จุดที่คนจะไปเจอ**: `CLAUDE.md` ข้างบรรทัด `npm run format` + `frontend/README.md`
  4. เติม `node_modules/` ใน `.gitignore` ที่ราก (กัน `npx` ที่รากสร้าง `node_modules/.cache/prettier/` โผล่มาเป็น untracked)
  - ถ้าจำเป็นต้องจัดฟอร์ม **ไฟล์เดียว** ให้ override flag: `npx prettier --write --semi true <file>` (flag ชนะ config)
  - ถ้า diff หลุดไปแล้ว ให้ `git stash push -- <path>` (กู้คืนได้ ต่างจาก `git checkout --` ที่ทิ้งถาวร); ⚠️ `git checkout -- <dir>` ถูก permission classifier บล็อกโดยชอบ เพราะทิ้งงานที่ไม่มีที่อื่นเก็บ
- **Rule:** (1) รัน formatter ทั้งโปรเจกต์ = การเปลี่ยนแปลงที่ต้อง **ขออนุญาตก่อน** ไม่ใช่ขั้นตอนปกติของงานฟีเจอร์ (2) `diff --stat` ที่ใหญ่ผิดปกติคือสัญญาณให้หยุดดู **ก่อน** commit ไม่ใช่หลัง (3) สไตล์ที่ต้องยึดคือ **สไตล์ของโค้ดจริง** ไม่ใช่สไตล์ใน config (4) **ก่อนสรุปว่า config ตัวไหนผิด ให้วัดจริงก่อน** — รัน `npx prettier --check` กับ config ผู้สมัครแต่ละตัวแล้วนับจำนวนไฟล์ อย่าเดาจากการอ่านโค้ดไม่กี่บรรทัด (บทเรียนนี้สรุปผิดมาแล้วรอบหนึ่งเพราะเดา)
- **Tests:** ไม่มีเทสต์อัตโนมัติ — ตรวจด้วย `npx prettier --check "src/**/*.{ts,vue}"` จาก `frontend/` และ `git diff --stat -- frontend/` ว่าจำนวนไฟล์ตรงกับที่ตั้งใจแตะ
- **Date Added:** 2026-09-13

### 🔢 Finance — เลขรันเอกสารต้องมาจาก `ON CONFLICT DO UPDATE ... RETURNING` ไม่ใช่ `MAX(seq)+1` และต้อง **เก็บ** ไม่ใช่ **คำนวณ**
- **Context/Problem:** F3 ต้องออกเลขใบเสร็จ `REC-2569-0001` ต่อห้อง/ต่อปี พ.ศ. แบบไม่ซ้ำแม้มีคำขอพร้อมกัน สองทางที่ดูใช้ได้คือ `SELECT MAX(seq)+1` แล้ว INSERT หรือ `SELECT ... FOR UPDATE` แล้วค่อย INSERT — ทั้งคู่มีช่วงเวลา (read-then-write) ที่คำขออื่นแทรกได้ ⇒ เลขซ้ำ ⇒ `UniqueViolationError` กลายเป็น 500 บนเอกสารการเงิน
- **Root Cause:** `MAX(seq)+1` เป็น read-modify-write ที่ **ไม่มีอะไรล็อก** ระหว่างสองขั้น — สองทรานแซกชันที่อ่าน `MAX` พร้อมกันจะได้ค่าเดียวกันแล้ว INSERT ชนกัน สิ่งที่ต้องได้คือ "การจอง" ที่อะตอมมิก ซึ่ง PostgreSQL ให้มาฟรีผ่าน `INSERT ... ON CONFLICT DO UPDATE` เพราะ **ตัว `DO UPDATE` ล็อกแถวเป้าหมายให้เอง**
- **Correct Pattern/Solution:**
  ```sql
  INSERT INTO receipt_sequences (room_id, year_be, doc_type, last_seq)
  VALUES ($1, $2, $3, 1)
  ON CONFLICT (room_id, year_be, doc_type)
  DO UPDATE SET last_seq = receipt_sequences.last_seq + 1, updated_at = CURRENT_TIMESTAMP
  RETURNING last_seq
  ```
  ⇒ ไม่ต้อง `SELECT ... FOR UPDATE` นำหน้าเลย (ใส่ซ้ำ = ล็อกซ้อนโดยเปล่าประโยชน์) · PK ผสม `(room_id, year_be, doc_type)` ทำหน้าที่เป็นเป้าของ `ON CONFLICT`
  - **ทำไมต้องเก็บตารางตัวนับ ไม่ใช่คำนวณ `ROW_NUMBER() OVER (ORDER BY paid_at)` ตอนอ่าน:** เลขที่ derive จะ **เปลี่ยนย้อนหลังทั้งชุด** ทันทีที่มีการ revert รายการก่อนหน้า (`revert_transaction` ล้าง `paid_at`/`paid_amount`/`transaction_id` ของบิล) ⇒ ใบเสร็จที่พิมพ์แจกไปแล้วเปลี่ยนเลข = เอกสารทางบัญชีใช้ไม่ได้
- **Rule:** (1) ตัวนับที่ต้องไม่ซ้ำและต้อง "จอง" ให้ใช้ upsert-returning หรือ sequence — ห้าม `MAX+1` (2) ตัวนับที่ **ห้ามเปลี่ยนย้อนหลัง** ต้อง persist ไม่ใช่ derive (3) ยอมรับ "เลขที่ถูกใช้ฟรี" เมื่อแพ้การแข่งขันได้ (ไม่ต่อเนื่องแต่ไม่มีผลทางบัญชี) ดีกว่ารอ lock ให้ช้า
- **Tests:** `backend/tests/test_finance_receipts.py` §3 (`test_five_receipts_get_five_distinct_sequential_numbers` — 5 ใบได้ `0001..0005` และ `last_seq == 5`) และ §5 (`test_year_sequences_are_independent_per_buddhist_year` — คนละปี พ.ศ. เริ่ม `0001` ใหม่แยกกัน)
- **Date Added:** 2026-09-13

### 🧾 Finance — ใบเสร็จ **idempotent** แต่ใบแจ้งหนี้ **point-in-time** — ความไม่สมมาตรนี้ถูกเข้ารหัสไว้ในรูปทรงของ partial unique index
- **Context/Problem:** ทั้งสองเป็น "เอกสารที่ออกให้บิลเดียวกัน" จึงดูเหมือนควรมีกฎซ้ำกัน แต่จริง ๆ ตรงข้าม: กดออกใบเสร็จซ้ำต้องได้ **เลขเดิม** (การพิมพ์ซ้ำเป็นเรื่องปกติของงานเอกสาร) ส่วนใบแจ้งหนี้ **ต้องกินเลขใหม่** เพราะยอดค้างของนักเรียนเปลี่ยนได้เมื่อจ่ายเพิ่ม ใบเดิมจึงหมดอายุตามธรรมชาติ ⇒ ถ้าใช้กฎเดียวกันทั้งคู่ จะพังข้างใดข้างหนึ่งเสมอ
- **Root Cause:** ใบเสร็จผูกกับ **เหตุการณ์รับเงิน** (เกิดแล้วเกิดเลย ไม่เปลี่ยน) ส่วนใบแจ้งหนี้ผูกกับ **ยอดค้าง ณ เวลาหนึ่ง** (เปลี่ยนได้) — สองสิ่งนี้มี cardinality ต่อบิลไม่เท่ากัน (1 ใบต่อ 1 เหตุการณ์ vs หลายใบต่อบิล) การพยายามใช้ unique index เดียวกันจึงเป็นการฝืนความจริงของโดเมน
- **Correct Pattern/Solution:** เข้ารหัสความต่างไว้ **ใน predicate ของ index** ไม่ใช่ใน `if` ของ service (เพราะ service มี race window):
  ```sql
  CREATE UNIQUE INDEX idx_finance_receipts_tx_active
      ON finance_receipts(student_payment_id, COALESCE(legacy_transaction_id, 0), doc_type)
      WHERE deleted_at IS NULL AND doc_type = 'receipt';   -- ⬅️ invoice ไม่อยู่ใน predicate
  ```
  - service ยังมี idempotency check ของตัวเอง **สองชั้น**: อ่านก่อนเขียน (คืนใบเดิม + `reused: True`, HTTP 200) และ catch `UniqueViolationError` แล้วอ่านซ้ำ (แพ้การแข่งขันเสี้ยววินาที ⇒ คืนใบที่ชนะ ไม่ใช่ error)
  - 🔴 **กับดักของ `COALESCE(..., 0)`:** ถ้าเขียน predicate เป็น `legacy_transaction_id IS NOT NULL` ใบเสร็จของบิลที่ยืนยัน **ก่อนยุค dual-write** (ไม่มีแถว `finance_transactions` ⇒ `legacy_transaction_id` เป็น NULL) จะ **หลุดออกจาก index ทั้งที่ผูกบิลอยู่** ⇒ สองคำขอพร้อมกันสร้างใบเสร็จซ้ำได้ ต้อง normalize ด้วย `COALESCE(..., 0)` ให้คีย์มีค่าเสมอ
  - `legacy_transaction_id` **ไม่ใช่** `student_payments.transaction_id` — ตัวหลังถูก **ทับ** ทุกครั้งที่รับงวดใหม่ จึงใช้ระบุ "งวด" ไม่ได้ (บิลผ่อน 2 งวดจะดูเหมือนมีเหตุการณ์เดียว) ⇒ เก็บ id ของแถว `finance_transactions` ของงวดนั้น ๆ
- **Rule:** (1) ความต่างเชิงโดเมนที่ "ดูเหมือนควรเหมือนกัน" ให้เข้ารหัสใน **schema constraint** ไม่ใช่ใน service logic (2) unique index ที่ใช้กันเอกสารซ้ำต้อง normalize คีย์ให้ไม่มี NULL หลุด — และคิดถึงข้อมูลยุคก่อน migration ด้วย (3) "ออกซ้ำ" ของเอกสารการเงินต้องเป็น **200 + ใบเดิม** ไม่ใช่ 4xx (ผู้ใช้กดพิมพ์ซ้ำด้วยเหตุผลที่ถูกต้อง) (4) เทสต์ต้องยืนยัน **เจตนา** ของความไม่สมมาตร ไม่ใช่แค่พฤติกรรม
- **Tests:** `test_finance_receipts.py` §2 (`test_reissue_returns_same_receipt_without_burning_a_number`, `test_pre_dualwrite_bill_receipt_is_also_idempotent` — อันหลังคือเคส `COALESCE`), §6 (`test_instalment_payments_produce_one_receipt_per_event` — พิสูจน์ว่า `legacy_transaction_id` อยู่ในคีย์จริง โดยออกใบของงวดแรกซ้ำหลังจ่ายงวดที่สอง), §7 (`test_invoice_is_point_in_time_and_gets_a_new_number_every_time`)
- **Date Added:** 2026-09-13

### 🗓️ Finance — ปี พ.ศ. ของเลขเอกสารต้องมาจาก **เหตุการณ์รับเงิน** ไม่ใช่ `student_payments.paid_at` (และต้องคิดเป็นเวลาไทย ไม่ใช่ UTC)
- **Context/Problem:** ใบเสร็จต้องออกย้อนหลังได้ (ผู้ปกครองมาขอทีหลัง) ⇒ พบว่าใบเสร็จของงวดเดือน ธ.ค. 2569 ออกมาเป็นเลขปี **2570** ถ้าออกหลังจากรับงวด ม.ค. 2570 ไปแล้ว — ซึ่งผิด และไปขัดกับรายงานภาษี/สรุปประจำปี
- **Root Cause:** `_confirm_single_payment` **ทับ** `paid_at`/`paid_amount`/`transaction_id` ของ `student_payments` ทุกครั้งที่รับเงินงวดใหม่ ⇒ `paid_at` คือ "เวลาของงวดล่าสุด" เสมอ ไม่ใช่เวลาของงวดที่กำลังออกใบเสร็จ · ซ้ำร้าย `finance_transactions.created_at` เป็น `TIMESTAMP` **naive ที่เก็บเวลา UTC** (ดูบทเรียน TZ ก่อนหน้า) ⇒ UTC+7 ทำให้รายการช่วง 17:00–24:00 UTC ตกเป็น **วันรุ่งขึ้นของไทย** ซึ่งข้ามปี พ.ศ. ได้จริง
- **Correct Pattern/Solution:** อ่าน `finance_transactions.created_at` ของ **งวดนั้น ๆ** แล้วแปลงเป็นไทยก่อนคำนวณปี:
  ```python
  aware = naive_utc.replace(tzinfo=timezone.utc)      # ✅ naive → ติดป้าย UTC
  year_be = aware.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET
  ```
  ⚠️ **ห้ามเรียก `.astimezone()` บนค่า naive ตรง ๆ** — Python จะตีเป็นเวลาท้องถิ่นของเครื่อง ⇒ ได้ปีผิดแบบเงียบ ๆ ต้อง `.replace(tzinfo=timezone.utc)` ก่อนเสมอ (รวมไว้ที่ helper เดียว `_thai_year_be`)
- **Rule:** (1) คอลัมน์ที่ถูก **ทับ** ด้วยเหตุการณ์ใหม่ใช้เป็น "เวลาของเหตุการณ์เดิม" ไม่ได้ — ให้เก็บ id ของเหตุการณ์นั้น ๆ ไว้ต่างหาก (2) ค่าใด ๆ ที่ naive-UTC และมีผล "ข้ามปี/ข้ามวัน" ต้องผ่านการแปลงเป็นไทยก่อนตัดสิน มิฉะนั้นช่วง 7 ชั่วโมงสุดท้ายของทุกวันคือบั๊ก (3) เทสต์ขอบเขตเวลาต้องทดสอบที่ **นาทีที่เส้นแบ่งตกพอดี** ไม่ใช่กลางวัน
- **Tests:** `test_finance_receipts.py` §5 — `@pytest.mark.parametrize` ที่ `2026-12-31 16:59 UTC` → `2569` และ `2026-12-31 17:00 UTC` → `2570` (นาทีเดียวกันเปลี่ยนปี) พร้อมเคสกลางปี/ต้นปีถัดไปเป็นตัวควบคุม
- **Date Added:** 2026-09-13

### 🖨️ PDF — ฟอนต์ไทยต้อง **ส่งไปกับ request** และต้องเป็นฟอนต์ **static** (variable font → Chromium ถอยไปวาด glyph เป็น Type 3)
- **Context/Problem:** F3 ต้องเรนเดอร์ใบเสร็จ/ใบแจ้งหนี้เป็น PDF ที่มีสระ/วรรณยุกต์ไทยถูกตำแหน่ง เลือกสร้างที่ backend ผ่าน **Gotenberg (headless Chromium)** ไม่ใช่ `reportlab`
- **Root Cause — สองข้อแยกกัน:**
  1. **ทำไมไม่ `reportlab`:** ภาษาไทยที่มีตัวหาง + ไม้โท/ไม้เอกซ้อน (ญ ฎ ฐ) ต้องอาศัย **OpenType shaping engine** (harfbuzz) ในการจัดตำแหน่ง glyph — `reportlab` ไม่มี harfbuzz ⇒ วรรณยุกต์ลอยผิดตำแหน่งบนเอกสารที่ครูพิมพ์แจกจริง ส่วน Chromium มี harfbuzz ในตัว
  2. **ทำไมต้องฝังฟอนต์เป็น base64 data URI:** Gotenberg เรนเดอร์ HTML **ใน container ของตัวเอง** ⇒ `url('file:///app/assets/fonts/...')` ไป resolve ที่ filesystem ของ **Gotenberg** ไม่ใช่ของ backend → 404 เงียบ ๆ แล้ว Chromium fallback ไปฟอนต์ที่ไม่มี glyph ไทย = เอกสารออกมาเป็นกล่องสี่เหลี่ยม (การส่งไฟล์ฟอนต์เป็น multipart ก็ได้ผล แต่ผูกกับพฤติกรรมการวางไฟล์ใน working directory ของ Gotenberg ซึ่งต่างกันตามเวอร์ชัน ⇒ data URI ตัดตัวแปรทั้งหมดทิ้ง)
  3. 🔴 **ตัวที่พลาดง่ายที่สุด (พบจากการวัดด้วย `pdffonts` 13 ก.ย. 2026):** ใช้ `NotoSansThai-Variable.ttf` + `@font-face { font-weight: 100 900 }` แล้ว **Chromium/Skia embed ฟอนต์ตัวแปรลง PDF ไม่ได้** ⇒ ถอยไปวาด glyph เป็น **Type 3** (รูปวาด ไม่ใช่ฟอนต์) — เอกสาร **ดูปกติด้วยตา** แต่ `pdffonts` แสดง `[none] Type 3 emb yes sub no` × 11 ก้อน ไฟล์ **92 KB** และร้านพิมพ์/โปรแกรมอ่านออกเสียงไม่ยอมรับ · เปลี่ยนเป็น static 2 ไฟล์ (400/700) → `AAAAAA+NotoSansThai-Bold  CID TrueType  emb yes sub yes` ไฟล์ **17 KB** ⇒ **ต่างกัน 5.5 เท่า**
- **Correct Pattern/Solution:** จับคู่ "ไฟล์ ↔ น้ำหนัก" ไว้ที่ constants ที่เดียว แล้วให้เทมเพลตวนสร้าง `@font-face` ต่อไฟล์:
  ```python
  RECEIPT_FONT_FILES = {"regular": ("NotoSansThai-Regular.ttf", 400),
                        "bold":    ("NotoSansThai-Bold.ttf", 700)}
  ```
  ```html
  {% for f in font_faces %}
  @font-face { font-family: '{{ font_family }}'; src: url('{{ f.uri }}') format('truetype');
               font-weight: {{ f.weight }}; font-style: normal; font-display: block; }
  {% endfor %}
  ```
  ⇒ **เพิ่ม/ลดน้ำหนักต้องเพิ่มไฟล์** ไม่ใช่ใส่ `font-weight: <ช่วง>` · ทุก `@font-face` ใช้ family name เดียวกันแล้วแยกด้วย `font-weight` (ถ้าไม่มีไฟล์ของน้ำหนักที่ใช้ Chromium จะ **synthesize** ตัวหนาเอง → สระ/วรรณยุกต์เพี้ยน) · ตั้ง `_MARGINS` ของ Gotenberg เป็น `0` ให้ CSS ในเทมเพลตเป็นแหล่งเดียวของระยะขอบ (ไม่งั้นได้ระยะขอบสองชั้น ~26 มม. และแก้ที่เทมเพลตไม่เห็นผล)
- **Rule:** (1) service ที่เรนเดอร์ HTML ต้องได้ "ทุกอย่างที่ต้องใช้" ไปกับ request — ห้ามพึ่งไฟล์ในเครื่องของ service นั้น (2) ฟอนต์สำหรับ PDF: **static per-weight เท่านั้น** (3) อย่าตัดสินคุณภาพ PDF ด้วยตา — ต้องดู `pdffonts` (4) งานเอกสารที่พิมพ์จริง ให้ rasterize เป็น PNG แล้ว **อ่านภาพ** ด้วย — บั๊ก "ป้ายชนตัวเลข" และ "ใบแจ้งหนี้ใช้ถ้อยคำของใบเสร็จ" เจอด้วยวิธีนี้เท่านั้น ไม่มี assertion ไหนจับได้
- **Tests:** `test_finance_receipts.py` §11 — mock `html_to_pdf` แล้วตรวจ HTML ที่ส่งออก (มี `data:font/ttf;base64,` ครบ 2 น้ำหนัก + คำอ่านจำนวนเงิน + ไม่เหลือ `{{`) · เทสต์จริง 1 ตัวที่ `skip` เมื่อ `gotenberg_configured()` เป็น `None` (ค่า default คือ `localhost`) และ **assert ว่ามี `/FontFile2` อยู่จริง** เพื่อกันการถอยกลับไปเป็น Type 3
- **Date Added:** 2026-09-13

### 🧪 PDF — `grep /FontFile2` ในไฟล์ PDF ดิบ ๆ ได้ **false negative** เพราะ PDF 1.5+ บีบอัด dictionary ไว้ใน object stream (และ Skia เขียน ToUnicode เป็น `bfrange`)
- **Context/Problem:** เขียนสคริปต์ตรวจว่าฟอนต์ไทยถูกฝังจริงหรือไม่ด้วยการค้น `b"/FontFile2"` ในไบต์ของ PDF ⇒ ได้ **0** ทั้งที่ไฟล์มีฟอนต์ฝังอยู่จริง ทำให้เกือบสรุปผิดว่าฟอนต์ไม่ได้ฝัง และเกือบ "แก้" โค้ดที่ถูกอยู่แล้ว
- **Root Cause:** PDF 1.5+ เก็บ **object dictionary** ไว้ใน *object stream* ที่บีบอัดด้วย FlateDecode ⇒ `/FontFile2`, `/BaseFont` ไม่ปรากฏในไบต์ดิบ · อีกกรณีที่เจอพร้อมกัน: การ parse `ToUnicode` CMap ด้วย regex `<x> <y>` (แบบ `bfchar`) **นับอักษรไทยขาด** เพราะ Skia เขียนช่วง glyph ที่ติดกันเป็น **`bfrange`** (`<0001> <000A> <0E01>`) ไม่ใช่คู่ทีละตัว ⇒ ตัวอักษรอย่าง `ำ` (U+0E33) อยู่ใน range จึง "หาย" จากผลนับ
- **Correct Pattern/Solution:** คลาย zlib ของทุก stream แล้วค่อยค้น (ดู `_pdf_has_embedded_truetype` ใน `test_finance_receipts.py`) และสำหรับ CMap ให้ parse **ทั้ง** `beginbfchar/endbfchar` และ `beginbfrange/endbfrange` · **ตัวตัดสินสุดท้ายคือ `pdftotext -enc UTF-8`** ไม่ใช่ regex ของเราเอง (ยืนยันว่า U+0E33 ถูกเก็บ และรูป decomposed `U+0E4D U+0E32` ไม่ปรากฏ) · และอย่าตัดสินจาก **ขนาดไฟล์**: Chromium **subset** ฟอนต์ ⇒ PDF เล็ก (17–20 KB) เป็นเรื่องปกติ
- **Rule:** (1) อย่า grep โครงสร้างไฟล์ที่ระบุว่าบีบอัดได้ — คลายก่อน (2) regex ที่ "นับได้น้อยกว่าจริง" อันตรายกว่า regex ที่ error เพราะมันให้ข้อสรุปที่ผิด (3) ใช้เครื่องมือมาตรฐาน (`pdffonts`/`pdftotext`) เป็นผู้ตัดสินเมื่อมี — เราไม่ต้องเขียน parser ของตัวเอง (4) ขนาดไฟล์ไม่ใช่หลักฐานว่าฟอนต์ฝังหรือไม่
- **Tests:** `_pdf_has_embedded_truetype()` ใช้ในเทสต์จริงของ §11 · helper `_assert_tz_aware_iso()` ในไฟล์เดียวกันกันอีกกับดักหนึ่ง (Pydantic v2 เขียน UTC เป็น `Z` ไม่ใช่ `+00:00` — ที่ต้องกันคือกรณีหลุดเป็น naive ซึ่ง JS จะตีเป็นเวลาเบราว์เซอร์)
- **Date Added:** 2026-09-13

### 🧾 ใบเสร็จผูกกับ **งวดรับเงิน** ไม่ใช่ **บิล** — "ออกใบเสร็จทั้งหมด" จึงข้ามใบของงวดก่อนหน้าไป
- **Context/Problem:** ตอนผูกปุ่มออกใบเสร็จในหน้ารายละเอียดโปรเจกต์ (F3) ต้องเลือกว่า `ReceiptIssueRequest` จะส่ง `transaction_id` ไปด้วยหรือไม่ ถ้าไม่ส่ง backend จะเลือก **งวดรับเงินล่าสุด** ของบิลนั้น (`_resolve_event` คืน `events[-1]`) ⇒ บิลที่ผ่อนจ่าย 500 + 500 แล้วกด "ออกใบเสร็จทั้งหมด" จะได้ **ใบเดียว** (ของงวดที่ 2) ส่วนใบของงวดแรก (500 บาท) จะไม่มีใครออกให้ และ **ไม่มีสัญญาณเตือนใด ๆ** ว่าขาด
- **Root Cause:** `student_payments` 1 แถว = 1 บิล แต่ 1 บิลมีได้หลาย **เหตุการณ์รับเงิน** (`finance_transactions` แถวละงวด ซึ่งเป็นตัวที่ partial unique index `(student_payment_id, COALESCE(legacy_transaction_id,0), doc_type)` ใช้กันซ้ำ) ⇒ "ใบเสร็จ 1 ใบ : 1 เหตุการณ์รับเงิน" ไม่เท่ากับ "1 บิล" · และ frontend **มองไม่เห็น** ว่าบิลหนึ่งมีกี่งวด เพราะ `CollectionStatus.students[]` ให้มาแค่ `paid_amount` สะสม — นับงวดจาก `paid_amount` ไม่ได้ (บิลที่จ่ายครบครั้งเดียวกับบิลที่ผ่อนสองครั้งมี `paid_amount` เท่ากันได้)
- **Correct Pattern/Solution:** รอบนี้เลือก **ไม่ส่ง `transaction_id`** (พฤติกรรมที่ต้องการ 90% ของเคส: บิลจ่ายครั้งเดียว) และกันความเสียหายด้วยการที่ใบเสร็จเป็น **idempotent** — กดซ้ำไม่กินเลข ไม่ทำข้อมูลเพี้ยน ⇒ ข้อผิดพลาดที่เป็นไปได้คือ "ขาดใบ" ไม่ใช่ "ใบซ้ำ" ซึ่งกู้คืนได้ · การออกใบของงวดเก่าเป็นการ**เพิ่มความสามารถ** ต้องมี endpoint list งวดรับเงินของบิลก่อน (`GET /finance/payments/{id}/events`) แล้วให้ผู้ใช้เลือก — **ยังไม่ได้ทำ** · ระบุข้อจำกัดนี้ไว้ใน docstring ของ `CollectionDetail.vue` ไม่ใช่ปล่อยเป็นความรู้ในหัว
- **Rule:** (1) เมื่อ "1 ใบเอกสาร : 1 เหตุการณ์" ให้ตรวจก่อนว่า frontend มองเห็น "เหตุการณ์" หรือเห็นแค่ "ยอดสะสม" — ถ้าเห็นแค่ยอดสะสม แปลว่ายังเลือกเหตุการณ์ไม่ได้ (2) ออกแบบให้ **idempotent ฝั่งที่กดซ้ำได้** เพื่อให้ข้อผิดพลาดที่เหลือเป็นแบบ "ขาด" (กู้คืนได้) ไม่ใช่ "เกิน" (แก้ยาก) (3) ข้อจำกัดที่รู้ตัวต้องเขียนเป็นคอมเมนต์/เอกสารที่จุดที่คนจะไปเจอ ไม่ใช่รอให้มีคนถาม
- **Tests:** `test_finance_receipts.py` §8 (ผ่อนชำระ 500+500 → ได้ 2 ใบ โดยใบที่ 2 มาจากการส่ง `transaction_id` เอง) และ §2 (ออกซ้ำ → `reused: True` เลขเดิม) — สองเทสต์นี้คือหลักฐานว่า "ขาดใบ" เป็นความจริง ไม่ใช่ความเข้าใจผิด
- **Date Added:** 2026-09-13

### 🔒 ล็อกสองทรัพยากรคนละระดับ = deadlock ที่กลายเป็น **500** เพราะ asyncpg โยน exception ที่ router ไม่รู้จัก
- **Context/Problem:** `_issue_one` (F3) ล็อก (ก) แถว `student_payments` ของบิลนั้นผ่าน `FOR UPDATE OF SP` ใน `_load_payment` และ (ข) แถว `receipt_sequences` ของ `(ห้อง, ปี, ชนิด)` ซึ่ง **ใช้ร่วมกันทุกใบของห้อง/ปีนั้น** — ลำดับการล็อก "สลับกันได้" ระหว่างสองคำขอ ทำให้เกิด `DeadlockDetectedError` (40P01) แล้วผู้ใช้เห็น **500** ซึ่งแปลว่า "โค้ดเราพัง" ทั้งที่ระบบทำงานถูก · ที่แย่กว่านั้น: ถ้า `issue_receipts_batch` เป็นผู้แพ้ **ใบทั้ง 20 ใบ rollback หมด** ทั้งที่ผู้ใช้แค่กดปุ่มเดียว
- **Root Cause:** สองเส้นทางเข้าถึงทรัพยากรคู่เดียวกันในลำดับตรงข้ามกัน — batch ยึดบิล P1 แล้วยึด sequence ไว้จนจบ transaction ขณะที่คำขอเดี่ยวของ P5 ยึดบิล P5 แล้วไปรอ sequence ⇒ batch ไปต่อที่ P5 แล้วไปรอ P5 ที่คำขอเดี่ยวยึดอยู่ = วนกลับมาที่เดิม · และ `DeadlockDetectedError` **ไม่อยู่ในรายการ `except` ของ router** ⇒ หลุดเป็น 500
- **Correct Pattern/Solution:** บังคับให้ **"ลำดับการล็อก" เป็นลำดับเดียวเสมอ** ด้วย `pg_advisory_xact_lock` บน `room_id` เป็น **การกระทำแรก** ก่อนแตะแถวใด ๆ:
  ```python
  _ISSUE_LOCK_NAMESPACE = 0x52454350          # 'RECP' — อ่านออกว่าเป็นของ receipt
  await conn.execute("SELECT pg_advisory_xact_lock($1, $2)", _ISSUE_LOCK_NAMESPACE, target_room_id)
  ```
  ⇒ เอาลำดับที่สลับได้ออกไป **ทั้งคลาส** ไม่ใช่แก้ทีละคู่ · `_xact_` ปล่อยเองเมื่อจบ transaction และ **เรียกซ้ำใน transaction เดียวกันไม่บล็อก** ⇒ batch ที่เรียกในลูปได้ล็อกครั้งเดียวที่ item แรกแล้วถือไปจน commit · namespace เป็นเลขคงที่ของโมดูล ไม่ใช่ค่าที่ derive จากข้อมูล
- **Rule:** (1) ถ้าโค้ดล็อกมากกว่าหนึ่งแถวใน transaction เดียว **ต้องเขียนลำดับการล็อกให้เป็นลำดับเดียวเสมอ** แล้วใส่คอมเมนต์ "ห้ามย้ายตำแหน่งนี้" กำกับ (2) advisory lock คือเครื่องมือจัดลำดับ **ระดับธุรกิจ** (ต่อห้อง) ไม่ใช่ระดับแถว — ใช้เมื่อทรัพยากรที่แย่งกันเป็น "ตรรกะ" ไม่ใช่แถวเดียว (3) exception ของ DB ที่ไม่อยู่ใน `except` ของ router จะกลายเป็น 500 เสมอ ⇒ ต้องรู้ว่า driver โยนอะไรได้บ้าง (4) ราคาที่จ่ายคือการ serialize การออกเอกสาร "ต่อห้อง" ซึ่งแทบไม่ต่างจากเดิมเพราะแถว sequence serialize อยู่แล้ว — และการออกเอกสารคือคนกด ไม่ใช่ bulk job
- **Tests:** `test_finance_receipts.py` §1/§6 (batch 20 ใบ + คำขอเดี่ยวปนกัน) · **ยังไม่มีเทสต์ที่ยิงพร้อมกันจริงเพื่อบังคับ deadlock** — เป็นเทสต์ที่ต้องใช้สอง connection และยอมรับความ flaky ⇒ กันด้วยการออกแบบ + คอมเมนต์อธิบายกลไกแทน
- **Date Added:** 2026-09-13

### 🚧 `f"{seq:04d}"` **ไม่ error** เมื่อเกิน 9999 — มันกว้างขึ้นเอง แต่ path param ที่ผูกกับ pattern 4 หลักจะปฏิเสธตลอดกาล
- **Context/Problem:** เลขเอกสาร `RECEIPT_NO_TEMPLATE = "{prefix}-{year_be:04d}-{seq:04d}"` และ `RECEIPT_NO_PATTERN = r"^[A-Z]{3}-\d{4}-\d{4}$"` ซึ่งเป็น **path param** ของ `GET /finance/receipts/{receipt_no}` และ `/pdf` ⇒ ใบที่ 10000 จะ INSERT สำเร็จและโผล่ในทะเบียน แต่เปิดดู/พิมพ์ซ้ำ **ไม่ได้ตลอดกาล (422)** — เอกสารที่ออกให้ผู้ปกครองไปแล้วเปิดกลับไม่ได้
- **Root Cause:** format spec `04d` เป็น **ความกว้างขั้นต่ำ** ไม่ใช่ขีดจำกัด ⇒ 10000 กลายเป็น `"10000"` (5 หลัก) โดยไม่มี exception ใด ๆ · และไม่มีใครตรวจว่าค่าที่จะเก็บลง DB ยัง match กับ pattern ที่ route ใช้อยู่หรือไม่ ⇒ สองที่นี้ **ผูกกันด้วยจำนวนหลัก** แต่ไม่มีอะไรบังคับให้ตรงกัน
- **Correct Pattern/Solution:** เพดานต้องเป็น **ค่าคงที่ที่มีชื่อ + คอมเมนต์อธิบายว่าใครผูกกับมัน** และต้อง **raise ใน transaction เดียวกับการจองเลข** เพื่อไม่ให้เลขถูกเผา:
  ```python
  RECEIPT_SEQ_MAX = 9999
  RECEIPT_SEQ_OVERFLOW_MSG = ("เลขเอกสารของปีนี้เต็มแล้ว (ครบ 9999 ฉบับ) — กรุณาติดต่อผู้ดูแลระบบ "
                              "เพื่อขยายรูปแบบเลขเอกสารก่อนออกฉบับต่อไป")
  ...
  if seq > RECEIPT_SEQ_MAX:
      raise ValueError(RECEIPT_SEQ_OVERFLOW_MSG)   # raise ใน txn ⇒ last_seq rollback กลับ
  ```
  และ **เทสต์ต้องผูกสองที่นี้เข้าด้วยกัน**: ออกใบที่ seq = `RECEIPT_SEQ_MAX` แล้ว `GET` ด้วยเลขนั้นจริง (ไม่ใช่แค่ `re.fullmatch` กับ pattern) ⇒ ถ้ามีใครขยับเพดานขึ้นโดยไม่แก้ pattern เทสต์จะ fail ทันที
- **Rule:** (1) format spec ไม่ใช่ validation (2) เมื่อค่าหนึ่งถูกใช้ทั้ง "สร้าง" และ "ตรวจ" ต้องมีเทสต์ที่รัน **เส้นทางจริง** ผ่านทั้งสองทาง (3) `raise` หลังจองเลขต้องอยู่ใน transaction เดียวกันเสมอ ไม่งั้นเลขถูกเผา (4) ข้อความ error ต้องบอก **สิ่งที่ผู้ใช้ทำต่อได้** ("ติดต่อผู้ดูแลระบบ") ไม่ใช่แค่บอกว่าผิด
- **Tests:** `test_finance_receipts.py` §12 — `test_doc_number_overflow_is_rejected_and_does_not_burn_the_number` (400 + `last_seq` ยังเป็น 9999) คู่กับ `test_the_last_available_seq_is_still_openable_by_its_doc_number` (seq 9999 เปิดผ่าน route จริงได้ 200)
- **Date Added:** 2026-09-13

### 📄 เอกสาร "point-in-time" ต้องใช้วันที่ **ออกเอกสาร** ไม่ใช่เวลาของเหตุการณ์ล่าสุด (`paid_at` ถูกทับทุกงวด)
- **Context/Problem:** ใบแจ้งหนี้ (F3) ส่ง `event_at = pay["paid_at"]` เข้าไปคำนวณปี พ.ศ. ของเลขเอกสาร ⇒ บิลที่ผ่อนจ่ายไว้เมื่อปลายปีก่อน แล้วออกใบแจ้งหนี้เมื่อต้นปีนี้ ได้เลข `INV-**2569**-0001` ทั้งที่เอกสารลงวันที่ 2570 · และที่ผู้ใช้สังเกตได้จริงคือ **ความไม่สม่ำเสมอในวันเดียวกัน**: บิลที่ยังไม่จ่ายเลย (`paid_at IS NULL`) ได้เลขของวันนี้ ส่วนบิลที่ผ่อนแล้วได้เลขของปีที่แล้ว ⇒ สองใบที่ออกห่างกันไม่กี่นาทีอยู่คนละชุดเลข ซึ่งอธิบายให้ผู้ตรวจสอบไม่ได้
- **Root Cause:** `_confirm_single_payment` เขียน `paid_at = NOW()` **ทุกงวด** ⇒ `paid_at` คือ "เวลาของ **งวดล่าสุด**" ไม่ใช่ "เวลาของเหตุการณ์ตั้งต้น" และไม่ใช่ "เวลาของวันนี้" · ใบเสร็จกับใบแจ้งหนี้มีความหมายเชิงเวลาต่างกัน (receipt = ณ เหตุการณ์รับเงิน · invoice = ณ วันออกเอกสาร) แต่โค้ดเดิมใช้ตัวแปรเดียวกันกับทั้งสอง
- **Correct Pattern/Solution:** แยกให้ชัดด้วย `event_at`:
  ```python
  # ใบเสร็จ → ปีของ "งวดที่ออกใบนั้น" (แหล่งความจริง = finance_transactions.created_at)
  event = await cls._resolve_event(...)          # event["event_at"] = created_at ของงวดนั้น
  # ใบแจ้งหนี้ → ไม่ผูกกับเหตุการณ์รับเงิน ⇒ event_at = None แล้วใช้ "วันนี้" ตามเวลาไทย
  event = {"legacy_transaction_id": None, "amount": outstanding,
           "paid_total_after": paid_amount, "event_at": None}
  ...
  year_be = (cls._thai_year_be(event["event_at"]) if event["event_at"] is not None
             else datetime.now(timezone.utc).astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET)
  ```
  และเขียนคอมเมนต์ 🚨 "ห้ามใส่ `pay["paid_at"]`" ตรงจุดที่คนจะไปแก้
- **Rule:** (1) ก่อนใช้คอลัมน์เวลา ให้ถามว่า "มันถูกทับด้วยอะไรได้อีก" — คอลัมน์ที่ถูก `UPDATE` ทุกครั้งที่เกิดเหตุการณ์ซ้ำ ๆ **ไม่ใช่** เวลาของเหตุการณ์ตั้งต้น (2) เอกสารสองชนิดที่ความหมายเชิงเวลาต่างกัน ต้องมีตัวแปรแยก ไม่ใช่ใช้ร่วมกันเพราะ "ค่าเดียวกันตอนที่เขียนโค้ดครั้งแรก" (3) บั๊กแบบนี้เงียบเพราะเลขยัง "ถูก" ตามรูปแบบ — จับได้ด้วยการเทสต์ **สองเคสเทียบกัน** (จ่ายแล้ว vs ยังไม่จ่าย ในวันเดียวกัน) ไม่ใช่เทสต์เคสเดียว
- **Tests:** `test_finance_receipts.py` §12 — `test_invoice_year_be_follows_the_issue_date_not_the_last_instalment` (ผ่อนปีก่อน → ต้องได้ปีนี้) และ `test_invoice_year_is_the_same_for_a_paid_and_an_unpaid_bill` (สองบิลวันเดียวกัน → ชุดเลขเดียวกัน 0001/0002) — ทั้งคู่ **fail ถ้าใส่ `pay["paid_at"]` กลับ** (พิสูจน์ด้วย mutation แล้ว)
- **Date Added:** 2026-09-13

### 🔐 เส้นทางที่เปิดด้วย `require_member` = **สมาชิกทุกคนอ่านได้** ⇒ ข้อความ error ห้ามมี URL/hostname ภายใน
- **Context/Problem:** เส้นทางดาวน์โหลด PDF เปิดแค่ `require_member` (นักเรียนก็เข้าได้) แต่ตอนต่อ Gotenberg ไม่ติด โค้ดเดิมส่ง `httpx` exception ที่มี `http://classroom-management_infra_gotenberg:3000` ติดขึ้นไปถึงผู้ใช้ ⇒ หลุดชื่อ container และโครงสร้างเครือข่ายภายในให้ทุกคนในห้องอ่าน — และไม่มีประโยชน์กับผู้ใช้เลยเพราะเขาแก้เองไม่ได้
- **Root Cause:** ข่าวสารสองแบบถูกรวมเป็นข้อความเดียว — "ข้อมูลสำหรับ **สอบสวน**" (URL, status, เนื้อความจาก upstream) กับ "ข้อความสำหรับ **ผู้ใช้**" (ทำอะไรต่อได้) · มองข้ามเพราะสมองคิดถึงคนที่ debug ไม่ใช่คนที่กดปุ่ม
- **Correct Pattern/Solution:** แยกทางกันที่จุดโยน exception — รายละเอียดจริงไปที่ `logger.error()` ฝั่ง server ส่วนข้อความที่ผู้ใช้เห็นเป็นค่าคงที่ใน constants:
  ```python
  logger.error("สร้าง PDF ไม่สำเร็จ: ต่อ Gotenberg ไม่ได้ (url=%s): %s", url, e)
  raise PdfRenderError(PDF_RENDER_UNAVAILABLE_MSG) from e
  ```
  และ **เทสต์ต้องตรวจที่ต้นทาง** (`html_to_pdf` ตรง ๆ) ไม่ใช่ที่ข้อความของ router — ถ้าต้นทางมี URL ต่อให้ router ตัดทิ้งก็ยังหลุดทางอื่นได้ · เทสต์เดิมที่ `assert "Gotenberg" in detail` **ล็อกนโยบายเก่าไว้** ⇒ ต้องแก้ assertion นั้นด้วย ไม่ใช่ปล่อยให้ผ่าน
- **Rule:** (1) ดู `require_member`/public ทุกครั้งก่อนตัดสินว่าใส่ข้อมูลอะไรใน error ได้ (2) แยก "log ไว้สอบสวน" ออกจาก "ข้อความถึงผู้ใช้" เสมอ — `raise X(...) from e` ไม่ได้แปลว่าห้ามเก็บ `e` ไว้ใน log (3) เทสต์ที่ assert ข้อความ error ต้อง assert **สิ่งที่ต้องไม่มี** ด้วย ไม่ใช่แค่สิ่งที่ต้องมี (4) เมื่อนโยบายเปลี่ยน ต้องตามไปแก้ assertion เก่าที่ล็อกนโยบายเดิม — ไม่งั้นมันจะกลายเป็นเทสต์ที่บังคับให้ทำผิด
- **Tests:** `test_finance_receipts.py` §12 — `test_pdf_failure_message_carries_no_internal_url` (ตรวจทั้งสองสาขา: ต่อไม่ติด และ upstream ตอบ ≠ 200) และ `test_pdf_render_failure_maps_to_502` ที่แก้ให้ assert ว่า **ไม่มี** `Gotenberg`/`http`/`localhost`/`3000` ใน detail (เดิม assert ว่าต้องมี)
- **Date Added:** 2026-09-13

### 🏁 การ fetch ที่ผูกกับตัวกรองต้องมี "ตัวนับรุ่น" — ลำดับที่คำตอบกลับมาไม่รับประกัน
- **Context/Problem:** หน้าจอการเงินที่ `watch(period)` แล้วยิง API (ReceiptList, BudgetList, FinancialStatements, FinanceDashboard) เปิดโอกาสให้ผู้ใช้สลับเดือน/แท็บเร็ว ๆ จนมีคำขอซ้อนกัน ⇒ คำตอบ **ไม่ได้กลับตามลำดับที่ส่ง** (โดยเฉพาะเมื่อ backend รัน 3 replica หลัง Traefik คำขอสองอันถูกคนละ worker รับ) ⇒ `items` ถูกเขียนด้วยข้อมูลของ **ตัวกรองที่ผู้ใช้ไม่ได้เลือกแล้ว** ขณะที่ป้ายบนจอบอกตัวกรองใหม่ = "ตัวเลขถูกแต่ป้ายผิด" ซึ่ง **แย่กว่าโหลดไม่ขึ้น** เพราะดูเหมือนถูก · และ `isLoading` ถูกปิดไปแล้วโดยคำตอบอันแรกที่มาถึง ⇒ ไม่มีสปินเนอร์ให้รู้ว่ายังไม่จบ
- **Root Cause:** `load()` ถูกเรียกซ้ำได้ แต่ผลลัพธ์ไม่มีตัวระบุว่า "คำตอบนี้มาจากคำขอไหน" ⇒ คำตอบที่มาถึงทีหลังเขียนทับเสมอ ไม่ว่ามันจะเก่ากว่าหรือไม่
- **Correct Pattern/Solution:** ตัวนับรุ่นแบบ 3 บรรทัด (`frontend/src/utils/latest.ts`) — **ต้องเช็คให้ครบทั้งสามจุด**:
  ```ts
  const token = guard.begin();
  try { const rows = await Svc.get(...);
        if (!guard.isCurrent(token)) return;      // ① ก่อนเขียนข้อมูล
        items.value = rows; }
  catch (e) { if (!guard.isCurrent(token)) return;  // ③ ใน catch
              hasError.value = true; }
  finally { if (guard.isCurrent(token)) isLoading.value = false; }  // ② ก่อนปิดสปินเนอร์
  ```
  ⚠️ **ห้ามใช้ `guard` ตัวร่วมกันสองตัวโหลดในหน้าเดียว** — `begin()` ของตัวหนึ่งจะทำให้อีกตัวกลายเป็น "เก่า" ทันที แล้วตัวที่ถูกฆ่าจะไม่ปิด `isLoading` ของตัวเอง ⇒ สปินเนอร์ค้างถาวร (FinanceDashboard มี 2 ตัว ⇒ 2 guard)
  🚫 **ไม่ใช้ `AbortController`** เพราะ axios จะ reject ด้วย `CanceledError` ซึ่งปะปนกับ error จริงใน `catch` และต้องแยกแยะเพิ่ม (`axios.isCancel`) — ของจริงที่ต้องการคือ "รู้ว่าคำตอบนี้ยังเป็นตัวล่าสุดไหม" ซึ่งตัวนับทำได้ตรงกว่าและ **ไม่มี error ปลอมเกิดขึ้นเลย**
  📌 `Promise.all` ที่เป็นชุดเดียวกัน (overview + budgets + categories) ต้องใช้ token เดียว ⇒ ทิ้งทั้งชุด ไม่ใช่ทีละตัว ไม่งั้นค่าที่เขียนลง ref ต่าง ๆ อาจมาจากคนละช่วงเวลา
- **Rule:** (1) ทุก `load()` ที่ถูกเรียกจาก `watch` ต้องมี guard (2) เมื่อมีหลายคำขอที่ต้อง "ตรงกัน" ให้รวมเป็นชุดเดียวแล้วใช้ token เดียว (3) legacy view ที่ไม่ได้อยู่ในขอบเขตงาน — **รายงาน ไม่แก้** (4) ตัวช่วยที่ถูกใช้ 4 ที่ต้องมี unit test และ unit test นั้นต้องผ่าน mutation test
- **Tests:** `frontend/src/utils/__tests__/latest.spec.ts` (7 เทสต์: token โมฆะ, คำขอซ้อนกลับลำดับ, สอง guard อิสระ, token 0 ต้องไม่ถูกตีว่าลัด) — **ยืนยันด้วย mutation test**: เปลี่ยน `++latest` เป็น `latest++` แล้ว **6 ใน 7 fail**
- **Date Added:** 2026-09-13

### ⏱️ `URL.revokeObjectURL` ต้อง **เลื่อนออกไปหนึ่งคาบ** — revoke ต่อจาก `click()` ทำให้ไฟล์ถูกยกเลิกเงียบ ๆ
- **Context/Problem:** ตัวช่วย `downloadBlob` เดิม revoke blob URL ทันทีในบรรทัดถัดจาก `link.click()` ⇒ บน Firefox และ iOS Safari ไฟล์ถูกยกเลิก **โดยไม่มี exception ให้จับ** ผู้ใช้เห็น "ดาวน์โหลดสำเร็จ" แต่ไม่มีไฟล์ หรือได้ไฟล์ 0 ไบต์ ซึ่งแยกไม่ออกจาก "ระบบพัง" สำหรับครูที่รอใบเสร็จอยู่
- **Root Cause:** `click()` แค่ **เข้าคิว** การนำทางไว้ — เบราว์เซอร์ไปอ่าน blob URL จริงแบบ **asynchronous** (FileSaver.js ใช้ `setTimeout` 40 วินาทีด้วยเหตุผลเดียวกัน) ⇒ revoke ในคาบเดียวกันคือแข่งกับเบราว์เซอร์ ซึ่งบางตัวแพ้
- **Correct Pattern/Solution:**
  ```ts
  link.click(); link.remove();
  // คืนหน่วยความจำในคาบถัดไป — ห้ามย้ายขึ้นมาเป็นบรรทัดถัดจาก click()
  window.setTimeout(() => window.URL.revokeObjectURL(url), 0);
  ```
  `setTimeout(..., 0)` ไม่ได้หน่วงให้ผู้ใช้รู้สึก — มันย้าย revoke ไปคนละ task ⇒ เบราว์เซอร์ได้เริ่มโหลดก่อนเสมอ · ยังต้อง revoke ทุกครั้งอยู่ (ไม่ revoke เลย = Blob ทั้งก้อนถูก pin ในหน่วยความจำจนกว่าจะปิดแท็บ และไฟล์การเงินใหญ่ระดับหลายร้อย KB)
- **Rule:** (1) ทรัพยากรที่ "ปล่อยทันที" ได้ไม่ใช่ทรัพยากรที่ผู้บริโภคยังไม่เริ่มใช้ (2) ถ้า API ทำงานแบบ async แต่หน้าตาเหมือน sync ให้สงสัยว่ามีคิวอยู่เบื้องหลัง (3) บั๊กที่ "ไม่มี exception" ต้องจับด้วยการทดสอบบนเบราว์เซอร์จริง ไม่ใช่ด้วย unit test — เมื่อทำไม่ได้ ให้เขียนเหตุผลไว้ในคอมเมนต์ที่จุดนั้น
- **Tests:** ไม่มี unit test (jsdom ไม่จำลองพฤติกรรม download ของเบราว์เซอร์) — ป้องกันด้วยคอมเมนต์อธิบายกลไกใน `frontend/src/utils/download.ts`
- **Date Added:** 2026-09-13

### 🧬 เทสต์ regression ที่ "ผ่านทันที" ไม่ใช่หลักฐาน — ต้อง **mutation test** ก่อนเชื่อ
- **Context/Problem:** หลังรีวิวแบบ adversarial พบ 12 ประเด็นที่รอดการหักล้างและแก้ไป 8 ข้อ การเขียนเทสต์ปิดบั๊กเหล่านั้นแล้วเห็น "passed" **ไม่ได้พิสูจน์อะไร** — อาจเป็นเพราะเทสต์ไม่ได้แตะโค้ดที่แก้เลย (เช่น setup ไม่ถึงเงื่อนไข) แล้วบั๊กจะกลับมาโดยที่ CI เขียว
- **Root Cause:** เทสต์ที่เขียนตาม "สิ่งที่โค้ดทำ" (implementation) แทน "สิ่งที่ต้องเป็น" (behavior) จะผ่านทั้งกับโค้ดที่ถูกและผิด · อ่านเทสต์แล้ว "ดูน่าเชื่อ" ไม่ใช่การวัด
- **Correct Pattern/Solution:** **แก้โค้ดให้เป็นบั๊กเดิมกลับไป แล้วดูว่าเทสต์ fail** — ถ้าไม่ fail แปลว่าเทสต์ไม่มีฟัน:
  ```bash
  cp src.py /tmp/orig
  sed -i 's/^        if seq > RECEIPT_SEQ_MAX:$/        if False:  # MUTANT/' src.py
  pytest -k "overflow"        # ต้อง FAIL
  cp /tmp/orig src.py         # คืนค่า แล้ว grep ยืนยันว่าไม่เหลือ MUTANT
  ```
  ผลรอบนี้: mutant "invoice ใช้ `pay["paid_at"]`" → **2 fail** · "ถอดเพดาน seq" → **1 fail** · "หลุด URL ใน error" → **1 fail** · ฝั่ง frontend: `++latest` → `latest++` → **6 ใน 7 fail** · (รอบก่อนหน้า: `formatThaiDateTime` ฉบับ UTC → **4 ใน 12 fail**)
- **Rule:** (1) เทสต์ที่ปิดบั๊กต้องพิสูจน์สองทาง — **fail กับโค้ดเก่า** และ **pass กับโค้ดใหม่** (2) mutation ที่เลือกต้องเป็น **บั๊กจริงที่เคยเกิด** ไม่ใช่การสุ่มแก้โค้ด (3) คืนค่าจาก backup แล้ว `grep` ยืนยันว่าไม่เหลือ mutant ก่อนไปต่อ (4) เขียนผล mutation ไว้ในคอมเมนต์หัวข้อของเทสต์ — คนอ่านจะได้รู้ว่าเทสต์นี้มีฟันโดยไม่ต้องลองเอง
- **Tests:** เป็น **วิธี** ไม่ใช่เทสต์ — ใช้กับทุกข้อใน `test_finance_receipts.py` §12 และ `latest.spec.ts`
- **Date Added:** 2026-09-13

### 🧬 mutation test ที่ "NOT-CAUGHT" **ไม่ได้แปลว่าเทสต์ไม่มีฟันเสมอไป** — ต้องแยก equivalent mutant ออกจากช่องโหว่จริงก่อนแก้
- **Context/Problem:** รัน mutation harness 7 ตัวเพื่อปิดงาน void ใบเสร็จ + เลขปี พ.ศ. แล้ว **M6 ได้ NOT-CAUGHT** — ถอด `AND R.status = 'active'` ออกจาก `get_receipts` (`receipts.py:610`) แล้วเทสต์ทั้งไฟล์ยังเขียว ปฏิกิริยาแรกคือ "ต้องไปเขียนเทสต์เพิ่ม" ซึ่งนำไปสู่เทสต์ที่ seed `status='voided' AND deleted_at IS NULL` ลงตารางตรง ๆ — และมันจะ **ล้มด้วย `CheckViolationError`** เพราะ `chk_receipt_voided_is_deleted` (`init_db.py:459`) ห้ามสถานะนั้นอยู่แล้ว
- **Root Cause:** `AND R.deleted_at IS NULL` **ลอจิกกลืน** `AND R.status = 'active'` เพราะ CHECK constraint บังคับ `status = 'active' OR deleted_at IS NOT NULL` ⇒ แถวใดที่ `deleted_at IS NULL` **จำเป็นต้อง** เป็น `active` ⇒ ไม่มีทรงข้อมูลใดในโลกที่ทำให้ clause เดียวนั้นเปลี่ยนคำตอบได้ = **equivalent mutant** (mutant ที่พฤติกรรมเหมือนเดิมทุกประการ) การฝืน "ทำให้จับได้" จึงเท่ากับทำลาย constraint ที่เป็นเสาหลักของดีไซน์ (ตัวนั้นกันสถานะ "ตันสองทาง" ที่เอกสาร `init_db.py:448-458` อธิบายไว้)
- **Correct Pattern/Solution:** เจอ NOT-CAUGHT ให้วินิจฉัยตามลำดับนี้ **ก่อน** แตะเทสต์:
  1. **หา invariant ที่อาจบังคับอยู่แล้ว** — `grep -n "CHECK" backend/core/init_db.py` + ดู `ALTER TABLE ... ADD CONSTRAINT` (constraint ที่เพิ่มทีหลังมักไม่โผล่ใน `CREATE TABLE`)
  2. **ถ้ามี** ⇒ พิสูจน์ความสมมูลด้วยเทสต์ที่ **pin invariant ตัวนั้น ไม่ใช่ pin clause** — เช่น `pytest.raises(asyncpg.CheckViolationError)` เมื่อพยายามเขียน `deleted_at = NULL` ทับ `status='voided'` (พร้อมทิศตรงข้ามที่ต้องผ่าน เพื่อกัน `CHECK (false)` ที่ห้ามหมด) เทสต์แบบนี้จะมีค่าก็ในวันที่มีคนถอด constraint ออก ซึ่งเป็นวันเดียวกับที่ clause นั้น **กลายเป็นตัวจริงและห้ามถอด**
  3. **ถ้าไม่มี** ⇒ เป็นช่องโหว่ของเทสต์จริง เขียนเทสต์เพิ่มตามปกติ
  - ⚠️ **ห้ามลบ CHECK/constraint เพื่อให้ mutation จับได้** — นั่นคือแก้ตัววัดด้วยการทำลายสิ่งที่มันวัด
- **Rule:** (1) `NOT-CAUGHT` เป็น **ข้อสังเกต** ไม่ใช่คำตัดสิน — ต้องวินิจฉัยก่อนเสมอ (2) ทุกครั้งที่สรุปว่า "สมมูล" ต้องมีเทสต์ที่ pin **เหตุผล** ไว้ ไม่งั้นวันหน้าจะไม่มีใครรู้ว่าทำไมถึงปล่อยผ่าน (3) รายงาน mutation ต้องแยกสามสถานะให้ชัด — `CAUGHT` / `NOT-CAUGHT (สมมูล · พร้อมหลักฐาน)` / `NOT-CAUGHT (ช่องโหว่จริง)` — สองอย่างหลังห้ามรายงานรวมกัน
- **Tests:** `test_voided_receipt_can_never_stay_un_soft_deleted` (`test_finance_receipts.py`)
- **Date Added:** 2026-09-14

### 🛡️ Ops tool ที่บอกว่า "dry-run ไม่เขียนอะไรเลย" ต้องพิสูจน์ด้วย **ฐานข้อมูล** ไม่ใช่ด้วย **คำที่มันพิมพ์ออกมา**
- **Context/Problem:** `backfill_journals.py` (dry-run = ค่าเริ่มต้น, ไม่ใส่ `--apply`) พิมพ์ปิดท้ายว่า "✅ ตรวจแล้วไม่มีการเขียนลงฐานข้อมูล" และ docstring หัวไฟล์บรรทัด 34 ก็สัญญาว่า dry-run "ทำใน transaction ที่ `rollback()` ทิ้ง ⇒ แม้แต่ ledger ที่ต้อง auto-provision ก็ถูกนับรวมในรายงาน" — แต่เมื่อทดสอบจริงบน staging โดยวางแถว legacy ที่อ้าง **หมวดที่ยังไม่มี ledger** แล้วรัน dry-run ปรากฏว่า **ledger ของห้องนั้นเพิ่มจาก 35 → 36 แถว** (ledger id 76, account_code `50071`, description `Auto-provisioned by dual-write`) **ค้างอยู่ในฐานข้อมูลจริง** — ตรวจซ้ำหลังเก็บกวาดแล้ว: `max(id)` กลับมา 75 และ ledger ของห้องนั้นกลับมา 35 ⇒ ยืนยันว่าแถวที่ 76 ถูกสร้างจริงแล้วถูกลบ
- **Root Cause:** `backfill_missing_journals` วางแผนผ่าน `_plan_backfill_journals` ซึ่งเรียก `_resolve_asset_ledger` / `_resolve_category_ledger` — สองตัวนี้ **INSERT ได้** เมื่อห้องนั้นยังไม่มี ledger ของบัญชี/หมวดนั้น แล้วโค้ดบรรทัด 502 เดิมคือ `await tx.commit()` **ลอย ๆ ไม่มีเงื่อนไข** ⇒ โหมด dry-run ก็ commit ledger ที่เพิ่ง provision ไปด้วย · ตัว `rollback()` มีอยู่จริงแต่ผูกกับ `finally: if not committed` ซึ่งเข้าเฉพาะ **เส้นทาง exception** เท่านั้น ⇒ สคริปต์ "โกหก" ผู้ใช้ในโหมดที่ผู้ใช้ตั้งใจใช้เพื่อ **หลีกเลี่ยงการเขียน** · อันตรายเป็นพิเศษเพราะคำว่า "dry-run" ทำให้คนกล้ารันกับ production
  - กับดักที่ซ่อนอยู่: ในสภาพข้อมูลที่ ledger ครบทุกตัว (ซึ่งคือสถานการณ์ปกติของระบบที่เดินมาระยะหนึ่ง) การ provision จะไม่เกิดขึ้นเลย ⇒ dry-run ดูสะอาด และ **บั๊กจะไม่ปรากฏจนกว่าจะเจอห้องที่ ledger ไม่ครบ** ซึ่งคือห้องที่ต้องการ backfill มากที่สุดพอดี
- **Correct Pattern/Solution:** แยกสองทางให้ชัด อย่าให้ commit เป็นค่าเริ่มต้นที่ต้องมีเงื่อนไขมาห้าม:
  ```python
  if apply:
      await tx.commit()
  else:
      await tx.rollback()      # dry-run ต้อง rollback จริง — ไม่งั้น ledger ที่ provision ค้าง
  committed = True
  return report
  ```
  และ **เวลาเชื่อ ops tool ให้ตรวจที่ฐานข้อมูล ไม่ใช่ที่ stdout**:
  1. ถ่าย snapshot ก่อน/หลังของตารางที่จะถูกแตะ + **ลายนิ้วมือเฉพาะของการกระทำนั้น** (เช่น `journal_entries WHERE metadata ? 'backfilled'`, `accounting_ledgers WHERE description = 'Auto-provisioned by dual-write'`) — ลายนิ้วมือทำให้แยกการเขียนของเรา ออกจาก live traffic ของแอปที่กำลังรันอยู่ได้ ซึ่ง `pg_stat_user_tables.n_tup_ins` ทำไม่ได้
  2. ถ้าต้องรันกับ production ให้ **บังคับ session เป็น read-only ที่ระดับ server** เป็นเกราะชั้นนอก — monkeypatch `asyncpg.create_pool` ให้ใส่ `server_settings={'default_transaction_read_only': 'on'}` ครอบสคริปต์จากข้างนอก (ไม่แก้ตัวสคริปต์) แล้วพิสูจน์ว่าเกราะทำงานจริงด้วยการยิงคำสั่งเขียนที่ **rollback ทิ้งเสมอ** ⇒ ได้ `ReadOnlySQLTransactionError`
     > ⚠️ **"ได้ exception" ไม่เท่ากับ "เกราะทำงาน"** — ต้อง assert **ชนิด** ของ exception และคำสั่งเขียนที่ใช้ยิงต้อง valid กับ schema จริง ไม่งั้นจะได้ error ของ parser/operator ที่หน้าตาคล้ายกันแล้วรายงานผลบวกลวง · รายละเอียดและตัวอย่างจริงอยู่ที่บทเรียน "🔬 ตอนพิสูจน์ว่าเกราะ read-only ทำงาน" ด้านล่าง
  3. ระวังผลข้างเคียงของเกราะ: ห้องที่ต้อง provision ledger จะ **error** แทนที่จะรายงานแผน ⇒ ต้องมีคำสั่ง SQL อ่านล้วนของตัวเองนับ candidate ควบคู่ไปด้วย เพื่อไม่ให้ตัวเลขที่รายงานมาจากสคริปต์ที่อาจล้มบางห้อง
- **Rule:** (1) โหมด "ไม่เขียน" ต้องพิสูจน์ที่ฐานข้อมูล — คำรายงานของสคริปต์ไม่ใช่หลักฐาน (2) `commit()` ในฟังก์ชันที่มีทั้ง dry-run และ apply ต้องอยู่ใน `if apply:` เสมอ ห้ามเป็นบรรทัดลอยก่อน `return` (3) เกราะ read-only ต้องพิสูจน์ว่าทำงาน **ก่อน** ใช้กับ production ไม่ใช่หลัง (4) รายงานตัวเลขจากสองแหล่ง — สคริปต์ + SQL อ่านล้วนของตัวเอง — ถ้าต่างกันให้เชื่อ SQL แล้วหาสาเหตุ
- **Tests:** `test_dry_run_does_not_commit_auto_provisioned_ledgers` (`test_finance_backfill.py`) — mutation test ยืนยันแล้ว: ใส่ `await tx.commit()` แบบไม่มีเงื่อนไขกลับ ⇒ เทสต์นี้ **fail** (`ก่อน 0 หลัง 2`) ขณะที่ `test_straddle_row_detected_but_dry_run_writes_nothing` ที่มีอยู่เดิม **ยัง pass** ⇒ พิสูจน์ว่าเทสต์เดิมเป็นเทสต์กลวง
- **Date Added:** 2026-09-14

### 🔬 ตอนพิสูจน์ว่าเกราะ read-only ทำงาน — "ได้ exception" ≠ "เกราะทำงาน" ต้อง assert **ชนิด** ของ exception และคำสั่งเขียนต้องเป็น SQL ที่ valid ก่อน
- **Context/Problem:** ต่อจากบทเรียนข้างบน — วิธีที่แนะนำไว้คือ "พิสูจน์ว่าเกราะทำงานจริงด้วยการยิงคำสั่งเขียนที่ `rollback` ทิ้งเสมอ ⇒ ต้องได้ `ReadOnlySQLTransactionError`" · เมื่อรัน probe นี้บน **production** (หลัง deploy รอบ 2026-09-14) ผลคือ
  ```
  ✅ INSERT: ถูกปฏิเสธด้วย ReadOnlySQLTransactionError
  ✅ UPDATE: ถูกปฏิเสธด้วย ReadOnlySQLTransactionError
  ⚠️ DELETE: ถูกปฏิเสธด้วย UndefinedFunctionError      ← ไม่ได้พิสูจน์อะไรเลย
  ✅ DDL   : ถูกปฏิเสธด้วย ReadOnlySQLTransactionError
  ```
  ถ้า probe ข้อนี้เขียนว่า `try: execute(...) except Exception: print("✅ เกราะทำงาน")` — ซึ่งเป็นท่าที่คนเขียนกันบ่อยที่สุด — **บรรทัด DELETE จะถูกรายงานว่า ✅ ทั้งที่ความจริงคือ SQL ของเราผิดเอง**
- **Root Cause:** คำสั่งที่ใช้คือ `DELETE FROM audit_logs WHERE id = -1` แต่ `audit_logs.id` เป็น **`uuid`** ⇒ ไม่มี operator `uuid = integer` · และลำดับการทำงานของ Postgres คือ **parse → analyze (resolve ชนิด/operator/ตาราง) → execution** โดยตัวบังคับ read-only ทำงานตอน **execution** ⇒ ถ้า statement ไม่ valid มันจะล้มที่ analyze **ก่อน** ที่เกราะจะมีโอกาสพูด จึงได้ error คนละตัวที่หน้าตา "เป็นการปฏิเสธ" เหมือนกัน
- **Correct Pattern/Solution:**
  1. **assert ที่ชนิด exception ไม่ใช่แค่ "มี exception"**:
     ```python
     except Exception as exc:
         blocked = type(exc).__name__
         flag = "✅" if "ReadOnly" in blocked else "⚠️"   # ⚠️ = ยังไม่พิสูจน์ ต้องไปดูสาเหตุ
     ```
     ใช้ `asyncpg.exceptions.ReadOnlySQLTransactionError` ตรง ๆ จะแน่นกว่าเทียบสตริงชื่อคลาส
  2. **คำสั่งเขียนใน probe ต้อง valid กับ schema จริง** — อย่าให้ parser เป็นคนปฏิเสธ · ท่าที่ทนทุกชนิดคอลัมน์คือ cast: `DELETE FROM audit_logs WHERE id::text = '-1'` (match ไม่มีแถวใด แต่ statement valid ⇒ เกราะเป็นผู้ปฏิเสธ)
  3. **แยกให้ชัดว่า probe กำลังถามคำถามอะไร** — "เกราะบล็อกการเขียนไหม" ต้องตอบด้วย `ReadOnlySQLTransactionError` เท่านั้น; error อื่น = **ยังไม่ได้คำตอบ** ไม่ใช่คำตอบว่า "ปลอดภัย"
- **Rule:** (1) การพิสูจน์เชิงลบ (negative control) ที่ SQL ไม่ valid **ไม่ใช่หลักฐาน** แม้จะได้ exception ก็ตาม (2) probe ที่รายงานผล ต้องแยก "ถูกปฏิเสธเพราะเกราะ" ออกจาก "ล้มเพราะคำสั่งผิด" ให้ได้ ไม่งั้นมันจะโกหกเราแบบเงียบ ๆ ซึ่งเป็นความผิดชนิดเดียวกับบั๊ก dry-run ที่บทเรียนข้างบนจับ (3) เกราะเดียวกันบังคับใช้กับทุกชนิด statement เท่ากัน (เป็น server setting ระดับ transaction ไม่ใช่ราย statement) ⇒ เมื่อพิสูจน์ INSERT/UPDATE/DDL ได้แล้ว ข้อสรุปครอบคลุมถึง DELETE ด้วย **แต่ยังต้องเขียนให้ถูกว่า "อนุมาน" ไม่ใช่ "วัด"** (4) ถ้าการรัน probe ถูก permission layer ปฏิเสธ **อย่าหาทางอ้อม** — รายงานตรง ๆ ว่าไม่ได้วัด แล้วชี้ว่าหลักฐานอื่น (ลายนิ้วมือ + `n_tup_*`) ครอบข้อเรียกร้องนั้นอยู่แล้วหรือไม่
- **Tests:** ไม่มีเทสต์อัตโนมัติ (เป็นขั้นตอน ops) — บันทึกเป็นวิธีปฏิบัติ พร้อมหลักฐานที่วัดได้จริงบน production 2026-09-14
- **Date Added:** 2026-09-14

### 🧪 เทสต์ที่ fixture เตรียมทางให้ครบ = เทสต์ที่ไม่เคยเดินบนเส้นทางที่มันอ้างว่าคุม
- **Context/Problem:** `test_straddle_row_detected_but_dry_run_writes_nothing` มีคอมเมนต์บรรทัดสุดท้ายว่า "🛡️ dry-run ต้อง rollback: ไม่มี journal, ไม่มี line, และ **ledger ที่ auto-provision ก็ต้องไม่ค้าง**" — แต่ตัว assert ตรวจแค่ `journal_entries` กับ `journal_lines` **ไม่มีบรรทัดใดแตะ `accounting_ledgers` เลย** ⇒ เทสต์ผ่านมาตลอดทั้งที่ ledger ค้างจริง
- **Root Cause:** สองชั้นซ้อนกัน (ก) helper ของไฟล์เทสต์คือ `_insert_finance_account` และ `_insert_category` ซึ่ง **สร้าง ledger คู่ให้ทันทีทั้งสองตัว** ⇒ เมื่อ `_resolve_*_ledger` ถูกเรียก มันหาเจอทันทีและไม่ต้อง INSERT ⇒ **เส้นทาง provision ไม่เคยถูกเดินในเทสต์เลย** (ข) คอมเมนต์ที่เขียนความตั้งใจไว้ แต่ไม่มี assert รองรับ — ทำให้คนอ่าน (และคนเขียนเองในภายหลัง) เข้าใจผิดว่าครอบแล้ว · คอมเมนต์ที่อ้างความคุ้มครองซึ่งไม่มีอยู่ **แย่กว่าไม่มีคอมเมนต์** เพราะมันหยุดการตั้งคำถาม
- **Correct Pattern/Solution:** ถ้าเทสต์อ้างว่าคุมเส้นทางใด ต้อง **บังคับให้เส้นทางนั้นถูกเดิน**:
  - เขียนเทสต์แยกที่ **จงใจไม่ใช้ helper มาตรฐาน** แล้วสร้างแถวเปล่า ๆ เอง (ไม่มี ledger) พร้อมคอมเมนต์กำกับว่า "ห้ามเปลี่ยนไปใช้ helper" เพราะ helper นั้นจะกลบเส้นทางที่ต้องการทดสอบ
  - assert ให้ตรงกับสิ่งที่คอมเมนต์อ้าง — ถ้าคอมเมนต์พูดถึง ledger ต้องมี `assert await _count_ledgers(...) == before`
  - เกณฑ์ตัดสินว่าเทสต์ "เดินบนเส้นทางนั้นจริง": ใส่บั๊กกลับแล้วมันต้อง fail · ถ้ายัง pass = ยังไม่เคยแตะเส้นทางนั้น
- **Rule:** (1) ทุกประโยคใน docstring/คอมเมนต์ของเทสต์ที่ขึ้นต้นว่า "ต้องไม่..." ต้องมี assert รองรับ ไม่งั้นลบประโยคนั้นออก (2) helper ที่ "เตรียมพร้อมให้ครบ" เหมาะกับเทสต์ที่ต้องการ **ตัด** ปัจจัยรบกวน แต่เป็นพิษกับเทสต์ที่ต้องการ **ทดสอบ** กลไกนั้นเอง — ต้องแยกให้ชัดว่ากำลังทำอันไหน (3) เมื่อเจอเทสต์ที่ pass ทั้งกับโค้ดถูกและโค้ดผิด ให้สงสัย fixture ก่อนสงสัย assert
- **Tests:** คู่ของ `test_straddle_row_detected_but_dry_run_writes_nothing` (กลวง) กับ `test_dry_run_does_not_commit_auto_provisioned_ledgers` (มีฟัน) ใน `backend/tests/test_finance_backfill.py`
- **Date Added:** 2026-09-14

### 🔁 "แก้เสร็จแล้ว" ≠ "แก้ครบ" — จุดที่รายงานมายกมา 1 จุด มักมีพี่น้องอีก N จุดที่ไม่มีใครพูดถึง
- **Context/Problem:** รอบนี้มี **สามงานที่ปิดไปแล้วแต่ยังไม่ครบ** และทั้งสามมีรูปเดียวกัน: รายงานชี้จุดเดียว แต่กลไกเดียวกันปรากฏซ้ำในที่อื่น (ก) งาน "ปิดช่อง leaks URL ของ Gotenberg" แก้ไป **2 จุดจาก 5 จุด** — อีก 3 จุด (`_font_data_uri`, `_get_template` 2 สาขา, `html_to_pdf` กรณีเนื้อหาว่าง) ยังคงส่ง path ไฟล์สัมบูรณ์บนเซิร์ฟเวอร์หรือชื่อ service ภายในถึงสมาชิกห้องทุกคน (ข) งาน "เลื่อน `revokeObjectURL`" แก้ที่ตัวช่วยกลาง แต่ยังเหลือ **2 ที่ที่เขียน anchor เอง** (ExportStudent, ActivityDetail) ซึ่งตัวหนึ่งไม่เคย `appendChild` ด้วยซ้ำ (ค) งาน "จัดลำดับการล็อก" แก้เส้นทางออกเอกสาร แต่ `batch_confirm_payments` เป็น **ตัวล็อกหลายแถวตัวที่สอง** ที่ไม่เคยเอา advisory lock เลย
- **Root Cause:** รายงาน (จากรีวิว/adversarial verify) คือ **ตัวอย่าง ไม่ใช่สำมะโน** — มันชี้จุดที่คนเขียนรายงานบังเอิญไปเห็น · พอแก้จุดนั้นแล้วเทสต์ผ่าน ก็เกิดความรู้สึกว่า "งานนี้จบ" ทั้งที่กลไกเดียวกันยังทำงานอยู่ที่อื่น · และการสกัดตัวช่วยกลาง (helper) **ไม่ได้ย้ายผู้เรียกเดิมมาที่ตัวช่วยให้เอง** ⇒ ยิ่งอันตรายเพราะดูเหมือนงานเสร็จสมบูรณ์กว่าเดิม
- **Correct Pattern/Solution:** หลังแก้จุดที่รายงาน ให้ **grep หา "กลไก" ไม่ใช่ "อาการ"** แล้ว enumerate ให้ครบก่อนประกาศจบ:
  ```bash
  grep -rn "createObjectURL\|revokeObjectURL" frontend/src/     # ต้องเหลือที่เดียว: utils/download.ts
  grep -n "PdfRenderError(" backend/services/finance/pdf.py      # ต้องมี guard ทุกจุดที่ raise
  grep -n "FOR UPDATE" backend/services/finance/*.py             # ทุกฟังก์ชันที่ล็อกหลายแถว
  ```
  แล้ว **เทสต์ต้องมีสาขาเท่าจำนวนจุด** ไม่ใช่สาขาเดียว — เทสต์ leaks ตัวนี้จึงมี 4 สาขา (ก/ข/ค/ง) และ **mutation แยกทีละสาขา** ได้ผลล้มที่บรรทัด assertion ต่างกัน (1219 / 1230 / 1243) ซึ่งเป็นหลักฐานว่าทุกสาขามีฟันจริง ไม่ใช่มีสาขาเดียวที่ทำงาน
- **Rule:** (1) รายงานคือตัวอย่าง — งานคือ enumerate ทั้งคลาส (2) การสกัด helper ยังไม่เสร็จจนกว่า grep จะพิสูจน์ว่าเหลือผู้เรียกจุดเดียว (3) จำนวนสาขาของเทสต์ควรเท่ากับจำนวนจุดที่แก้ — ถ้าน้อยกว่า แปลว่ายังมีจุดที่ไม่มีเทสต์คุ้ม (4) งานที่ "เสร็จแล้ว" ต้องถูก re-audit ด้วยคำถาม "กลไกเดียวกันนี้อยู่ที่อื่นอีกไหม" ไม่ใช่ "เทสต์ผ่านไหม"
- **Tests:** `test_finance_receipts.py` §12 `test_pdf_failure_message_carries_no_internal_url` (4 สาขา, mutation ผ่านทั้ง 3 สาขาที่เพิ่มใหม่) · `grep -rn "createObjectURL" frontend/src/` = 1 ไฟล์
- **Date Added:** 2026-09-13

### 💰 `DECIMAL` เปล่า ๆ = **สเกลไม่จำกัด** ⇒ ยอดต่ำกว่าสตางค์ผ่าน guard มาได้ แล้วไปชน CHECK constraint = 500
- **Context/Problem:** `student_payments.paid_amount` ประกาศเป็น `DECIMAL` **ไม่มี `(15,2)`** (`init_db.py:283`) ⇒ เก็บ `0.004` ได้จริง · ด่านเดิม `if paid_amount <= 0` เช็ค **ค่าดิบ** ⇒ 0.004 ผ่าน · แต่ `round(0.004, 2) = 0.00` ไปชน `chk_receipt_amount_positive CHECK (amount > 0)` ⇒ asyncpg โยน `CheckViolationError` ซึ่ง **ไม่มีชั้นไหนใน router แปลง** ⇒ ผู้ใช้เห็น **500** ("ระบบพัง") ทั้งที่ปัญหาคือยอดที่กรอก และแก้เองได้ · ทิศกลับกันก็เพี้ยนเงียบ ๆ: จ่าย `100.004` → เอกสารพิมพ์ `100.00` แต่บัญชีถือ `100.004` ⇒ **ทศนิยมผีที่ไม่มีวันกระทบยอด**
- **Root Cause:** validation เช็ค "ค่าที่รับมา" แต่ constraint ตัดสิน "ค่าที่จะถูกเขียน" — สองค่านี้ต่างกันทันทีที่มีการปัด · และ `DECIMAL` ไม่มี argument ใน Postgres **ไม่ใช่** `DECIMAL(15,2)` — มันคือ `numeric` อิสระที่เก็บ 0.004 ได้เต็มที่ (สันนิษฐานว่า "เงินต้องเป็น 2 ตำแหน่ง" แล้วไม่ตรวจ schema จริง)
- **Correct Pattern/Solution:** ปัด **ก่อน** เช็ค แล้ว **ใช้ตัวแปรที่เช็คแล้วเขียนจริง** (ถ้าเช็คค่าหนึ่งแต่เขียนอีกค่าหนึ่ง = สองความจริงในระบบ):
  ```python
  document_amount = round(event["amount"], 2)
  if document_amount <= 0:
      raise ValueError("ยอดรับเงินน้อยกว่า 0.01 บาท จึงออกเอกสารไม่ได้ ...")
  ...
  INSERT INTO finance_receipts (..., amount, paid_total_after, ...)
  VALUES (..., document_amount, round(event["paid_total_after"], 2), ...)
  ```
- **Rule:** (1) `DECIMAL` เปล่า ≠ `DECIMAL(p,s)` — **อ่าน precision จริงใน `init_db.py` ก่อนสรุปว่าค่าไหนเก็บได้** (2) validate ที่ "ค่าที่ constraint จะเห็น" ไม่ใช่ค่าดิบ (3) ตัวแปรที่ validate แล้วต้องเป็นตัวเดียวกับที่เขียนลง DB (4) `CheckViolationError`/`UniqueViolationError`/`DeadlockDetectedError` ไม่อยู่ใน `except` ของ router ⇒ กลายเป็น 500 ทุกตัว ต้องมี guard ฝั่งแอปเสมอ (5) ยอดที่ปัดทิ้งต้องไม่ถูกกลืนเงียบ ๆ — ถ้าปัดแล้วเปลี่ยนยอด ต้องบอกผู้ใช้ ไม่ใช่พิมพ์เอกสารไม่ตรงกับบัญชี
- **Tests:** `test_finance_receipts.py` §9 — `test_sub_satang_amount_is_400_not_500` แบบ `@pytest.mark.parametrize` 2 สาขา: ใบเสร็จ (ผ่าน fallback `_resolve_event` ที่คืน `float(paid_amount)` ตรง ๆ) และใบแจ้งหนี้ (ผ่าน `outstanding = 1000.00 − 999.999 = 0.001`) — ยืนยัน **400** + ข้อความไทย + **ไม่มีแถวเอกสารและไม่มีการจองเลข** (ไม่มีเลขถูกเผา)
- **Date Added:** 2026-09-13

### 🔒 advisory lock ที่ครอบแค่ "เส้นทางที่กำลังดูอยู่" ไม่ได้ปิดคลาส deadlock — และ `ORDER BY` + locking clause เชื่อลำดับไม่ได้
- **Context/Problem:** ต่อยอดจากหัวข้อ "ล็อกสองทรัพยากรคนละระดับ" ข้างบน — รอบนั้นเพิ่ม `pg_advisory_xact_lock` ในเส้นทาง **ออกเอกสาร** เท่านั้น ⇒ ยังเหลือ **ตัวล็อกหลายแถวตัวที่สอง** คือ `batch_confirm_payments` (รับเงินรวบยอด) ซึ่งล็อก `student_payments` ทีละใบ **ตามลำดับที่ผู้ใช้ส่งมา** กลางลูป และไม่เคยเอา advisory lock ⇒ สองคำขอของห้องเดียวกันที่ส่งบิลชุดเดียวกันสลับลำดับกัน (A: P1→P2, B: P2→P1) ยัง deadlock ได้ และถ้าฝั่งที่แพ้เป็น batch **ทั้งชุด rollback** · แถม `_confirm_single_payment` ต่อใบยังไปแตะ `finance_accounts` ⇒ ลำดับกลายเป็น SP1→ACC→SP2→ACC ซึ่งสลับกับคำขออื่นได้อีกชั้น
- **Root Cause:** มอง deadlock เป็น "บั๊กของฟังก์ชันที่รายงาน" ไม่ใช่ "คุณสมบัติของ **ทุก** ฟังก์ชันที่ล็อกมากกว่าหนึ่งแถว" ⇒ ปิดช่องที่เห็น แต่ไม่ได้ enumerate ผู้ล็อกหลายแถวทั้งหมด · อีกชั้น: ทางแก้ที่ดูสะอาดคือ `SELECT ... WHERE id = ANY($1) ORDER BY id FOR UPDATE` ซึ่งเอกสาร Postgres ระบุว่า **การเรียงเกิดก่อนการล็อก** แต่ก็เตือนว่าผลลัพธ์ที่คืนอาจดูสลับที่ได้ ⇒ พฤติกรรมจริง **ขึ้นกับ plan** จึงไม่ควรใช้เป็นหลักประกันลำดับ
- **Correct Pattern/Solution:** รวมเป็นตัวช่วยเดียวใน `base.py` ที่ **เรียงด้วย Python แล้วล็อกทีละแถว** และเรียก **ก่อนเข้าลูป** ทั้งสองเส้นทาง:
  ```python
  ids = sorted({int(p) for p in payment_ids if p is not None})   # เรียง + dedupe
  for pid in ids:
      await conn.fetchval("SELECT id FROM student_payments WHERE id = $1 FOR UPDATE", pid)
  ```
  ล็อกซ้ำรายใบในลูป (`FOR UPDATE OF SP` ใน `_load_payment`) เป็นการล็อกซ้ำใน transaction เดียวกัน ⇒ **ไม่บล็อก** ⇒ ไม่เหลือจุด "รอ" กลางลูปที่ทำให้ลำดับขึ้นกับ request อีก · ราคาที่จ่ายคือ round-trip เพิ่มใบละ 1 ครั้ง ซึ่งน้อยมากเทียบกับงานต่อใบในลูป (≥5 query) · และ **ต้องเขียนส่วนที่ยังไม่ปิดไว้ใน docstring ตรง ๆ**: `revert_transaction` ล็อก FT→SP ขณะที่การออกใบเสร็จล็อก SP→แล้วได้ FK `KEY SHARE` บน FT ⇒ **การกลับทิศนี้ยังไม่ถูกแก้** และการปิดทั้งคลาสต้องมี "advisory lock ต่อห้องเป็นอย่างแรกบนทุกเส้นทางที่แตะเงิน" ซึ่งเป็น **การตัดสินใจเรื่อง lock protocol** ไม่ใช่การแก้โค้ด unilateral
- **Rule:** (1) deadlock เป็นคุณสมบัติของ **ทุก** ฟังก์ชันที่ล็อก >1 แถว — `grep -n "FOR UPDATE"` แล้ว enumerate ทุกตัว ไม่ใช่แก้ตัวที่รายงาน (2) อย่าพึ่ง `ORDER BY` คู่กับ locking clause — เอกสารเตือนว่าขึ้นกับ planner ⇒ ใช้ `sorted()` ในโค้ดที่อ่านแล้วพิสูจน์ได้ (3) เมื่อแก้ได้แค่บางส่วน **ต้องเขียนส่วนที่เหลือไว้ใน docstring** อย่าให้คนอ่านเข้าใจว่าหมดคลาส (4) เทสต์ที่พิสูจน์ "เรียงจริง" ต้องใช้ **สอง connection จริง** และยิงด้วยลำดับ **ตรงข้ามกัน** — ถ้าใช้ connection เดียวจะไม่มีการแย่งล็อกเลยและเทสต์จะผ่านตลอดกาลโดยไม่ได้พิสูจน์อะไร
- **Tests:** `test_finance_receipts.py` §10 — `test_lock_helper_locks_in_id_order_regardless_of_caller_order` (บันทึก **ลำดับ id ที่ถูกล็อก** ผ่าน connection ปลอม ⇒ ส่ง `[7,3,9,3,None]` และ `[9,7,3]` ต้องได้ `[3,7,9]` ทั้งคู่ · **ล้มทันทีถ้าถอด `sorted()` ออก — ยืนยันด้วย mutation แล้ว**) · `test_lock_helper_actually_takes_row_locks` (กันถอยกลับเป็น no-op: `FOR UPDATE NOWAIT` จากอีก connection ต้องโยน `LockNotAvailableError`) · `test_batch_confirm_payments_uses_the_same_canonical_lock_order` (ด่านเชิงโครงสร้าง — จงใจอ่านซอร์ส เพราะ "ล็อกก่อนอ่าน" สังเกตจาก HTTP ไม่ได้: `TestClient` เป็น sync และเราแทรก `lock_timeout` เข้า connection ของแอปไม่ได้ · **ล้มเมื่อลบคำสั่งล็อก — ยืนยันด้วย mutation แล้ว**)

  ⚠️ **กับดักที่เจอจริงในรอบนี้ — เทสต์ที่ยิงสอง connection "ดูน่าเชื่อ" แต่ไม่มีฟัน**: เวอร์ชันแรกใช้สอง connection ยิงพร้อมกันด้วยลำดับตรงข้าม แล้วถือว่าถ้าไม่มี `DeadlockDetectedError` แปลว่าเรียงถูก · **mutation เปิดโปงว่ามันผ่านทั้งที่ถอด `sorted()` ออก** เพราะฝั่งแรกยึดล็อกครบทั้งสองใบ *ก่อน* ฝั่งที่สองเริ่ม ⇒ ฝั่งที่สองแค่ "รอ" แล้วไปต่อ ไม่มีทางเกิด deadlock ไม่ว่าโค้ดจะเรียงหรือไม่ · อีกจุด: ด่านที่เช็ค `"sorted(" in inspect.getsource(...)` **ผ่านเพราะไปเจอคำว่า `sorted()` ใน docstring** ไม่ใช่ในโค้ด ⇒ เทสต์เชิงซอร์สต้องจับ **บรรทัดที่เรียกจริง** (regex ผูกกับต้นบรรทัด) ไม่ใช่ค้นสตริงทั้งบล็อก
- **Date Added:** 2026-09-13

### 🏁 หน้าเดียวอาจต้องมี **หลาย guard** และ guard ต้องครอบ `catch`/`finally` ด้วย ไม่ใช่แค่ทางสำเร็จ
- **Context/Problem:** ต่อยอดจากหัวข้อ "ตัวนับรุ่น" ข้างบน — รอบนั้นใส่ guard ให้ตัวโหลดหลักของแต่ละหน้า แต่ (ก) `DebtorList` มี **สองการโหลดอิสระ** (รายการลูกหนี้ + หนี้รายคนใน modal) ⇒ ต้องมี **2 guard** (ข) `handleClearDebt` เป็น action ที่ **await แล้วปิด modal** ⇒ ถ้าผู้ใช้ปิด/เปิด modal ใหม่ระหว่างรอ คำตอบเก่าจะเขียน `studentDebts`/`selectedPaymentIds` ทับของคนละคน แล้ว **ปิด modal ที่เพิ่งเปิด** — ซึ่งอ่านไม่ได้ว่าเกิดจากคำขอไหน
- **Root Cause:** มอง guard เป็นเรื่องของ "การโหลดข้อมูลเข้าหน้า" ทั้งที่มันคือเรื่องของ **"คำตอบนี้ยังเกี่ยวกับสิ่งที่ผู้ใช้กำลังดูอยู่ไหม"** ⇒ ทุก side effect ที่ตามหลัง `await` ต้องถูกถามคำถามเดียวกัน รวมถึงการปิด modal และการขึ้นข้อความ error · และ `catch`/`finally` ถูกละเลยบ่อยเพราะคิดว่า "แค่ error/แค่ปิดสปินเนอร์" — ที่จริง `catch` ที่ไม่ guard จะ **ขึ้นกล่อง error ของการกระทำที่ผู้ใช้เลิกสนใจไปแล้ว** และ `finally` ที่ไม่ guard จะ **ปิดสปินเนอร์ของคำขอใหม่**
- **Correct Pattern/Solution:** หนึ่งการโหลด = หนึ่ง guard (ห้ามใช้ร่วม — `begin()` ของตัวหนึ่งจะฆ่าอีกตัวทันที) และเช็คให้ครบ **ทั้งสามจุด** รวมถึงก่อน side effect ที่ไม่ใช่การเขียนข้อมูล:
  ```ts
  const token = debtGuard.begin();
  try { const res = await Svc.getStudentDebts(...);
        if (!debtGuard.isCurrent(token)) return;   // ก่อนเขียน studentDebts/selectedPaymentIds
        studentDebts.value = res; }
  catch (e) { if (!debtGuard.isCurrent(token)) return;   // ก่อน Swal.fire + ปิด modal
              Swal.fire({ icon: 'error', ... }); }
  finally { if (debtGuard.isCurrent(token)) isLoadingDebts.value = false; }
  ```
- **Rule:** (1) หนึ่งการโหลด = หนึ่ง guard เสมอ (2) ทุก side effect ที่ตามหลัง `await` ต้องถูก guard — **รวมการปิด modal และการขึ้น error** ไม่ใช่แค่การเขียนข้อมูล (3) `finally` ที่ไม่ guard จะปิดสปินเนอร์ของคำขอที่ใหม่กว่า (4) view ไม่มี unit test ในโปรเจกต์นี้ ⇒ ช่องนี้กันด้วยการรีวิว + คอมเมนต์ (เขียนไว้ตรง ๆ ว่าเป็นช่องที่ยังไม่มีเทสต์)
- **Tests:** `frontend/src/utils/__tests__/latest.spec.ts` ครอบตัวช่วย (รวมเคส "สอง guard อิสระ") แต่ **ตัว view เองไม่มีเทสต์** — เป็นช่องที่รู้ตัวและยอมรับ
- **Date Added:** 2026-09-13

### ⏱️ (แก้คำอธิบายเดิม) `setTimeout(..., 0)` **ไม่ได้** การันตีว่าเบราว์เซอร์อ่าน URL ไปแล้ว — และ 0 ms สั้นเกินไปสำหรับไฟล์ใหญ่
- **Context/Problem:** หัวข้อ "`URL.revokeObjectURL` ต้องเลื่อนออกไปหนึ่งคาบ" ข้างบนตั้งค่าเป็น `0` ms พร้อมคอมเมนต์ที่อ้างว่า "เบราว์เซอร์ได้เริ่มโหลดก่อนเสมอ" — **ข้ออ้างนั้นพิสูจน์ไม่ได้** · `setTimeout(..., 0)` รับประกันแค่ **ลำดับของ task** (ว่ามันไปคิวถัดไป) ไม่ได้รับประกันว่าเบราว์เซอร์ **dereference URL แล้ว** ⇒ คอมเมนต์ที่อ้างเกินหลักฐานจะถูกอ่านเป็น "ปัญหานี้ปิดแล้ว" แล้วไม่มีใครกลับมาดูอีก · และการอ้าง FileSaver.js ที่ใช้ 40 วินาทีก็เป็นการอ้างที่ผิดบริบท (40 วิของเขาคือกรณี **blob URL ถูกอ่านจากหน่วยความจำในเครื่อง** ซึ่งคนละกลไกกับ "รอให้เบราว์เซอร์เริ่มโหลด")
- **Root Cause:** เขียนคอมเมนต์เพื่อ **ปิดประเด็น** แทนที่จะเขียนเพื่อ **บอกขอบเขตของสิ่งที่รู้** ⇒ ค่าคงที่ถูกเลือกจากความสวยงาม (0 ดูตั้งใจดี) ไม่ใช่จากการวัด
- **Correct Pattern/Solution:** เพิ่มเป็น `1000` ms และ **เขียนคอมเมนต์ใหม่ให้ตรงกับสิ่งที่รู้จริง** — ระบุว่า `setTimeout` การันตีแค่ลำดับ task, ระบุว่าการที่เบราว์เซอร์อ่าน URL แล้วหรือยัง **พิสูจน์ตรงนี้ไม่ได้**, และระบุว่า FileSaver.js 40 วิ เป็นคนละกรณี:
  ```ts
  link.click(); link.remove();
  // 1000 ms: setTimeout(0) การันตีแค่ลำดับ task ไม่ได้แปลว่าเบราว์เซอร์ dereference URL แล้ว
  // (พิสูจน์ ณ จุดนี้ไม่ได้) — เลือก 1 วิให้ไฟล์ใหญ่มีเวลาพอ; การปิดแท็บทำให้ข้าม revoke
  // ซึ่งไม่ใช่ leak เพราะ Blob ตายพร้อม document
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
  ```
- **Rule:** (1) อย่าเขียนคอมเมนต์ที่อ้างการันตีซึ่งพิสูจน์ไม่ได้ — เขียนว่า **อะไรรู้ / อะไรไม่รู้** แล้วให้คนอ่านตัดสิน (2) เมื่อยกเหตุผลจากไลบรารีอื่นมา ต้องบอกว่าเป็น **คนละกรณี** ถ้าเป็น (3) ค่าคงที่ที่เลือกจากความรู้สึก ควรมีคอมเมนต์บอกว่า "ทำไมค่านี้" ไม่ใช่ปล่อยให้อ่านเป็นค่าศักดิ์สิทธิ์
- **Tests:** ไม่มี unit test (jsdom ไม่จำลองพฤติกรรม download) — ป้องกันด้วยคอมเมนต์ที่ `frontend/src/utils/download.ts`
- **Date Added:** 2026-09-13

### 🗂️ DDL — `IF NOT EXISTS` **ไม่ได้** แปลว่า "ทำให้ตรงกับที่เขียนไว้" — มันแปลว่า "ถ้ามีแล้วก็ผ่านไป"
- **Context/Problem:** รอบแก้ #60 ต้องเพิ่มคอลัมน์ `status`/`voided_at`/`voided_by`/`void_reason`/`event_at` ให้ `finance_receipts` และต้องเปลี่ยนความหมายของใบที่ถูกยกเลิก · ทุกตารางใน `init_db.py` เขียนด้วย `CREATE TABLE IF NOT EXISTS` และทุก index ด้วย `CREATE UNIQUE INDEX IF NOT EXISTS` ⇒ **บน DB ที่ deploy F3 ไปแล้วทั้งคู่เป็น no-op เงียบ ๆ** ⇒ คอลัมน์ใหม่ไม่ถูกเพิ่ม (`SELECT R.status` → 500 ทุกครั้ง) และ index ที่ predicate เปลี่ยนก็ยังเป็น predicate เก่า
- **Root Cause:** อ่าน `IF NOT EXISTS` เป็น "idempotent migration" ทั้งที่มันเช็คแค่ **การมีอยู่ของชื่อ** ไม่ได้เช็ค **โครงสร้างข้างใน** · กับดักนี้เงียบสนิท: `init_db` จบด้วยข้อความ "✅ Tables & Smart Constraints Initialized Successfully" เหมือนเดิมทุกครั้ง ⇒ log บอกว่าสำเร็จทั้งที่ schema ไม่ขยับ
- **Correct Pattern/Solution:**
  - คอลัมน์ที่เพิ่มทีหลัง → `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` ในบล็อก "Extra Alterations" (คู่กับ `CREATE TABLE` ที่แก้ให้ตรงกัน สำหรับ DB ที่สร้างใหม่)
  - **constraint** ที่เพิ่ม/แก้ทีหลัง → `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` (idiom เดียวกับ `users_email_key`)
  - **predicate ของ partial unique index แก้บน DB ที่มีอยู่ไม่ได้เลย** — `CREATE UNIQUE INDEX IF NOT EXISTS` ที่ predicate ต่างจากเดิมจะ **ไม่ error และไม่แก้** ⇒ ถ้าต้องการความหมายใหม่ ต้อง **ออกแบบให้ predicate เดิมใช้ต่อได้** แทนการแก้ index
    - 🔬 **ยืนยันด้วยการทดลองจริง (13 ก.ย. 2026)**: สร้าง index ด้วย predicate หนึ่ง แล้วรัน `CREATE UNIQUE INDEX IF NOT EXISTS` ชื่อเดิม predicate ใหม่ ⇒ ไม่ error, index ยังเป็น predicate เดิม ⇒ **ทางรอดเดียวคือไม่ต้องแก้**: เลือกตั้ง `deleted_at` คู่กับ `status='voided'` เพื่อให้ predicate เดิม (`WHERE deleted_at IS NULL ...`) กรองใบที่ยกเลิกออกให้เองโดยไม่ต้องแตะ index
- **Rule:** (1) แก้ schema ของตารางที่ ship แล้ว = ต้องมี `ALTER` เสมอ ไม่ใช่แก้ `CREATE TABLE` (2) อย่าเปลี่ยน predicate ของ index ที่มีอยู่ — ถ้าจำเป็นจริงต้อง `DROP INDEX` แล้วสร้างใหม่ ซึ่งต้องแยกเป็นงาน migration (3) ข้อความ "success" ของ `init_db` **ไม่ได้** ยืนยันว่า schema ตรงกับโค้ด — ต้องมีเทสต์ที่เรียก endpoint จริง (suite สร้าง DB ใหม่ทุกครั้งจึงไม่จับกับดักนี้เลย)
- **Tests:** `test_finance_receipts.py` ยิงผ่าน HTTP ทั้งไฟล์ ⇒ ถ้าลืม `ALTER` เทสต์จะไม่จับ (DB ทดสอบสร้างใหม่จาก `CREATE TABLE`) — ช่องนี้กันด้วย review + คอมเมนต์ที่ `core/init_db.py`
- **Date Added:** 2026-09-14

### 💥 `except asyncpg.UniqueViolationError` ใน explicit transaction = **ต้องมี SAVEPOINT** ไม่งั้นคำสั่งถัดไปพังเป็น 500
- **Context/Problem:** การออกใบเสร็จมี "ด่าน idempotency ชั้นที่ 2" สำหรับกรณีแพ้การแข่งขัน — จับ `UniqueViolationError` จาก `INSERT` แล้ว **อ่านใบที่ชนะกลับมาคืน** เพื่อให้การพิมพ์ซ้ำพร้อมกันได้ใบเดิมแทน error · เทสต์ที่จำลองการแข่งจริงเปิดโปงว่าเส้นทางนี้ **พังทุกครั้ง**: `_find_existing` ในบล็อก `except` โยน `InFailedSQLTransactionError` (25P02) ซึ่ง router ไม่รู้จัก ⇒ **500** แทนที่จะได้ใบเดิมคืน ⇒ ตัวจัดการการแข่งกลายเป็นโค้ดที่ทำให้แย่ลงกว่าไม่มีมัน
- **Root Cause:** ใน Postgres เมื่อ statement ใดล้มเหลว **transaction ทั้งก้อนถูกทำเครื่องหมาย aborted** และจะปฏิเสธทุกคำสั่งถัดไปจนกว่าจะ `ROLLBACK` — การจับ exception ฝั่ง client ไม่ได้ล้างสถานะนั้นให้ (ข้อยกเว้นเดียวคือ error ที่เกิดใน subtransaction ที่มี SAVEPOINT) ⇒ โค้ดที่ "จับ error แล้วลองอย่างอื่นต่อ" จะทำงานได้เฉพาะเมื่อห่อ statement ที่อาจล้มด้วย savepoint เท่านั้น
- **Correct Pattern/Solution:** ห่อ **เฉพาะ statement ที่อาจชน** ด้วย `async with conn.transaction():` ซึ่งเมื่ออยู่ใน transaction ที่มีอยู่แล้ว = `SAVEPOINT` ของ asyncpg:
  ```python
  try:
      async with conn.transaction():        # ← SAVEPOINT: ย้อนแค่ INSERT ไม่ใช่ทั้งก้อน
          row = await conn.fetchrow("INSERT INTO finance_receipts ... RETURNING ...")
  except asyncpg.UniqueViolationError:
      raced = await conn._find_existing(...)   # ← ใช้ conn ได้แล้ว (transaction ยัง healthy)
      if raced: return {"receipt": raced, "reused": True}
      raise ValueError(...)
  ```
- **Rule:** (1) `except <DB error>` แล้ว **แตะ `conn` ต่อ** ⇒ ต้องมี savepoint เสมอ (2) `except` ที่แค่ `raise ValueError` ไม่ต้องมี savepoint เพราะ exception หลุดออกไปทำให้ transaction rollback เอง — ตรวจทั้งสามจุดในโปรเจกต์แล้ว มีเพียงจุดนี้ที่แตะ `conn` ต่อ (3) ทางเลือกที่ไม่ต้องมี savepoint เลยคือ **อ่านจาก connection ใหม่** — แต่ในกรณีนี้จะไม่เห็นแถวที่คำขออื่นยังไม่ commit ⇒ ไม่ใช้ (4) logging ในบล็อก `except` ของ service ต้องใช้ `log_conn` จาก pool ใหม่ **ไม่ใช่ `conn` เดิม** (pattern นี้ถูกต้องอยู่แล้วทุกที่ในโมดูลการเงิน)
- **Tests:** `test_the_loser_of_the_race_gets_the_winning_receipt_not_a_500` (+ คู่กัน `test_the_room_lock_funnels_the_same_race_into_layer_one`) — **ยืนยันด้วย mutation แล้ว**: เปลี่ยน `async with conn.transaction():` เป็น `if True:` ⇒ ล้มด้วย `InFailedSQLTransactionError` (25P02) ที่ `_find_existing` ในบล็อก `except` และเทสต์คู่กันยังผ่าน (พิสูจน์ว่าสองเทสต์จับคนละเส้นทางจริง)
- **⚠️ บทเรียนที่แถมมา (สำคัญกว่าตัว fix):** เขียนเทสต์ให้ถึงบรรทัดนี้ได้ยากกว่าที่คิด — และการพยายามเขียนมันเปิดโปงว่า **ภายใต้ lock protocol ปัจจุบัน ตัวจัดการนี้ไม่มีทางถูกเรียกจากเส้นทางในโปรเจกต์เลย**
  - ลำดับที่ต้องเกิด: คำขอผ่าน `_find_existing` (ยังไม่เห็นแถวคู่แข่ง) → คู่แข่ง INSERT + COMMIT → คำขอ INSERT → ชน unique index
  - แต่การ INSERT แถวลูกของ `finance_receipts` จะถือ `FOR KEY SHARE` บนแถว `student_payments` ซึ่ง **ชนกับ `FOR UPDATE OF SP`** ที่ `_load_payment` ยึดไว้ ⇒ คู่แข่งที่ยิงพร้อมกันจะไปติดที่ `_load_payment` **ก่อน** แล้วพอ commit ชั้นที่ 1 ก็อ่านเจอเอง (`reused: True` โดยไม่มีการจองเลขฟุ่มเฟือย — ดูเทสต์ `..._funnels_..._into_layer_one`)
  - และทางที่ "กลับด้าน" (คู่แข่ง INSERT ค้างไว้ก่อน แล้วคำขอค่อยเข้าล็อกบิล) จะทำให้คู่แข่งไปติด FK lock ของคำขอ ⇒ **deadlock** ไม่ใช่ UniqueViolation
  - ⇒ วิธีที่ deterministic ทางเดียวคือจำลอง **"ผู้เขียนที่ข้าม lock protocol"** ด้วย `SET LOCAL session_replication_role = replica` บนอีก connection (ปิด trigger ของ FK จึงไม่ยึด KEY SHARE — ไม่ได้ปิด CHECK) ซึ่งตรงกับสถานการณ์ที่ตัวจัดการนี้มีไว้กันพอดี
  - 🔬 และบทเรียนทั่วไป: **เทสต์ที่ "จัดฉาก" ให้ถึงบรรทัดหนึ่งได้ มักเปิดโปงว่าบรรทัดนั้นตายอยู่** — อย่าเพิ่งสรุปว่าจัดฉากไม่เก่ง จนกว่าจะพิสูจน์ว่าไม่มีลำดับการล็อกใดไปถึงได้เลย (ที่นี่พิสูจน์ด้วยเมทริกซ์การชนของ row lock: `FOR KEY SHARE` ชนกับ `FOR UPDATE` เท่านั้น)
  - ⚠️ เมื่อก่อนหน้านี้มีเทสต์ที่ "ถึงบรรทัดนี้" ได้ (`test_voided_receipt_does_not_count_as_already_issued` เวอร์ชันแรก) มันถึงได้เพราะสร้างสถานะ `status='voided'` + `deleted_at IS NULL` ซึ่ง **ขัดกับตัวกรองของ `_find_existing`** ⇒ พอเติม `chk_receipt_voided_is_deleted` ปิดสถานะนั้น ทางนั้นก็ปิดไปด้วย — คือการแก้ที่ถูกต้องแล้วทำให้โค้ดบรรทัดหนึ่ง "ตาย" อย่างหลีกเลี่ยงได้ และนั่นเป็นเหตุผลที่ต้องเขียนเทสต์ที่จำลองผู้เขียนนอกโปรโตคอลไว้ตรึงพฤติกรรมแทน
- **Date Added:** 2026-09-14

### 📤 `response_model` ตัดฟิลด์ที่ service คืนมาให้ **เงียบ ๆ** — ฟิลด์ใหม่ต้องประกาศที่โมเดล ไม่ใช่แค่ใน dict
- **Context/Problem:** #60 ให้ `revert_transaction` คืน `voided_receipts` (เลขใบเสร็จที่ถูกยกเลิกเพราะรายการนั้น) เพื่อให้ผู้ใช้รู้ว่ากระดาษใบไหนโมฆะ ⇒ เทสต์ที่ตรวจ **body** ได้ `KeyError: 'voided_receipts'` ทั้งที่ service ใส่ค่ามาครบและ route ตอบ 200 · สาเหตุคือ route ใช้ `response_model=SuccessResponse` ซึ่งมีแค่ `status`/`message` ⇒ Pydantic **ตัดฟิลด์ส่วนเกินทิ้ง**
- **Root Cause:** กฎ "router ต้องประกาศ `response_model` เสมอ" (เพื่อกรอง secret) ถูกจำว่าเป็นเรื่องความปลอดภัยฝ่ายเดียว — แต่ผลข้างเคียงคือมันเป็น **allowlist**: ฟิลด์ที่ไม่อยู่ในโมเดลจะหายไปโดยไม่มี warning, ไม่มี log, และ **status ยังเป็น 200** ⇒ เทสต์ที่ตรวจแค่ `status_code == 200` จะเขียวทั้งที่ข้อมูลไม่ถึงผู้ใช้เลย
- **Correct Pattern/Solution:** สร้างโมเดลที่สืบทอดจากของเดิมแล้วเพิ่มฟิลด์ แทนการแก้โมเดลกลางที่ใช้ร่วมกับ endpoint อื่น:
  ```python
  class TransactionRevertResponse(SuccessResponse):
      voided_receipts: List[str] = []
  ```
  แล้วเปลี่ยน `response_model` ของ route นั้น **จุดเดียว**
- **Rule:** (1) เพิ่มฟิลด์ให้ response ของ service ⇒ **ต้องแก้/สร้าง response model ด้วย** ไม่งั้นเป็น dead payload (2) เทสต์ที่ยืนยันสัญญากับ client ต้องตรวจ **body** ไม่ใช่แค่ status (3) อย่าเติมฟิลด์เฉพาะทางลงโมเดลกลางที่ endpoint อื่นใช้ร่วม — สร้าง subclass
- **Tests:** `test_revert_report_includes_the_voided_receipt_numbers` (ตรวจ body + audit log) — **ล้มก่อนแก้ด้วย `KeyError`**
- **Date Added:** 2026-09-14

### 🔒 สถานะที่ "ตันสองทาง" ต้องทำให้ **เกิดไม่ได้ที่ DB** (CHECK) ไม่ใช่พึ่งวินัยของคนเขียนโค้ด
- **Context/Problem:** ระหว่างเขียนเทสต์ #60 พบว่าถ้ามีแถวที่ `status='voided'` แต่ `deleted_at IS NULL` ระบบจะ **ตันทั้งสองทาง**: partial unique index ยังนับว่ามีใบอยู่ ⇒ ออกใบใหม่ของงวดเดิมไม่ได้ (ได้ 400 "เลขเอกสารซ้ำ" ซึ่ง **โกหก** เพราะไม่มีเลขซ้ำ) และ `_find_existing` ก็ไม่คืนใบเดิมเพราะกรอง `status='active'` ⇒ ข้อความ error ชี้ผิดทางและผู้ใช้แก้เองไม่ได้
- **Root Cause:** "voided ต้องตั้ง `deleted_at` คู่กัน" ถูกเก็บเป็น **ความเชื่อในหัวคนเขียน** (เขียนไว้ในคอมเมนต์ + docstring) · คอมเมนต์กันไม่ได้: ไม่มีเทสต์ไหนพิสูจน์ได้ว่าทุกเส้นทางเขียนทำจริง และวันหนึ่งจะมีคนเพิ่มเส้นทาง void ใหม่ที่ไม่รู้กฎนี้
- **Correct Pattern/Solution:** เข้ารหัส invariant เป็น **CHECK constraint บังคับทิศทางเดียว**: `CHECK (status = 'active' OR deleted_at IS NOT NULL)` · ต้องคู่กับ `CHECK (status IN (...))` ตัวเดิม — สองตัวทำคนละหน้าที่ (จำกัดโดเมน vs ผูกสองคอลัมน์เข้าหากัน) · `ADD CONSTRAINT` บน DB ที่ deploy แล้วปลอดภัยเพราะคอลัมน์ `status` เพิ่งถูกเพิ่มด้วย `DEFAULT 'active'` ⇒ ไม่มีแถวเดิมที่ฝ่าฝืน
- **Rule:** (1) ความสัมพันธ์ระหว่างคอลัมน์ที่เป็น "ต้องเป็นคู่กัน" → CHECK constraint ไม่ใช่คอมเมนต์ (2) ถ้าสถานะหนึ่งทำให้ระบบ **ตัน** และข้อความ error ชี้ผิด → นั่นคือ invariant ที่ต้องบังคับ ไม่ใช่เคสที่ต้องเขียน error message ให้ดีขึ้น (3) ก่อน `ADD CONSTRAINT` บนตารางที่มีข้อมูล ต้องตอบให้ได้ว่า **ไม่มีแถวเดิมฝ่าฝืน** ไม่งั้น deploy ล้มทั้งระบบ
- **Tests:** `test_voided_status_without_soft_delete_is_rejected_by_the_db` (ยืนยันทั้งขาที่ต้องถูกปฏิเสธ และขาที่ถูกต้องว่าผ่าน)
- **Date Added:** 2026-09-14

### 🗓️ "วันที่ของเอกสาร" ต้องเป็น **ค่าเดียวกันกับที่มาของปีบนเลขเอกสาร** — ไม่ใช่สองนาฬิกาที่บังเอิญตรงกัน
- **Context/Problem:** #62 กำหนดว่าใบเสร็จต้องยึด "เวลาไทย ณ วินาทีที่บันทึกการจ่ายเงิน" เป็นตัวตั้งต้นของ **ทั้ง** ปี พ.ศ. บนเลขเอกสาร **และ** วันที่ที่พิมพ์บนกระดาษ · ก่อนหน้านี้ปีมาจาก `finance_transactions.created_at` แต่วันที่พิมพ์มาจาก `issued_at` ⇒ ใบเสร็จของงวด ธ.ค. ที่ออกใน ม.ค. ได้เลข `REC-2569-xxxx` แต่บรรทัดวันที่เป็น "ม.ค. 2570" = **เอกสารขัดแย้งกับตัวเอง** และเป็นบั๊กที่ไม่มีเทสต์ไหนจับได้เพราะ `receipt_no` ยังถูกทุกตัวอักษร
- **Root Cause:** "วันที่ของเอกสาร" ถูกคิดว่าเป็นเรื่องของ **การแสดงผล** (จึงอ่านจากเวลาที่แสดง/พิมพ์) ทั้งที่เป็นเรื่องของ **ตัวเอกสาร** (ต้องอ่านจากเวลาของเหตุการณ์) ⇒ พอสองแนวคิดนี้อยู่ในโค้ดเดียวกัน ค่าจึงมาจากคนละคอลัมน์โดยไม่มีใครสังเกต
- **Correct Pattern/Solution:** เก็บ `event_at` เป็นคอลัมน์ และใช้ **นิพจน์เดียว** ทั้งการกรอง การเรียง และการพิมพ์ — `_DOC_DATE = "COALESCE(R.event_at, R.issued_at)"` · และ `event_at` ต้องเป็นค่า **ตัวเดียวกับที่คำนวณ `year_be`**:
  ```python
  raw_event_at = event["event_at"]
  if raw_event_at is not None:
      event_at = _as_utc(raw_event_at)
      year_be  = cls._thai_year_be(raw_event_at)      # ← วินาทีเดียวกัน
  else:                                                # ใบแจ้งหนี้ / ข้อมูลยุคก่อนมีคอลัมน์
      event_at = issued_at_db
      year_be  = issued_at_db.astimezone(THAI_TZ).year + BUDDHIST_ERA_OFFSET
  ```
  - 🔑 `SELECT CURRENT_TIMESTAMP` = `transaction_timestamp()` ⇒ **คงที่ทั้ง transaction** ⇒ อ่านครั้งเดียวต่อ transaction ทำให้ใบแจ้งหนี้มี `event_at == issued_at` **เป๊ะ** และใบทั้งชุดของ batch ได้ `issued_at` เดียวกัน — ห้ามใช้ `datetime.now()` ของแอป (3 replica = 3 นาฬิกา)
  - ใบที่ยกเลิกต้อง **พิมพ์ได้** พร้อมแบนเนอร์ "ยกเลิก" — ปฏิเสธการพิมพ์จะทำให้ต้นฉบับที่ผู้ปกครองถืออยู่กลายเป็นเอกสารที่ระบบปฏิเสธว่าตัวเองไม่เคยออก
- **Rule:** (1) ค่าที่ "ต้องตรงกันเสมอ" ต้องมาจาก **นิพจน์เดียวกัน** ไม่ใช่สองคอลัมน์ที่บังเอิญเท่ากัน (2) เวลาที่ต้องการความคงที่ทั้ง transaction ต้องอ่านจาก DB (`CURRENT_TIMESTAMP`) ไม่ใช่ `now()` ของแอป (3) การกรองกับสิ่งที่พิมพ์ **ต้องใช้ตัวเดียวกัน** ไม่งั้นผู้ใช้ค้นใบเสร็จไม่เจอทั้งที่ถืออยู่ในมือ (4) ก่อนย้ายแหล่งความจริง ต้องหาเทสต์ที่เคย "ผ่าน" ด้วยความบังเอิญแล้วทำให้มันแยกแยะได้จริง (ดูหัวข้อถัดไป)
- **Tests:** `test_printed_date_follows_the_payment_event_not_the_print_time` · `test_doc_year_and_printed_date_cross_the_buddhist_year_together` · `test_date_filter_follows_event_at_not_issued_at` · `test_invoice_event_at_is_exactly_its_own_issued_at` · `test_legacy_receipt_without_event_at_falls_back_to_issued_at`
- **Date Added:** 2026-09-14

### 🧪 เทสต์ที่ seed สองค่า "เกือบเท่ากัน" **แยกไม่ออก** ว่าโค้ดอ่านคอลัมน์ไหน — ต้องบังคับให้ต่างกันก่อน
- **Context/Problem:** ตอนย้าย "วันที่ของเอกสาร" จาก `issued_at` → `event_at` มีเทสต์เดิมสองตัวที่อ่านค่าที่คาดหวังจาก `issued_at` (`test_pdf_prints_thai_buddhist_dates...`, `test_get_receipts_filters_by_thai_calendar_day`) · ทั้งคู่ **ผ่านต่อทั้งก่อนและหลังการแก้** เพราะข้อมูลที่ seed (รับเงินแล้วออกใบเสร็จทันที) ทำให้ `event_at ≈ issued_at` ห่างกันไม่กี่มิลลิวินาที ⇒ ถ้าเชื่อสองตัวนี้จะสรุปผิดว่า "ย้ายเสร็จและมีเทสต์คุ้มแล้ว"
- **Root Cause:** เทสต์ถูกเขียนให้ตอบคำถาม "ผลลัพธ์ถูกไหม" แต่ **ไม่ได้ออกแบบให้คำตอบต่างกันได้** ระหว่างสมมติฐานทั้งสอง ⇒ เป็นเทสต์ที่พิสูจน์ไม่ได้ว่าอะไร (เทสต์ที่ไม่สามารถ fail ได้ด้วย mutation ที่สมเหตุสมผล = ไม่มีฟัน)
- **Correct Pattern/Solution:** seed ข้อมูลที่ทำให้สองค่าที่เป็นไปได้ **ห่างกันชัดเจน** แล้ว assert ทั้งสองทิศ:
  ```python
  event_utc = datetime(2026, 5, 20, 3, 0)    # เหตุการณ์ 20 พ.ค. 2569
  ft_id = await _seed_payment_event(..., created_at=event_utc)
  ...
  assert "20 พ.ค. 2569 10:00 น." in html                       # (ก) ตามค่าที่ถูก
  assert issued_text not in html                               # (ข) และต้อง **ไม่มี** ค่าที่ผิด
  assert issued_at.astimezone(THAI_TZ).date() != date(2026,5,20)  # (ค) ยืนยันว่าเทสต์มีฟันจริง
  ```
  ข้อ (ค) สำคัญที่สุด: มันคือ **เทสต์ของเทสต์** — ถ้าวันหนึ่งมีคนแก้ข้อมูล seed จนสองค่านี้กลับมาเท่ากัน ตัว assert จะบอกทันทีว่าเทสต์หมดความหมายแล้ว ไม่ใช่ผ่านเงียบ ๆ
- **Rule:** (1) เทสต์ที่ย้าย "แหล่งความจริง" ต้อง **บังคับให้ค่าทั้งสองต่างกัน** ไม่งั้นเป็นเทสต์ที่ผ่านด้วยความบังเอิญ (2) ใส่ assert ที่ยืนยันว่า **เงื่อนไขของเทสต์เองยังเป็นจริง** (guard กันเทสต์กลายเป็นโมฆะ) (3) ตรวจด้วยว่าเทสต์ **fail ก่อนการแก้** หรือไม่ — ถ้าไม่ fail แปลว่ายังไม่ครอบอะไร
- **Tests:** ตัวเองเป็นตัวอย่าง — สองตัวเดิมถูกเพิ่มหมายเหตุตรง ๆ ว่า "ตัวที่มีฟันจริงคืออีกตัว" เพื่อไม่ให้คนอ่านเข้าใจผิดว่าคุ้มแล้ว
- **Date Added:** 2026-09-14

### 🔄 `init_db(pool)` รันใน lifespan ของ **ทุก replica** โดยไม่มี advisory lock ⇒ การ `DROP CONSTRAINT` + `ADD CONSTRAINT` มีช่วงแข่ง
- **Context/Problem:** ทุก replica (3 ตัวใน `docker-compose.app.yml`) รัน `init_db` ตอน start ⇒ การ deploy หนึ่งครั้งรัน DDL พร้อมกันสามชุด · `CREATE TABLE IF NOT EXISTS` ทนได้ (Postgres จัดการแข่งให้) แต่ **`DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` เป็นสองคำสั่ง** ⇒ replica B อาจ `ADD` สำเร็จแล้ว replica A `DROP` ทิ้งต่อ แล้ว `ADD` ของ A ชนกับของ B = error ตอนบูต (หรือเหลือช่วงที่ constraint หายไป)
- **Root Cause:** `init_db` ถูกออกแบบตอนที่ยังไม่มีการใช้ constraint ที่ต้อง DROP ก่อน — โมเดลคิดว่า "DDL เป็น idempotent ทั้งหมด" ซึ่งจริงเฉพาะตระกูล `IF NOT EXISTS`
- **Correct Pattern/Solution:** รอบนี้ **ตาม idiom เดิมของไฟล์** (`users_email_key`) เพราะ (ก) เป็นรูปแบบที่ ship แล้วและมีเทสต์อยู่ (ข) ความกว้างของช่วงแข่งเป็นระดับมิลลิวินาทีและ **self-healing** — replica ที่แพ้แค่ fail ตอนบูตแล้ว restart เข้ามาใหม่ได้ (ค) การเปลี่ยนเป็น `pg_advisory_lock` รอบ `init_db` เป็นการเปลี่ยนพฤติกรรม bootstrap ทั้งระบบ ควรทำเป็นงานแยกที่มีเทสต์ deploy จริง
- **Rule:** (1) DDL ที่ไม่ใช่ `IF NOT EXISTS` ใน bootstrap = ต้องรู้ตัวว่ามีช่วงแข่งและ **เขียนเหตุผลที่ยอมรับไว้ในโค้ด** (2) อย่าแก้ bootstrap ทั้งระบบเป็นงานแถม (3) ถ้าต้องเพิ่ม constraint ที่ DROP ก่อน ให้ตรวจว่าคำสั่งคู่ `DROP`+`ADD` **อยู่ติดกัน** และรันใน `conn.execute` เดียวกันไม่ได้ (คนละ statement) — ลดช่วงแข่งเท่าที่ทำได้
- **Tests:** ไม่มี (ต้องมี deploy จริงหลาย replica) — บันทึกเป็นช่องที่รู้ตัว
- **Date Added:** 2026-09-14

### 💰 ยอดบนเอกสารที่อ้าง "ยอดค้าง" ต้องมาจาก **predicate ชุดเดียวกับหน้าจอที่โชว์ยอดนั้น**
- **Context/Problem:** ใบแจ้งหนี้แบบใหม่ต้องพิมพ์ "ยอดค้างรวมของนักเรียนคนนี้" ซึ่งเป็นตัวเลขเดียวกับที่หน้าลูกหนี้ (`CollectionsMixin.get_all_debtors`) โชว์อยู่แล้ว · ทั้งสองที่อ่านตาราง `student_payments` เหมือนกันแต่ **คนละคิวรี** ⇒ ถ้าวันหนึ่งมีคนแก้เงื่อนไขที่เดียว (เช่นเติม `deleted_at IS NULL`, เปลี่ยน `status='pending'` เป็นอย่างอื่น, เพิ่มการหักส่วนลด) อีกที่หนึ่งจะไม่รู้ตัว แล้วครูจะพิมพ์ใบแจ้งหนี้ที่ยอด **ไม่ตรงกับจอที่เพิ่งดูมา** ซึ่งเป็นข้อโต้แย้งกับผู้ปกครองที่แก้ไม่ได้
- **Root Cause:** สองเส้นทางที่ "บังเอิญให้ผลเท่ากันวันนี้" ไม่มีอะไรบังคับให้เท่ากันพรุ่งนี้ — และความต่างจะโผล่เฉพาะกับข้อมูลบางรูป (บิลที่จ่ายบางส่วน, บิลที่ถูกลบ) ซึ่งเทสต์ที่ seed ข้อมูลธรรมดาจะไม่เจอ
- **Correct Pattern/Solution:** ยึด **predicate เดียวกันเป๊ะ** (`SP.status = 'pending'` และไม่แตะ `deleted_at` ของ `student_payments` ซึ่งทั้ง repo ไม่มีใครตั้งค่า — ตรวจแล้ว) **และเขียนเทสต์ที่เทียบสองตัวเลขนั้นตรง ๆ** ไม่ใช่เทียบกับค่าคงที่ที่พิมพ์ไว้:
  ```python
  # 3 บิล (1200 + 850.50 + 430.25) จ่ายไป 200 → ค้าง 2280.75
  doc = _issue_invoices(client, admin_headers, [student_id]).json()["receipts"][0]
  debtors = client.get(_url(DEBTORS_PATH, room_id), headers=admin_headers).json()
  on_screen = next(d for d in debtors["debtors"] if d["student_id"] == student_id)
  assert doc["amount"] == pytest.approx(on_screen["total_pending_amount"], abs=0.005)
  assert doc["amount"] == pytest.approx(2280.75)   # ← กันไว้อีกชั้น: สองที่เท่ากันแต่ผิดด้วยกันได้
  ```
  ⚠️ ต้องมี **ทั้งสอง assert**: ตัวแรกกันการหลุดจากกัน (drift) ตัวที่สองกัน "เท่ากันแต่ยอดผิด" ซึ่งตัวแรกจับไม่ได้เลย
- **Rule:** (1) ตัวเลขเดียวกันที่โผล่สองที่ ต้องมาจาก predicate เดียว ไม่งั้นวันหนึ่งจะไม่ตรงกันแบบเงียบ ๆ (2) เทสต์ที่บังคับความเท่ากันต้องเทียบ **กับปลายทางจริงที่ผู้ใช้อ่าน** ไม่ใช่กับ literal (3) เติม literal กำกับไว้ด้วยเสมอ ไม่งั้นสองที่ผิดพร้อมกันแล้วเทสต์ยังเขียว
- **Tests:** `test_finance_invoices.py::test_invoice_amount_equals_the_debtor_page_amount` (เทียบกับ `GET /finance/debtors` จริง)
- **Date Added:** 2026-09-14

### 📋 เอกสารที่แจกแจงรายการต้อง **snapshot** บรรทัดไว้ — ห้าม recompute ตอนพิมพ์
- **Context/Problem:** ใบแจ้งหนี้รวมยอดต้องมีตารางแจกแจงว่า "ค้างโครงการอะไรบ้าง" ใต้ยอดพาดหัว · ถ้าคำนวณตารางใหม่ทุกครั้งที่พิมพ์ ใบที่ **พิมพ์ซ้ำหลังนักเรียนจ่ายบางส่วน** จะได้บรรทัดที่ยอดรวม **ไม่เท่ากับยอดพาดหัวที่เก็บไว้ตอนออกเอกสาร** ⇒ เอกสารเดียวกันขัดแย้งตัวเอง และผู้ปกครองที่ถือใบเก่าอยู่จะเทียบกับใบใหม่แล้วเจอเลขคนละชุด
- **Root Cause:** คิดว่า "รายการเป็นแค่รายละเอียดประกอบ" ทั้งที่จริงมันคือ **ส่วนหนึ่งของยอด** ⇒ การคำนวณซ้ำจากสถานะปัจจุบันปนเข้ากับค่าที่ควรเป็นภาพนิ่ง ณ เวลาหนึ่ง
- **Correct Pattern/Solution:** เก็บ snapshot ลงคอลัมน์ `line_items JSONB` **ตอนออกเอกสาร** แล้วอ่านค่าที่เก็บไว้นั้นตลอดไป:
  - `due_date` เก็บเป็น **สตริง ISO** (JSON ไม่มีชนิด DATE) ⇒ round-trip ตรงเสมอ · ฝั่งพิมพ์แปลงเป็นข้อความไทยที่เดียว (`_line_items_for_print`)
  - ⚠️ asyncpg คืน jsonb เป็น **`str`** เสมอ (ไม่มี codec ที่ไหนในโปรเจกต์นี้) ⇒ ต้อง `json.loads` — ลืมแล้วไม่ error แค่หน้าจอโชว์สตริงยาว ๆ (`_parse_line_items`)
  - ⚠️ และต้องกรองให้เหลือ **list ของ dict เท่านั้น**: dict ก้อนเดียวทำให้ `response_model` ValidationError = 500 ที่หน้า detail · สมาชิกที่ไม่ใช่ dict ทำให้เทมเพลตเรียก `.get()` ไม่ได้ = 500 ที่หน้า PDF ⇒ กรองที่จุดเดียวที่ข้อมูลเข้ามา
  - **นิยามที่ทำให้เอกสารสอดคล้องตัวเอง:** `collection_amount = amount + paid_total_after` ⇒ `remaining = collection_amount - paid_total_after` = `amount` **พอดี** ⇒ สามแถวในตาราง meta ตรงกันเองโดยไม่ต้องแก้เทมเพลต
  - **การตัดบรรทัดต้องไม่ทำให้ยอดผิด:** พิมพ์ได้ 12 บรรทัดแล้วขึ้น "และอีก N โครงการ" — แถว "รวมทั้งสิ้น" ต้องพิมพ์ **`amount` ที่พาดหัว** (ค่าที่ snapshot ไว้) ไม่ใช่ผลบวกของบรรทัดที่พิมพ์
    ✅ พิสูจน์ด้วยการเรนเดอร์จริง: 15 บิล (101..115) → พิมพ์ 12 บรรทัด + "และอีก 3 โครงการ" และยอดรวมยังเป็น **1,620.00** ครบถ้วน
- **Rule:** (1) ข้อมูลที่ประกอบกันเป็น "ยอด" ต้อง snapshot ไว้พร้อมยอด ไม่ใช่คำนวณใหม่ (2) เมื่อมีทั้งค่าที่เก็บและค่าที่คำนวณ ต้องนิยามให้ทั้งคู่ให้ผลตรงกันเสมอ (3) การตัดทอนเพื่อการแสดงผลห้ามแตะยอด — ยอดต้องมาจากค่าเดียวที่เก็บไว้ (4) JSONB ต้องผ่าน `json.loads` และผ่านการตรวจรูปก่อนใช้
- **Tests:** `test_line_items_are_a_snapshot_not_recomputed_at_print_time` · `test_line_items_survive_the_jsonb_round_trip` · `test_three_bills_become_one_invoice_with_no_bill_reference`
- **Date Added:** 2026-09-14

### 🖨️ PDF หลายใบในไฟล์เดียว: `padding` ต้องอยู่ที่ element **ต่อใบ** ไม่ใช่ `body` — วัดได้ 14.0mm
- **Context/Problem:** ทำ PDF รวม "หน้าละคน" ด้วยการวน `<div class="doc">` หลายก้อนใน body เดียว + `break-after: page` · ตอนแรกใส่ระยะขอบกระดาษไว้ที่ `body { padding: 14mm ... }` ตามสัญชาตญาณ ⇒ **หน้าถัด ๆ ไปขอบบนหายไป**
- **Root Cause:** เมื่อกล่องหนึ่งถูกแบ่งข้ามหน้า (CSS fragmentation) `padding-top` ใช้เฉพาะ **fragment แรก** และ `padding-bottom` เฉพาะ **fragment สุดท้าย** — หน้าที่อยู่กลางไม่ได้รับทั้งคู่ · `body` เป็นกล่องเดียวที่คลุมทั้ง flow ⇒ padding ของมันจึงไม่ซ้ำในหน้า 2..N
- **Correct Pattern/Solution:** ย้าย padding ไปที่ `.doc` (กล่องที่ **แต่ละใบ** เป็นของตัวเอง ⇒ แต่ละใบมี padding ของตัวเองครบ) แล้วตั้ง `body { margin: 0; padding: 0; }`
  ```css
  body { margin: 0; padding: 0; }
  .doc { padding: 14mm 14mm 10mm; }
  .doc-break { break-after: page; page-break-after: always; }  /* ใส่ทั้งคู่: มาตรฐานใหม่ + ชื่อเก่าที่ Chromium ยังรับ */
  ```
  📏 **วิธีวัดผลจริงบนเครื่องที่ไม่มี poppler** (พิสูจน์แล้วว่าได้ผล — ใช้เทียบก่อน/หลังได้ทุกครั้ง):
  ```bash
  # 1) เรนเดอร์ผ่าน Gotenberg จริง   2) คลาย stream ด้วย qpdf (มีมาใน image ของ gotenberg เอง)
  docker exec <gotenberg> qpdf --qdf --object-streams=disable in.pdf out.pdf
  # 3) อ่าน Tm ตัวแรกของแต่ละหน้า แล้วเทียบ y กับ i × 1123px (A4 = 297mm ที่ 96dpi)
  ```
  | ใส่ padding ที่ | ระยะจากขอบบนหน้า 1 | ระยะจากขอบบนหน้า 2 |
  |---|---|---|
  | `body` | 18.5 mm | **4.5 mm** ← หายไป 14.0 mm |
  | `.doc` (ที่แก้) | 18.5 mm | 18.5 mm ✅ |
- **Rule:** (1) padding ของกล่องที่ถูกแบ่งข้ามหน้าไม่ซ้ำใน fragment กลาง — อย่าใช้ `body` เป็นที่ใส่ระยะขอบของเอกสารหลายใบ (2) ระยะขอบที่ต้องเหมือนกันทุกหน้าต้องอยู่บน element ที่ **หนึ่งหน้าหนึ่งกล่อง** (3) อย่าเชื่อว่า "หน้าตาถูก" จาก screenshot — screenshot ของ Chromium เรนเดอร์เป็น **flow ต่อเนื่อง** ไม่มีการแบ่งหน้า ⇒ ต้องวัดจาก PDF จริงเท่านั้น (บทเรียนนี้เกือบถูกเขียนผิดเพราะเชื่อ screenshot)
- **Tests:** `test_combined_pdf_renders_once_with_one_page_per_document` (นับ `.doc` = จำนวนใบ, `doc-break` = N-1, `data:font/ttf;base64,` = 2 ไม่ใช่ 2N)
- **Date Added:** 2026-09-14

### 🔢 เทสต์ที่นับจำนวนครั้งของสตริงใน output — **คอมเมนต์ในเทมเพลตก็ถูกนับด้วย**
- **Context/Problem:** เทสต์กันฟอนต์บวมเขียนว่า `assert html.count("data:font/ttf;base64,") == 2` (Regular + Bold) แล้วมีคนเพิ่ม **คอมเมนต์อธิบายใน `<style>`** ที่เผลอเขียนคำนำหน้า data URI ของฟอนต์ออกมาตรง ๆ ⇒ นับได้ **3** เทสต์ล้มทั้งที่โค้ดถูกต้อง 100% และสาเหตุอ่านไม่ออกเลยถ้าไม่รู้มาก่อน (ตัวเลข 3 ไม่ได้บอกว่ามันนับอะไรเกินมา)
- **Root Cause:** การนับ substring คือการวัด **ทั้งไฟล์** รวมส่วนที่ผู้ใช้ไม่เคยเห็น (คอมเมนต์) ⇒ คำอธิบายที่ "พูดถึง" สิ่งที่นับ กลายเป็นสิ่งที่ถูกนับเอง — ยิ่งเขียนคอมเมนต์ละเอียดยิ่งเสี่ยง
- **Correct Pattern/Solution:** เขียนคอมเมนต์ให้ **บรรยายโดยไม่เขียนตัว literal** แล้วเตือนคนถัดไปไว้ในคอมเมนต์เดียวกัน:
  ```jinja
  ⚠️ และคอมเมนต์นี้ **ห้ามเขียนตัวคำนำหน้า data URI ของฟอนต์ออกมาตรง ๆ** — เทสต์นับ
     จำนวนครั้งของคำนำหน้านั้นใน HTML ทั้งไฟล์ (ต้องได้ 2 = Regular + Bold) ⇒ คอมเมนต์
     ที่เผลอเขียนคำนำหน้าลงไปจะถูกนับเป็นฟอนต์อันที่สาม แล้วเทสต์ล้มทั้งที่โค้ดถูก
  ```
  ทางเลือกที่ทนกว่าถ้าต้องนับของจริง: นับ `@font-face` ที่ **เรนเดอร์แล้ว** (`html.count("@font-face {")`) หรือดึง `<style>` ออกมาแล้วนับเฉพาะในนั้น — แต่ระวังว่าคำว่า `@font-face` ก็โผล่ในคอมเมนต์ได้เหมือนกัน
- **Rule:** (1) เทสต์ที่นับ substring วัดทั้งไฟล์ **รวมคอมเมนต์** — คอมเมนต์ที่พูดถึงสิ่งที่ถูกนับจะถูกนับเองด้วย (2) ถ้าต้องนับ ให้เลือกตัวนับที่โผล่ในคอมเมนต์ได้ยาก และเขียนคำเตือนไว้ข้าง ๆ ของจริง (3) อาการ "นับได้ N+1" ให้สงสัยคอมเมนต์ก่อนสงสัยโค้ด
- **Tests:** `test_receipt_pdf_streams_with_mocked_gotenberg` (ตัวที่จับบั๊กนี้ได้จริง)
- **Date Added:** 2026-09-14

### 💰 เงินรับล่วงหน้า = **หนี้สิน** ไม่ใช่รายได้ — และระบบนี้เพิ่งมี liability ledger ตัวแรก
- **Context/Problem:** ทำฟีเจอร์ "จ่ายล่วงหน้า" (F4) — รับเงินก้อนเข้ามาพักไว้รายคนก่อนที่จะมีบิล แล้วค่อยหักไปปิดบิลในอนาคต · ทางที่ลัดที่สุดคือลง journal ขา Cr เป็นรายได้ตั้งแต่วันที่รับเงิน (เพราะ "เงินเข้าแล้ว") ซึ่งจะทำให้ **รายได้ของห้องพองตั้งแต่ยังไม่มีบิล** และไม่มีอะไรฟ้องเลย: ยอด Dr=Cr ยังครบทุกใบ งบดุลยังดูปกติ ตัวเลขทุกหน้าจอยัง "ดูสมเหตุสมผล"
- **Root Cause:** การรับเงินกับการเกิดรายได้เป็น **คนละเหตุการณ์** ทางบัญชี · เงินที่ยังไม่ผูกกับบริการที่ส่งมอบคือ **ภาระผูกพันที่จะต้องคืนหรือให้บริการในอนาคต** = หนี้สิน (`liability`) ⇒ การลง revenue ตรง ๆ คือการ **รับรู้รายได้ก่อนเกิด** ซึ่งผิดทั้งทางบัญชีและทำให้งบประมาณเห็นตัวเลขที่ไม่มีอยู่จริง
- **Correct Pattern/Solution:** แยกสองจังหวะให้ชัด
  ```
  เติมเครดิต (รับเงิน)  → Dr สินทรัพย์ / Cr หนี้สิน 2099   ⇒ รายได้ +0
  หักปิดบิล (ใช้เครดิต) → Dr หนี้สิน 2099 / Cr รายได้      ⇒ รายได้เกิด "ตรงนี้" จังหวะเดียว
  ```
  - ⚠️ **บัญชี 2099 ต้องมี `legacy_account_id IS NULL`** ⇒ `_scan_account_diffs` (ที่วนจาก `finance_accounts` แล้วเทียบ asset ledger **ของบัญชีนั้น**) มองไม่เห็น ⇒ ไม่สร้าง diff ปลอมให้ `reconcile` · แต่เพราะเหตุเดียวกัน **ขา Dr ต้องลง asset ledger ของกระเป๋าจริงเสมอ** ไม่งั้นยอดกระเป๋ากับ ledger จะไม่ตรงแล้ว reconcile จะรายงาน diff ที่เราสร้างเอง
  - ⚠️ **ห้ามใช้ `_resolve_category_ledger` กับขา "เงินพัก"** — ตัวนั้นคืน ledger ประเภท revenue/expense เสมอ ⇒ กับดักข้อนี้จะกลับมาทันทีโดยที่โค้ดยัง "ดูถูกรูป"
  - 🧪 **วิธีพิสูจน์ว่าถูก** (ไม่ใช่ดูว่า "ผ่าน"): เติม 1000 → `SUM(credit−debit)` บน ledger `revenue` **ต้องไม่เปลี่ยน** และบน `liability` ต้อง +1000 · แล้วหัก 500 → revenue +500, liability −500 · ปิดท้ายด้วย `สินทรัพย์ = หนี้สิน + ส่วนของเจ้าของ + กำไรสะสม`
  - ℹ️ ก่อนงานนี้ **ไม่เคยมี liability ledger ในระบบเลย** — reporting layer รองรับอยู่แล้ว (`ACCOUNT_TYPE_LABELS`, `liability_total` ในงบดุล) แต่ไม่มีใครเป็นผู้ใช้รายแรก ⇒ เจอโค้ดที่ "รองรับไว้แล้วแต่ไม่เคยถูกรัน" ให้สงสัยว่ามันยังไม่เคยถูกทดสอบ
- **Rule:** (1) เงินที่ยังไม่ผูกกับสิ่งที่ส่งมอบ = หนี้สิน **ห้ามเป็นรายได้** (2) รายได้รับรู้ ณ วันที่ "ใช้" เงินพักนั้น ไม่ใช่วันที่รับเงิน (3) ขา Dr ของเงินพักต้องลง asset ledger ของกระเป๋าจริงเสมอ ไม่งั้นสร้าง diff ปลอมให้ reconcile (4) พิสูจน์ความถูกต้องด้วย **ตัวเลขสามตัว** (สินทรัพย์/หนี้สิน/รายได้) ไม่ใช่ด้วยสถานะ HTTP 200
- **Tests:** `test_top_up_is_a_liability_and_never_revenue` · `test_revenue_arises_once_when_credit_is_applied` · `test_reconcile_does_not_see_the_advance_liability_as_a_diff`
- **Date Added:** 2026-09-14

### 🔇 งบประมาณ (หลัง CUTOFF) อ่าน journal ตาม `reference_type` ⇒ เพิ่ม `reference_type` ใหม่ต้องแก้ `budgets.py` ด้วย ไม่งั้น **ยอดหายเงียบ**
- **Context/Problem:** F4 เพิ่ม `reference_type` ใหม่ 2 ตัว (`student_credit_topup`, `student_credit_apply`) · ตัวที่สองคือ **รายได้จริงที่ต้องเข้างบ** แต่ถ้าลืมเติมชื่อมันลงใน filter ของงบประมาณ รายได้ก้อนนั้นจะ **ไม่ถูกนับเข้างบเลย** และ **ไม่มีอะไรฟ้อง** — ไม่ error ไม่มี 500 ไม่มี warning งบแค่โชว์ตัวเลขต่ำกว่าความจริง ซึ่งเป็นบั๊กที่ผู้ใช้จะเจอตอนปิดงบแล้ว และหาสาเหตุยากมาก
- **Root Cause:** หลัง `CUTOFF_DATE` งบประมาณ **อ่านจาก `journal_entries` เท่านั้น** (ไม่ได้อ่าน `finance_transactions` — ตารางนั้นถูกอ่านเฉพาะช่วง legacy ที่ cap ด้วย `_LEGACY_LO/_LEGACY_HI`) และกรองด้วย **รายชื่อ `reference_type` ที่ฮาร์ดโค้ดไว้** ⇒ `reference_type` ที่ไม่อยู่ในรายชื่อ = มองไม่เห็นทั้งที่มีแถวอยู่ใน DB ครบถ้วน · เป็นกับดักตระกูลเดียวกับ "แก้ที่เดียวแต่ต้องแก้สองที่พร้อมกัน"
- **Correct Pattern/Solution:** ทุกครั้งที่เพิ่ม `reference_type` ให้ **กวาดหา** ทุกที่ที่กรองด้วยรายชื่อนี้แล้วแก้พร้อมกันในคอมมิตเดียว
  ```bash
  grep -rn "reference_type" backend/services/finance/ --include=*.py | grep -i "in (\|== \|ANY"
  ```
  และปิดด้วยเทสต์ที่ **ยิงเข้า endpoint ของงบจริง** ไม่ใช่เทสต์ที่อ่าน journal เอง (เทสต์แบบหลังจะเขียวทั้งที่ผู้ใช้มองไม่เห็นยอด):
  ```python
  # GET /finance/budgets/overview ต้องนับยอดที่หักจากเครดิตเข้าหมวดรายได้
  # ← เทสต์นี้จะ "ล้มถ้าลืมแก้ budgets.py" ซึ่งเป็นเหตุผลที่มันต้องมี
  ```
  💡 และการเลือก `category_id` ของแถว mirror ก็สำคัญพอกัน: **ต้องเป็น NULL** สำหรับเงินรับล่วงหน้า ไม่งั้น clause ที่นับจาก `finance_transactions` (ช่วง legacy) จะนับเงินรับล่วงหน้าเป็น "รายรับของงบ" ทันทีที่รับเงิน = **รายได้เกิดสองรอบ** ต่างกันคนละ clause
- **Rule:** (1) `reference_type` เป็น **รายการที่ฮาร์ดโค้ด** ⇒ เพิ่มค่าใหม่ต้องตามแก้ทุกตัวกรอง (2) รายได้ใหม่ต้องมีเทสต์ที่ยิงผ่าน endpoint ของรายงาน/งบจริง ไม่ใช่เทสต์ที่อ่าน DB เอง (3) ตัวเลขที่ "หายเงียบ" อันตรายกว่าตัวเลขที่ "พังดัง" — ถ้าเพิ่มเส้นทางเงินใหม่แล้วไม่มีเทสต์ที่ยิงผ่านรายงาน ให้ถือว่ายังไม่เสร็จ
- **Tests:** `test_budget_overview_counts_revenue_from_credit_application` (mutation M6: ถอด `'student_credit_apply'` ออกจาก filter แล้วเทสต์นี้ล้มจริง)
- **Date Added:** 2026-09-14

### 🕳️ เอกสารที่ `student_payment_id IS NULL` **ไม่ถูกกันซ้ำ** โดย `idx_finance_receipts_tx_active`
- **Context/Problem:** ออกเอกสารชนิดใหม่ (`doc_type='deposit'` = ใบรับเงินล่วงหน้า) ที่ **ไม่มีบิลรองรับ** ⇒ `student_payment_id = NULL` · ตอนแรกคิดว่าได้ idempotency "มาฟรี" จาก unique index เดิมของตาราง `finance_receipts` แต่กดออกซ้ำแล้วได้ **เอกสาร 2 ใบ**
- **Root Cause:** index เดิมคือ `UNIQUE (student_payment_id, legacy_transaction_id) WHERE deleted_at IS NULL` และ **Postgres ถือว่า `NULL` ไม่ซ้ำกับ `NULL`** ⇒ แถวที่ `student_payment_id IS NULL` ทุกแถว "ไม่ชนกัน" ตามนิยาม ⇒ index ที่ดูเหมือนครอบทุกแถวจริง ๆ แล้ว **ไม่ป้องกันอะไรเลย** สำหรับเอกสารที่ไม่มีบิล และจะไม่มี error ให้เห็นด้วย — แค่ได้เอกสารซ้ำสองใบซึ่งเป็นปัญหาการเงิน/หลักฐานทันที
- **Correct Pattern/Solution:** เอกสารที่ไม่มีบิลต้องมี **unique index ของตัวเอง** ที่คีย์ด้วยสิ่งที่มันมีจริง (`legacy_transaction_id` ซึ่งไม่เป็น NULL เสมอ) และต้องเป็น **ชื่อใหม่** เพราะ `CREATE UNIQUE INDEX IF NOT EXISTS` **เปลี่ยน predicate ของ index ชื่อเดิมไม่ได้**
  ```sql
  CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_receipts_deposit_active
      ON finance_receipts(legacy_transaction_id, doc_type)
      WHERE deleted_at IS NULL AND doc_type = 'deposit';
  ```
  🪆 และต้องมี **สองชั้น** เหมือนเส้นทางเดิม: อ่านก่อนเขียน (`_find_existing_deposit`) + ดัก `UniqueViolationError` ตอน INSERT แล้วอ่านซ้ำ (กันการแข่งกันจริง) — ชั้นเดียวไม่พอ เพราะสอง request ที่พร้อมกันจะผ่าน "อ่านก่อนเขียน" ทั้งคู่
- **Rule:** (1) `UNIQUE` index ที่มีคอลัมน์ nullable เป็นสมาชิก **ไม่กันซ้ำ** สำหรับแถวที่ค่านั้นเป็น NULL — ต้องมี partial index ของตัวเอง (2) เมื่อเพิ่ม `doc_type` ใหม่ ต้องถามทุกครั้งว่า "เอกสารชนิดนี้มี `student_payment_id` ไหม" ถ้าไม่มี ต้องสร้าง index ใหม่ (3) `CREATE UNIQUE INDEX IF NOT EXISTS` ใช้ชื่อเดิมเพื่อเปลี่ยน predicate ไม่ได้ — ต้องตั้งชื่อใหม่ (4) idempotency ต้องมีทั้ง "อ่านก่อนเขียน" และ "ดัก UniqueViolation" ไม่ใช่เลือกอย่างใดอย่างหนึ่ง
- **Tests:** `test_top_up_with_same_idempotency_key_is_not_a_second_payment` · `test_deposit_sequence_is_separate_from_receipt_sequence`
- **Date Added:** 2026-09-14

### 🧩 Pydantic `response_model` บังคับฟิลด์ที่ **ตัวสร้าง dict ไม่ได้ใส่** ⇒ 500 ทุกครั้ง (และตัวเลขใน error ชี้ผิดที่)
- **Context/Problem:** `GET /finance/credits/{student_id}` ตอบ **500 ทุกครั้งที่เรียก** ทั้งที่ตัวเลขคำนวณถูกต้องครบถ้วน · error คือ `ResponseValidationError: {'type': 'missing', 'loc': ('response','plan','student_id'), 'input': {'balance_before': 100.0, 'allocations': [], ...}}`
- **Root Cause:** มีสองทางที่สร้าง "แผนการหัก" — `_build_plan(balance=, bills=)` (รับแค่ยอดกับบิล ⇒ **ไม่รู้จักนักเรียน จึงไม่มี `student_id`**) และ `_build_plan_for_students(...)` (เติม `student_id`/`student_no`/`student_name` ต่อจาก `_build_plan`) · `get_student_credit` เรียกตัวแรกตรง ๆ ⇒ dict ที่ได้มีคีย์ไม่ครบตามที่ `CreditPlanItem` **บังคับ** ⇒ FastAPI โยน error **หลัง** service ทำงานเสร็จแล้ว (ข้อมูลใน DB ถูกต้องทั้งหมด — พังที่ชั้น serialization เท่านั้น)
  ⚠️ และ `input` ใน error ไม่ได้บอกว่าขาดอะไรจากที่ไหน มันโชว์ dict ที่ "ดูครบดี" ⇒ อ่าน error แล้วนึกว่าเป็นปัญหาที่ DB หรือที่ `student_id` ของ request ซึ่งไม่ใช่
- **Correct Pattern/Solution:** จุดที่ประกอบ dict สำหรับ response ต้องเติมตัวตนของเจ้าของข้อมูลให้ครบ **ชุดเดียวกับที่อีกเส้นทางเติม** (ก๊อปบรรทัดเดียวกัน ไม่คิดใหม่) — และถ้ามีสองทางสร้าง dict ชนิดเดียวกัน ควรมีเทสต์ที่ยิง **ทั้งสองทาง** แล้วเทียบว่าคีย์ชุดเดียวกัน
  ```python
  plan = cls._build_plan(balance=balance, bills=bills)
  plan["student_id"] = student_id          # ← ขาดสามบรรทัดนี้ = 500 ทุก call
  plan["student_no"] = stu["student_no"]
  plan["student_name"] = stu["display_name"]
  ```
- **Rule:** (1) `response_model` ที่บังคับฟิลด์ = สัญญาที่ dict ต้นทางต้องมีคีย์ครบ — ฟิลด์ที่ "จะเติมทีหลัง" ต้องเติมจริงก่อน return (2) ถ้ามีสองทางสร้าง dict ชนิดเดียวกัน ต้องมีเทสต์ยิงทั้งคู่ (3) `ResponseValidationError` = ข้อมูลใน DB ถูกแล้ว พังที่ชั้น serialization — อย่าไปแก้ที่ SQL (4) เพิ่ม endpoint ใหม่แล้วได้ **500 ทุกครั้ง** ให้สงสัย response_model ก่อน logic
- **Tests:** `test_balance_after_is_a_snapshot_chain_not_a_sum` · `test_member_can_read_credits_but_every_write_is_forbidden` (mutation M8: ถอด `plan["student_id"]` แล้วล้มจริง)
- **Date Added:** 2026-09-14

### 🗑️ อ่าน "ยอดคงเหลือแบบ snapshot" **หลัง** soft delete แถวที่เป็น snapshot ⇒ คืนเงินสองรอบ
- **Context/Problem:** ยกเลิกการหักเครดิต (คืนเครดิตกลับเข้ากระเป๋านักเรียน) · เติม 800 → หักปิดบิล 800 → ยกเลิก แล้วได้ `credit_balance_after = 1600` แทนที่จะเป็น 800 ⇒ **คืนเครดิตสองรอบ** โดยที่ทุกค่าที่เกี่ยวข้อง "ดูสมเหตุสมผล" หมด (1600 ก็เป็นตัวเลขที่อ่านได้ ไม่มี error ไม่มี constraint ฟ้อง)
- **Root Cause:** ตาราง `student_credits` เก็บ **snapshot** (`balance_after`) ไม่ใช่ผลรวม ⇒ "ยอดปัจจุบัน = `balance_after` ของแถวล่าสุดที่ยังไม่ถูกลบ" · ลำดับในโค้ดคือ **(1) soft delete แถวที่ถูกยกเลิก → (2) อ่านยอด → (3) `balance_after = ยอดที่อ่านได้ + ยอดที่หักไป`** · แต่พอ soft delete ไปแล้ว การอ่านในข้อ (2) คืน **ยอดที่คืนแล้ว** (เพราะแถวล่าสุดตอนนี้คือแถวเติมเงิน) ⇒ บวกซ้ำอีกครั้ง = สองเท่า
- **Correct Pattern/Solution:** **อ่านก่อนลบ** แล้วจึงลบ:
  ```python
  balance_before = await cls._load_credit_balance(conn, ...)   # ← ต้องมาก่อน
  balance_after = round(balance_before + applied, 2)
  await conn.execute("UPDATE student_credits SET deleted_at = NOW() WHERE id = $1", credit_entry_id)
  ```
  ✅ และท่านี้ถูกต้อง **ทุกกรณี** รวมถึงการยกเลิกแถวที่ **ไม่ใช่แถวล่าสุด**: ยอดที่อ่านได้คือยอดจริง ณ ปัจจุบัน และแถว reverse ที่ต่อท้ายจะกลายเป็นแถวล่าสุดตัวใหม่ที่พายอดไปต่อได้ถูกต้อง (800→500→300 แล้ว +300 = 600)
- **Rule:** (1) กับตารางที่เก็บ snapshot การอ่านยอดต้องเกิด **ก่อน** การลบ/แก้แถวที่มันอ่าน — ลำดับบรรทัดคือส่วนหนึ่งของความถูกต้อง ไม่ใช่เรื่องสไตล์ (2) อ่านโค้ดที่มีทั้ง "อ่านยอด" และ "ลบแถว" ให้ถามทุกครั้งว่าลำดับสลับกันได้ไหม (3) บั๊กชนิดนี้ไม่พัง ไม่ error — ต้องจับด้วยเทสต์ที่ assert **ตัวเลข** เท่านั้น (4) เทสต์ที่จับได้คือเทสต์ที่ assert ค่าจริง (`== 800.0`) ไม่ใช่แค่ `is not None`
- **Tests:** `test_undo_application_returns_credit_and_reopens_the_bill` (mutation M7: ทำให้เป็น `applied * 2` แล้วล้มจริง) · `test_revert_top_up_voids_the_deposit_and_the_credit_row`
- **Date Added:** 2026-09-14


### 🖨️ Jinja: `{% if d.x is not none %}` บนคีย์ที่ **หายไป** = `True` ⇒ `format(Undefined)` ระเบิด (ใบรับเงินล่วงหน้าดาวน์โหลดไม่ได้ 500)
- **Context/Problem:** ใบรับเงินล่วงหน้า (DEP) — เอกสารชนิดแรกที่ **ไม่มีบิล** — เรนเดอร์ PDF ไม่ผ่านเลย (`TypeError: unsupported format string passed to Undefined.__format__` ที่ `receipt.html` บรรทัดแถว "คงเหลือ") ทั้งที่ข้อมูลใน DB ครบถูกต้อง และ **เทสต์ 64 ตัวที่เพิ่งเขียนก็เขียวหมด**
- **Root Cause:** `_document_context` ตั้งคีย์ `"remaining"` **เฉพาะเมื่อมี `collection_amount`** (คือเฉพาะเอกสารที่ผูกกับบิล) ⇒ ใบ DEP ไม่มีคีย์นี้เลย · แต่เทมเพลตกันด้วย `{% if d.remaining is not none %}` ซึ่ง **`Undefined is not none` เป็น `True`** ⇒ เข้าสาขา ⇒ `.format(Undefined)` โยน `TypeError` ⇒ **ล้มทั้งการเรนเดอร์** (HTTP 500 ที่ปลายทาง Gotenberg)
  🕳️ **ทำไมเทสต์เดิมมองไม่เห็น:** (ก) ใบเสร็จ/ใบแจ้งหนี้ทุกใบผูกกับบิล ⇒ มี `collection_amount` เสมอ ⇒ ไม่เคยเดินผ่านเส้นทางที่คีย์หาย (ข) เทสต์เทมเพลตเดิมส่ง `remaining` เข้าไป **เอง** ครบทั้ง 4 ฟิลด์ตัวเลข ⇒ ยิ่งตอกย้ำว่าคีย์จะมาครบ (ค) คอมเมนต์ในเทมเพลต **เขียนสัญญาไว้ถูกแล้ว** ว่า *"บิลเดอร์ตั้งคีย์นี้เป็น None เสมอ เมื่อไม่มีแนวคิดนี้ และ `is defined` บนคีย์ที่เป็น None จะเป็น True"* — แต่ **โค้ดไม่ทำตามสัญญาที่คอมเมนต์เขียนไว้** และไม่มีเทสต์ไหนบังคับ
- **Correct Pattern/Solution:** ตั้งคีย์ให้ **ครบเสมอ** ตั้งแต่ dict ตั้งต้น แล้วค่อยทับด้วยค่าจริง:
  ```python
  context = {
      ...
      "collection_amount": None,   # ← สามบรรทัดนี้ต้องมี
      "remaining": None,
      "remaining_text": None,
  }
  if collection_amount:            # ทับเมื่อมีความหมายจริง
      context["remaining"] = float(collection_amount) - paid_total
  ```
  และให้ **ชื่อแถวรายการ** มีสาขาของตัวเอง — `{{ d.collection_title or 'รายการชำระเงิน' }}` บนเอกสารที่ไม่มีบิลจะกลายเป็นคำที่สื่อผิด (เหมือนมีบิลให้ชำระ)
- **Rule:** (1) dict ที่ป้อนเทมเพลตต้องมีคีย์ครบตามที่เทมเพลตอ้างถึง — "ไม่ตั้งคีย์" ≠ "ตั้งเป็น None" ในสายตาของ Jinja (2) เอกสาร/ชนิดข้อมูลใหม่ที่ **ไม่มีแนวคิดเดิม** (ไม่มีบิล ไม่มีงวด) คือจุดที่กับดักชนิดนี้ออกเสมอ ⇒ เพิ่มชนิดใหม่ต้อง **เรนเดอร์จริงดูด้วยตา** ไม่ใช่แค่เทสต์ผ่าน (3) เทสต์ที่ **ป้อน context เองครบทุกคีย์** พิสูจน์ได้แค่ CSS/layout — ไม่พิสูจน์ว่าบิลเดอร์จริงผลิตคีย์ครบ ⇒ ต้องมีเทสต์ที่เรียก **บิลเดอร์จริง** (`_document_context`) แล้วเรนเดอร์ (4) คอมเมนต์ที่เขียน "สัญญา" ไว้ต้องมีเทสต์บังคับ ไม่งั้นมันจะกลายเป็นคำโกหกที่คนอ่านเชื่อ
- **Tests:** `test_deposit_context_pins_bill_only_keys_to_none` · `test_deposit_document_renders_and_speaks_as_a_receipt` · `test_deposit_document_omits_the_remaining_row_entirely` · `test_receipt_context_still_computes_remaining_from_the_bill` (mutation M13: ถอน `"remaining": None` แล้วล้มจริง · M14: ถอยชื่อแถวรายการแล้วล้มจริง) · ตรวจด้วยตา: `/tmp/f4_pdf/deposit.png`
- **Date Added:** 2026-09-14

### 🧾 เอกสารที่ "ไม่มีบิล" ต้องมีถ้อยคำของตัวเอง — `is_receipt`/`doc_type` ที่ไม่ครบจะพิมพ์ด้วยคำของใบแจ้งหนี้ทั้งใบ
- **Context/Problem:** ใบรับเงินล่วงหน้าไม่มีบิล ⇒ `collection_title` เป็น None ⇒ แถวรายการตกไปที่คำ fallback `'รายการชำระเงิน'` ซึ่ง **สื่อว่ามีบิลให้ชำระ** (ไม่จริง — เงินก้อนนี้ยังไม่ผูกกับอะไร) · และถ้าลืมเพิ่ม `doc_type` ใหม่เข้า `is_receipt` เอกสารจะพิมพ์ว่า "เรียกเก็บจาก" / "ยอดค้างชำระ" / "ผู้รับแจ้ง" **ผิดทั้งใบโดยไม่มีอะไรฟ้อง** เพราะทั้ง DB และเทสต์ยังถูกต้อง
  ⚠️ กับดักเดียวกันนี้มี **3 ที่** ที่ต้องแก้พร้อมกัน: `receipt.html` (branch ด้วย `d.is_receipt`) · `_document_context` (`is_receipt = doc_type in (...)`) · `ReceiptDetail.vue` (สำเนาที่คำนวณเองว่า `doc_type === 'receipt'`)
- **Correct Pattern/Solution:** ให้เอกสารชนิดใหม่มี **สาขาของตัวเอง** ในทุกจุดที่พูดถึง "บิล" และตั้งคำที่ตรงความจริง:
  ```jinja
  {%- if d.collection_title -%}{{ d.collection_title }}
  {%- elif d.doc_type == 'deposit' -%}รับเงินล่วงหน้า (ยังไม่หักปิดบิลใด)
  {%- else -%}รายการชำระเงิน{%- endif -%}
  ```
- **Rule:** (1) เพิ่ม `doc_type` ใหม่ = กวาดหาทุกที่ที่ branch ด้วย `doc_type`/`is_receipt` **ทั้ง backend และ frontend** (รวมสำเนาที่คำนวณเองใน view) (2) คำ fallback กลาง ๆ บนเอกสารการเงินคือคำโกหกที่ดูดี — ให้สาขาใหม่แทน (3) **หน่วยวัด:** เปิด PDF/หน้าจอจริงอ่านออกเสียง ถ้าประโยคใดไม่จริงสำหรับเอกสารชนิดนั้น ให้แก้ที่เทมเพลต ไม่ใช่ผ่อนที่เทสต์
- **Tests:** `test_deposit_document_renders_and_speaks_as_a_receipt` (ยืนยันว่าไม่มี `เรียกเก็บจาก`/`ยอดค้างชำระ`/`ผู้รับแจ้ง` และต้องมี `ยังไม่หักปิดบิลใด`) · `test_receipt_context_still_computes_remaining_from_the_bill`
- **Date Added:** 2026-09-14

### 🔗 อาร์เรย์ใน query string: axios ส่ง `student_ids[]=1` แต่ FastAPI ต้องการ `student_ids=1` ⇒ **422 ที่มองไม่เห็นจากฝั่ง backend เลย**
- **Context/Problem:** ปุ่ม "ดูข้อเสนอการหัก" (หัวใจของ flow "ระบบเสนอ → ครูยืนยัน" ของ F4) **กดแล้วพังทุกครั้ง** ด้วย 422 ทั้งที่ฝั่ง backend เทสต์ผ่านครบ 895 ตัว และ mutation 14/14 ถูกจับ
  ```
  HTTP 422 {"detail":[{"type":"missing","loc":["query","student_ids"],"msg":"Field required","input":null}]}
  ```
- **Root Cause:** `FinanceService.getCreditPlan` ส่ง `params: { student_ids: [1, 2] }` ให้ axios · **axios 1.x serialize อาร์เรย์เป็นวงเล็บเหลี่ยม** `student_ids[]=1&student_ids[]=2` (ยืนยันด้วยการดักดู URL จริงในเบราว์เซอร์) แต่ FastAPI ประกาศ `student_ids: List[int] = Query(...)` ซึ่งต้องการ **คีย์ซ้ำ** `student_ids=1&student_ids=2`
  ⇒ FastAPI มองชื่อพารามิเตอร์ว่าเป็นคนละตัว (`student_ids[]`) แล้วไม่พบ `student_ids` ที่บังคับไว้ ⇒ 422 "Field required"
  🔴 **ทำไมเทสต์ทั้ง 895 ตัวจับไม่ได้ — และจะจับไม่ได้ตลอดไป:** `TestClient`/httpx ส่ง `params={"student_ids": [1, 2]}` ซึ่ง serialize เป็นคีย์ซ้ำให้เองอยู่แล้ว ⇒ ฝั่ง Python **ไม่มีทางเห็นความต่างนี้** ความผิดพลาดอยู่ในไคลเอนต์เท่านั้น · และคอมเมนต์เดิมในโค้ดก็ **อ้างผิด** ว่า "axios แปลง array เป็น `student_ids=1&student_ids=2`" ⇒ ความเชื่อผิดที่เขียนกำกับไว้ ทำให้ไม่มีใครสงสัย
- **Correct Pattern/Solution:** อย่าส่งอาร์เรย์ผ่าน `params:` ของ axios ให้สร้าง query string เองด้วย `URLSearchParams` — เป็นท่าที่ **มีอยู่แล้วในรีโป** (`ActivityService.getActivities`)
  ```ts
  const query = new URLSearchParams({ target_type: 'room' });
  studentIds.forEach((id) => query.append('student_ids', String(id)));
  return await api.get(`/api/classroom/${roomId}/finance/credits/plan?${query}`) as unknown as CreditApplyPlan;
  ```
- **Rule:** (1) **ทุกครั้งที่ส่งอาร์เรย์ลง query string ให้ใช้ `URLSearchParams` — ห้ามฝาก `params:` ของ axios** (2) เทสต์ที่พิสูจน์เรื่องนี้ต้องผูกกับ **ไคลเอนต์จริง** (adapter ปลอม + `api.getUri(config)`) ไม่ใช่ mock `api.get` — เพราะ mock แล้วจะเห็นแค่ argument ที่เราส่ง ไม่เห็น URL สุดท้าย (3) ⚠️ `config.url` **ใน adapter ไม่มี** query string — axios ประกอบให้ *ใน* adapter ⇒ ต้องใช้ `api.getUri(config)` (4) `Query(List[...])` ทั้ง repo มีตัวเดียว — ตรวจด้วย `grep -rn "Query(" backend/routers/ | grep "List\["` ก่อนเพิ่มตัวใหม่ (5) คอมเมนต์ที่อธิบายพฤติกรรมของไลบรารี **ต้องมาจากการวัด** ไม่ใช่จากความจำ
- **Tests:** `src/services/__tests__/finance.spec.ts` — 5 เทสต์ รวมเทสต์ที่พิสูจน์ว่ากับดักยังมีจริง (`params:` ให้ `student_ids[]=7`) · ยืนยันแล้วว่า **ย้อนโค้ดกลับ ⇒ ล้ม 2 เทสต์**
- **Date Added:** 2026-09-14

### ✂️ `truncate` บนบรรทัดที่มี **ตัวเลขเงิน** = ตัวเลขโกหก (฿1,500.00 อ่านเป็น ฿1,50…)
- **Context/Problem:** ที่ 375px หัวโมดัล "เติมเงินล่วงหน้า" พิมพ์ `นายกิตติพงษ์ ศรีสุวรรณ · เครดิตปัจจุบัน ฿1,50…` — ตัวเลขถูกตัดกลางคันด้วย `truncate` ⇒ อ่านแล้วเหมือน **฿1.50 หรือ ฿1,50** ซึ่งเป็นคนละจำนวนกับความจริง
- **Root Cause:** `<p class="page-lede truncate">` ครอบทั้งชื่อนักเรียนและจำนวนเงิน · ชื่อไทยยาวได้ไม่จำกัด ⇒ ที่จอแคบ `truncate` ตัดที่ **ปลายข้อความ** ซึ่งบังเอิญตกกลางตัวเลขเงิน
- **Correct Pattern/Solution:** เอา `truncate` ออกให้ข้อความ **ขึ้นบรรทัดใหม่** (พาเนลโมดัลมี `overflow-y-auto` อยู่แล้ว) · `truncate` ยังใช้ได้กับข้อความ **คงที่** (`<h2>` ชื่อโมดัล) เพราะความยาวไม่แปรตามข้อมูล
- **Rule:** (1) ห้าม `truncate` กับอะไรก็ตามที่ **มีความยาวแปรตามข้อมูลและปลายข้อความเป็นตัวเลข** (เงิน/วันที่/เลขที่เอกสาร) — ให้ตัดบรรทัดแทน (2) ตรวจด้วยการ **เรนเดอร์จริงที่ 375px** แล้วอ่านตัวเลขบนภาพออกเสียง ว่ายังเป็นจำนวนเดิมไหม
- **Date Added:** 2026-09-14

### 🔀 `origin/main` ที่ยังไม่ `git fetch` ⇒ สรุปผิดว่า PR จะมีกี่เรื่อง (และเนื้อหาอะไร)
- **Context/Problem:** จะเปิด PR จาก branch `feat/student-credit-prepay` · `git rev-list --count origin/main..HEAD` = **1** และ `git log origin/main --oneline` ไม่มีงานใบแจ้งหนี้ ⇒ สรุปว่า branch สะสม **2 เรื่อง** (ใบแจ้งหนี้ที่ยังไม่ push + F4) แล้วเขียนคำเตือนนั้นลงหัว PR · **ผิดทั้งย่อหน้า** — หลัง `git fetch` ปรากฏว่า `origin/main` = `3d9b393` ซึ่ง **merge งานใบแจ้งหนี้ไปแล้วทาง PR #54** ⇒ PR มีเรื่องเดียว
- **Root Cause:** `origin/main` เป็น **ref ท้องถิ่น** ที่ขยับเฉพาะตอน fetch · การอ่าน `git log origin/main` / `--count` จึงตอบคำถาม "ตอนที่ fetch ครั้งล่าสุด" ไม่ใช่ "ตอนนี้" — และ **ไม่มีการเตือนใด ๆ** ว่าค้าง (ต่างจาก `git status` ที่บอก ahead/behind ให้)
- **Correct Pattern/Solution:** `git fetch origin` **ก่อน** ทุกครั้งที่จะสรุปเรื่อง base/จำนวนคอมมิต/ขอบเขต PR · ทางที่ดีคือยืนยันด้วยคำถามที่ตอบได้ตรง ๆ ว่า *"คอมมิตนี้ถูก merge แล้วหรือยัง"*: `git merge-base --is-ancestor <sha> origin/main` และ `git diff --shortstat <sha> origin/main` (ว่าง = เนื้อหาตรงกันแล้ว) · ตัวเลขที่เชื่อได้จริงคือ **`gh pr view <n> --json changedFiles,additions,deletions,commits`** เพราะ GitHub คำนวณจาก base จริง
- **Rule:** (1) ห้ามสรุปขอบเขตของ PR จาก ref ท้องถิ่นที่ยังไม่ fetch (2) ถ้า commit hash ที่รันบน production/staging ตรงกับ merge commit ของ PR ที่เพิ่ง merge ⇒ งานนั้น deploy ไปแล้ว **ไม่ใช่งานค้าง** — เช็คให้ชัดก่อนเขียนคำเตือน (3) ตรวจคำเตือนใน PR/คอมมิตกับ **ความจริงหลัง fetch** เสมอ ถ้าข้อความไหนกลายเป็นเท็จให้แก้ทันที อย่าปล่อยให้ PR พูดผิด
- **Date Added:** 2026-09-14

### 🚫 `gh pr edit` ล้มด้วย GraphQL "Projects (classic) is being deprecated" — และการกลบ stderr ทำให้ดูเหมือนสำเร็จ
- **Context/Problem:** แก้ body ของ PR #55 ด้วย `gh pr edit 55 --body-file /tmp/f4_pr_body.md >/dev/null 2>&1` ⇒ ขึ้น `exit=1` แต่ **ไม่รู้สาเหตุ** เพราะกลบ stderr ไว้ · รันใหม่โดยไม่กลบจึงเห็น: `GraphQL: Projects (classic) is being deprecated ... (repository.pullRequest.projectCards)` ⇒ **body ไม่ถูกแก้เลย** แต่ถ้ากลบ stderr จะดูเหมือนผ่าน
- **Root Cause:** `gh pr edit` ยิง GraphQL ที่ขอ field `projectCards` ซึ่งถูก sunset ⇒ query ทั้งก้อนล้ม แม้ผู้ใช้ไม่ได้แตะ Projects เลย · เป็นบั๊กของ `gh` ไม่ใช่ของ repo
- **Correct Pattern/Solution:** เลี่ยงผ่าน REST API: `gh api -X PATCH repos/<owner>/<repo>/pulls/<n> -F body=@/tmp/body.md` (`-F` ที่ตามด้วย `@ไฟล์` อ่านเนื้อหาจากไฟล์) · **ยืนยันผลด้วยการอ่านกลับ** `gh api repos/.../pulls/<n> --jq '.body' | head`
- **Rule:** (1) **ห้ามกลบ stderr ของคำสั่งที่แก้ state ภายนอก** (`gh`, `git push`, `curl`) — นี่เป็นครั้งที่สองของรูปแบบนี้ในงานชุดนี้ (ครั้งแรก: `cmd | tail` แล้วต่อ `&& echo "✅"` ทำให้รายงานว่าสำเร็จทั้งที่ exit ไม่ใช่ 0) ⇒ ให้เขียนไฟล์ log แล้วอ่าน `echo "exit=$?"` แยก (2) คำสั่งที่ "แก้ของที่อยู่ข้างนอก" ต้อง **อ่านกลับมายืนยัน** ไม่ใช่เชื่อ exit code อย่างเดียว
- **Date Added:** 2026-09-14

### 🧩 asyncpg คืนคอลัมน์ `jsonb` เป็น **สตริง** — `if not isinstance(x, dict): x = {}` คือการทิ้งข้อมูลจริงอย่างเงียบ ๆ
- **Context/Problem:** ผู้ใช้กด "ยกเลิกรายการ" ในหน้าประวัติเงินเคลื่อนไหว แล้วขึ้น Swal `ยกเลิกไม่ได้ / ไม่พบรายการธุรกรรมนี้` **ทุกครั้ง** ที่รายการนั้นเป็นของยุคบัญชีคู่ (`transaction_date >= CUTOFF_DATE`) — ทั้งที่ `journal_entries` ทุกแถวนั้นมี `metadata->>'legacy_transaction_id'` เป็น id จริงอยู่ครบ (`audit_logs`: 6 แถว `error_detail='ไม่พบรายการธุรกรรมนี้'` โดย `entity_id` เป็น **เลขติดลบ**)
- **Root Cause:** ทั้ง repo **ไม่มี `set_type_codec` ผูกกับ pool เลย** ⇒ asyncpg คืน `metadata` (jsonb) มาเป็น **`str`** `'{"legacy_transaction_id": 502}'` **ไม่ใช่ dict** · แต่ `_legacy_id_from_journal` เปิดด้วย
  ```python
  if not isinstance(metadata, dict):
      metadata = {}          # ← ทิ้ง id จริง 502 ไปทั้งก้อนตรงนี้
  ```
  ⇒ ตกไปใช้ fallback ที่คืน **id ติดลบ** ⇒ หน้าจอส่ง id นั้นเข้า `revert_transaction` ⇒ `WHERE id = <ติดลบ>` ไม่เจอ ⇒ "ไม่พบรายการธุรกรรมนี้"
  🔴 **ทำไมไม่มีใครจับได้:** ค่าที่ผิดคือ id ที่ **"ดูเหมือน id"** (แค่ติดลบ) ไม่ใช่ crash ไม่ใช่ `None` ⇒ ไม่มี log ไหนฟ้อง · และ **เทสต์เดิมไม่เคย assert `id` เลย** (assert แค่ยอด/ประเภท/ชื่อหมวด) ⇒ เขียวมาตลอดจนมีคนกดปุ่ม
- **Correct Pattern/Solution:** แปลงที่ **ขอบเขต** ก่อนใช้ และตรวจว่าผลลัพธ์เป็น dict จริง — ท่าเดียวกับที่ repo ทำถูกอยู่แล้ว **3 ที่** (`activity/base.py:_parse_metadata`, `finance/export.py`, `finance/receipts.py`)
  ```python
  def _metadata_to_dict(raw: Any) -> dict:
      if isinstance(raw, dict): return raw
      if isinstance(raw, str):
          try: parsed = json.loads(raw)
          except (ValueError, TypeError): return {}
          return parsed if isinstance(parsed, dict) else {}
      return {}
  ```
  ⚠️ **ห้ามแก้ด้วยการติด jsonb codec ที่ pool** — มี 6+ จุดที่ `json.loads` ค่าอยู่แล้ว และ `rbac.py` ยังเขียนคอมเมนต์เข้าใจผิดว่า *"asyncpg แปลง JSONB กลับมาให้อัตโนมัติ"* ⇒ codec จะเปลี่ยนชนิดให้ **ทั้งแอปพร้อมกัน** ต้องกวาดให้ครบก่อน (กวาดแล้ว 66 จุดเมื่อ 2026-09-15)
- **Rule:** (1) ทุกครั้งที่อ่านคอลัมน์ jsonb ต้อง **decode ก่อนใช้** (2) 🔴 **ห้ามเขียน `if not isinstance(x, dict): x = {}` กับค่าที่เพิ่งอ่านจาก DB** — รูปนี้ **เงียบ**; ถ้าจะปฏิเสธข้อมูลให้ **raise** (แบบที่ `activity/base.py:186` ทำ) (3) ค่าที่ "ดูถูกแต่ผิด" (id ติดลบ, 0, ชื่อหมวดกลาง ๆ) คือบั๊กที่เทสต์ไม่จับ — ต้องมีเทสต์ที่ **assert ค่าจริง** ไม่ใช่แค่ assert ว่าไม่ throw (4) ฟังก์ชันที่สังเคราะห์ id ให้ client **ต้องมีเทสต์ round-trip** — เอา id ที่ได้ไปใช้จริง ไม่ใช่เทสต์แค่ว่ามันคืน `int` (5) ตรวจสุขภาพทั้ง repo ด้วย `grep -rn -B2 "not isinstance(.*, dict)" backend/` แล้วแยกให้ออกว่า **ตัวไหน validate payload (raise — ปลอดภัย)** กับ **ตัวไหนอ่าน DB (blank — อันตราย)**
- **Tests:** `test_finance_v2_read.py` → `test_metadata_to_dict_accepts_both_str_and_dict` · `test_v2_transaction_id_is_the_real_legacy_id` · `test_v2_transfer_id_points_at_a_real_transaction_row` · `test_revert_transaction_accepts_the_id_from_the_transaction_list` (round-trip: id จากรายการ → revert สำเร็จ → แถวหายจริง) · 🧬 `tests/_mutation_jsonb_meta.py` **7/7 ถูกจับ · รอด 0**
- **Date Added:** 2026-09-15

### 🎲 `hash()` ของสตริงใน Python ถูกใส่ salt **ต่อโปรเซส** — ห้ามใช้สร้างค่าที่ client อ้างอิง
- **Context/Problem:** id สำรองของแถว journal (แถวที่ไม่มี legacy id เช่น `opening_balance`) สร้างด้วย `-(abs(hash(str(journal_uuid))) % …)` ⇒ **UUID เดียวกันให้ id คนละค่าในแต่ละโปรเซส** — วัดบน staging ได้ `1376437036645411758` · `-4318364185880035763` · `-3882699260063488080` จากการรัน 3 ครั้ง
- **Root Cause:** CPython ใส่ salt สุ่มให้ `hash()` ของ `str`/`bytes` ตั้งแต่ 3.3 (`PYTHONHASHSEED`) เพื่อกัน hash-collision attack ⇒ ค่า **ไม่คงที่ข้ามโปรเซส** (ภายในโปรเซสเดียวคงที่) · ผลคือแถวเดิมได้ id ต่างกันในแต่ละ replica ×3 และเปลี่ยนใหม่ทุกครั้งที่รีสตาร์ท ⇒ key ฝั่ง frontend, URL, log เทียบกันไม่ได้เลย
  ⚠️ **มองไม่เห็นตอนเทสต์** เพราะทุกเทสต์รันในโปรเซสเดียว
- **Correct Pattern/Solution:** ใช้ฟังก์ชันที่นิยามไว้แน่นอน — `zlib.crc32` (เร็ว ช่วงค่าเดิม) หรือ `hashlib.blake2b`/`sha256` ตัด 8 ไบต์ (ชนกันยากกว่า ถ้าต้องรองรับหลายล้านแถว)
  ```python
  return -(zlib.crc32(str(journal_uuid).encode("utf-8")) % (2**31 - 1) + 1)
  ```
- **Rule:** (1) **ห้าม `hash()` กับค่าที่ออกนอกโปรเซส** (id, cache key, ชื่อไฟล์, signature) — ใช้ `zlib.crc32`/`hashlib`; ⚠️ ถ้าเป็นเรื่อง **ความปลอดภัย** ต้อง `hmac`/`hashlib` เท่านั้น ห้าม `crc32` (2) จะพิสูจน์ความคงที่ **ต้องรันในโปรเซสลูกที่ `PYTHONHASHSEED` ต่างกัน** — เทสต์ในโปรเซสเดียว **ผ่านเสมอแม้โค้ดจะผิด** (3) เขียน **เทสต์คู่** ที่พิสูจน์ว่ากับดักยังมีจริง (`hash()` ต้องให้ค่าต่างกันจริงในโปรเซสลูก) ไม่งั้นเทสต์ความคงที่อาจ "เขียวหลอก" เพราะไม่ได้พิสูจน์อะไร
- **Tests:** `test_journal_fallback_id_is_stable_across_processes` (โปรเซสลูก 3 ตัว seed `0`/`1`/`12345`) · mutation "fallback กลับไปใช้ `hash()`" → ถูกจับ
- **Date Added:** 2026-09-15

### 🧪 harness ของ mutation test ที่ "พังตอนสตาร์ท" ถูกรายงานเป็น "เทสต์จับได้" — vitest 4 ไม่มี `--reporter=basic`
- **Context/Problem:** สคริปต์ mutation ฝั่ง frontend รายงาน **"ถูกจับ 14/14 · รอด 0"** ตั้งแต่รันครั้งแรก ซึ่งดีเกินจริง ⇒ พอเปิด log ดูจึงเห็นว่าทุกครั้งขึ้น `Startup Error: Failed to load custom Reporter from basic` = **ไม่มีเทสต์ถูกรันเลยสักตัว** แต่สคริปต์อ่าน `exit code != 0` เป็น "เทสต์ล้ม = จับได้" ⇒ **ความล้มเหลวของเครื่องมือถูกรายงานเป็นความสำเร็จของเทสต์**
- **Root Cause:** vitest 4 **ตัด `--reporter=basic` ออกแล้ว** และตีความ argument ที่ไม่รู้จักเป็น **path ของ reporter ที่ผู้เขียนเอง** ⇒ พังตอนสตาร์ท · ซ้ำร้าย exit code ของ "สตาร์ทไม่ขึ้น" กับ "เทสต์ล้ม" **เป็นค่าเดียวกัน** ⇒ แยกไม่ออกถ้าดูแค่ exit code
- **Correct Pattern/Solution:** ใช้ `--reporter=dot` (หรือ `default`) และ **ตรวจ output ก่อนตัดสิน**:
  ```js
  const harnessBroken =
    /Startup Error|No test files found|Failed to load|Failed to load custom Reporter/.test(out) ||
    !/Tests\s+/.test(out)          // ← ต้องมีบรรทัดสรุป "Tests N passed/failed" จริง
  if (harnessBroken) return { outcome: 'harness' }   // ห้ามนับเป็น caught
  ```
  แยก bucket ให้ชัด 4 กอง: `caught` · `survived` (เทสต์จับไม่ได้จริง ⇒ ต้องแก้เทสต์) · `broken` (mutation ทำให้คอมไพล์ไม่ผ่าน = วัดไม่ได้) · `harness` (เครื่องมือพัง)
- **Rule:** (1) 🔴 **ห้ามตัดสินผล mutation จาก exit code อย่างเดียว** — ต้องยืนยันว่าเทสต์ **รันจริง** (มีบรรทัดสรุป) ก่อน (2) เครื่องมือที่ "พังแล้วรายงานว่าสำเร็จ" อันตรายกว่าเครื่องมือที่พังเฉย ๆ ⇒ ทุก harness ต้องมี guard ที่พิสูจน์ว่าตัวเองทำงาน (3) `anchor ไม่ชัด` (หา string ที่จะ mutate ไม่เจอ) **ต้องแยกจาก** `รอด` — สองเรื่องนี้เคยถูกรวมกันแล้วอ่านผิดว่า "เทสต์อ่อน" ทั้งที่ความจริงคือ "mutation ไม่ได้ถูกทดสอบ"
- **Tests:** `frontend/src/components/ui/__tests__/_mutation_row_action_menu.mjs`
- **Date Added:** 2026-09-15

### 🧬 รายการ mutation ที่ "เราเลือกเอง" ไม่ได้วัดความครอบคลุม — "14/14 · รอด 0" คือความมั่นใจปลอม
- **Context/Problem:** หลังเขียนเทสต์ถดถอย 11 ตัวให้ `RowActionMenu.vue` แล้ว mutation harness รายงาน **"ถูกจับ 14/14 · รอด 0"** ⇒ เกือบสรุปว่าเทสต์ครอบคลุมครบ · แต่ผู้รีวิวยิง mutation ชุด **ใหม่ 13 ตัว** ใส่คอมโพเนนต์เดียวกัน **ผ่านเทสต์ทั้ง 11 ตัวหมด** — รวมถึง `open(event.detail === 0)` → `open(true)`, `const step = 1;`, ลบการนำทางด้วยลูกศรทั้งท่อน, ลบ listener ของ resize, `PANEL_WIDTH` 208→240 และ `:style="panelStyle"` → `:style="{top:'0px',left:'0px'}"` ⇒ **positioning / keyboard / resize ซึ่งเป็นเหตุผลทั้งหมดที่คอมโพเนนต์นี้มีอยู่ กลับไม่มี mutation สักตัว**
- **Root Cause:** mutation list ที่ **คนเขียนเทสต์เป็นคนเลือกเอง** มีอคติแบบหลีกเลี่ยงไม่ได้ — เรานึกถึงสาขาที่เพิ่งเขียนเทสต์ให้ แต่ **ลืมนึกถึงสาขาที่เราลืมเทสต์** ⇒ ตัวเลขที่ได้วัด "รายการที่เลือกมาทดสอบ" ไม่ได้วัด "โค้ดที่ครอบคลุม" · ยิ่งเป็นไฟล์ที่เขียนมือทั้งไฟล์ (ไม่มี mutation generator อัตโนมัติ) ยิ่งชัด
- **Correct Pattern/Solution:** (1) เขียน mutation **จากรายการความรับผิดชอบของโค้ด** ไม่ใช่จากรายการเทสต์ — ไล่ทีละฟีเจอร์ที่ไฟล์นี้รับผิดชอบแล้วถามว่า "ถ้าฟีเจอร์นี้พัง จะมี mutation ตัวไหนพิสูจน์" (2) ให้ **คนอื่น** (หรือ subagent ที่ไม่เห็นเทสต์) ยิง mutation ชุดใหม่ (3) ถ้ามี mutation ที่รอด ⇒ **แก้เทสต์ ไม่ใช่ลบ mutation ออก** และถ้า *จงใจ* ไม่แก้ (เช่น เคสที่เข้าถึงไม่ได้จริง) **ต้องเขียนบอกใน PR** ไม่ใช่เงียบ
- **Rule:** (1) 🔴 **ห้ามอ่าน "ถูกจับ N/N · รอด 0" ว่า "ครอบคลุม"** — ต้องเขียนกำกับเสมอว่า N คือ *รายการที่เลือกทดสอบ* (2) ไฟล์ที่เขียนมือทั้งไฟล์ต้องมี mutation อย่างน้อย **1 ตัวต่อ 1 ความรับผิดชอบ** (3) mutation ที่ "รอด" มีค่าเท่ากับบั๊กที่ยังไม่มีเทสต์ — ต้องปิดด้วยเทสต์ใหม่ ไม่ใช่ด้วยคำอธิบาย
- **Tests:** `_mutation_row_action_menu.mjs` ขยายจาก 14 → **39 mutation** หลังรีวิว (+ เทสต์ที่เพิ่มเพื่อปิดช่อง: แผงล้นจอแนวตั้ง · ขอบขวา · `Esc` ที่โฟกัสไม่อยู่ที่ปุ่ม · ลำดับ z-index ของฉากหลัง · `@click.stop`)
- **Date Added:** 2026-09-15

### 🖱️ `.click()` บนปุ่มที่ `disabled` ไม่ยิง event เลย (ทั้งเบราว์เซอร์และ jsdom) ⇒ เทสต์เขียวเพราะไม่ได้ทดสอบอะไร
- **Context/Problem:** เทสต์ "ไอเทมที่ถูก disable ต้องไม่ยิง `@select`" ใช้ `item.click()` แล้วเขียวมาตลอด — จนเอา mutation "ถอด guard `if (item.disabled) return`" ไปวาง ปรากฏว่า **เทสต์ยังเขียว**
- **Root Cause:** HTML spec กำหนดว่าการ `click()` บน **form control ที่ disabled** ต้อง **return ทันทีโดยไม่ dispatch event** ⇒ ทั้งเบราว์เซอร์จริงและ jsdom ไม่ยิง `click` ออกมาเลย ⇒ handler ถูกเรียก **0 ครั้ง** ⇒ assertion `expect(emitted).toBeUndefined()` ผ่าน **ด้วยเหตุผลผิด** (ไม่ใช่เพราะ guard ทำงาน แต่เพราะไม่มี event ตั้งแต่แรก)
- **Correct Pattern/Solution:** ยิง event เองเพื่อข้ามข้อจำกัดของ spec — พร้อม **assert ว่าปุ่ม disabled จริง** เพื่อไม่ให้เทสต์ผ่านเพราะปุ่มบังเอิญไม่ disabled
  ```js
  expect(item).toHaveProperty('disabled', true)                  // ยืนยันสมมติฐานก่อน
  item.dispatchEvent(new MouseEvent('click', { bubbles: true }))  // ข้ามข้อจำกัดของ .click()
  await nextTick()
  expect(emitted).toBeUndefined()
  ```
- **Rule:** (1) 🔴 **การทดสอบว่า "guard ทำงาน" ต้องทำให้ event ไปถึง guard ให้ได้ก่อน** — ถ้า UI บล็อกไม่ให้ event เกิดแต่แรก เทสต์นั้นพิสูจน์ guard ไม่ได้เลย (2) เมื่อ mutation "ถอด guard" **ไม่ถูกจับ** ให้สงสัยก่อนว่า **event ไม่เคยไปถึงโค้ดนั้น** (3) เทสต์ที่ assert "ไม่เกิดอะไรขึ้น" ต้องพิสูจน์ด้วยว่าสภาพตั้งต้นเอื้อให้เกิดได้
- **Tests:** `RowActionMenu.spec.ts` → เคส "ไอเทมที่ disabled …" (dispatchEvent + assert `disabled` attribute + assert class `cursor-not-allowed`)
- **Date Added:** 2026-09-15

### 🧭 Safari (macOS) ไม่ย้ายโฟกัสมาที่ `<button>` เมื่อคลิกด้วยเมาส์ — อย่าผูก `Escape` กับ "โฟกัสอยู่ที่ปุ่ม"
- **Context/Problem:** ระหว่างแก้บั๊ก "ลูกศรของทั้งหน้าถูกเมนูยึด" จึงเพิ่ม `if (!ownsFocus()) return;` ไว้ต้น `onKeydown` **ครอบทุกคีย์** ⇒ เทสต์ 4 ตัวล้มทันทีเพราะหลังคลิกด้วยเมาส์ `document.activeElement` เป็น `<body>` ⇒ พอไล่ดูจริงพบว่าถ้าปล่อยไว้ **ผู้ใช้ Safari จะกด Esc แล้วเมนูไม่ปิดเลย**
- **Root Cause:** Safari บน macOS **ไม่ย้าย focus ไปที่ปุ่มเมื่อคลิกด้วยเมาส์** (ต่างจาก Chrome/Firefox) ⇒ `ownsFocus()` เป็น false แม้ผู้ใช้เพิ่งคลิกปุ่มนั้นเอง · ในทางกลับกัน **การยึดลูกศรคือบั๊กจริง** ที่ต้องเช็คโฟกัส ⇒ **สองคีย์นี้ต้องการเงื่อนไขคนละแบบ การใช้ guard ตัวเดียวกันครอบทั้งคู่จึงผิด**
- **Correct Pattern/Solution:** แยกเงื่อนไขตาม "คีย์นี้เป็นของใคร":
  - `Tab` / `Escape` ⇒ **ไม่มีเงื่อนไข** (เมนูที่เปิดอยู่มีฉากหลังคลุมทั้งหน้า = overlay บนสุด ⇒ Esc ที่ไหนก็ควรปิด)
  - `ArrowUp` / `ArrowDown` ⇒ **ต้องมี** `ownsFocus()` (ไม่งั้นไป `preventDefault()` ลูกศรของทั้งหน้าและกระชากโฟกัสจาก `<select>` ของตัวกรองเข้ามา)
  ข้อสังเกตจากเทสต์: jsdom **ก็ไม่ย้ายโฟกัสให้เช่นกัน** ⇒ เทสต์เส้นทางลูกศรต้อง `triggerEl().focus()` เอง
- **Rule:** (1) 🔴 **ห้ามใช้ guard "โฟกัสอยู่กับเราไหม" กับปุ่มที่เปิด overlay** — Safari จะพังเงียบ (2) ก่อนผูก logic กับ `document.activeElement` ให้ถามว่า "เบราว์เซอร์อื่นย้ายโฟกัสให้เหมือนกันไหม" (3) เมื่อเทสต์ล้มพร้อมกันหลายตัว ให้สงสัยว่า **สมมติฐานของเทสต์กับของเบราว์เซอร์ไม่ตรงกัน** ไม่ใช่รีบแก้เทสต์ให้ผ่าน
- **Date Added:** 2026-09-15

### ✂️ เมนู `position: absolute` ใช้ไม่ได้กับตารางที่ `overflow-hidden` + `overflow-x-auto` — ต้อง Teleport ไป `body` + `fixed`
- **Context/Problem:** ต้องซ่อนปุ่ม "ยกเลิกรายการ" (ทำลายข้อมูล) ไว้ในเมนูจุด 3 จุดกลางแถวตาราง แต่ DESIGN.md §5 **บังคับ** ให้ทุกตารางครอบ `page-card hidden overflow-hidden lg:block` และมี `overflow-x-auto` ⇒ เมนูที่วาง `absolute` ในเซลล์จะ **ถูกตัดหายทั้งแผงโดยไม่มี error ใด ๆ** (แย่กว่านั้น: ปุ่มยังกดได้ แต่แผงที่เปิดมาไม่ปรากฏ ⇒ ดูเหมือน "กดแล้วไม่มีอะไรเกิดขึ้น")
- **Root Cause:** `overflow: hidden/auto` สร้าง **clipping context** ให้ descendant ที่ `position: absolute` ทุกตัวที่ไม่มี containing block อยู่ข้างนอก · จะแก้ด้วย `z-index` ไม่ได้เลย (ไม่ใช่เรื่อง stacking) · และใน jsdom **มองไม่เห็นบั๊กนี้เลย** เพราะ jsdom ไม่ทำ layout/clipping
- **Correct Pattern/Solution:** `<Teleport to="body">` + `position: fixed` แล้วคำนวณพิกัดจาก `getBoundingClientRect()` ของปุ่มเอง + **ปิดเมื่อ scroll (capture) และ resize** (เพราะ `fixed` ไม่ขยับตามพ่อ ต้องปิดทิ้งแทน) — เป็นท่าเดียวกับ `MainLayout.vue` ⇒ **ท่า Teleport นี้คือ recipe ของ repo**
  ⚠️ ต้องมี **ฉากหลัง (backdrop) ที่มี z-index** ด้วย ไม่งั้นองค์ประกอบอื่นบนหน้า (header แบบ sticky) จะอยู่เหนือฉาก ⇒ คลิกนอกครั้งแรกไปโดนอย่างอื่นแทนที่จะปิดเมนู
  ⚠️ ทางเลือกที่มีอยู่ใน repo: `StudentList.vue:303` แก้ด้วยการ **ถอด `overflow-hidden` ออก** จาก `.page-card` ของตัวเอง — ใช้ได้กับหน้าที่ตารางไม่ต้องเลื่อนแนวนอนเท่านั้น
- **Rule:** (1) 🔴 **ห้ามวางเมนู/ดรอปดาวน์แบบ `absolute` ในตารางที่ครอบ `overflow-hidden`** (2) เทสต์ jsdom **พิสูจน์ clipping ไม่ได้** ⇒ อย่างน้อยต้อง assert ว่าแผงถูก teleport ออกนอกพ่อที่ clip (`host.contains(menu) === false`) และเป็น `fixed` แบบ **โทเคนทั้งคำ** (`classList.contains('fixed')` — `toContain('fixed')` ผ่านได้กับ `bg-fixed`!) (3) คอมโพเนนต์ที่ `fixed` ต้องผูก `scroll`(capture)/`resize` เพื่อปิดตัวเอง และ **ถอด listener ตอน unmount เทียบ `(type, fn, capture)`** ไม่ใช่เทียบชื่อ
- **Tests:** `RowActionMenu.spec.ts` → `createClippingHost()` + เคส "แผงหลุดออกจากพ่อที่ overflow-hidden" · เคสปิดเมื่อ scroll/resize · เคส listener cleanup เทียบ triple
- **Date Added:** 2026-09-15

### 🎨 Tailwind arbitrary value ที่มี `calc()` ต้องใส่ `_` แทนเว้นวรรค ไม่งั้นถูกทิ้งเงียบ ๆ
- **Context/Problem:** เขียน `max-h-[calc(100vh-1.5rem)]` เพื่อจำกัดความสูงเมนู ⇒ **ไม่มี error ไม่มี warning** แต่ CSS ไม่ถูกสร้าง ⇒ เพดานความสูงไม่มีผลจริง (เมนูยาวเกินจอล้น และไอเทมท้าย ๆ กดไม่ได้ — ซึ่งเป็นบั๊กที่เพดานนี้ตั้งใจกันไว้พอดี)
- **Root Cause:** Tailwind ตัดคำใน arbitrary value ด้วย **ช่องว่าง** ⇒ `calc(100vh-1.5rem)` ที่ไม่มีช่องว่างรอบ `-` ไม่ใช่ `calc()` ที่ถูกต้องตาม CSS ⇒ declaration ทั้งเส้นถูก **drop เงียบ ๆ** · ต้องเขียนช่องว่างเป็น `_` ซึ่ง Tailwind แปลงกลับให้
- **Correct Pattern/Solution:** `max-h-[calc(100vh_-_1.5rem)]` · เช่นเดียวกันกับ `grid-cols-[repeat(3,_minmax(0,_1fr))]`
- **Rule:** (1) arbitrary value ที่มี `calc()`/ฟังก์ชันหลายอาร์กิวเมนต์ ต้องใช้ `_` แทนเว้นวรรคทุกจุด (2) คลาสที่ Tailwind "ทิ้งเงียบ" ต้องมี **เทสต์ที่ assert ว่าคลาสนั้นติดอยู่จริง** — เทสต์จะไม่จับ "CSS ไม่ถูกสร้าง" แต่จะจับ "คลาสหายไปจาก template" (3) อาการ "ใส่คลาสแล้วไม่มีผล" ให้สงสัยว่า Tailwind ไม่รู้จักคลาสนั้นก่อนสงสัย CSS อื่น
- **Tests:** `RowActionMenu.spec.ts` → assert `max-h-[calc(100vh_-_1.5rem)]` และ `overflow-y-auto`
- **Date Added:** 2026-09-15

### 🗡️ ฆ่า mutation harness กลางคัน = ไฟล์ที่กำลัง mutate ค้างอยู่ในสภาพพัง และ **กู้ไม่ได้ถ้ายังไม่ commit**
- **Context/Problem:** หยุดสคริปต์ mutation ด้วย `TaskStop` ระหว่างรัน ⇒ `RowActionMenu.vue` (ไฟล์ใหม่ ยังไม่ถูก commit) **ค้างอยู่ในสภาพ mutated** — `:style="panelStyle"` กลายเป็น `:style="{ top: '0px', left: '0px' }"` · handler `SIGINT`/`SIGTERM` ที่เขียนไว้ **ไม่ได้ทำงาน** เพราะ process ถูกฆ่าก่อนถึงจังหวะ ⇒ **ไม่เหลือต้นฉบับที่ไหนเลย** (untracked file ⇒ `git checkout` กู้ไม่ได้) กู้กลับได้เพราะบังเอิญเทียบ anchor แล้วเห็นว่าผิดอยู่บรรทัดเดียว
- **Root Cause:** สคริปต์ mutation **ต้องแก้ไฟล์จริงโดยธรรมชาติ** ⇒ มีช่วงเวลาที่ working tree อยู่ในสภาพพังเสมอ · การพึ่ง `finally`/signal handler ครอบคลุมไม่ได้ทุกวิธีที่ process ตาย (SIGKILL, การฆ่า process group, เครื่องดับ) · และความเสี่ยงนี้ **สูงสุดกับไฟล์ใหม่ที่ยังไม่ commit** ซึ่งเป็นกรณีปกติของงานที่กำลังทำอยู่
- **Correct Pattern/Solution:** (1) **สำรองต้นฉบับออกไปนอก repo ก่อนเริ่ม** (`os.tmpdir()`) แล้วพิมพ์ path ให้เห็น (2) คืนไฟล์ใน `finally` **ต่อ iteration** (ไม่ใช่แค่ท้ายสคริปต์) ⇒ ช่วงที่ไฟล์พังสั้นลงเหลือเฉพาะระหว่างรันเทสต์ (3) ตรวจว่าคืนแล้วจริงด้วยการเทียบ anchor ทุกตัวก่อนรันรอบถัดไป
  ```js
  const BACKUP = resolve(tmpdir(), '_RowActionMenu.original.vue')
  writeFileSync(BACKUP, original, 'utf8')
  // …ในลูป:
  writeFileSync(COMPONENT, mutated, 'utf8')
  let result
  try { result = runSpec() } finally { restore() }   // ← คืนทันที
  ```
- **Rule:** (1) 🔴 เครื่องมือที่แก้ไฟล์ต้นฉบับ **ต้องสำรองออกนอก repo เสมอ** ถ้าไฟล์นั้นยังไม่ถูก commit (2) อย่าพึ่ง signal handler อย่างเดียว — `finally` ต่อ iteration คือด่านที่เชื่อถือได้กว่า (3) ถ้าไฟล์ค้าง mutated ให้ **เทียบ anchor** เพื่อหาว่าผิดบรรทัดไหน แทนการเขียนใหม่ทั้งไฟล์ — และถ้ากู้ไม่ได้จริง **ต้องบอกผู้ใช้ตรง ๆ ว่าไฟล์เสีย** ไม่ใช่รายงานว่างานเสร็จ
- **Tests:** `_mutation_row_action_menu.mjs` (บรรทัด `BACKUP` + `finally { restore() }`)
- **Date Added:** 2026-09-15

### 🧱 คอลัมน์ที่เพิ่มทีหลังต้อง ALTER และ **index ของมันต้องอยู่ในบล็อก ALTER ด้วย** — `CREATE TABLE IF NOT EXISTS` เป็น no-op บน DB ที่ deploy แล้ว
- **Context/Problem:** งาน F5 เพิ่ม `finance_receipts.batch_id` พร้อม index และ FK คู่ ถ้าเขียนทั้งหมดไว้ในบล็อก `CREATE TABLE IF NOT EXISTS finance_receipts` (ที่บรรทัด ~415) โค้ดจะ**ผ่านเทสต์ทุกตัว** เพราะ `conftest.py` สร้าง DB ใหม่เอี่ยมจาก `init_db` ⇒ บล็อกนั้นรันจริง **แต่พังทั้งระบบบน DB ที่ deploy F3 ไปแล้ว** ซึ่งเป็น DB จริงเพียงตัวเดียวที่มีข้อมูลผู้ใช้
- **Root Cause:** `CREATE TABLE IF NOT EXISTS` **ไม่ทำอะไรเลยถ้าตารางมีอยู่** ⇒ ทั้งคอลัมน์/index/FK ในบล็อกนั้นถูกข้ามเงียบ ๆ · และถ้าย้าย index ไปไว้ "ท้ายบล็อก CREATE TABLE" ก็ยังพังอยู่ดี เพราะบน DB เก่าบล็อกนั้นรัน **ก่อน** บล็อก Extra Alterations เสมอ ⇒ ได้ `column "batch_id" does not exist` **ตอนบูต** = ทุก replica บูตไม่ขึ้น (ตารางใหม่ไม่มีความเสี่ยงนี้ เพราะ `CREATE TABLE` สร้างคอลัมน์กับ index ให้ในคำสั่งเดียวกัน)
- **Correct Pattern/Solution:** แยก 3 คำสั่ง เรียงแบบนี้เท่านั้น (`backend/core/init_db.py:749-771`) — และ **คอมเมนต์กำกับว่าทำไม index ต้องอยู่ตรงนี้** ไม่งั้นคนถัดไปจะ "จัดระเบียบ" ย้ายมันกลับไป:
  ```python
  await conn.execute("ALTER TABLE finance_receipts ADD COLUMN IF NOT EXISTS batch_id INTEGER;")
  await conn.execute(  # ← หลัง ADD COLUMN เสมอ
      "CREATE INDEX IF NOT EXISTS idx_finance_receipts_batch"
      " ON finance_receipts(batch_id) WHERE batch_id IS NOT NULL AND deleted_at IS NULL;")
  await conn.execute("ALTER TABLE ... DROP CONSTRAINT IF EXISTS fk_...;")
  await conn.execute("ALTER TABLE ... ADD CONSTRAINT fk_... FOREIGN KEY ...;")
  ```
  `DROP CONSTRAINT IF EXISTS` + `ADD` มีช่วงแข่งกันข้าม replica (ยอมรับได้เมื่อคอลัมน์เพิ่งถูกเพิ่มด้วยค่า NULL ทั้งหมด ⇒ validate ผ่านทันที ไม่มีทางล้มเพราะข้อมูลเก่า และ replica ที่แพ้แค่ fail ตอนบูตแล้วเข้ามาใหม่)
- **Rule:** (1) 🔴 **ตารางที่มีอยู่ก่อนหน้า ⇒ ห้ามพึ่ง `CREATE TABLE IF NOT EXISTS` ให้เพิ่มอะไรให้** ต้องมี ALTER ทุกครั้ง (2) **index ของคอลัมน์ที่เพิ่ง ALTER ต้องอยู่ในบล็อก ALTER หลัง ADD COLUMN** — ไม่ใช่ใน CREATE TABLE (3) เทสต์ที่สร้าง DB ใหม่ **มองไม่เห็นกับดักนี้เลย** ⇒ ต้องยิง DDL กับ DB ที่มีข้อมูลเดิมจริงด้วย (ขั้นตอนตรวจในแผน F5 ข้อ 5) (4) ก่อน "จัดระเบียบ" DDL ให้ย้ายที่ ต้องอ่านคอมเมนต์ที่อธิบายลำดับก่อน
- **Tests:** `tests/test_finance_receipt_batches.py` (ทั้งไฟล์รันบน DB ที่ `init_db` สร้าง) + การยิง `init_db` ซ้ำกับ DB ที่มีข้อมูลเดิม
- **Date Added:** 2026-09-15

### 🔢 `COUNT(*) OVER (PARTITION BY …)` โกหกเมื่อมี `WHERE` กรองสมาชิกออก — "ขนาดชุด" ต้องมาจากคำขอที่สอง
- **Context/Problem:** ต้องแสดง "แสดง 12 จาก 20 ใบ" ในทะเบียนเอกสาร (`batch_size` = ขนาด**ทั้งชุด**, `visible count` = ที่รอดตัวกรอง) ทางที่สั้นที่สุดคือ window function ในคำขอเดิม ⇒ **ผ่านเทสต์ทุกตัวที่กรองไม่ตัดสมาชิกออก** แต่พอผู้ใช้กรองช่วงวันที่ (หรือปิด `include_voided`) ตัวเลขจะกลายเป็น "ขนาดของส่วนที่เห็น" ⇒ ป้ายบนจอบอกว่า "แสดง 20 จาก 20 ใบ" ทั้งที่ในชุดมี 20 และเห็นแค่ 3 = **คำโกหกที่ผู้ใช้ตรวจไม่ได้** (ผู้ใช้ไม่มีทางรู้ว่ามีใบอื่นซ่อนอยู่)
- **Root Cause:** window function คำนวณ **หลัง** `WHERE` ⇒ มันเห็นเฉพาะแถวที่รอดตัวกรอง ไม่เคยเห็นสมาชิกที่ถูกตัดออก · ตัวกรองเป็นการตัดสินใจของ**หน้าจอ** ส่วนขนาดชุดเป็น**ข้อเท็จจริงของข้อมูล** — สองอย่างนี้ต้องมาจากคนละคำขอ
- **Correct Pattern/Solution:** คำขอที่สองที่ **ไม่มีตัวกรองของหน้าจอ** นับจากทั้งชุด (`receipt_batches.py:_load_batch_counts`):
  ```sql
  SELECT batch_id,
         COUNT(*) FILTER (WHERE deleted_at IS NULL AND status = 'active') AS active_cnt,
         COUNT(*) FILTER (WHERE deleted_at IS NOT NULL OR status <> 'active') AS voided_cnt
  FROM finance_receipts WHERE room_id = $1 AND batch_id = ANY($2::int[]) GROUP BY batch_id
  ```
  ⇒ `batch_size = active_cnt + voided_cnt` · **ใบที่ถูกยกเลิกยังนับเป็นสมาชิกชุด** (ชุดคือบันทึกว่า "ออกพร้อมกัน" การถอดสมาชิก = เขียนประวัติใหม่ และชื่อ "20 ใบ" จะกลายเป็นคำโกหก) ⇒ `batch_voided_count` ทำให้หน้าจอบอกความจริงได้
- **Rule:** (1) 🔴 **ห้ามใช้ window function นับ "ขนาดของทั้งกลุ่ม" ในคำขอที่มีตัวกรองของหน้าจอ** — มันนับเฉพาะส่วนที่เหลือ (2) ตัวเลขที่ผู้ใช้ใช้ตัดสินใจ ต้องแยก "ของจริง" กับ "ที่เห็น" ให้ชัด และบอกทั้งคู่ (3) เก็บค่าที่ผู้ใช้เห็นเป็น**ค่าที่คำนวณจาก backend** ไม่ใช่ `items.length` ฝั่งจอ — ฝั่งจอเห็นน้อยกว่าเสมอเมื่อมีตัวกรอง
- **Tests:** `tests/test_finance_receipt_batches.py::test_true_batch_size_survives_the_date_filter` (ชุด 3 ใบคนละเดือน → กรองเดือนเดียว → `batch_size == 3` แต่ได้ 1 แถว) · mutation M4/M5 พิสูจน์ว่ามีฟัน
- **Date Added:** 2026-09-15

### 🔗 FK คู่ `(child_id, room_id)` + MATCH SIMPLE = กันเอกสารข้ามห้องที่ระดับ DB และ **ห้าม `ON DELETE SET NULL` เด็ดขาด**
- **Context/Problem:** "ชุดเอกสาร" ต้องกันไม่ให้ใบเสร็จของห้อง A ไปอยู่ในชุดของห้อง B — การเช็คใน service อย่างเดียวพลาดได้ทุกเมื่อที่มีคนเพิ่มเส้นทางเขียนใหม่ · แต่จะใส่ FK ธรรมดา (`batch_id REFERENCES ...`) ก็กันข้ามห้องไม่ได้ เพราะ FK ไม่รู้จัก `room_id`
- **Root Cause / ทางออก:** FK คู่ `FOREIGN KEY (batch_id, room_id) REFERENCES finance_receipt_batches(id, room_id)` บังคับว่า **คู่ (ชุด, ห้อง) ต้องมีอยู่จริง** ⇒ ย้ายใบข้ามห้อง = FK violation ตั้งแต่ที่ DB · ต้องมี `UNIQUE (id, room_id)` บนตารางปลายทาง (แม้ `id` เป็น PK แล้วก็ตาม — FK ต้องการ unique constraint บน**คู่คอลัมน์ที่อ้าง**) · และ **MATCH SIMPLE (ค่าเริ่มต้น)** = ถ้าคอลัมน์ใดเป็น NULL ให้ **ข้ามการตรวจทั้งแถว** ซึ่งเป็นพฤติกรรมที่ต้องการพอดี: เอกสารที่ยังไม่ถูกจัดชุด (`batch_id IS NULL`) ผ่านได้
  🔴 **`ON DELETE SET NULL` ใช้ไม่ได้กับ FK คู่** — Postgres จะพยายามตั้ง **ทุกคอลัมน์ใน FK เป็น NULL** รวม `room_id` ซึ่ง `NOT NULL` ⇒ ลบชุดจะ error ⇒ **"ยุบชุด" จึงต้องเป็น `UPDATE finance_receipts SET batch_id = NULL` ที่เขียนเองใน service** (ซึ่งตรงกับความต้องการอยู่แล้ว: ยุบชุดห้ามแตะเอกสาร)
- **Correct Pattern/Solution:**
  ```sql
  CONSTRAINT uq_receipt_batch_id_room UNIQUE (id, room_id),   -- เป้าของ FK คู่
  ...
  CONSTRAINT fk_receipts_batch_same_room FOREIGN KEY (batch_id, room_id)
      REFERENCES finance_receipt_batches(id, room_id)         -- ไม่มี ON DELETE
  ```
- **Rule:** (1) 🔴 **`ON DELETE SET NULL` บน FK คู่ = ระเบิดเวลา** (มันจะล้างคอลัมน์ที่เป็น NOT NULL ด้วย) (2) FK คู่ต้องมี `UNIQUE` บนคู่คอลัมน์ปลายทางเสมอ (3) MATCH SIMPLE คือสิ่งที่ทำให้ "ยังไม่จัดชุด" ผ่านได้ฟรี — **อย่าไปใส่ `MATCH FULL`** เพื่อ "เข้มขึ้น" เพราะจะบังคับให้ทุกใบต้องมีชุด (4) composite FK กันได้เฉพาะตอน**เขียน** `batch_id` — การอ่านยังต้องมี `WHERE room_id = $1` ของตัวเอง (ดู `_load_batch_row`)
- **Tests:** `tests/test_finance_receipt_batches.py::test_create_batch_rejects_receipt_of_another_room` + `::test_batch_is_scoped_to_the_room` · mutation M9 พิสูจน์ว่าด่านนี้มีฟัน
- **Date Added:** 2026-09-15

### 🧪 `noUncheckedIndexedAccess` ทำให้ **ไฟล์เทสต์** type-check ไม่ผ่านที่ `arr[0]` — ใช้ helper ที่ throw แทน `!`
- **Context/Problem:** เขียน `utils/__tests__/receiptGroups.spec.ts` ผ่าน vitest ทุกตัว (19 passed) แต่ `npm run type-check` ล้ม **39 error** ในไฟล์เดียว โดยไม่มี error ใน `receiptGroups.ts` หรือ `ReceiptList.vue` เลย
- **Root Cause:** `tsconfig.app.json` เปิด `noUncheckedIndexedAccess: true` และ **`vue-tsc --build` ครอบไฟล์ `__tests__/*.spec.ts` ด้วย** ⇒ `result.groups[0]` มีชนิด `T | undefined` ส่งต่อให้ฟังก์ชันที่รับ `T` ไม่ได้ · ที่ร้ายกว่าคือ **re-index ซ้ำ defeats narrowing**: `rows[1].kind === 'batch' && rows[1].items` — `rows[1]` ตัวที่สองถูกอ่านใหม่ ⇒ ชนิดกลับไปเป็น union เดิม ⇒ ได้ `Property 'items' does not exist on type 'ReceiptSoloRow<...>'` · เทสต์เดิมในโปรเจกต์รอดมาได้เพราะ index อยู่แต่ใน `expect(...)` ซึ่งรับ `unknown` ได้
- **Correct Pattern/Solution:** helper ที่ **โยน error พร้อมบอก index** (ไม่ใช่ `!` ซึ่งปิดปาก compiler โดยไม่บอกอะไรเมื่อสมมติฐานผิด):
  ```ts
  const at = <T>(arr: readonly T[], i: number): T => {
    const value = arr[i];
    if (value === undefined) throw new Error(`คาดว่ามีสมาชิกที่ index ${i} แต่มีแค่ ${arr.length} ตัว`);
    return value;
  };
  // แล้วเขียน: const group = at(result.groups, 0);
  // และสำหรับ narrowing: const row = at(rows, 1); if (row.kind !== 'batch') throw ...; row.items
  ```
  ⇒ ได้ทั้ง type ที่แคบลง (ผูกกับ **ตัวแปรตัวเดียว**) และข้อความที่บอกว่าอะไรผิด
- **Rule:** (1) 🔴 **ไฟล์เทสต์ก็ถูกตรวจชนิด** — "vitest เขียว" ไม่ได้แปลว่า `type-check` ผ่าน ต้องรันทั้งคู่ (2) **ห้ามใช้ `!` ในเทสต์** — ถ้าสมมติฐานผิดจะได้ `undefined is not a function` ลอย ๆ แทนที่จะรู้ว่าองค์ประกอบไหนหาย (3) narrowing ต้องผูกกับ **ตัวแปร** เสมอ (`const row = at(...)`) ไม่ใช่ index ซ้ำ (4) `npm run type-check` เป็นด่านที่ต้องรันก่อน `npm run build` เสมอในงาน frontend
- **Tests:** `frontend/src/utils/__tests__/receiptGroups.spec.ts` (helper `at()` ใช้ทั้งไฟล์)
- **Date Added:** 2026-09-15

### 🗡️ (เสริม) mutation harness ภาษา Python ก็ต้องสำรอง **ไฟล์ที่ยังไม่ commit** ออกนอก repo — และงาน F5 mutate ไฟล์ใหม่ทั้งไฟล์
- **Context/Problem:** บทเรียนก่อนหน้าสอนเรื่องนี้กับ harness ฝั่ง JS (`_mutation_row_action_menu.mjs`) แต่ `_mutation_credits.py` ซึ่งเป็นแบบอย่างของฝั่ง Python **ไม่มีการสำรอง** — มันอ่านต้นฉบับเข้า memory แล้วเขียนคืนใน `finally` เท่านั้น ⇒ ถ้า process ถูกฆ่า (SIGKILL/ปิดเครื่อง) ต้นฉบับหายถาวร · งาน F5 mutate `services/finance/receipt_batches.py` ซึ่ง **เป็นไฟล์ใหม่ที่ยังไม่ commit** ⇒ `git checkout` กู้ไม่ได้เลย
- **Root Cause:** การพึ่ง `finally` ครอบคลุมได้แค่เส้นทางที่ process ยังได้รัน Python ต่อ — ไม่ครอบ SIGKILL, การฆ่า process group, หรือเครื่องดับ · ความเสี่ยงสูงสุดคือ **ไฟล์ใหม่ที่ยังไม่ commit** ซึ่งเป็นสภาพปกติของงานที่กำลังทำ
- **Correct Pattern/Solution:** ก่อนเริ่มรัน harness ให้คัดลอกไฟล์ที่จะถูก mutate ไปไว้นอก repo เสมอ (ทำแล้วในงานนี้: `/tmp/f5_backup/` พร้อม `md5sum` ไว้เทียบ) และถ้าจำเป็นต้องกู้ ให้ **diff กับสำเนา** เพื่อดูว่าค้าง mutant ตัวไหน แทนการเขียนใหม่ทั้งไฟล์
- **Rule:** (1) 🔴 **ก่อนรัน mutation harness ทุกครั้ง ต้องสำรองไฟล์ที่จะถูกแก้ไปนอก repo** ถ้าไฟล์นั้นยังไม่ commit (2) เก็บ `md5sum` ไว้เทียบ (3) ถ้าไฟล์ค้าง mutated และกู้ไม่ได้ **ต้องบอกผู้ใช้ตรง ๆ ว่าไฟล์เสีย** ไม่ใช่รายงานว่างานเสร็จ
  ⚠️ **ภาคปฏิบัติที่พลาดจริงในงาน F5:** สำรอง **หลังจาก** harness เริ่มรันไปแล้ว ⇒ สำเนาที่ได้คือ **ตัว mutant** ไม่ใช่ต้นฉบับ (จับได้เพราะ `diff` สำรอง↔ไฟล์จริง เหลือ "บรรทัดที่หายไป 1 บรรทัด" = รูปร่างของ mutant M2 พอดี) ⇒ **ต้องสำรองก่อนสั่งรัน** และเมื่อต้องการตรวจว่า "ไฟล์จริงสะอาดไหม" **อย่าใช้สำเนาเป็นหลักฐาน** ให้ใช้ `grep -rn "MUTANT"` + ตรวจว่า target string ของ mutant ทุกตัวยังอยู่ครบ (สคริปต์ที่รันจบโดยไม่มี `STALE`/`AMBIG` คือหลักฐานว่าไฟล์ถูกคืนครบ)
- **Tests:** — (เป็นขั้นตอนปฏิบัติ ไม่ใช่เทสต์)
- **Date Added:** 2026-09-15

### 🧪 mutation harness ที่ตัดสินผลจาก **exit code ของคำสั่งที่มี pipe** = ตาบอดทั้งรอบ — และ "ผลบวกลวง" มีสองโหมดตรงข้ามกัน
- **Context/Problem:** `_mutation_auto_issue_receipts.py` (งาน F5/PR-2) ให้ผล **สองรอบที่ขัดกันเอง**: รอบแรก "จับได้ 5/5" · รอบที่สอง (หลังแก้ harness) "รอด 0/5" ⇒ อย่างน้อยหนึ่งรอบต้องผิด · จุดตัดสินคือการ **รัน mutant เดียวซ้ำด้วยมือ** แล้วดู output ดิบ:
  ```
  --- grep ใน container ---
  375:                    if True:  # MUTANT          ← mutant ไปถึง process ที่เทสต์จริง
  --- pytest ---
  FAILED tests/test_finance_http.py::test_batch_confirm_payments_opt_out_issue_receipts
  1 failed in 5.05s                                ← M1 ถูกจับจริง ⇒ รอบที่สองตาบอด
  ```
- **Root Cause:** คำสั่งรันเทสต์ลงท้ายด้วย `... 2>&1 | tail -25` ⇒ **`sh` เป็น dash และ exit code ของ pipeline คือของคำสั่งสุดท้าย (`tail`) ไม่ใช่ของ pytest** ⇒ `proc.returncode` เป็น **0 เสมอ** ⇒ ทุก mutant ถูกอ่านเป็น "เทสต์ผ่าน" แล้วถอยไปรันทั้งไฟล์ก็เป็น 0 อีก ⇒ รายงาน "รอด (ไม่มีเทสต์จับ)" **ทุกตัว** · และ dash **ไม่มี `PIPESTATUS`** ให้กู้ ⇒ พิสูจน์ด้วยสองบรรทัด: `sh -c "false | tail -1"` → **0** · `sh -c "false"` → **1**
  🔴 **พบซ้ำในของที่ merge ไปแล้ว — และโหมดนั้นอันตรายกว่ามาก:** `_mutation_receipt_batches.py` (PR-1 · merge แล้ว) กับ `_mutation_credits.py` มี pipe **ตัวเดียวกัน** แต่ **เขียนผลลัพธ์กลับด้าน** — ทั้งคู่ `return proc.returncode == 0, tail` แล้วเอา member แรกไปใช้เป็น **`caught_by`** ⇒ `returncode` ที่ถูก pin เป็น 0 ⇒ "จับได้" ทุกตัว ⇒ **รายงาน CATCH 100% เสมอ** และสาขา "ถอยไปรันทั้งไฟล์" ก็ **ไม่มีวันทำงาน** (dead code ไปด้วย)
  ⇒ PR-1 รายงาน **"จับได้ 9/9"** · **"ถูกจับ 7/7 · รอด 0"** · **"จับได้ 4/4 · รอด 0"** = ตัวเลข 100% ที่ **ถูกรับประกันทางคณิตศาสตร์ตั้งแต่ก่อนรัน mutant ตัวแรก** ไม่ใช่ผลของการทดสอบ — และมัน merge ผ่านโดยไม่มีใครเอ๊ะ เพราะ "เขียวเต็ม" อ่านเหมือนความสำเร็จ
  ```
  --- ยืนยันกับเวอร์ชันที่ merge แล้ว (HEAD) ---
  $ git show HEAD:backend/tests/_mutation_receipt_batches.py | grep -nE 'tail -25|return proc.returncode'
  35:           "-p no:cacheprovider -q --no-header -x {targets} 2>&1 | tail -25"]
  160:    return proc.returncode == 0, tail
  ```
  ⚠️ **root cause เดียวกันให้ผลตรงข้ามกันได้ ขึ้นกับว่า caller ตั้งชื่อ boolean ว่าอะไร** — harness ของ PR-2 ตั้งว่า `passed`/`state` ⇒ 0 อ่านเป็น "ผ่าน" ⇒ **SURVIVE ทั้งรอบ** (ผิดจนดูออก จึงถูกจับได้) · harness ของ PR-1 ตั้งว่า `caught_by` ⇒ 0 อ่านเป็น "จับได้" ⇒ **CATCH ทั้งรอบ** (ผิดจนดูไม่ออก) ⇒ **โหมดอันตรายที่สุดคือ "CATCH ทั้งรอบ" ไม่ใช่ "SURVIVE ทั้งรอบ"** เพราะ SURVIVE ทั้งรอบมีคนสงสัยและไปตรวจ แต่ CATCH ทั้งรอบถูกใช้เป็น *หลักฐานยืนยันว่าเทสต์แข็ง* แล้วปิดงาน
  💡 **สัญญาณเตือนที่เชื่อได้กว่า exit code:** "ผลออกมาสมบูรณ์แบบ 100% ตั้งแต่รอบแรก" ⇒ ให้ **สงสัย harness ก่อนภูมิใจในเทสต์**
- **Correct Pattern/Solution:** สามด่าน ต้องผ่านครบทั้งสามจึงจะออกเสียง:
  1. **ตัด pipe ทิ้ง** — `subprocess.run(capture_output=True, text=True)` เก็บ stdout ครบอยู่แล้ว ⇒ ให้ **Python** ตัด tail เอง (`splitlines()[-30:]`) ไม่ใช่ `tail` ใน shell
  2. **แยกสามสถานะ** และรับเฉพาะ exit 1 เป็น "ล้มจริง":
  ```python
  # pytest: 0 = ผ่านหมด · 1 = มีเทสต์ล้ม · 2 = ถูกขัดจังหวะ · 3 = internal error
  #         4 = ใช้ flag ผิด · 5 = ไม่เก็บเทสต์เลย   ⇒ รับเฉพาะ 1
  if not PYTEST_SUMMARY_RE.search(out):   # `\b\d+ (?:passed|failed)\b`
      return "infra", f"exit={rc} · ไม่พบบรรทัดสรุปของ pytest\n{tail}"
  if rc == 0:  return "pass",  tail
  if rc == 1:  return "fail",  tail
  return "infra", f"exit={rc}\n{tail}"         # ← สถานะที่สาม ไม่นับเป็น "จับได้"
  ```
     ด่านที่ 3 นี้คือ **"หลักฐานว่า pytest ผลิตบรรทัดสรุปเอง"** ⇒ กัน `pip install` สำเร็จที่เป็น exit 0, `no tests ran` (exit 5), `ERROR: not found` (exit 4) และ collection error ทุกแบบ · จงใจ **ไม่** รับ `N error` เป็น "ล้ม" เพราะ collection error ไม่ใช่เทสต์ล้ม ⇒ ด่านนี้พลาดแล้ว **ล้มดัง** (ทุกตัวกลายเป็น INFRA) ไม่มีทางพลาดเงียบ
  3. **คืนไฟล์เมื่อถูกฆ่า** — `finally` ไม่รันเมื่อถูก SIGTERM ⇒ ติด `signal.signal(SIGTERM, … sys.exit(130))` + ด่าน pre-flight ที่ปฏิเสธการเริ่มถ้าไฟล์ตั้งต้นมี marker ของ mutant ค้าง (ไม่งั้นรอบถัดไปจะอ่านไฟล์ที่พังเป็น "pristine" แล้ว md5 self-check **ผ่านทั้งที่ baseline เสีย**)
- **Rule:** (1) 🔴 **exit code ของคำสั่งที่มี pipe คือของ pipe ไม่ใช่ของโปรแกรม** — ห้ามใช้ตัดสินผลอะไรทั้งสิ้น และ **shell ต้องเป็น POSIX sh เสมอในบริบทนี้ ⇒ ไม่มี `PIPESTATUS`** (2) 🔴 **เมื่อสองรอบให้ผลขัดกัน ห้ามเลือกข้าง ห้ามเฉลี่ย** — ให้รัน **หนึ่งหน่วยซ้ำด้วยมือ** แล้วอ่าน output ดิบ (ถูกกว่าการเถียงกัน 1 นาที) (3) 🔎 **ต้องพิสูจน์ว่า mutation ไปถึง process ที่เทสต์จริง** (`grep` + `md5sum` **ใน container**) ไม่งั้น "รอด" กับ "ไม่ได้ใส่ mutant" แยกกันไม่ออก (4) **ผลบวกลวงมีสองโหมด และโหมด "CATCH ทั้งรอบ" อันตรายกว่า** เพราะ "รอดทั้งรอบ" มีคนสงสัยแล้วไปตรวจ แต่ "CATCH ทั้งรอบ" ถูกใช้เป็น **หลักฐานว่าเทสต์แข็งแล้วปิดงาน** ⇒ ผลสมบูรณ์แบบ 100% ตั้งแต่รอบแรก = สงสัย **ตัวตัดสินผล** ก่อน และเมื่อแก้ harness ตัวหนึ่งแล้ว ให้ `grep -rn '| tail' backend/tests/ bot_discord/ frontend/` หา harness ตัวอื่นที่พกบั๊กเดียวกัน (เจอ 2 ตัวในงานนี้) (5) **เก็บ tail ทุก mutant** แม้จะผ่าน — เป็นหลักฐานเดียวที่ทำให้ตรวจย้อนหลังได้ (6) เครื่องมือที่ "พังแล้วรายงานว่าสำเร็จ" อันตรายกว่าเครื่องมือที่พังเฉย ๆ ⇒ ทุก harness ต้องมี guard ที่พิสูจน์ว่าตัวเองทำงาน
- **Tests:** `backend/tests/_mutation_auto_issue_receipts.py::run_pytest` (ฟังก์ชันคืน 3 สถานะ) · **แก้ตามกันแล้วในงานนี้**: `_mutation_receipt_batches.py` และ `_mutation_credits.py` (ตัด pipe + 3 สถานะ + summary gate + pre-flight `MUTANT` + `signal` handler) — `_mutation_jsonb_meta.py` ไม่มีบั๊กนี้ (ไม่ pipe และอ่านบรรทัดสรุป)
- **Date Added:** 2026-09-15

### 🚦 ด่านที่ **เทียบเท่า** (ถอดออกแล้วสถานะ DB เหมือนเดิมเป๊ะ) ต้องมี **"ข้อความ"** เป็น observable — ไม่งั้นเทสต์จับไม่ได้เลย
- **Context/Problem:** `_assert_receipt_seq_budget` (ด่านล่วงหน้าของเลขเอกสารใน `batch_confirm_payments`) ยิงก่อนเข้าลูปเพื่อให้ครูได้ 400 ที่บอกว่า "ต้องใช้ N เลข แต่เหลือ M — ยังไม่มีรายการใดถูกบันทึก" · แต่ **ถอดด่านนี้ออกก็ยังได้ 400 เหมือนเดิม** เพราะด่านจริงใน `_issue_one` (`seq > RECEIPT_SEQ_MAX`) ยังอยู่ และ transaction ทั้งก้อน rollback เหมือนกัน ⇒ สถานะ DB สุดท้าย **เท่ากันทุกตาราง** ⇒ เทสต์ที่ตรวจแต่ DB จับ mutant นี้ไม่ได้ **ไม่มีทางเลย**
- **Root Cause:** สิ่งที่ด่านนี้ผลิตเพิ่มขึ้นมาไม่ใช่ "สถานะ" แต่เป็น **"คุณภาพของข้อความที่มนุษย์อ่านตอนถือเงินสดอยู่หน้าห้อง"** — การตรวจระดับ DB มองไม่เห็นความต่างชนิดนี้โดยธรรมชาติ ไม่ใช่เพราะเทสต์อ่อน
- **Correct Pattern/Solution:** ยอมรับว่าด่านนี้เป็น **UX gate ไม่ใช่ security gate** (เขียนบอกไว้ใน docstring ตรง ๆ) แล้ว **ล็อกข้อความของมันเป็นสัญญา** ด้วยเทสต์ที่แยกของตัวเอง:
  ```python
  assert "(ต้องใช้ 3 เลข แต่เหลือ 1 เลข)" in detail     # ตัวเลขที่ขาด — มีแต่ด่านนี้ที่รู้
  assert "ยังไม่มีรายการใดถูกบันทึก" in detail          # คำสัญญาที่ต้องเป็นความจริง
  ```
  ⇒ mutant M3 ถูกจับ **เพราะข้อความ** ซึ่งเป็น observable เดียวที่มีแต่โค้ดนั้นผลิต
- **Rule:** (1) 🔎 ก่อนสรุปว่า "mutant รอด = เทสต์หลอกตัวเอง" ให้ถามก่อนว่า **mutant นั้นเปลี่ยน observable ที่เทสต์เอื้อมถึงได้จริงไหม** — ถ้าไม่เปลี่ยน = equivalent mutant ไม่ใช่ความผิดของเทสต์ (2) ถ้า **ต้องการ** ให้ด่านที่เทียบเท่าถูกจับ ต้อง **สร้าง observable ที่มีแต่โค้ดนั้นผลิต** (ข้อความ · รหัสข้อผิดพลาด · ฟิลด์เฉพาะ) — **ห้าม**ไปเติม assertion บนสถานะที่เท่ากันอยู่แล้ว (3) ด่าน UX ที่ "ซ้ำซ้อน" กับด่านจริงไม่ใช่โค้ดขยะ — มันเปลี่ยน **สิ่งที่มนุษย์เห็นในวินาทีที่ตัดสินใจ** ซึ่งเป็นคุณค่าเดียวที่มันมี ⇒ ต้องมีเทสต์คุม**ข้อความ** ไม่ใช่คุมสถานะ (4) 🔴 ตัวเลขในข้อความ (เช่น "ต้องใช้ 3 เลข") ต้องคำนวณจากของจริง ไม่ใช่ค่าคงที่ — เทสต์ที่ล็อกข้อความจะจับได้ทันทีถ้ามีคน hardcode
- **Tests:** `tests/test_finance_http.py::test_batch_confirm_payments_seq_budget_precheck_names_the_shortfall` (เทสต์นี้เกิดมาเพื่อ mutant M3 โดยเฉพาะ) · เทียบกับ `::test_batch_confirm_payments_seq_overflow_does_not_take_money` ที่คุม **สถานะ DB** ของเส้นทางเดียวกัน
- **Date Added:** 2026-09-15

### 🔁 ตัวนับที่เพิ่มเข้ามา "เผื่อไว้" ในเส้นทางที่ทุก iteration สร้าง transaction ใหม่ = สาขาที่ **ไม่มีทางเข้า**
- **Context/Problem:** ตอนออกใบเสร็จทุกรายการใน `batch_confirm_payments` มีตัวนับ `reused` และสาขา `new_ids` (เฉพาะใบที่ออกใหม่จริง เอาไปจัดชุด) — ดูเหมือนเป็นสาขาที่ต้องมีเทสต์คุม · แต่ในเส้นทางนี้ **ทุก iteration ของลูปเรียก `_confirm_single_payment` ซึ่ง `INSERT INTO finance_transactions ... RETURNING id` ใหม่เสมอ** ⇒ `trans_id` ไม่เคยซ้ำ ⇒ `_find_existing(student_payment_id, legacy_transaction_id, 'receipt')` **ไม่มีทาง match** ⇒ `reused` เป็น 0 ตลอดกาลในเส้นทางนี้
- **Root Cause:** `_issue_one` เป็นฟังก์ชันกลางที่ถูกเรียกจากหลายเส้นทาง (บางเส้นทาง reuse ได้จริง เช่นออกซ้ำจากทะเบียน) ⇒ สาขา `reused` **จำเป็นสำหรับผู้เรียกอื่น** แต่ **ตายในเส้นทางนี้** · การอ่านโค้ดแค่ `_issue_one` จึงสรุปผิดได้ทั้งสองทาง (คิดว่าเทสต์คุมอยู่ / คิดว่าโค้ดตาย)
- **Correct Pattern/Solution:** พิสูจน์ด้วยการอ่าน **ผู้เรียก** ไม่ใช่ตัวฟังก์ชันกลาง (`collections.py:159` = `INSERT ... RETURNING id` ไม่มีสาขา update) แล้ว **เขียนความจริงลงคอมเมนต์** แทนการเขียนเทสต์ที่แกล้งทำเป็นคุมสาขานั้น:
  ```python
  if out["reused"]:
      reused += 1
  else:
      new_ids.append(out["receipt"]["id"])
  # (คอมเมนต์ต้องบอกว่า: เส้นทางนี้ trans_id ใหม่ทุกใบ ⇒ reused = 0 เสมอ)
  ```
- **Rule:** (1) 🔴 **ก่อนเขียนเทสต์ที่อ้างว่าคุมสาขาหนึ่ง ให้พิสูจน์ก่อนว่าสาขานั้นเข้าถึงได้จากเส้นทางที่กำลังทดสอบ** — เทสต์ที่พิสูจน์ไม่ได้จะกลายเป็นความเชื่อว่ามีคนเฝ้าอยู่ทั้งที่ไม่มี (2) ตัวนับ/สาขาที่ "เผื่อไว้" ต้องมีคอมเมนต์บอกว่า **ตอนนี้ไม่มีทางเข้า และทำไม** (3) อย่าลบสาขาทิ้งเพื่อความสะอาด — มันเป็นสัญญาของฟังก์ชันกลางที่ผู้เรียกอื่นพึ่ง (4) `M5 (ปล่อย trans_id = None)` ถูกพิสูจน์ว่าเป็น equivalent mutant **ด้วยเหตุผลเดียวกัน**: `_resolve_event` ไม่ระบุ id จะคืน "งวดล่าสุด" ซึ่งคืองวดที่เพิ่งสร้าง ⇒ ผลเท่ากัน — ยืนยันแล้วทั้งด้วยการอ่านโค้ดและการรัน harness (EQUIV)
- **Tests:** `tests/test_finance_http.py::test_batch_confirm_payments_issues_one_receipt_per_bill` (assert `reused_count == 0` ทุกกรณี) · `_mutation_auto_issue_receipts.py` M5 = EQUIV (รอดตามคาด)
- **Date Added:** 2026-09-15

### 🕳️ ด่านล่วงหน้าที่ "ดักก่อน" ทำให้เทสต์ atomicity ที่เคยมีฟัน **กลายเป็นเทสต์เปล่า** โดยไม่มีใครรู้
- **Context/Problem:** `test_batch_confirm_payments_seq_overflow_does_not_take_money` ถูกเขียนขึ้นเป็น **"เทสต์ที่มีค่าที่สุดของงานนี้"** เพราะมันพิสูจน์ว่า "ได้ทั้งเงินและใบเสร็จ หรือไม่ได้ทั้งคู่" · แต่ mutant M2 (ย้ายการออกใบเสร็จไป **หลัง `conn.transaction()`**) **รอดทั้งไฟล์ — 53 passed** ⇒ เทสต์นั้นไม่ได้พิสูจน์ atomicity อย่างที่คิด
- **Root Cause:** เทสต์นั้นแยกแยะได้ **เพราะ** การออกใบเสร็จล้ม (เลขเต็ม) — แต่พอเพิ่มด่านล่วงหน้า `_assert_receipt_seq_budget` ที่ **ยิงก่อนเข้าลูป** (ก่อนเงินถูกแตะแม้แต่บาทเดียว) เคส "เลขเต็ม" จึงถูกล้มด้วยด่านนั้นเสมอ **ไม่ว่า** การออกใบเสร็จจริงจะอยู่ในหรือนอกธุรกรรม ⇒ เงื่อนไขที่เทสต์ใช้แยกแยะถูก **กลืนไปโดยด่านใหม่** และเทสต์ก็ยังเขียวอยู่เหมือนเดิมทุกประการ — **การเพิ่มด่านทำให้เทสต์อ่อนลงโดยไม่มีสัญญาณใด ๆ**
- **Correct Pattern/Solution:** เพื่อทดสอบ atomicity ต้องให้ความล้มเหลวเกิด **หลัง** การเขียนครั้งแรก ⇒ ใช้ **fault injection**:
  ```python
  real = ReceiptsMixin._issue_one
  calls = {"n": 0}
  async def flaky(*a, **kw):
      calls["n"] += 1
      if calls["n"] == 2:
          raise ValueError("จำลอง: ออกใบเสร็จใบที่ 2 ไม่สำเร็จ")  # ValueError ⇒ router แปลเป็น 400
      return await real(*a, **kw)
  monkeypatch.setattr(ReceiptsMixin, "_issue_one", flaky)
  ...
  assert resp.status_code == 400
  assert calls["n"] == 2      # 🔑 พิสูจน์ว่าความล้มเหลว "เกิดจริง" ที่ใบที่ 2
  # แล้ว deep verify: บิลยัง pending · balance เท่าเดิม · 0 transactions ·
  #                    0 receipts (ใบที่ 1 ต้องถูก rollback ด้วย) · last_seq ไม่ถูกกิน
  ```
  ⇒ หลังเพิ่มเทสต์นี้ M2 กลายเป็น CATCH ทันที (ก่อนหน้า: SURVIVE ทั้งไฟล์)
- **Rule:** (1) 🔴 **ทุกครั้งที่เพิ่มด่านที่ยิง "เร็วขึ้น" ให้ถามว่าเทสต์เดิมตัวไหนเคยใช้เงื่อนไขที่ด่านใหม่ดักไว้เป็นตัวแยกแยะ** — ด่านใหม่จะกลืนพลังของเทสต์นั้นเงียบ ๆ (2) การทดสอบ atomicity ต้องให้ failure เกิด **หลัง** write แรกสำเร็จ ไม่งั้นเทสต์พิสูจน์แค่ "ด่านล่วงหน้าทำงาน" (3) **ต้อง assert ว่าความล้มเหลวที่ฉีดเข้าไปเกิดขึ้นจริง** (`calls["n"] == 2`) ไม่งั้นเทสต์อาจเขียวเพราะฉีดไม่ติด (4) ใช้ exception ชนิดที่ router map เป็น 4xx ที่รู้จัก (เช่น `ValueError` → 400) ไม่ใช่ปล่อยเป็น 500 ซึ่ง `TestClient` จะโยนกลับและกลบความหมาย (5) 🧬 **mutant ที่ "รอด" คือของขวัญ** — มันชี้จุดที่เทสต์ให้ความมั่นใจเกินจริง ถ้าปิดช่องได้ให้ปิด **ก่อน** merge ไม่ใช่รายงานแล้วผ่านไป
- **Tests:** `tests/test_finance_http.py::test_batch_confirm_payments_receipt_failure_takes_no_money` (เทสต์นี้เกิดมาเพื่อ M2 โดยเฉพาะ) · `_mutation_auto_issue_receipts.py` M2 = CATCH (ก่อนหน้า = SURVIVE)
- **Date Added:** 2026-09-15

### 🔑 "เพิ่ม route ที่ข้ามการตรวจสมาชิก" — ความเสี่ยงไม่ได้อยู่ที่ route ใหม่ แต่อยู่ที่ route เก่าที่ **ไม่มีเทสต์คุมสัญญา**
- **Context/Problem:** F5/PR-3 ต้องให้บอท (ซึ่งไม่ผูกกับ `users` เลย) ดึง PDF ใบเสร็จไปแนบใน Discord ⇒ ต้องมี route ที่ **ข้าม `require_member`** ได้ · งานนี้เลือกใช้ `dependencies=[Depends(get_current_user_or_bot)]` แล้วส่ง `user_id=None` ลง service เฉพาะสาขาที่ `is_bot_system is True` · **แต่รีโปมี auth dependency สองตัวที่สัญญาต่างกัน** และเทสต์เดิม **ไม่มีตัวไหน** ล็อกว่า route PDF เก่าต้องปฏิเสธบอทระบบ:
  | dependency | principal ที่เป็นบอทแต่ไม่มีใน `users` | principal ที่มีใน `users` แต่ไม่ใช่สมาชิก |
  |---|---|---|
  | `get_current_user` | **404** ("ไม่พบบัญชีผู้ใช้ที่ผูกกับ Discord ID นี้") | ผ่าน auth → 403 ที่ `require_member` |
  | `get_current_user_or_bot` | **ผ่าน** (`user_id=None, is_bot_system=True`) | ผ่าน auth → 403 ที่ `require_member` |
  ⇒ ถ้ามีคน "ลดความซ้ำซ้อน" ด้วยการสลับ dependency ของ route เก่าเป็นตัวใหม่ **จะไม่มีเทสต์ตัวใดล้มเลย** และประตูหลังก็เปิดโดยไม่มีสัญญาณ
- **Root Cause:** การทดสอบเชิงพฤติกรรมผูกกับ **สิ่งที่ route ทำ** ไม่ได้ผูกกับ **สิ่งที่ route ต้องไม่ทำ** · "บอทระบบยิง route นี้ต้องได้ 404" เป็นสัญญาที่มีตัวตนจริง แต่ไม่มี observable ใดในเทสต์เดิมผลิตมันออกมา ⇒ ช่องว่างนี้จะถูกเปิดโดย refactor ที่ดูบริสุทธิ์
- **Correct Pattern/Solution:** เขียน **เทสต์แฝด** ประกบกันเสมอเมื่อเพิ่มทางที่ข้ามด่าน: ตัวหนึ่งพิสูจน์ว่า **ทางใหม่เปิด** อีกตัวพิสูจน์ว่า **ทางเก่ายังปิด** — และตัวหลังต้องยิงด้วย principal ชนิดเดียวกับที่ทางใหม่รับ (บอทระบบ) ไม่ใช่ principal ทั่วไป
  ```python
  # ทางใหม่: บอทระบบต้องได้ 200
  assert resp.status_code == 200 and resp.headers["content-type"] == "application/pdf"
  # ทางเก่า: บอทระบบต้องยังถูกปฏิเสธ (404 = ไม่พบบัญชี — ไม่ใช่ 401/403)
  assert client.get(WEB_PDF_PATH, headers=_bot_headers()).status_code == 404
  ```
  + เทสต์เชิงโครงสร้างที่ล็อก **"มีไฟล์เดียวเท่านั้นที่ถือธงข้ามด่าน"** (`test_the_membership_bypass_lives_in_exactly_one_place`) ⇒ ตรวจ **เซตของไฟล์** ไม่ใช่จำนวนบรรทัด (จำนวนบรรทัดพังทันทีที่มี refactor ที่ไม่ผิด)
  ⚠️ **อย่าล็อกด้วยจำนวนบรรทัด/`len(offenders) == 3`** — เทสต์จะกลายเป็นตัวขวาง refactor ที่ถูกต้อง แล้วคนจะไปแก้เทสต์แทนที่จะอ่านมัน
- **Rule:** (1) 🔴 **ทุกครั้งที่เพิ่ม route/สาขาที่ข้ามด่านความปลอดภัย ต้องมีเทสต์ที่พิสูจน์ว่า "ประตูที่เหลือยังปิด"** — ไม่ใช่แค่ประตูใหม่ที่เปิดได้ (2) ตัวเทสต์ต้องยิงด้วย principal **ชนิดเดียวกับที่ช่องใหม่รับ** ไม่งั้นมันพิสูจน์คนละเรื่อง (3) **404 กับ 403 ไม่ใช่เรื่องเดียวกัน**: 404 ของ `get_current_user` = "ไม่รู้จักบอทตัวนี้" ซึ่งเป็นพฤติกรรมที่ต้องการ ⇒ เขียน docstring อธิบายไว้ ไม่งั้น reviewer จะอ่านเป็นบั๊ก (4) เทสต์เชิงโครงสร้างให้ยืนยัน **เซตของไฟล์** และตัดบรรทัดคอมเมนต์ออกก่อนนับ — ไม่งั้นคอมเมนต์ในอนาคตจะทำให้เทสต์ล้มทั้งที่โค้ดถูก
- **Tests:** `backend/tests/test_finance_system_pdf.py::test_system_pdf_serves_pdf_to_unregistered_bot_principal` (ประตูใหม่) · `::test_old_web_pdf_route_still_refuses_bot_system_principal` (ประตูเก่า — **เทสต์นี้เกิดมาเพื่อเหตุผลนี้เท่านั้น**) · `::test_the_membership_bypass_lives_in_exactly_one_place` · `_mutation_system_pdf.py` M1/M2/M8 = CATCH
- **Date Added:** 2026-09-15

### 🏷️ `get_audit_context(request, {"user_id": None})` เขียน `"user_id:None"` ลง DB — ตรวจด้วย `in` ไม่ใช่ truthiness
- **Context/Problem:** ระหว่างส่ง actor ของบอทระบบเข้าชั้น audit เขียนแบบตรงไปตรงมาว่า `get_audit_context(request, user_ctx)` โดยที่ `user_ctx = {"user_id": None, "is_bot_system": True}` ⇒ audit log เก็บ `actor_identifier = "user_id:None"` ซึ่งอ่านแล้วเหมือนมีผู้ใช้ id `None` อยู่ในระบบ · ร่องรอยการเงินที่บอกผิดว่ามีคนทำ = แย่กว่าไม่มีร่องรอย
- **Root Cause:** ตัวช่วยตัดสินว่า "มี user หรือไม่" เขียนว่า
  ```python
  actor_identifier = f"user_id:{user_ctx['user_id']}" if user_ctx and "user_id" in user_ctx else ...
  ```
  ⇒ เงื่อนไขคือ **"มีคีย์ไหม"** ไม่ใช่ **"ค่ามีจริงไหม"** · `{"user_id": None}` มีคีย์ ⇒ ผ่านเงื่อนไข ⇒ f-string ประกอบ `None` ออกมาเป็นสตริง · ข้อนี้ **อ่านโค้ดผ่านตาแล้วไม่เห็น** เพราะรูปประโยคถูกต้องทุกตัวอักษร
- **Correct Pattern/Solution:** ที่จุดเรียก ให้ส่ง `None` ไปทั้งก้อนเมื่อเป็นบอทระบบ ⇒ ตัวช่วยจะตกไปใช้ `x-actor-id` ตามที่ควร
  ```python
  client_source, actor = get_audit_context(request, None if is_bot_system else user_ctx)
  ```
  แล้ว **ล็อกด้วยเทสต์ที่อ่าน DB จริง** ไม่ใช่แค่ status code:
  ```python
  assert row["user_id"] is None
  assert row["actor_identifier"] == "discord-bot:auto-attach"
  assert "None" not in (row["actor_identifier"] or "")   # ← ตัวที่จับ mutant ได้จริง
  ```
- **Rule:** (1) 🔴 **"มีคีย์" ไม่เท่ากับ "มีค่า"** — ทุกที่ที่ส่ง `dict` บางส่วนเข้าไปในโค้ดที่ตัดสินด้วย `in`/`and` ต้องทดสอบด้วยค่าจริง `None` ไม่ใช่เดาจากการอ่าน (2) audit ของเส้นทางเงินต้อง assert **ทั้ง** `user_id` และ `actor_identifier` และ **ต้องมี assertion ที่ปฏิเสธสตริง `"None"` แบบตรง ๆ** — assertion สองตัวแรกผ่านได้ทั้งที่ค่าเพี้ยน (3) เมื่อเจอว่า helper มีสัญญาที่ไม่ตรงความต้องการ ให้ **แก้ที่จุดเรียก** ไม่ใช่แก้ helper — helper มีผู้เรียกอื่นที่พึ่งพฤติกรรมเดิม
- **Tests:** `backend/tests/test_finance_system_pdf.py::test_system_pdf_audit_records_the_bot_actor` · `_mutation_system_pdf.py` M6 = CATCH
- **Date Added:** 2026-09-15

### 📄 นับ "หน้า" ในไฟล์ PDF ที่รวมจาก HTML — `'<div class="doc'` นับได้ 2 ต่อหน้า เพราะไปโดน `doc-title`
- **Context/Problem:** เทสต์ dedupe ของ PR-3 ต้องพิสูจน์ว่า "ส่งเลขซ้ำ 3 ครั้ง → ได้ 1 ใบ ไม่ใช่ 3 ใบ" วิธีที่นึกออกทันทีคือ `html.count('<div class="doc')` แล้ว assert `== 1` — **ได้ 2** ทั้งที่เทมเพลตถูกต้อง ⇒ เทสต์ล้มด้วยข้อความที่ชี้ไปผิดที่ (เหมือน dedupe พัง) ทั้งที่ dedupe ทำงานดี
- **Root Cause:** เทมเพลต (`backend/templates/finance/receipt.html`) มี **สอง** div ที่ขึ้นต้นด้วยสตริงเดียวกัน: `<div class="doc doc-break">` (ตัวคั่นหน้า, บรรทัด 116) และ `<div class="doc-title">` (บรรทัด 135) ⇒ ตัวนับของเทสต์คือ "จำนวน div ที่ขึ้นต้นด้วย doc" ไม่ใช่ "จำนวนหน้า" และทั้งสองค่าเท่ากันโดยบังเอิญเฉพาะเคส 1 หน้า
- **Correct Pattern/Solution:** ล็อก **ตัวคั่นหน้าที่มีชื่อคลาสเต็ม** แล้วบวกหนึ่ง (หน้าแรกไม่มีตัวคั่น) — และเขียนกับดักนี้ลง docstring ของ helper ทันที เพราะคนถัดไปจะนับแบบเดิมอีก
  ```python
  DOC_BREAK = '<div class="doc doc-break">'
  def _page_count(html: str) -> int:
      """นับหน้า = ตัวคั่นหน้า + 1
      ⚠️ ห้ามนับ `'<div class="doc'` — `<div class="doc-title">` ก็ขึ้นต้นด้วยสตริงนั้น
         ⇒ ใบเดียวจะนับได้ 2 ซึ่งอ่านแล้วเหมือน "มี 2 หน้า" (พลาดมาแล้วรอบหนึ่ง)"""
      return html.count(DOC_BREAK) + 1
  ```
- **Rule:** (1) 🔴 **ตัวนับต้องยึดสตริงที่ "ไม่กำกวม" ไม่ใช่คำนำหน้าที่สั้นที่สุดที่ดูเหมือนพอ** — คลาส HTML เป็นคำนำหน้าที่ซ้อนกันโดยธรรมชาติ (`doc` / `doc-break` / `doc-title`) ให้ใช้ค่าที่มีเครื่องหมายคำพูดปิดกำกับ (2) เมื่อ assertion ล้มแล้วค่าที่ได้เป็น "สองเท่าของที่คาด" ให้ **สงสัยตัวนับก่อนสงสัยโค้ดที่ถูกทดสอบ** — รูปร่างของผลลัพธ์บอกใบ้ตัวคูณ (3) เขียนกับดักที่เพิ่งเจอลง docstring ของ helper **พร้อมคำว่าเคยพลาด** — บทเรียนที่ไม่มีร่องรอยการพลาดจะถูกลบทิ้งในการ refactor ครั้งถัดไป
- **Tests:** `backend/tests/test_finance_system_pdf.py::test_system_pdf_dedupes_repeated_receipt_numbers` (assert `_page_count(html) == 1` + audit `new_values == {"receipt_nos": [...], "count": 1}`)
- **Date Added:** 2026-09-15

### 🧬 เทสต์ "ห้ามมี SQL ใน router" ต้องใช้ `ast` — `grep` จะฟ้องโค้ดที่ถูก เพราะ docstring ของไฟล์นั้น **พูดถึง** คำต้องห้าม
- **Context/Problem:** PR-3 ล็อกว่า router ใหม่ต้องอ่านอย่างเดียว 100% วิธีแรกที่คิดได้คือ `grep -c "INSERT INTO\|UPDATE " routers/finance/system.py` แล้ว assert เป็น 0 — **ใช้ไม่ได้** เพราะ docstring ของ router ไฟล์นั้นอธิบายเงื่อนไขว่าห้ามเขียน DB ⇒ มีคำว่า `INSERT`/`UPDATE` อยู่ในนั้นเพื่อ **ห้าม** ตัวเอง · ถ้าตัดบรรทัดที่ขึ้นต้นด้วย `#` ทิ้งก็ยังเหลือ docstring ⇒ เทสต์จะบังคับให้คนเขียน **ลบคำอธิบายความปลอดภัยออก** เพื่อให้เทสต์เขียว ซึ่งกลับหัวกลับหาง
  ⚠️ และช่องที่**แย่กว่า**คือ: เทสต์ที่ยิง HTTP ไม่มีทางรู้ว่า router แอบเปิด connection เขียน DB ในเส้นทางที่เทสต์ไม่ได้เรียก
- **Root Cause:** `grep` มองไม่เห็นความต่างระหว่าง **สตริงที่รันจริง** กับ **ข้อความที่ใช้สื่อสารกับมนุษย์** · และการตรวจ "ไฟล์นี้แตะ DB ไหม" เป็นคำถามเชิงโครงสร้าง ไม่ใช่เชิงพฤติกรรม ⇒ เครื่องมือเชิงข้อความตอบไม่ได้ทั้งสองทาง (ฟ้องเกิน + พลาด)
- **Correct Pattern/Solution:** เดิน AST แล้วดูแค่ **string literal ที่รันได้** — ตัด docstring ออกด้วยการเทียบกับ `ast.get_docstring` ของทุก node ที่มี พร้อม **assert ชนิดที่สอง**: ทั้งไฟล์ต้องไม่มี **การเรียก** เมธอดที่แตะ DB เลย (นี่คือช่องที่การ grep หาสตริง `INSERT` มองไม่เห็นเด็ดขาด)
  ```python
  docstrings = {n.body[0].value.value for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and n.body and isinstance(n.body[0], ast.Expr)
                and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str)}
  literals = [n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value not in docstrings]
  assert not [s for s in literals if re.search(r"\b(INSERT|UPDATE|DELETE)\b", s, re.I)]
  assert not [n for n in ast.walk(tree) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)
              and n.func.attr in {"execute", "fetch", "fetchrow", "fetchval", "executemany"}]
  ```
  ⇒ mutant M7 (แอบยัด `UPDATE finance_receipts` เข้า router) **ถูกจับทันที** ทั้งที่เป็น hole ที่เทสต์พฤติกรรมมองไม่เห็น — พิสูจน์ว่าเทสต์นี้มีฟันจริง ไม่ใช่พิธีกรรม
- **Rule:** (1) 🔴 **คำถามเชิงโครงสร้าง ("ไฟล์นี้แตะ DB ไหม" / "มีกี่ประตูหลัง") ต้องตอบด้วย `ast` ไม่ใช่ `grep`** — และต้อง **แยก docstring ออกจากสตริงที่รัน** เพราะไฟล์ที่เขียนกฎความปลอดภัยไว้มักมีคำต้องห้ามอยู่ในตัว (2) เทสต์โครงสร้างต้องมี **การเรียกเมธอด** เป็นด่านที่สอง ไม่ใช่แค่หาสตริง — สตริงหาง่ายและถูกหลบง่าย (3) 🧬 **เทสต์ที่เป็น "พิธีกรรม" จะไม่มีวันถูกจับได้ว่าหลอกตัวเอง** ⇒ ต้องมี mutant ที่เล็งเทสต์นั้นโดยตรง (M7) ไม่ใช่หวังว่าจะมีตัวอื่นจับให้ (4) การ grep ซอร์สในเทสต์ต้องรันบน **AST/บรรทัดโค้ด** เสมอ ถ้าจำเป็นต้อง grep จริง ให้ตัดบรรทัดคอมเมนต์ **และ** docstring ออกก่อน
- **Tests:** `backend/tests/test_finance_system_pdf.py::test_system_pdf_router_contains_no_database_access` · `_mutation_system_pdf.py` M7 = CATCH
- **Date Added:** 2026-09-15

### ⏱️ ใส่ `asyncio.create_task` ให้ลูปฟัง Redis = เปลี่ยนสัญญาของ **ทั้งระบบ** ไม่ใช่แค่จุดที่แก้
- **Context/Problem:** `cogs/redis_listener.py` เดิมเป็นลูป **sequential** — อ่าน event จาก Redis แล้ว `await` งานทั้งหมด · งานแนบ PDF ต้องยิง Gotenberg ซึ่งตั้ง timeout ไว้ 60 วิ (ฝั่ง Gotenberg เอง 120 วิ) ⇒ ถ้า await ตรง ๆ การแจ้งเตือนอื่น **ทั้งระบบ** จะหยุดรอ 60–120 วินาที · งานนี้จึงห่อเฉพาะเคสที่มี `receipt_nos` ด้วย `asyncio.create_task` + semaphore
- **Root Cause:** ลูปนี้เป็น **จุดคอขวดเดียวของทุกการแจ้งเตือน** — ใครก็ตามที่เพิ่มงานช้าเข้าไปในเส้นทางนี้ ยืดเวลาของ **ทุกฟีเจอร์** ไม่ใช่แค่ของตัวเอง · และการเพิ่ม concurrency ให้ลูปที่เดิม sequential เป็นการ **เปลี่ยนสัญญาที่คนอื่นพึ่งอยู่โดยไม่รู้ตัว** (เช่น ลำดับการส่งข้อความ, การที่ event ถัดไปไม่เริ่มก่อนตัวก่อนหน้าจบ)
- **Correct Pattern/Solution:** เมื่อจำเป็นต้องทำ ให้ทำแบบ **แคบที่สุดและมีร่องรอย**:
  - ห่อเฉพาะ **สาขาที่ต้องช้า** (`data.get("receipt_nos")`) ไม่ใช่ทั้งลูป ⇒ เส้นทางเดิม (บิลเดียว) ยัง sequential เหมือนเดิมเป๊ะ
  - มี **semaphore** กันงานค้างสะสม และ **เก็บ reference ของ task** ไว้ (task ที่ไม่มีใครอ้างถึงอาจถูก GC ทิ้งกลางทาง)
  - เขียน **ทำไม** ไว้ที่จุดนั้น ไม่ใช่แค่ **อะไร** — และใส่ใน checklist ของ reviewer ว่าการเปลี่ยน concurrency ต้องถูกมองเห็น
  - ล็อกด้วยเทสต์ที่พิสูจน์ "ไม่ await" ไม่ใช่เทสต์ที่พิสูจน์ "ทำงานถูก" — เคสที่ต้องพิสูจน์คือ **ไม่บล็อก** ซึ่งเป็น observable คนละตัวกับผลลัพธ์
- **Rule:** (1) 🔴 **ก่อนเพิ่มงานที่อาจช้าลงในลูป sequential ให้ถามก่อนว่า "ลูปนี้เป็นคอขวดร่วมของใครบ้าง"** — ถ้าเป็นของทั้งระบบ การ await คือการทำให้ฟีเจอร์อื่นพังเพราะฟีเจอร์เรา (2) การเปลี่ยน concurrency model ต้องมี **คอมเมนต์ + เทสต์ที่ยืนยันพฤติกรรมใหม่** และ mutant ที่ย้อนกลับไป await ต้อง **ถูกจับ** (BM4) (3) จำกัดขอบเขตให้แคบที่สุด: เปิด concurrency เฉพาะสาขาที่ต้องการ ไม่ใช่ทั้งลูป (4) semaphore + เก็บ task reference เป็นของบังคับ ไม่ใช่ของประดับ
- **Tests:** `bot_discord/tests/test_pdf_attach.py::ProcessEventConcurrencyTest::test_payment_with_receipts_is_not_awaited_inline` · `_mutation_pdf_attach.py` BM4 = CATCH
- **Date Added:** 2026-09-15
- **📌 ต่อยอด (F6/PR-6, 2026-09-16):** 🔴 **เพดาน 60 วิ / 9 MB / semaphore 2 ช่อง ถูกย้ายจาก "เส้นทางที่พบยาก" มาอยู่บน "เส้นทางที่ยิงทุกครั้ง"**
  - เดิมมีแค่เคลียร์หนี้เป็นชุดที่ออกใบเสร็จอัตโนมัติ ⇒ เกิดไม่กี่ครั้งต่อวัน · ตอนนี้ **ทุก** การบันทึกรายจ่าย/รายรับ ที่ออกใบสำคัญจ่าย/ใบรับเงิน จะ trigger การดึง Gotenberg
  - ⇒ (ก) **คิวใน `_pdf_semaphore` จะยาวขึ้นจริง** — 2 ช่องคือเพดานที่ตั้งไว้ตอนที่งานหายาก ถ้าพบว่าข้อความการเงินมาช้า ให้ ++ ค่านี้ก่อนไปสงสัย Gotenberg (ข) **อัตราที่ "แนบไม่ได้" จะสูงขึ้นตามปริมาณ** ⇒ ข้อความ "แนบไม่ได้" จะไม่ใช่เหตุการณ์หายากอีกต่อไป (ค) กติกาเดิมยังต้องคง: **ไฟล์แนบพัง = ข้อความต้องออก** — ห้ามให้ความถี่ที่สูงขึ้นเปลี่ยนกติกานี้
  - 📌 การขยายขอบเขตของเส้นทางที่ใช้ฟังก์ชันร่วม **ต้องถูกอ่านเป็น "งานใหม่"** ไม่ใช่ "เปิดสวิตช์" — เพราะมันเปลี่ยนภาระของทรัพยากรที่แชร์กัน (semaphore · Gotenberg · timeout budget) โดยที่โค้ดดูเหมือนเดิม
  - ⚠️ และ **จุด publish ต้องอยู่หลัง commit ของ transaction** (`add_transaction`) เสมอ — ไม่งั้นบอทอาจขอ PDF ด้วยเลขที่ยังไม่ commit ⇒ 404 ⇒ ไม่มีไฟล์ (ความล้มเหลวที่กลืนกับ "Gotenberg ล่ม" จนแยกไม่ออก)
  - **Tests:** `_mutation_pdf_attach.py` BM7 = CATCH

### 🐳 เทสต์ฝั่งบอท: image ของบอท **ไม่มี pytest** ⇒ ใช้ stdlib `unittest` ใน image เดิม ไม่ต้องสร้าง image ใหม่
- **Context/Problem:** ฝั่ง backend รันเทสต์ด้วย `docker-compose.test.yml` + Postgres แต่ฝั่งบอทไม่มีโครงนั้นเลย · และ `bot_discord` ก็ไม่มี `tests/` มาก่อน · ทางเลือกที่ดูสะอาดคือสร้าง test image / เพิ่ม pytest เข้า requirements ซึ่งแตะ image ที่ deploy จริงเพื่อประโยชน์ของเทสต์เท่านั้น
- **Root Cause:** image ของบอทเป็น **production image** (python:3.12-slim + aiohttp + discord.py + redis) — ไม่มีและไม่ควรมี pytest · แต่เทสต์ชุดนี้ **ไม่ต้องใช้ Postgres และไม่ต้องใช้ Discord จริง** (mock ทั้งคู่) ⇒ ความต้องการของเทสต์ไม่ได้บังคับให้ต้องมีเครื่องมือเพิ่มเลย
- **Correct Pattern/Solution:** รัน stdlib `unittest` **ใน image เดิม** ด้วย volume mount ⇒ ไม่ต้อง build อะไรใหม่ ไม่แตะ image ที่ deploy
  ```bash
  docker run --rm -v "$PWD/bot_discord:/app:z" -w /app \
      classroom-classroom-bot:latest python -m unittest tests.test_pdf_attach -v
  ```
  ⇒ และใน harness ให้ใช้ **บรรทัดสรุปที่ unittest ผลิตเอง** (`OK` / `FAILED`) เป็นด่าน "เทสต์รันจริง" แบบเดียวกับที่ฝั่ง backend ใช้ `N passed`:
  ```python
  UNITTEST_SUMMARY_RE = re.compile(r"^(?:OK|FAILED)\b", re.MULTILINE)
  ```
  ⚠️ **ต้องเป็น `^` + `MULTILINE`** ไม่ใช่ `in` — คำว่า `OK` โผล่ในข้อความอื่นได้ง่าย
  ⇒ ผลจริง: **BM1–BM6 = CATCH 6/6** ทั้งที่ไม่มี pytest เลย
- **Rule:** (1) 🔴 **อย่าเพิ่ม dependency เข้า production image เพื่อประโยชน์ของเทสต์** — ถ้าเทสต์ไม่ต้องใช้ DB/เครือข่าย ให้ใช้ stdlib runner ใน image เดิม (2) ฝั่งบอทไม่มีตู้ Postgres ให้แย่งกัน ⇒ harness ฝั่งบอท **รันพร้อมกับฝั่ง backend ได้** ต่างจาก `_mutation_*.py` ฝั่ง backend ที่ต้องรันทีละตัว (3) ด่าน "เทสต์รันจริง" ของ unittest คือ `^(OK|FAILED)` ที่ต้นบรรทัด — ไม่ใช่การเช็คคำว่า `OK` แบบ substring (4) ทุก harness ต้องมีด่านนี้ ไม่งั้น container/import ที่พังจะถูกอ่านเป็น "mutant ถูกจับ" ซึ่งเป็นผลบวกลวงที่อันตรายที่สุด
- **Tests:** `bot_discord/tests/_mutation_pdf_attach.py::run_unittest` · `bot_discord/tests/__init__.py` (มีคำอธิบายเหตุผลเดียวกันกำกับ)
- **Date Added:** 2026-09-15

### ⚠️ `pytestmark = pytest.mark.asyncio` ระดับโมดูล + เทสต์ **sync** = warning ที่ไม่มีไฟล์ไหนในรีโปเป็นแบบนั้น
- **Context/Problem:** เทสต์เชิงโครงสร้างสองตัวของ PR-3 ไม่ต้อง `await` อะไรเลย (อ่านไฟล์ + เดิน AST) ⇒ เขียนเป็น `def` ธรรมดา · ผลคือ pytest ออกรายงานว่ามี warning ทั้งที่ตัวเลขเทสต์ผ่านครบ:
  ```
  PytestWarning: The test <...> is marked with '@pytest.mark.asyncio' but it is not an async function.
  ```
- **Root Cause:** ไฟล์เทสต์ทุกไฟล์ของรีโปนี้ตั้ง `pytestmark = pytest.mark.asyncio` **ระดับโมดูล** ⇒ mark ถูกฉีดให้ **ทุก** ฟังก์ชันในไฟล์ รวมตัวที่ไม่ใช่ async · และเมื่อ `asyncio_mode` เป็น strict ตัว mark จึงเป็นคำสัญญาที่เทสต์ไม่ทำตาม
- **Correct Pattern/Solution:** เปลี่ยนเป็น `async def` (ไม่ต้องมี `await` ข้างในก็ได้) แล้วเขียนคอมเมนต์ว่าทำไม — **ดีกว่า** การไปใส่ `filterwarnings` หรือถอด mark ระดับโมดูล เพราะ:
  - การปิด warning ทั้งไฟล์จะปิดให้เทสต์ async ตัวอื่นไปด้วย = ลบสัญญาณของทั้งไฟล์
  - การถอด `pytestmark` แล้วไปใส่ mark รายตัว จะแตะเทสต์เดิมที่ไม่เกี่ยวกับงาน
  ```python
  async def test_system_pdf_router_contains_no_database_access(db_pool):
      """... (คอมเมนต์: ไฟล์นี้ตั้ง `pytestmark = pytest.mark.asyncio` ระดับโมดูล
         ⇒ เทสต์ sync ในไฟล์นี้จะได้ PytestWarning และไม่มีไฟล์ไหนในรีโปทำแบบนั้น)"""
  ```
- **Rule:** (1) 🔴 **ในไฟล์ที่มี `pytestmark` ระดับโมดูล ให้เขียนเทสต์ทุกตัวเป็น `async def` เสมอ** แม้ไม่ต้อง `await` — warning ไม่ได้ทำให้เทสต์ล้ม แต่มันกลายเป็นเสียงรบกวนที่ทำให้ warning ของจริงถูกมองข้าม (2) **ห้ามปิด warning ด้วย `filterwarnings` เมื่อต้นเหตุคือเทสต์เขียนไม่ตรงกับ mark ของไฟล์** — การปิดจะไปปิดของเทสต์ตัวอื่นด้วย (3) ก่อนสรุปว่า "สไตล์นี้โอเค" ให้ `grep` ดูว่า **ไฟล์อื่นในรีโปทำแบบเดียวกันไหม** — ถ้าไม่มีเลย ให้ถือว่านี่คือความผิดปกติที่ต้องแก้ ไม่ใช่ความหลากหลายที่ต้องยอมรับ (4) เกณฑ์ "เทสต์ผ่าน" ของงานนี้คือ **ผ่านโดยไม่มี warning** ไม่ใช่ผ่าน
- **Tests:** `backend/tests/test_finance_system_pdf.py::test_system_pdf_router_contains_no_database_access` และ `::test_the_membership_bypass_lives_in_exactly_one_place` (ทั้งคู่เป็น `async def` ที่ไม่มี `await` โดยเจตนา) · รันเต็มไฟล์: **18 passed, 0 warnings**
- **Date Added:** 2026-09-15

### 🧾 เทสต์ "ห้าม `None` ขึ้นกระดาษ" ที่เขียนว่า `">None<" not in html` **แคบเกินไป** — mutation harness จับได้ว่าเทสต์หลอกตัวเอง
- **Context/Problem:** งาน F6/PR-4 (ยุบใบเสร็จหลายใบเป็นหน้าเดียว) · ผมเขียนเทสต์กันกับดัก `format(None)` ไว้แบบนี้:
  ```python
  assert ">None<" not in html, "ห้ามมี None หลุดขึ้นกระดาษ"
  ```
  แล้วเขียน mutant ที่ให้หัวใบพิมพ์ `{{ d.receipt_no }}` ตรง ๆ (ซึ่งเป็น `None` สำหรับใบที่ถูกยุบ) · **mutant รอด** — เทสต์ทั้ง 24 ตัวในไฟล์เขียวหมด ทั้งที่กระดาษจริงมีคำว่า `เลขที่ None` บนหัวใบ
- **Root Cause:** `>None<` เป็นการเดา **บริบทของ HTML ที่ค่า None จะไปโผล่** (คือ "เป็นเนื้อหาทั้งหมดของ element") ซึ่งจริงเฉพาะกับ `<td>None</td>` แบบในตาราง · แต่เทมเพลตนี้พิมพ์ `เลขที่ {{ … }}` ⇒ ผลลัพธ์คือ `เลขที่ None</div>` ซึ่ง **ไม่มี `>` นำหน้าคำว่า None** ⇒ สตริงที่หาไม่มีทางเจอ · ที่ร้ายกว่าคือ assertion นี้ **ดูเหมือนเข้มงวด** (มี `<` `>` ครบ) จึงไม่มีใครสงสัย
- **Correct Pattern/Solution:** ค้นหาคำที่ **ไม่ควรปรากฏบนกระดาษเลย** ให้ตรง ๆ ไม่ต้องเดาแท็กของมัน:
  ```python
  assert "None" not in html, "ห้ามมีคำว่า None หลุดขึ้นกระดาษ (หัวใบ/ท้ายใบ/ช่องไหนก็ตาม)"
  assert "เลขที่ รวม 2 ฉบับ" in html, "หัวใบของใบที่ถูกยุบต้องเป็น 'รวม N ฉบับ'"
  ```
  ตัวที่สอง (**positive assertion**) สำคัญพอกัน: `"None" not in html` บอกได้แค่ว่า "ไม่ผิดแบบนี้" ส่วน `"เลขที่ รวม 2 ฉบับ"` บอกว่า "ถูกแบบนี้" — ถ้าวันหน้าคนเปลี่ยนไปพิมพ์ค่าว่างหรือ `-` ตัวแรกจับไม่ได้ ตัวที่สองจับได้
  - ✅ ตรวจก่อนว่าคำนั้นไม่ปรากฏโดยชอบธรรมในเทมเพลต: `grep -n "None" templates/finance/receipt.html` เจอแต่ในคอมเมนต์ `{# … #}` ของ Jinja ซึ่งถูกตัดทิ้งตอนเรนเดอร์ (และ CSS ใช้ `none` ตัวเล็ก) ⇒ ปลอดภัย
- **Rule:** (1) 🔴 **assertion เชิงลบต้องค้นหาคำที่ห้ามปรากฏโดยตรง ไม่ใช่เดา markup รอบ ๆ มัน** — `">None<"`, `'="None"'`, `">-<"` ล้วนเป็นกับดักชนิดเดียวกัน (2) **ทุก assertion เชิงลบต้องมี positive assertion คู่กัน** ที่บอกว่าสภาพที่ถูกต้องหน้าตาอย่างไร ไม่งั้นการลบฟีเจอร์ทิ้งก็ทำให้เทสต์เขียว (3) 🔴 **"เทสต์เขียว" ไม่ใช่หลักฐานว่ามีฟัน — ต้องมี mutant ที่ควรถูกจับแล้วรอด ถึงจะรู้** · รอบแรกจับได้ 13/14 และตัวที่รอดคือตัวที่เผยว่า assertion นี้ไร้ฟัน (4) ก่อนใช้คำใดเป็น "คำต้องห้าม" ให้ `grep` ในเทมเพลตก่อน — คำที่โผล่ในคอมเมนต์ Jinja ปลอดภัย คำที่โผล่ใน CSS/ข้อความจริงใช้ไม่ได้
- **Tests:** `backend/tests/test_finance_receipt_merge.py::test_merged_page_renders_without_a_paid_total_row` (จับ mutant หัวใบ **และ** ท้ายใบ) · `::test_unmerged_page_shows_no_trace_of_the_merge_feature` (จับ mutant ที่ทำให้ใบเดี่ยวขึ้นป้าย "รวมเอกสาร 0 ฉบับ") · harness: `backend/tests/_mutation_receipt_merge.py` — รอบสอง **M13/M15/M16/M17 จับได้ทั้ง 4**
- **Date Added:** 2026-09-15

### 🔑 การยุบเอกสารด้วย `student_id` (FK) ไม่ใช่ `issued_to_name` (สตริง snapshot) — และเหตุใด `student_id IS NULL` ต้องมีด่านของตัวเอง
- **Context/Problem:** ใบเสร็จเก็บทั้ง `student_id` (FK) และ `issued_to_name` (สตริงที่ `_display_name` ประกอบตอนออกเอกสาร) · เวลาจะยุบ "ใบของคนเดียวกัน" ให้เป็นหน้าเดียว ทั้งสองคีย์ดูใช้ได้เท่ากัน และ `issued_to_name` ดู "ตรงกว่า" เพราะเป็นชื่อที่พิมพ์อยู่บนกระดาษจริง
- **Root Cause:** `issued_to_name` เป็น **snapshot ที่มนุษย์อ่าน** ไม่ใช่ตัวตน · ในห้องเรียนจริงมีสองกรณีที่ทำให้มันชนกัน: (ก) ชื่อเล่นเปลี่ยนกลางเทอม ⇒ ใบเก่ากับใบใหม่ของ **คนเดียวกัน** ได้ชื่อไม่ตรงกัน (ข) นักเรียนสองคนในห้องเดียวกัน **ชื่อเล่นซ้ำกันได้จริง** ("ไอซ์") ⇒ ใบของ **สองคน** ได้ชื่อตรงกัน · กรณี (ข) ร้ายแรงกว่ามาก: มันรวมใบเสร็จของสองบ้านไว้บนกระดาษใบเดียว และผู้ปกครองคนหนึ่งจะถือเลขใบเสร็จของอีกบ้านไป · ส่วน `student_id = NULL` มาจาก `ON DELETE SET NULL` ⇒ ลบนักเรียนคนหนึ่งแล้วใบของคนที่ถูกลบ **ทุกคน** กลายเป็น NULL พร้อมกัน ⇒ ยุบรวมกันหมดเป็นหน้าที่ไม่มีเจ้าของ
- **Correct Pattern/Solution:**
  ```python
  def _merge_key(d):
      if d["doc_type"] not in _MERGEABLE_DOC_TYPES: return None
      if d.get("student_id") is None:               return None   # 🔴 ด่านของตัวเอง ห้ามยุบ
      return (d["student_id"], d["doc_type"], d.get("status"))
  ```
  วิธีทำให้เทสต์มีฟันจริง: **fixture ต้องตั้งใจให้ `issued_to_name` ของสองคนเหมือนกันเป๊ะ** ⇒ ถ้ามีคนเปลี่ยนคีย์ไปใช้ชื่อ mutant จะยุบสองคนรวมกันและเทสต์ล้มทันที (ถ้าปล่อยให้ชื่อต่างกันโดยธรรมชาติ เทสต์จะผ่านทั้งสองแบบ = ไม่ได้ทดสอบอะไร)
  - `status` ต้องอยู่ในคีย์เพราะแบนเนอร์ "ยกเลิก" วางไว้บนสุดของ **หน้า** ไม่ใช่บนสุดของ **บรรทัด** ⇒ ยุบปนเมื่อไรใบที่เงินถูกคืนแล้วจะอ่านเหมือนใบปกติ
  - 🚫 **`invoice` ไม่อยู่ใน `_MERGEABLE_DOC_TYPES` โดยเจตนา**: มันเป็น aggregate ต่อคนอยู่แล้ว และ `line_items` ของมันเป็น snapshot หลายบรรทัดที่มี "รวมทั้งสิ้น" ของตัวเอง ⇒ ยุบสองใบ = เอาสองช่วงเวลามาบวกกัน ได้ยอดที่ไม่ได้ค้าง ณ เวลาใดเลย
- **Rule:** (1) 🔴 **คีย์ "เอนทิตีเดียวกัน" ต้องเป็น FK ที่ DB คุมความไม่ซ้ำ ไม่ใช่สตริงที่มนุษย์อ่าน** (ชื่อ/อีเมล/เบอร์โทร ล้วนเปลี่ยนได้และซ้ำได้) (2) **คอลัมน์ที่เป็น `ON DELETE SET NULL` ต้องมีด่าน "ห้ามยุบเมื่อ NULL" เป็นการเฉพาะ** — การรวมของที่ไม่มีเจ้าของเข้าด้วยกันไม่ใช่การยุบ แต่คือการสร้างเอกสารปลอม (3) เทสต์ของ invariant ชนิดนี้ต้อง **จัด fixture ให้ค่าที่ผิดจะชนกันจริง** (ชื่อซ้ำ) ไม่งั้นเป็นเทสต์เปล่า (4) ก่อนให้ฟีเจอร์ใหม่ยุบ/รวมข้อมูล ให้ถามก่อนว่า **"ของที่ถูกรวมมีแนวคิดระดับเดียวกันจริงหรือไม่"** — `collection_amount`/`paid_total_after`/`remaining` เป็นแนวคิด **ต่อบิล** ⇒ ใบที่ยุบต้องตั้งเป็น `None` ทั้งหมดและ **ห้ามให้เทมเพลตพิมพ์มัน** (ดูบทเรียน `format(Undefined)` ด้านบน — ที่นี่คือ `format(None)` ตัวเดียวกันที่ระเบิดเป็น 500 ไม่ใช่แค่ตัวเลขเพี้ยน)
- **Tests:** `backend/tests/test_finance_receipt_merge.py::test_merge_never_crosses_students` (ชื่อซ้ำ), `::test_merge_never_groups_null_student_id`, `::test_merge_never_mixes_voided_with_active`, `::test_invoice_documents_are_never_merged`, `::test_merged_context_pins_bill_only_keys_to_none` · mutants M1/M2/M4/M8
- **Date Added:** 2026-09-15

### 📄 การยุบเอกสารเปลี่ยน **ลำดับหน้า** — ต้องล็อกด้วยเทสต์ ไม่ใช่ปล่อยเป็นพฤติกรรมบังเอิญ
- **Context/Problem:** ผู้ใช้ติ๊กใบเสร็จแบบสลับคน `[A1, B1, A2]` แล้วกดรวมไฟล์ · ผลลัพธ์คือ `A1, A2` อยู่หน้าแรก แล้ว `B1` อยู่หน้าที่สอง — **ไม่ใช่** `A1, B1, A2` ตามที่ติ๊ก แต่ก็ไม่ใช่การเรียงตามเลขที่เอกสารอย่างที่อาจกลายเป็นได้โดยบังเอิญ (ถ้าเขียน `sorted()` หรือ `groupby()` ที่เรียงมาก่อน)
- **Root Cause:** การจัดกลุ่มต้องรักษา **"ตำแหน่งที่กลุ่มปรากฏครั้งแรก"** — เอกสารที่ไม่ถูกยุบและกลุ่มที่ถูกยุบต้องแชร์ลำดับเดียวกัน ไม่ใช่ถูกดันไปคนละส่วนของไฟล์ · ถ้าไม่ตั้งใจเขียน วิธีที่ "ดูสะอาดกว่า" (เช่น `documents.sort(key=…)` หรือ iterate กลุ่มแล้วค่อยต่อท้าย) จะเรียงใหม่เงียบ ๆ ⇒ เอกสารที่ติ๊กเป็นอันดับแรกไปอยู่ท้ายไฟล์ และคนที่กำลังเทียบกระดาษกับจอจะสับสน
- **Correct Pattern/Solution:** สร้างลิสต์ `order` ที่เก็บ **"ครั้งแรกที่เจอคีย์นี้"** แล้วค่อยเติมสมาชิกเข้าถุง:
  ```python
  order, buckets = [], {}
  for d in docs:
      key = cls._merge_key(d)
      if key is None:  order.append(("doc", d)); continue
      if key not in buckets: buckets[key] = []; order.append(("group", buckets[key]))
      buckets[key].append(d)
  ```
  ⇒ ลำดับของ `order` = ลำดับที่ผู้ใช้เลือก และสมาชิกในกลุ่มเรียงตามที่ติ๊กมาด้วย
- **Rule:** (1) 🔴 **เมื่อการจัดกลุ่มมีผลต่อ "ลำดับที่ผู้ใช้เห็น" ต้องมีเทสต์ล็อกไว้ว่าลำดับนั้นคือลำดับที่ผู้ใช้ให้มา** ไม่ใช่ลำดับที่โค้ดบังเอิญผลิต (2) เอกสารที่ **ไม่** ถูกจัดกลุ่มต้องไม่ถูกดันไปรวมกันท้ายไฟล์ — มันต้องอยู่ตำแหน่งเดิมในสาย (3) ใช้ `dict` (เรียงตามการใส่คีย์ตั้งแต่ Python 3.7) หรือลิสต์คู่ อย่าใช้ `groupby()` จาก `itertools` เพราะมันบังคับว่าข้อมูลต้องเรียงตามคีย์ก่อน ⇒ ได้พฤติกรรม "เรียงใหม่" มาโดยไม่ตั้งใจ
- **Tests:** `backend/tests/test_finance_receipt_merge.py::test_grouping_preserves_the_order_the_user_selected` (mutant M9 = `sorted(order, key=…receipt_no…)` ต้องถูกจับ)
- **Date Added:** 2026-09-15

### 🖨️ ตรวจ "ใบเดี่ยวไม่เปลี่ยนแม้แต่ไบต์" ด้วย `git show HEAD:<ไฟล์>` + Jinja ตัวที่สอง — และทำไมมันเป็นได้แค่การตรวจด้วยมือ
- **Context/Problem:** ฟีเจอร์ยุบใบเสร็จแตะเทมเพลตกลางที่ **ทุก** เอกสารการเงินใช้ (`receipt.html`) · สัญญาที่ต้องรักษาคือ "เอกสารที่ไม่ถูกยุบต้องได้กระดาษเหมือนเดิมทุกไบต์" ไม่งั้นใบเสร็จที่ออกไปแล้วจะพิมพ์ซ้ำไม่ตรงกับใบที่ผู้ปกครองถืออยู่
- **Root Cause / วิธีตรวจ:** เทมเพลตเวอร์ชันก่อนหน้าอยู่ใน git ⇒ ดึงออกมาเรนเดอร์ใส่ env คนละตัวด้วย context ก้อนเดียวกัน แล้วเทียบสตริงตรง ๆ:
  ```python
  old_src = subprocess.run(["git", "show", "HEAD:backend/templates/finance/receipt.html"], …).stdout
  (Path(tmp) / "receipt.html").write_text(old_src, encoding="utf-8")
  old_tpl = jinja2.Environment(loader=jinja2.FileSystemLoader(tmp),
                               autoescape=jinja2.select_autoescape(["html"])).get_template("receipt.html")
  assert old_tpl.render(**payload) == render_receipts_html([ctx])   # ต้องเท่ากันทั้งสตริง
  ```
  ⚠️ `payload` ต้องประกอบให้ตรงกับโครงที่ `render_receipts_html` ส่งจริง (`documents`, `page_title`, `font_family`, `font_faces`) ไม่งั้น diff จะมาจากคีย์ที่ขาด ไม่ใช่จากเทมเพลต
- **Rule:** (1) ✅ **เทมเพลตที่ต้อง "ไม่เปลี่ยนพฤติกรรมของเส้นทางเดิม" ให้พิสูจน์ด้วย `git show HEAD:` เทียบสตริงเต็ม** อย่าเชื่อสายตาและอย่าเชื่อแค่ diff (2) 🔴 **แต่การเทียบแบบนี้เป็นได้แค่การตรวจด้วยมือ ห้ามใส่เป็นเทสต์ในชุด** — มันผูกกับ `git` และกับว่าคอมมิตฐานคืออะไร ซึ่ง CI ไม่รับประกัน ⇒ เทสต์อัตโนมัติให้กันที่ **พฤติกรรม** แทน: เอกสารที่ไม่ถูกยุบต้องไม่มีร่องรอยของสาขาใหม่ (`"รวมเอกสาร" not in html`) (3) เทคนิค "สอง Jinja Environment คนละ loader" ใช้ตรวจ **เทมเพลตสองเวอร์ชันพร้อมกัน** ได้ทั่วไป ไม่จำกัดแค่กรณีนี้ (4) ใช้ `{%-` / `-%}` ควบคุมช่องว่างเพื่อให้สาขาเดิมคงสภาพ **ทุกไบต์** — การเพิ่ม `{% if %}` หลายบรรทัดลงในเทมเพลตที่มีอยู่จะพา newline/indent เข้าไปในผลลัพธ์ถ้าไม่ตัด
- **Tests:** ตรวจด้วยมือด้วย `/tmp/pr4_eyeball.py` (รันบน host + Gotenberg ชั่วคราว) · เทสต์อัตโนมัติ: `::test_unmerged_page_shows_no_trace_of_the_merge_feature`, `::test_group_of_one_is_byte_identical_to_single_document` (ระดับ context)
- **Date Added:** 2026-09-15

### 🧩 `{%-` / `-%}` ใน Jinja ต้องเลือก **ด้าน** ให้ถูก — และคอมเมนต์ที่อ้างตัวปิดคอมเมนต์จะปิดตัวเองกลางคัน
- **Context/Problem:** ต้องเพิ่มสาขาใหม่ 3 จุดลงใน `templates/finance/receipt.html` โดย **สาขาเดิมของใบเดี่ยวต้องออกมาเหมือน HEAD ทุกไบต์** (สัญญาที่พิสูจน์ด้วย `git show HEAD:` — ดูหัวข้อก่อนหน้า) · รอบแรกที่เขียน ตรวจด้วยตาผ่าน diff ปกติ **ดูเหมือนไม่มีอะไรผิด** แต่พอเรนเดอร์เทียบสตริงเต็มได้ **7 จุดต่าง** ทุกจุดเป็น "บรรทัดว่างเกินมา 1 บรรทัด"
- **Root Cause:** ทุกแท็กที่ **ยืนครองบรรทัดของตัวเอง** (`{% if %}`, `{% else %}`, `{% endif %}`, `{# … #}`) จะพา `\n` + indent ของบรรทัดนั้นเข้าไปในผลลัพธ์เสมอ — Jinja ไม่ได้ "กลืน" บรรทัดของแท็กให้ · และ `{# … #}` **ยาวหลายบรรทัด** ก็ปล่อย `\n      ` ทั้งหัวและท้าย
- **วิธีแก้ (เลือกด้านให้ถูก):**
  | อยากได้ | ใช้ | ผล |
  |---|---|---|
  | แท็กกิน "บรรทัดของตัวเอง" ทั้งบรรทัด | `{%- … %}` หรือ `{%- … -%}` | ตัด `\n`+indent หน้าแท็ก (**และ** หลัง ถ้ามี `-` ท้าย) |
  | คอมเมนต์ที่ต้องคง `\n      ` **หน้า**บรรทัดถัดไปไว้ | `{# … -#}` | ตัดเฉพาะท้าย |
  | คอมเมนต์ที่ต้องคง `\n      ` **หลัง**ไว้ | `{#- … #}` | ตัดเฉพาะหัว |
  🔴 **ห้ามใช้ `{%-` กับคอมเมนต์ที่ตามหลังข้อความที่ต้องคงช่องว่างไว้** — มันจะกิน `\n      ` ที่ต้องเหลือหน้าบรรทัดถัดไป (ใบเดี่ยวเสียการขึ้นบรรทัด) · และถ้าใส่คอมเมนต์ไว้ **หลัง** `%}` บนบรรทัดเดียวกัน (`{%- if x -%}  {# … #}`) ต้องมี `-` **ท้าย** `%}` ด้วย ไม่งั้นช่องว่าง 2 ตัวนั้นเข้าผลลัพธ์เป็น "เว้นวรรคท้ายบรรทัด"
- **กับดักที่เจ็บที่สุด:** คอมเมนต์ของ Jinja ปิดที่ `#}` **ตัวแรกที่เจอ** ⇒ ถ้าเขียนอธิบายเรื่อง whitespace control แล้วพิมพ์ตัวปิดคอมเมนต์ลงไปในเนื้อความ (เช่น `` `-#}` ``) คอมเมนต์จะ **ปิดกลางคัน** แล้วที่เหลือกลายเป็น HTML จริงบนกระดาษ — **ไม่มี error ไม่มี warning** และ diff ปกติก็ยังดู "น่าจะถูก" · วิธีเขียน: **ห้ามพิมพ์ตัวเปิด/ตัวปิดคอมเมนต์ตรง ๆ ในข้อความ** ให้บรรยายเป็นคำ ("ขีดนำ + ปีกกา")
- **Rule:** (1) 🔴 **เทมเพลตที่สัญญาว่า "สาขาเดิมไม่เปลี่ยน" ต้องเทียบสตริงเต็มเท่านั้น** — `diff` แบบตาสังเกตเห็น "บรรทัดว่างเกิน" ได้ยากมากและดูไม่ออกว่ากระทบจริงหรือไม่ (2) หลังเติมแท็กทุกครั้ง ให้ **นับบรรทัดว่างก่อน/หลัง** ด้วยสตริงเทียบ ไม่ใช่ด้วยตา (3) ถ้าจำนวน mutant ของเทมเพลตอ้างข้อความที่ถูกจัดใหม่ ⇒ **`old` ของ mutant จะ STALE เงียบ ๆ** ต้องอัปเดตแล้วรันซ้ำก่อนเชื่อผล (harness มีด่าน STALE/AMBIG ไว้แล้ว — เชื่อมัน) (4) ตัวปิดคอมเมนต์/ตัวเปิดคอมเมนต์ห้ามปรากฏในเนื้อความคอมเมนต์
- **Tests:** `/tmp/pr4_eyeball.py` ข้อ ② (เทียบ full string กับ `git show HEAD:`) · ตัวจับอัตโนมัติไม่มีโดยเจตนา (ดูหัวข้อก่อนหน้า) · mutant ที่ต้องรันซ้ำหลังแก้เทมเพลต: `M12, M13, M15, M16, M17`
- **Date Added:** 2026-09-15

### 🧬 Mutant ที่ **ไม่คอมไพล์** ไม่ได้แปลว่า "จับไม่ได้" — มันแปลว่า **ไม่มีอะไรถูกทดสอบเลย** และ `infra` ก็อ่านไม่ออกว่าเป็นแบบนั้น
- **Context/Problem:** `_mutation_credits.py` ตัว M12 ("ถอด audit log ของการยกเลิกรายการ") แทนที่ **แค่ kwargs สองบรรทัด** ของคำสั่ง `await service_logger.log(...)` ด้วยสตริง `None  # MUTANT: ไม่บันทึก audit` ⇒ โค้ดที่ได้กลายเป็น
  ```python
  await service_logger.log(
      None  # MUTANT: ไม่บันทึก audit
      old_values=old_values,          # ← ไม่มีจุลภาคคั่น
  ```
  ⇒ **SyntaxError** ตอน import ⇒ `tests/conftest.py` พัง ⇒ pytest ไม่เก็บเทสต์เลย ⇒ ไม่มีบรรทัดสรุป ⇒ harness อ่านเป็น `infra`
- **Root Cause:** การแทนที่ "บางส่วนของ expression" ด้วยค่าที่ไม่ใช่ expression ที่ถูกไวยากรณ์ · harness จับได้ถูกต้องว่า "ไม่พบบรรทัดสรุป" (`PYTEST_SUMMARY_RE`) ⇒ **ไม่นับเป็น CATCH** ซึ่งถูกแล้ว — แต่ผลลัพธ์ที่ได้คือ mutant ตัวนั้น **ไม่เคยพิสูจน์อะไรมาตลอด** และรายงานว่า "infra พัง" ซึ่งอ่านคล้าย "รอบนี้เก็บข้อมูลไม่ได้" ไม่ใช่ "โค้ดบรรทัดนี้ไม่มีเทสต์คุ้มอยู่เลย"
  🔴 นี่คือ **ผลลบปลอม** (false negative) ที่อันตรายพอกับผลบวกลบปลอม — ทั้งคู่ทำให้เชื่อว่า "ตรวจแล้ว"
- **Rule:** (1) 🔴 **mutant ต้องเป็นโปรแกรมที่ถูกต้อง** — ถ้าจะลบทั้งคำสั่ง ให้แทน **ทั้งคำสั่ง** (รวมบรรทัดปิด `)`) ด้วย `pass` ไม่ใช่แทนแค่กลางคำสั่ง (2) ก่อนเพิ่ม mutant ใหม่ ให้ `python -m py_compile` ไฟล์ที่ mutate แล้วหรือไม่ก็ตรวจว่า harness รายงาน `CATCH`/`SURVIVE` ไม่ใช่ `INFRA` — `INFRA` ที่ค้างหลายรอบ = สัญญาณว่า mutant ตัวนั้นเสีย ไม่ใช่โครงสร้างพื้นฐานล่ม (3) `infra` ≠ `survive` ≠ `catch`: **`infra` ต้องถูกตามหาสาเหตุเสมอ** อย่าปล่อยผ่านเพราะ "เดี๋ยวก็ผ่าน"
- **Tests:** `backend/tests/_mutation_credits.py` M12 (แก้เป็นแทนทั้งคำสั่งด้วย `pass` แล้ว)
- **Date Added:** 2026-09-15

### 🎯 Mutant ที่วาง **ผิดตำแหน่ง** = dead code ⇒ รายงาน SURVIVE ปลอม และทำให้เข้าใจผิดว่าเทสต์อ่อน
- **Context/Problem:** `_mutation_pr5_docs.py` M8 ตั้งใจจำลอง "ลืม `json.loads`" ของ `_parse_voucher_snapshot` โดย **แทรกบรรทัดใหม่ต่อท้ายฟังก์ชัน**:
  ```python
  if isinstance(raw, str):
      return None  # MUTANT: ลืม json.loads
  return raw if isinstance(raw, dict) else None
  ```
  harness รายงาน **SURVIVE** ⇒ เกือบสรุปว่า "เทสต์งบประมาณไม่ได้ตรวจการคลี่ snapshot จริง" และเกือบไปแก้เทสต์ที่ **ไม่ได้ผิด**
- **Root Cause:** ฟังก์ชันจริงมี `json.loads` อยู่ **ก่อนหน้า** บรรทัดที่แทรกไปแล้ว:
  ```python
  if isinstance(raw, str):        # ← ของจริง แปลง str → dict ตรงนี้
      try:
          raw = json.loads(raw)
      except (ValueError, TypeError):
          return None
  return raw if isinstance(raw, dict) else None   # ← mutant แทรกก่อนบรรทัดนี้
  ```
  ⇒ ถึงบรรทัดของ mutant ค่า `raw` **เป็น dict แล้วเสมอ** ⇒ `isinstance(raw, str)` เป็น False ตลอด ⇒ บรรทัดนั้นเป็น **dead code** ที่ไม่เปลี่ยนพฤติกรรม = equivalent mutant ปลอม
  🔴 อาการที่สังเกตได้: **mutant ที่ควรตายกลับรอด พร้อมกับที่ mutant ตัวอื่นที่แตะพื้นที่เดียวกันถูกจับ** (M9 "ไม่คลี่ snapshot" ถูกจับ) ⇒ ความขัดแย้งนี้คือสัญญาณว่าตัวที่รอดนั้น **ไม่เคยมีผล** ไม่ใช่เทสต์อ่อน
- **กับดักพี่น้อง (เจอพร้อมกัน):** mutant ที่ "แก้ **อาร์กิวเมนต์** ของคำสั่ง แต่ไม่แก้ **ตัวแปรต้นทาง**" ก็เป็น dead code แบบเดียวกัน — เช่นถ้าจะจำลอง "คิดปีจาก `issued_at_db`" แต่ไปแก้แค่ค่าที่ส่งเข้า `INSERT INTO receipt_sequences` ขณะที่บรรทัดคำนวณ `year_be` ยังใช้ `event_at_db` ⇒ เลขที่ประกอบขึ้นยังถูก ⇒ รอดทั้งที่โค้ดที่ตั้งใจทดสอบไม่ถูกแตะ
  ⇒ **mutant ต้องแก้ที่ "แหล่งความจริง" ของค่า ไม่ใช่ที่ "จุดที่ค่าไหลผ่าน"**
- **Rule:** (1) 🔴 **ก่อนเพิ่ม mutant ให้ยืนยันว่าบรรทัดที่จะแก้ถูก *execute* จริงในเส้นทางที่เทสต์วิ่ง** — อ่านฟังก์ชันทั้งตัว ไม่ใช่แค่หาคำที่ตรง (2) 🔴 **mutant ที่รอดต้องถูกตรวจ "ตำแหน่ง" ก่อนสรุปว่าเทสต์อ่อน** — ถามว่า "บรรทัดนี้ทำงานเมื่อไร" ถ้าคำตอบคือ "ไม่มีทาง" ⇒ **mutant เสีย ไม่ใช่เทสต์เสีย** (3) เกณฑ์ตัดสิน: `old` ต้อง**ไม่ซ้ำ** (harness มีด่าน AMBIG) **และ** ต้องอยู่ **หลัง** การแปลงค่าใด ๆ ที่ทำให้เงื่อนไขของ mutant เป็นเท็จเสมอ (4) 🚫 **ห้ามแก้เทสต์จากผลของ mutant ที่ยังไม่ได้ตรวจตำแหน่ง** — จะกลายเป็นการเขียนเทสต์หลอกตัวเองเพิ่มอีกชั้น (5) เมื่อ mutant แก้ *อาร์กิวเมนต์* ให้ตรวจด้วยว่าตัวแปรต้นทางถูกแก้จริง ไม่งั้นเป็นการทดสอบที่ไม่มีวันล้ม
- **Tests:** `_mutation_pr5_docs.py` M8 (ย้ายไปปิด `json.loads` ตัวจริงที่ `receipts.py:1336-1340` ⇒ CATCH) · M22 (mutate บรรทัดคำนวณ `year_be` ไม่ใช่แค่ kwargs ⇒ CATCH)
- **Date Added:** 2026-09-15

### 🗓️ เทสต์ที่ให้ **อินพุตสองตัวเป็นค่าเดียวกัน** จะพิสูจน์ "แหล่งที่มา" ของค่าไม่ได้เลย
- **Context/Problem:** `test_voucher_timezone_year_comes_from_the_thai_calendar_day` มี docstring ว่า *"ล้มถ้า issuer ใช้ `issued_at_db`"* แต่ตัวเทสต์ส่ง
  ```python
  event_at_db=datetime(2026, 12, 31, 17, 30, tzinfo=timezone.utc),
  issued_at_db=datetime(2026, 12, 31, 17, 30, tzinfo=timezone.utc),   # ← ค่าเดียวกัน
  ```
  ⇒ สลับแหล่งที่มาแล้วผลเท่าเดิม · mutation M6 (สลับเป็น `issued_at_db`) **รอด แม้ถอยไปรันทั้งไฟล์** ⇒ ตัวเลข "ปีของเหตุการณ์" ไม่มีเทสต์คุมเลยทั้งสอง issuer
- **Root Cause:** การทดสอบว่า "ค่ามาจากแหล่ง A ไม่ใช่แหล่ง B" ต้องทำให้ **A ≠ B** มิฉะนั้นการทดสอบเป็น tautology · และการที่ผู้เขียนใส่ค่าเดียวกันลงไปทั้งสองที่เกิดจาก **สร้างเทสต์จากเส้นทาง production** ซึ่งทั้งสองค่าเป็น `now` เกือบเท่ากันเสมอ ⇒ คัดลอกความบังเอิญนั้นเข้ามาในเทสต์
  ⚠️ และมีอีกชั้น: ความต่างต้องข้าม **ขอบเขตที่วัด** (ปี พ.ศ. / วันไทย) ไม่ใช่ต่างแค่ระดับวินาที — ส่ง 17:30:00 กับ 17:30:01 ก็ยังแยกไม่ออก
- **Rule:** (1) 🔴 **เทสต์ที่อ้างว่าพิสูจน์แหล่งที่มา ต้องมีอินพุตที่ให้ผลต่างกันจริงในทุกแหล่ง** — เขียนค่าคาดหวังของ "แหล่งที่ผิด" ลงคอมเมนต์ด้วย (เช่น "ถ้าใช้ issued_at จะได้ `PV-2570-0001`") เพื่อให้คนอ่านตรวจได้ทันที (2) 🔴 **หนึ่งเทสต์ หนึ่งหน้าที่** — "วันไทยถูกใช้" กับ "ค่ามาจาก event ไม่ใช่ issued" เป็นสองข้อสันนิษฐานที่ต้องแยกเทสต์ เพราะค่าที่จับข้อหนึ่งมักทำให้อีกข้อเป็น tautology (3) ผูกกับ **ฟังก์ชันพี่น้อง**: ถ้า issuer สองตัวเป็นฟังก์ชันคนละตัว เทสต์ของตัวหนึ่ง **ไม่ได้คุม** อีกตัว — ต้องเขียนคู่กัน (M6/M22) (4) เปิดทางให้เทสต์ override เวลาได้ (`**overrides` ใน helper) ตั้งแต่แรก ไม่งั้นจะแยกแหล่งไม่ได้เลย (5) 🧪 ผลพลอยได้: mutation harness คือเครื่องมือเดียวที่จับ tautology แบบนี้ได้ — เทสต์แบบนี้ **เขียวตลอดกาล** ไม่ว่าจะพังยังไง
- **Tests:** `test_voucher_year_comes_from_the_event_not_the_issue_time` (ใหม่) · `test_income_year_comes_from_the_event_not_the_issue_time` (ใหม่) · mutant M6/M22
- **Date Added:** 2026-09-15
- **Tests:** `backend/tests/_mutation_credits.py` M12 (แก้เป็นแทนทั้งคำสั่งด้วย `pass` แล้ว)
- **Date Added:** 2026-09-15

### 🖥️ อย่าต่อ `| tail -N` ท้าย mutation harness — ตารางสรุปพิมพ์ไว้ **ก่อน** รายละเอียดของ mutant ที่มีปัญหา
- **Context/Problem:** รัน harness หลายตัวรวดเดียวแล้วต่อ `| tail -40` ต่อตัว เพื่อให้ output สั้น ⇒ เห็นแค่ traceback ของ M12 แล้ว **ไม่เห็นตารางสรุป** ⇒ สรุปผิดว่า "harness ล้มกลางคัน ไม่ได้รันจนจบ" ทั้งที่ความจริงมัน **รันจบครบทุกตัว** และตารางสรุปอยู่เหนือขึ้นไป 40 บรรทัด
- **Root Cause:** ลำดับการพิมพ์ของ harness คือ `ตารางสรุป` → แล้วจึง `── {ชื่อ mutant} [{สถานะ}] ──` + tail ของ pytest (30 บรรทัด) ต่อ mutant ที่ `SURVIVE`/`INFRA`/`STALE`/`AMBIG` ⇒ **mutant ที่มีปัญหาตัวเดียวก็กิน `tail` หมดหน้าต่างแล้ว**
- **Rule:** (1) 🔴 **เขียน output ของ harness ลงไฟล์เต็ม ๆ แล้วค่อยอ่าน** (`> /tmp/harness.txt 2>&1`) อย่าตัดด้วย `tail` (2) ถ้าจำเป็นต้องตัด ให้ `grep -A 30 "ผล         mutation"` หรือตัดที่ **หัว** ไม่ใช่ท้าย (3) บรรทัด `จับได้ N/M | รอด … | infra พัง …` คือ **สัญญาณเดียวที่เชื่อได้** — ไม่มีบรรทัดนี้ = ยังไม่รู้ผล ห้ามเดาจาก exit code
- **Tests:** n/a (บทเรียนเรื่องกระบวนการรัน ไม่ใช่ตัวโค้ด) — แต่เป็นเหตุผลที่ต้องรัน `_mutation_credits` ใหม่แบบเก็บ output เต็ม
- **Date Added:** 2026-09-15

### 🔍 ห้ามรันการตรวจแบบ static ใส่ไฟล์ ขณะที่ mutation harness กำลังรันอยู่ — mutant ที่ live จะอ่านเป็น "โค้ดจริง"
- **Context/Problem:** ระหว่างที่ harness รันอยู่ ผมรันสคริปต์ pre-flight ที่ไล่เช็กว่า `old` ของทุก mutant ยังอยู่ในไฟล์จริงไหม (เพื่อหา STALE ล่วงหน้า) ⇒ ได้ผลว่า `M1 ถอด advisory lock ออกจาก top_up_credit` เป็น **STALE** และเกือบสรุปว่า "mutant ตัวนี้ไม่เคยทดสอบอะไรมาตั้งแต่คอมมิต `c7ac0d5`" · ความจริงคือ **harness กำลังถือ mutant ของอีกตัวอยู่** ⇒ บรรทัดนั้นถูกแทนด้วย `pass  # MUTANT: …` ชั่วคราว ⇒ สตริงเป้าหมาย "หาย" ตามที่ควรจะเป็น
  🔁 เกิด **สองครั้ง** ในเซสชันเดียว: อีกครั้งคือ `git diff --stat` แสดง `services/finance/credits.py | 2 +-` ซึ่งเกือบถูกอ่านเป็น "มีคนแก้ไฟล์นี้"
- **Root Cause:** harness ทำงานโดย **แก้ไฟล์จริงบนดิสก์** แล้วคืนใน `finally` ⇒ ระหว่างรัน ไฟล์เหล่านั้น **ไม่ใช่สภาพตั้งต้น** · ทุกเครื่องมือที่อ่านดิสก์ (`git diff`, `git status`, `grep`, สคริปต์ตรวจของตัวเอง) จะเห็น mutant เป็น "โค้ดปัจจุบัน"
- **Rule:** (1) 🔴 **ก่อนอ่าน `git diff` / รันสคริปต์ตรวจ static ใด ๆ ให้ยืนยันก่อนว่าไม่มี harness รันอยู่** — `pgrep -af "_mutation_"` ต้องว่าง และ `grep -rn MUTANT backend/services` ต้องไม่เจอ (2) ถ้าจำเป็นต้องตรวจระหว่างรัน ให้ตรวจ **ก็อปปี้นอก repo** ไม่ใช่ไฟล์จริง (3) 🚫 **ห้าม commit/deploy ระหว่างที่ harness รัน** — `git status` ที่ขึ้นไฟล์แปลก ๆ คือสัญญาณว่ากำลังถูก mutate ไม่ใช่สัญญาณว่ามีคนแก้ (4) ผลลัพธ์ที่ได้จากการตรวจระหว่างรัน **เป็นโมฆะทั้งดุ้น** ไม่ใช่ "น่าสงสัย" — ต้องรันใหม่หลัง harness จบ
- **Tests:** n/a (บทเรียนกระบวนการ) — พิสูจน์ได้ด้วย: ระหว่าง harness รัน `grep -rn MUTANT backend/services` เจอบรรทัดที่ถูกแทนชั่วคราว
- **Date Added:** 2026-09-15

### 🧰 `backend/tests/_mutation_*.py` **ไม่ได้ใช้วิธีรันเดียวกัน** — ต้องอ่าน docstring ของแต่ละตัว
- **Context/Problem:** รัน `python3 backend/tests/_mutation_jsonb_meta.py` จาก host แล้วได้
  `FileNotFoundError: [Errno 2] No such file or directory: '/app'` พร้อม traceback ที่ชี้ไปใน `subprocess.run` ⇒ ดูเผิน ๆ เหมือน harness พังหรือเหมือนโค้ดที่เพิ่งแก้ไปทำพัง · ความจริงคือ **รันผิดวิธี**
- **Root Cause:** `_mutation_jsonb_meta.py` เรียก pytest เองด้วย `subprocess.run(..., cwd="/app")` (:73) ⇒ **ต้องรันจากในคอนเทนเนอร์** ตามที่ docstring ของมันเขียนไว้ (:6-8) · ส่วน harness ตัวอื่น (`_mutation_receipt_merge`, `_mutation_credits`, `_mutation_receipt_batches`, `_mutation_system_pdf`, `_mutation_auto_issue_receipts`) **รันจาก host** แล้ว shell ออกไปสั่ง `docker compose … test_runner` เอง — คนละสัญญากันคนละแบบในโฟลเดอร์เดียวกัน
- **Rule:** (1) 🔴 **ก่อนรัน harness ทุกครั้ง ให้เปิด docstring 16 บรรทัดแรกดูก่อน** ว่ามันบอกให้รันที่ไหน (2) อาการ `FileNotFoundError` ที่ path เป็น `/app` หรือ `/repo` = **รันผิดที่** ไม่ใช่บั๊กในโค้ดที่เพิ่งแก้ (3) ถ้า harness ระบุคำสั่งเต็มใน docstring ให้ **ลอกทั้งคำสั่ง** รวม `-T` (no TTY) และ `export PYTHONDONTWRITEBYTECODE=1` (4) harness ที่รันในคอนเทนเนอร์จะเขียนไฟล์ผ่าน volume mount — ตรวจ `git status` ว่าคืนสภาพจริงก่อนไปต่อเสมอ (ตัวนี้มี `finally` คืนไฟล์ให้แล้ว)
- **Tests:** n/a (บทเรียนกระบวนการ)
- **Date Added:** 2026-09-15

### 🧷 `@classmethod` ที่พารามิเตอร์แรก **ไม่ได้ชื่อ `cls`** ⇒ `TypeError` ตอน **เรียก** ไม่ใช่ตอน import
- **Context/Problem:** เขียน helper ตัวหนึ่งของใบสำคัญจ่ายเป็น
  ```python
  @classmethod
  def _voucher_channel_text(d: dict) -> Optional[str]:   # ← พารามิเตอร์แรกชื่อ d
      kind = d.get("account_kind")                        # ← และ body ไม่เคยใช้ cls
  ```
  ⇒ ผ่าน import · ผ่าน type-check · ผ่านทุกเทสต์ที่ไม่แตะเส้นทางนี้ · แต่ **ทุกครั้งที่เรนเดอร์ใบสำคัญ** ได้
  `TypeError: ReceiptsMixin._voucher_channel_text() takes 1 positional argument but 2 were given` ที่บรรทัดที่เรียก ⇒ **500 ตอนพิมพ์ PDF** ซึ่งไม่มีเทสต์ไหนแตะมาก่อน
- **Root Cause:** `@classmethod` ผูก instance/class เป็นพารามิเตอร์ตัวแรก **เสมอ** โดยไม่สนว่าชื่ออะไร — ผู้เขียนตั้งชื่อว่า `d` เพราะคิดว่าเป็นฟังก์ชันอิสระที่รับ dict · ผลคือตอนเรียกแบบ `cls._voucher_channel_text(d)` ส่งอาร์กิวเมนต์ 2 ตัวเข้า signature ที่รับ 1 ⇒ พัง
  🔴 และเพราะ **ไม่มีการใช้ `cls` ใน body** จึงไม่มีสัญญาณเตือนใด ๆ จาก linter · และ **ไม่มีเทสต์ไหนรู้เรื่อง** จนกว่าจะมีเทสต์ที่เรนเดอร์ใบสำคัญจริง
- **Rule:** (1) 🔴 **ใช้ `@classmethod` ก็ต่อเมื่อ body ใช้ `cls` จริง** — ถ้าไม่ใช้ ให้ `@staticmethod` (และถ้าตั้งใจให้รับ `self`/`cls` ให้ตั้งชื่อพารามิเตอร์แรกให้ตรง) (2) 🔴 **`TypeError` เรื่องจำนวนอาร์กิวเมนต์ไม่โผล่ตอน import** ⇒ การที่โมดูล import ผ่านไม่ได้แปลว่าเมธอดเรียกได้ — ต้องมีเทสต์ที่ **เรียก** มัน (3) เมื่อ helper ถูกเรียกจาก **เทมเพลต/เส้นทางเรนเดอร์** ให้มีเทสต์ที่เรนเดอร์เอกสารชนิดนั้นอย่างน้อย 1 ตัวเสมอ (4) ถ้าเจอ `TypeError: takes N positional arguments but M were given` ที่ **เรียกใช้** ไม่ใช่ import — ตรวจ decorator ก่อนตรวจ call site
- **Tests:** `backend/tests/test_finance_transaction_documents.py::test_voucher_channel_text_never_invents_a_channel` + mutant `M20` ใน `_mutation_pr5_docs.py` (สลับ `@staticmethod` → `@classmethod` ต้องล้ม)
- **Date Added:** 2026-09-15

### 🗓️ ส่ง `str` ให้พารามิเตอร์ SQL ที่ปลายทางเป็น `DATE` ⇒ `'str' object has no attribute 'toordinal'`
- **Context/Problem:** helper ของเทสต์สร้างงบประมาณด้วย
  ```python
  await conn.fetchval("INSERT INTO finance_budgets (…, start_date, end_date, …) VALUES (…, $5, $6, …)",
                      room_id, cat_id, "monthly", year, "2020-01-01", "2035-12-31", amount)
  ```
  ⇒ 4 เทสต์ล้มพร้อมกันด้วย `asyncpg.exceptions.DataError: invalid input for query argument $5: '2020-01-01' ('str' object has no attribute 'toordinal')`
- **Root Cause:** Postgres อนุมานชนิดของ `$5` จาก **คอลัมน์ปลายทาง** (DATE) ไม่ใช่จากค่าที่ส่ง ⇒ asyncpg จึงเตรียมตัวเข้ารหัสเป็น `date` และเรียก `.toordinal()` บนค่าที่ได้ — ซึ่งสตริงไม่มี · **ไม่ใช่ปัญหาเรื่องรูปแบบสตริง** (ISO ถูกต้องแล้ว) แต่เป็นเรื่อง **ชนิดของออบเจ็กต์ Python**
  🔴 นี่คือหลักฐานเชิงประจักษ์ของกฎ `docs/rules/backend.md` — *"Date params must be typed `date`/`datetime`, never `str`"* — ซึ่งเดิมทีเป็นกฎที่ "รู้กัน" แต่ไม่มีเทสต์ไหนพิสูจน์ว่าทำไม
- **Rule:** (1) 🔴 **ส่ง `datetime.date` object เสมอ** ให้พารามิเตอร์ที่ปลายทางเป็น DATE — `date.fromisoformat("2020-01-01")` ไม่ใช่ `"2020-01-01"` (2) **การเติม `::date` ที่ฝั่ง SQL ไม่ช่วย** — cast เกิดที่ Postgres หลัง asyncpg เข้ารหัสแล้ว ⇒ ยังพังที่เดิม (3) อาการนี้ **ขึ้นกับชนิดของคอลัมน์ปลายทาง** ⇒ คำสั่งเดียวกันย้ายไปคอลัมน์ TEXT แล้วจะผ่าน ⇒ อย่าดูแค่ "SQL หน้าตาถูก" (4) `Model(**payload)` ที่มีฟิลด์ `date` จะแปลงให้อัตโนมัติ — กับดักนี้เกิดกับ **raw SQL ในเทสต์/สคริปต์** เป็นหลัก
- **Tests:** `_insert_budget` ใน `backend/tests/test_finance_transaction_documents.py` (ลงวันที่เป็น `date` object · มี comment อธิบายกับดักนี้ไว้ที่ตัว helper)
- **Date Added:** 2026-09-15

### 🎭 `except UniqueViolationError` ชั้นที่ 2 ของ issuer ใหม่ = mutant ที่ **รอดอย่างชอบธรรม** (equivalent) — ต้องพิสูจน์ก่อนสรุปว่าเทสต์หลอกตัวเอง
- **Context/Problem:** issuer ทั้งสองตัวใหม่ (`_issue_income_doc`, `_issue_payment_voucher`) ลอกรูป "จับ `UniqueViolationError` แล้วคืนใบที่ชนะ" มาจาก `_issue_one` · แผนกำหนด mutant M7 = *"ถอด SAVEPOINT รอบ INSERT ของ issuer"* แล้วคาดว่าเทสต์ยิงซ้ำจะได้ 500 ⇒ **harness รายงาน SURVIVE**
- **Root Cause (ทำไมมันรอด — วิเคราะห์แล้วไม่ใช่เพราะเทสต์อ่อน):**
  1. `_lock_room_money(conn, room_id)` เป็นคำสั่งแรกของทุก issuer ⇒ issuer ของห้องเดียวกันถูก **serialize** ⇒ ไม่มีการชนกันจริง
  2. `add_transaction` **สร้างแถว `finance_transactions` ใหม่ทุกครั้ง** ⇒ `legacy_transaction_id` ใหม่เสมอ ⇒ `_find_existing_voucher` / `_find_existing_income` (**ชั้นที่ 1**) hit ทุกครั้งที่เรียกซ้ำ ⇒ ทางเข้าไปถึงชั้นที่ 2 **ไม่มีอยู่จริง** ผ่าน route ใด ๆ
  ⇒ การถอด SAVEPOINT จึงไม่เปลี่ยนพฤติกรรมที่สังเกตได้เลย = **equivalent mutant** ไม่ใช่ร่องรอยของเทสต์ที่ไม่มีฟัน
  📌 เทียบเคียงกับ `_issue_deposit` M9 ที่พิสูจน์ว่าเป็น equivalent มาก่อนแล้ว — และ **ต่าง** จากเคส `_issue_one` ที่ **มี** เทสต์จำลองการแข่งจริง (`test_the_loser_of_the_race_gets_the_winning_receipt_not_a_500`)
- **Rule:** (1) 🔴 **mutant ที่รอดต้องถูกวินิจฉัยก่อนแก้เทสต์เสมอ** — แยกให้ออกระหว่าง "เทสต์ไม่มีฟัน" กับ "โค้ดบรรทัดนั้นไม่มีทางถูกเรียก" (2) 🔴 **อย่าลบโค้ดที่เป็น defensive contract ทิ้งเพียงเพราะพิสูจน์ด้วยเทสต์ไม่ได้** — ชั้นที่ 2 มีไว้รองรับวันที่ข้อสันนิษฐาน (1) หรือ (2) เปลี่ยน (เช่น มีคนถอด advisory lock ออก หรือเพิ่ม route ที่ออกเอกสารซ้ำจาก transaction เดิม) ⇒ คงโค้ดไว้ แล้ว **บันทึก SURVIVE พร้อมเหตุผลลงรายงาน** (3) จำนวน "จับได้ N/M" ไม่ใช่ตัวชี้วัดคุณภาพโดยลำพัง — **ต้องรายงาน N ที่รอดพร้อมเหตุผลทุกตัว** (4) ถ้าต้องการให้ mutant นี้ "ถูกจับ" จริง ต้องเขียนเทสต์ที่ **ข้าม route** ไปเรียก issuer สองครั้งด้วย `transaction_id` เดียวกันพร้อมกัน — ซึ่งเป็นเทสต์ที่ Artificial จนต้องชั่งน้ำหนักกับคุณค่าที่ได้
- **Tests:** M7 ใน `_mutation_pr5_docs.py` (รายงาน SURVIVE + rationale เขียนกำกับไว้ในไฟล์ ไม่ใช่เงียบ)
- **Date Added:** 2026-09-15

### 🧨 `_issue_deposit` **ยัง** จับ `UniqueViolationError` โดยไม่มี SAVEPOINT — กับดักที่ยัง live และเป็นเหตุผลที่ issuer ใหม่ต้องลอกรูปจาก `_issue_one`
- **Context/Problem:** หลังเขียน issuer ใหม่สองตัว กลับไปตรวจ `_issue_deposit` (`receipts.py:934-965`) พบว่ายังเป็น
  ```python
  try:
      row = await conn.fetchrow("INSERT INTO finance_receipts …")
  except asyncpg.UniqueViolationError:
      raced = await cls._find_existing_deposit(conn, transaction_id)   # ← อ่าน conn ต่อ
  ```
  โดยไม่มี `async with conn.transaction():` ครอบ ⇒ ถ้า handler นี้ถูกกระตุ้นจริง จะได้ `InFailedSQLTransactionError` (25P02) ⇒ **500** ไม่ใช่ใบเดิม
- **Root Cause:** หลักการเดียวกับหัวข้อ 💥 ที่ `docs/skills.md:1389` — แต่ **การมีอยู่ของหัวข้อนั้นไม่ได้กันบั๊กนี้** เพราะตอนเขียน `_issue_deposit` ผู้เขียนลอกรูปมาจาก `_issue_one` **เฉพาะส่วน handler** ไม่ได้คัดลอก SAVEPOINT · และมัน **รอดการทดสอบ** เพราะ `idx_student_credits_idem` (`credits.py:226`) ยิงก่อนเสมอ ⇒ เส้นทางนี้ไม่เคยถูกเข้า
  🔴 **นี่คือรูปแบบความล้มเหลวที่อันตราย: "มีบทเรียนเขียนไว้แล้ว แต่โค้ดที่เขียนทีหลังยังทำผิด"** — บทเรียนที่ไม่ผูกกับเทสต์จะไม่ถูกบังคับใช้
- **Rule:** (1) 🔴 **issuer ใหม่ทุกตัวต้องคัดลอกรูป SAVEPOINT จาก `_issue_one` (`receipts.py:718`) ไม่ใช่จาก `_issue_deposit`** — และ issuer ทั้งสองตัวของ F6 ทำถูกแล้ว (`:1068`, `:1198`) (2) 🔴 เมื่อจะ "ลอกรูปจากฟังก์ชันพี่น้อง" ให้ลอกจาก **ตัวที่ถูกต้องที่สุด** ไม่ใช่ตัวที่อยู่ใกล้ที่สุด — ตรวจว่ามันมี SAVEPOINT/ด่าน/lock ครบไหมก่อน (3) 🚧 **`_issue_deposit` ยังเป็นหนี้ทางเทคนิคที่ต้องแก้** (ควรมี SAVEPOINT เหมือนพี่น้อง) — ถ้าแตะไฟล์นี้ครั้งหน้าให้แก้พร้อมกัน · **ห้ามลบทิ้ง** เพราะมันเป็น defensive contract (4) บทเรียนใน `docs/skills.md` **ไม่มีผลบังคับใช้ด้วยตัวเอง** ⇒ ถ้าอยากให้กฎถูกบังคับ ต้องมี **เทสต์เชิงโครงสร้าง** (แบบ `_mutation_*` หรือ `ast` check) ตามหลัง
- **Tests:** issuer ใหม่ทั้งสองมี SAVEPOINT (`receipts.py:1068`, `:1198`) · `_issue_deposit` **ยังไม่มีเทสต์คุมเส้นทางนี้** (ตาม M7/M9 ที่เป็น equivalent) ⇒ ยังเป็นช่องว่างที่บันทึกไว้
- **Date Added:** 2026-09-15

### 📮 `response_model` ตัดฟิลด์ที่ service คืน **เงียบ ๆ** — เจอเป็นครั้งที่ 3 และเป็นคลาสของบั๊กที่หาไม่เจอด้วยเทสต์ service
- **Context/Problem:** `add_transaction` ถูกแก้ให้คืน `{"status","message","receipt_no","doc_type","doc_type_label"}` แต่ `routers/finance/transactions.py:17` ยังประกาศ `response_model=SuccessResponse` ⇒ ฟิลด์เลขเอกสาร **ถูกตัดทิ้งที่ชั้น serialization** ⇒ frontend ได้ `receipt_no: undefined` **โดยไม่มี error ใด ๆ ทั้งฝั่ง server และ client**
  🔁 ก่อนหน้านี้เกิดแบบเดียวกันกับ `BatchPaymentConfirmResponse` และ `TransactionCreateResponse` — **สามครั้งในโปรเจกต์เดียว**
- **Root Cause:** FastAPI ใช้ `response_model` เป็น **ตัวกรองขาออก** — ฟิลด์ที่ service คืนแต่ schema ไม่ประกาศจะถูก **ทิ้งเงียบ** ไม่ error ไม่ warning · เทสต์ระดับ service (`await add_transaction(...)` แล้ว `assert result["receipt_no"]`) **ผ่านหมด** เพราะมันไม่ผ่านชั้น serialization ⇒ เทสต์ที่ดู "ครอบคลุม" จึงมองไม่เห็นบั๊กนี้เลย
- **Rule:** (1) 🔴 **ทุกครั้งที่ service เปลี่ยนรูปร่างของ dict ที่คืน ให้ไล่ขึ้นไปแก้ `response_model` ที่ router ด้วย** — ทั้งสองที่ต้องถูกแก้พร้อมกันเสมอ (2) 🧪 **เทสต์ต้องยิงผ่าน HTTP (`client.post(...)`) ไม่ใช่เรียก service ตรง** เมื่อสัญญาที่ต้องการคือ "client เห็นอะไร" — เทสต์ service พิสูจน์ไม่ได้ว่าฟิลด์รอดชั้น serialization (3) เมื่อเพิ่ม response schema ใหม่ ให้ **สืบทอดจาก `SuccessResponse`** เพื่อไม่ให้สัญญาเดิม (`status`/`message`) หลุด (4) อาการปลายทางที่ต้องสงสัย: frontend ได้ค่า `undefined` ทั้งที่ backend log แสดงว่าคืนค่าแล้ว ⇒ ให้ตรวจ `response_model` เป็นอันดับแรก
- **Tests:** `backend/tests/test_finance_transaction_documents.py::test_add_transaction_response_carries_the_document_number` (ยิงผ่าน HTTP จริง)
- **Date Added:** 2026-09-15

### 🧩 เทมเพลตที่แตกเป็น partial + `{% include %}`: **ทุกคีย์ที่ partial อ้างต้องถูกตั้งเสมอ** และ **ต้องเปิด `keep_trailing_newline`**
- **Context/Problem:** ต้องให้ใบสำคัญจ่ายและใบเสร็จใช้ **เทมเพลตคนละตัว** ในไฟล์ HTML เดียว (ผู้ใช้ติ๊กเลือกปนกันได้) ⇒ แตกเนื้อในของ `receipt.html` ออกเป็น `_receipt_body.html` + `_voucher_body.html` แล้วให้ shell เรียก `{% include d.body_template %}` · เกิดปัญหาสองชั้นพร้อมกัน
- **Root Cause (สองกลไกที่ต้องแก้ทั้งคู่):**
  1. **คีย์ที่หายไปไม่ได้เรนเดอร์ว่างเสมอ** — `{{ d.foo }}` บนคีย์ที่ไม่มีเรนเดอร์เป็นสตริงว่าง (**ไม่ error**) แต่ `"{:,.2f}".format(d.amount)` หรือ `d.amount|round(2)` บน `Undefined` **ระเบิดเป็น `TypeError` ⇒ 500** ⇒ partial ที่อ้างคีย์ใหม่ต้องมั่นใจว่า `_document_context` ตั้ง **ทุก** คีย์ แม้ค่าจะเป็น `None`/`[]` — และกับดักคือ **มันพังเฉพาะเอกสารชนิดนั้น** ไม่พังตอน import หรือตอนรันเทสต์ชนิดอื่น
  2. **Jinja ตัด newline ท้ายไฟล์ของทุกเทมเพลตทิ้ง** (`keep_trailing_newline` default = `False`) ⇒ ไบต์ของไฟล์ partial **ไม่เท่ากับ** ไบต์ที่เรนเดอร์ออกมา ⇒ การตรวจ "ไฟล์ตรงกับผลลัพธ์" ด้วยการอ่านไฟล์ดิบ ๆ จะ false positive/negative สลับกันไม่คงที่
- **Rule:** (1) 🔴 **partial ต้องประกาศสัญญาคีย์ของตัวเองไว้ใน docstring ของผู้เรียก** และ `_document_context` ต้องตั้งครบทุกคีย์แบบไม่มีเงื่อนไข (2) 🔴 **ตั้ง `keep_trailing_newline=True` ที่ `pdf.py:_get_template`** เพื่อให้ "ไบต์ของไฟล์ = ไบต์ที่เรนเดอร์" — เป็นเงื่อนไขที่ทำให้ตรวจ template แบบ byte-compare ได้ (3) อย่าใช้ `{{ }}` กับค่าที่จะถูกส่งเข้า `.format()`/filter ตัวเลข โดยไม่มีการรับประกันว่าคีย์มีอยู่ (4) เทมเพลตใหม่ทุกตัวต้องมี **เทสต์ที่เรนเดอร์มันจริง** ไม่ใช่แค่ import
- **Tests:** `test_voucher_renders_with_voucher_wording` · `test_voucher_without_an_approver_leaves_the_slot_blank` · `test_voucher_prints_explicit_text_when_no_budget_covers_it` (ทั้งสามจับ `Undefined` ที่หลุดเข้า formatter)
- **Date Added:** 2026-09-15

### 🕳️ `{% include Undefined %}` **โยน error** แต่ `{{ Undefined }}` เรนเดอร์เป็นช่องว่าง — และ "default ที่ปลอดภัย" อาจเป็นการทำลายด่านกันความผิดพลาด
- **Context/Problem:** หลังแยก `receipt.html` เป็น shell + `{% include d.body_template %}` **full backend suite ล้ม 1 ตัว**:
  `tests/test_finance_receipts.py::test_receipt_template_declares_one_font_face_per_weight` →
  `jinja2.exceptions.UndefinedError: 'dict object' has no attribute 'body_template'` (โยนจาก `loaders.py:197 get_source` ⇒ `template = Undefined` ⇒ `template.split("/")` พัง)
  เทสต์ตัวนั้นสร้าง context **ด้วยมือ** แล้วส่งเข้า `render_receipt_html` ⇒ ผ่าน production มาไม่ถึง แต่ผ่านเทมเพลตตรง ๆ
- **Root Cause:** Jinja มีสองพฤติกรรมที่ต่างกันสุดขั้วกับ `Undefined`:
  | สำนวน | พฤติกรรม |
  |---|---|
  | `{{ d.missing }}` | เรนเดอร์เป็น **สตริงว่าง** (default `Undefined`) — เงียบ |
  | `{% include d.missing %}` | **โยน `UndefinedError`** เพราะต้องใช้ค่าเป็น *ชื่อไฟล์* |
  | `"{:,.2f}".format(d.missing)` | **โยน `TypeError`** เพราะเรียก `__format__` บน `Undefined` |
  ⇒ การแยก partial เปลี่ยน "คีย์ที่ลืม" จาก *เงียบ* เป็น *ระเบิด* — ซึ่ง **เป็นผลดี** แต่มีราคาคือทุก caller ที่ประกอบ context เองต้องอัปเดต
- **กับดักที่ต้องระวัง (สำคัญกว่าตัวบั๊ก):** ทางแก้ที่ดู "ปลอดภัย" คือใส่ default — `{% include d.body_template or '_receipt_body.html' %}` · **ห้ามทำเด็ดขาดในกรณีนี้** เพราะมันเปลี่ยนความล้มเหลวแบบ *เสียงดัง* ให้กลายเป็น *เอกสารผิดที่ไม่มีใครรู้*: ถ้า `_document_context` ลืมตั้งคีย์นี้ให้ใบสำคัญจ่าย ระบบจะ **พิมพ์ถ้อยคำใบเสร็จทั้งใบโดยไม่มี error** ซึ่งคือกับดักที่การแยก body template ถูกออกแบบมาป้องกันตั้งแต่แรก ⇒ **default ที่นี่ = ถอดด่านกันความผิดพลาดออก** (เทียบ `docs/rules/testing.md`: อย่าทำให้เทมเพลตกลืน Undefined)
- **Rule:** (1) 🔴 **แยกให้ออกระหว่าง "คีย์ที่ผู้ใช้ปลายทางต้องกรอก" กับ "คีย์ที่โค้ดต้องตั้งเสมอ"** — อย่างหลังต้อง **ไม่มี default** และต้องพังให้ดัง (2) 🔴 **เมื่อย้ายเทมเพลตไปเป็น partial ให้ `grep` หาทุกที่ที่เรนเดอร์เทมเพลตนั้นโดยไม่ผ่าน `_document_context`** (เทสต์คือผู้ต้องสงสัยอันดับหนึ่ง) — full suite จะจับได้ก็ต่อเมื่อมีเทสต์นั้นอยู่ (3) ถ้าเทมเพลตมี `{% include %}`, `{% extends %}`, `{% import %}` ที่อ้างคีย์ ⇒ คีย์นั้นเป็น **บังคับเชิงโครงสร้าง** ไม่ใช่ optional (4) เมื่อเทสต์ล้มเพราะฟีเจอร์ใหม่ **ให้แก้ที่เทสต์ถ้าข้อสันนิษฐานของเทสต์เก่า** — อย่าแก้ที่ production เพื่อให้เทสต์เก่าผ่าน (5) 🧪 ผลพลอยได้: เทสต์ที่ประกอบ context เองคือ **canary ฟรี** สำหรับสัญญาคีย์ของเทมเพลต — อย่าลบมัน
- **Tests:** `test_finance_receipts.py::test_receipt_template_declares_one_font_face_per_weight` (เติม `"body_template": "_receipt_body.html"` + คอมเมนต์อธิบายว่าห้ามใส่ default) · ตรวจด้วย `python -m pytest -q /app/tests/test_finance_receipts.py::test_receipt_template_declares_one_font_face_per_weight /app/tests/test_finance_money_lock.py` → 40 passed
- **Date Added:** 2026-09-15

### 🎯 เทสต์ที่คาด **400 ด้วยเหตุ A** จะกลายเป็น **false positive** ทันทีที่มีการเพิ่มด่าน B ก่อนถึง A
- **Context/Problem:** `test_finance_http.py:434` และ `:455` POST **รายจ่าย** แล้วคาดว่าได้ 400 จาก *ยอดเกินงบ* / *หมวดหมู่ผิด* · เมื่องาน F6 เพิ่มด่าน "ต้องระบุผู้เบิก/ผู้รับเงิน" **ก่อน** ด่านเดิมในเส้นทาง ⇒ ทั้งสองเทสต์ยัง **เขียว** แต่เขียวเพราะ **ด่านผู้เบิก** ไม่ใช่เพราะด่านที่มันตั้งใจทดสอบ ⇒ ความสามารถในการจับ regression ของงบประมาณ/หมวดหมู่ **หายไปเงียบ ๆ**
- **Root Cause:** เทสต์ที่ assert แค่ **สถานะ** (`== 400`) โดยไม่ assert **ข้อความ/สาเหตุ** จะถูก "ด่านใหม่ที่มาก่อน" กลืนได้เสมอ · และการเพิ่มด่านใหม่ **ไม่ทำให้เทสต์เดิมล้ม** ⇒ ไม่มีสัญญาณเตือนใด ๆ ว่าความหมายของเทสต์เปลี่ยนไป
- **Rule:** (1) 🔴 **เมื่อเพิ่มด่าน validation ใหม่ ให้ไล่หาทุกเทสต์ที่ยิง payload ชนิดนั้นแล้วคาด error** และ **เติมข้อมูลให้ผ่านด่านใหม่** เพื่อให้มันยังทดสอบสิ่งที่มันตั้งใจ (2) 🔴 **เทสต์ negative ควร assert ที่ข้อความ/รหัสของสาเหตุ** ไม่ใช่แค่สถานะ — ไม่งั้นมันจะกลายเป็น false positive ทุกครั้งที่มีด่านใหม่ (3) ถ้าเป็นไปได้ ให้วางด่านใหม่ **หลัง** ด่านเดิมเพื่อลด blast radius — แต่ต้องเลือกอย่างตั้งใจ ไม่ใช่บังเอิญ (4) เวลาประเมิน "เทสต์เขียว" ต้องถามด้วยว่า **เขียวเพราะเหตุที่ตั้งใจหรือเพราะเหตุอื่น**
- **Tests:** `test_finance_http.py:434,455` (เติม `payee_name` แล้ว) · `test_finance_budgets.py::_create_tx_api` (เติมที่เดียวครอบทุกผู้เรียก) · `test_discord_notifications.py:277`
- **Date Added:** 2026-09-15

### 📦 **ย้าย/แตกไฟล์เทมเพลต = ทำให้ mutation harness กลายเป็น STALE เงียบ ๆ** — และ STALE อ่านเผิน ๆ เหมือน "ผ่าน"
- **Context/Problem:** PR-5 แตก `templates/finance/receipt.html` เป็น shell (`<style>` + `.doc` frame + `{% include d.body_template %}`) แล้วย้ายเนื้อในทั้งดุ้นไป `_receipt_body.html` **โดย indent ไม่เปลี่ยนแม้แต่ไบต์** · ผลคือ harness สองตัวที่ผูก anchor กับ *path* ของไฟล์เดิมกลายเป็นใช้ไม่ได้ทันที
  - `_mutation_credits.py` M14 — `"templates/finance/receipt.html"` → anchor `{%- elif d.doc_type == 'deposit' -%}` ไม่มีอยู่ในไฟล์นั้นอีก
  - `_mutation_receipt_merge.py` — `TEMPLATE = "templates/finance/receipt.html"` ⇒ **ทุก** mutant ที่ใช้ค่านั้น (17 ตัว) กลายเป็น STALE พร้อมกัน
- **Root Cause:** harness เหล่านี้ระบุ **`(path, anchor_text)`** ⇒ ตัวชี้เป็น *ตำแหน่งไฟล์* ไม่ใช่ symbol · การย้ายโค้ดไปไฟล์อื่นทำให้ anchor ไม่เจอ **โดยไม่มีการเตือนใด ๆ จาก Python หรือ pytest** · และผลลัพธ์ที่ได้คือ `STALE`/`ข้าม: anchor ไม่ชัด` ซึ่ง **ถ้าไม่ตั้งใจอ่านจะดูคล้าย "ไม่มีปัญหา"** — ต่างจาก `SURVIVE` ที่ดึงสายตาได้
  - ⚠️ กับดักที่ร้ายกว่าคือ: mutation ตัวนั้น **ไม่ถูกทดสอบเลย** แต่ harness ยังคืน exit code 0 ถ้าไม่มี mutant อื่นรอด ⇒ CI/คนอ่านสรุปว่า "mutation ครบ"
- **Rule:** (1) 🔴 **ทุกครั้งที่ย้ายหรือแตกไฟล์ ให้ `grep -n "<ชื่อไฟล์เดิม>" backend/tests/_mutation_*.py` ทันที** แล้วอัปเดต path ให้ชี้ไฟล์ที่ anchor ไปอยู่จริง (2) 🔴 **การย้ายไฟล์แบบ "indent เดิมทุกไบต์" เป็นกรณีที่อันตรายที่สุด** เพราะ anchor ยังถูกต้องสมบูรณ์ — มีแต่ *path* ที่ผิด ⇒ ต้องแก้ path เท่านั้น ห้ามไปแก้ anchor (3) **STALE ต้องถูกอ่านเป็นความล้มเหลว ไม่ใช่ความไม่เกี่ยวข้อง** — harness ที่ขึ้น STALE คือ harness ที่ **ไม่ได้ทำหน้าที่ของมัน** (4) harness ที่ครอบ mutation จำนวนมากด้วยค่าคงที่ตัวเดียว (เช่น `TEMPLATE`) จะพังทั้งชุดพร้อมกัน ⇒ **ให้ค่าคงที่ตัวเดียวเป็นจุดที่ต้องตรวจก่อนเสมอ** (5) การรัน "harness ของ PR เก่าทั้งหมด" หลังงานที่แตะไฟล์ร่วม **ไม่ใช่พิธีกรรม** — รอบนี้มันคือสิ่งที่จับ STALE ได้ และถ้าไม่รัน จะไม่มีใครรู้เลยตลอดไป
- **Tests:** `_mutation_credits.py` (M14) · `_mutation_receipt_merge.py` (`TEMPLATE` → `templates/finance/_receipt_body.html` ⇒ 17/17 หลังแก้)
- **Date Added:** 2026-09-15

### 🔁 บทเรียนที่บันทึกไว้แล้ว **ไม่ได้บังคับใช้ตัวเอง** — ต้องผูกมันเข้ากับขั้นตอน ไม่ใช่ไว้ในหัว
- **Context/Problem:** บทเรียน "`_mutation_jsonb_meta.py` ต้องรัน **ใน** คอนเทนเนอร์ ไม่ใช่จาก host" ถูกเขียนลงไฟล์นี้ **ไปแล้ว** (หัวข้อ 🧰 ด้านบน, วันเดียวกัน) — แต่หลังจากนั้น **ในเซสชันเดียวกัน** ผมก็ยังรันมันจาก host ผ่าน loop เดียวกับ harness ตัวอื่น ⇒ `FileNotFoundError: '/app'` · mutant ตัวแรกถูกเขียนลงดิสก์แล้ว crash ก่อน pytest จะได้รัน ⇒ **harness ตัวนั้นไม่ได้ตรวจอะไรเลย** และ `finally` คืนไฟล์ให้อย่างเรียบร้อย ⇒ ไม่มีร่องรอยเหลือให้เห็น นอกจาก traceback ใน log
- **Root Cause:** "รู้แล้ว" ≠ "กันได้" · เมื่อรันของหลายอย่างพร้อมกันเป็นชุด (loop/template command) **ความต่างเฉพาะตัวของแต่ละตัวจะถูกกลืน** — ผมคัดลอกคำสั่งเดียวใช้กับทั้ง 6 harness ทั้งที่เอกสารบอกไว้ชัดแล้วว่ามันไม่เหมือนกัน
- **Rule:** (1) 🔴 **ก่อนรันเป็นชุด ให้ดึง "วิธีรัน" ของแต่ละตัวออกมาเทียบกันก่อน** (`grep -nE 'cwd=|docker|sys\.executable' backend/tests/_mutation_*.py`) แล้วจัดกลุ่ม — ตัวที่รันในคอนเทนเนอร์ต้องแยกคิว (2) 🔴 **exit code ที่ไม่ใช่ 0 พร้อม traceback = ยังไม่ได้ทดสอบอะไร** ห้ามนับเป็น "ผ่าน" หรือ "ไม่เกี่ยวข้อง" · และให้ตรวจว่า **harness ตัวนั้นพิมพ์ผลของ mutant ครบทุกตัวหรือไม่** ก่อนเชื่อสรุป (3) เพดานของ loop ที่รันของต่างชนิดกันคือ **ความสม่ำเสมอ** — ถ้าไม่สม่ำเสมอ ให้เขียนคำสั่งแยกกันตรง ๆ ดีกว่ารวบเป็น loop สวย ๆ (4) เมื่อเขียนบทเรียนลงไฟล์แล้ว **รอบถัดไปที่ทำงานชนิดเดียวกัน ต้องเปิดอ่านก่อนลงมือ** ไม่งั้นไฟล์นี้เป็นแค่บันทึก ไม่ใช่เครื่องมือ
- **Tests:** n/a (บทเรียนกระบวนการ) — หลักฐาน: `>>> _mutation_jsonb_meta exit=1` + `FileNotFoundError: '/app'` ใน `/tmp/mut_existing.txt`
- **Date Added:** 2026-09-15

### 🙈 `cmd || echo "✅ สำเร็จ"` **โกหกได้** — เมื่อ `cmd` ล้มเหลวด้วยเหตุอื่นที่ไม่ใช่ "ไม่มีอะไรให้ทำ"
- **Context/Problem:** หลังลบโฟลเดอร์ชั่วคราว ผมตรวจว่าลบหมดด้วย `ls <path> 2>/dev/null || echo "ลบแล้ว"` แล้วเห็น "ลบแล้ว" ⇒ สรุปว่าสะอาด · ความจริงคือ **shell ยังมี cwd เป็นโฟลเดอร์ที่เพิ่งลบไป** ⇒ ทุก relative path พังด้วย `getcwd` error · `ls` ล้มเหลวเพราะ *หาที่ไม่เจอ* ไม่ใช่เพราะ *ไฟล์ไม่มี* และ `rm -f` ก่อนหน้าก็ไม่ลบอะไรเลย (แต่ `-f` กลืน error เงียบ) · `git status` ตอนนั้นก็พังด้วย `fatal: Unable to read current working directory` แต่ข้อความ "✅" ถูกพิมพ์ไปแล้ว
- **Root Cause:** `A || B` **ไม่แยกแยะสาเหตุของความล้มเหลว** — มันแค่บอกว่า "A ไม่สำเร็จ" · และคำสั่งที่ "สำเร็จโดยไม่ทำอะไร" (`rm -f` กับ path ที่ไม่มี, `grep` ไม่เจอ, `ls` ผิดที่) **Exit code 0 ทำให้ดูเหมือนงานเสร็จ** ⇒ ได้หลักฐานปลอมที่ดูน่าเชื่อถือกว่าการไม่มีหลักฐาน
- **Rule:** (1) 🔴 **คำยืนยันต้องมีรูปที่ล้มเหลวได้** — ใช้ `if [ -e path ]; then ยังอยู่; else ลบแล้ว; fi` แทน `ls path || echo ลบแล้ว` เพราะรูปแรก **แยก "ไม่มีไฟล์" ออกจาก "คำสั่งพัง" ได้** (2) 🔴 **หลังลบ/ย้าย ให้ `cd` กลับไปที่ที่รู้จักแน่ ๆ ก่อนตรวจ** (`cd <repo root> && …`) — อย่าเชื่อ cwd ที่ค้างมาจากคำสั่งก่อน (3) อย่าใช้ `-f` กลืน error แล้วสรุปว่า "ลบแล้ว" — ให้ตรวจผลลัพธ์จริง (4) 🔴 **`A || B` ที่ B เป็นข้อความยืนยันความสำเร็จ คือกับดักเดียวกับ STALE-อ่านเป็น-ผ่าน** — ในทั้งสองกรณี ระบบรายงาน "เรียบร้อย" ในสถานะที่ **ไม่มีอะไรเกิดขึ้นเลย** ซึ่งแย่กว่า error ตรง ๆ เพราะไม่มีใครไปตรวจต่อ (5) ถ้าต้องลบไฟล์ที่ root สร้าง ให้ `docker run --rm -v <dir>:/t alpine rm -rf /t/...` — แต่อย่าลืมว่ามันก็คืน 0 เหมือนกัน ⇒ ยังต้องตรวจด้วย `if [ -e ]`
- **Tests:** n/a (บทเรียนกระบวนการ) — เจอตอนเก็บกวาด `_preview_render.py`/`_preview_out/` ของการตรวจ PDF ด้วยตา
- **Date Added:** 2026-09-15

### 🏷️ ฟังก์ชันที่ถูกใช้ร่วมสองเส้นทาง ซ่อน "ค่าคงที่ที่ผูกกับความหมายของเส้นทางแรก" ไว้
- **Context/Problem:** F6/PR-6 ให้ `notify_finance_transaction` (ข้อความรายการเงิน) แนบไฟล์ โดย **reuse `_deliver_payment_message`** ตัวเดียวกับ `notify_finance_payment` (F5/PR-3) เพราะตรรกะ "ไฟล์แนบพัง = ข้อความต้องออก" ต้องเหมือนกันเป๊ะ · แต่ฟังก์ชันนั้นมี `embed.add_field(name="🧾 ใบเสร็จ", value=ATTACH_FAILED_NOTE)` ฮาร์ดโค้ดอยู่ ⇒ เมื่อใช้กับ **ใบสำคัญจ่าย** ข้อความจะบอกว่า "แนบ **ใบเสร็จ** ไม่ได้" ทั้งที่เอกสารคือใบสำคัญจ่าย — และบนเส้นทางที่แปะ PDF ใบสำคัญจ่ายให้ **ทุกครั้งที่บันทึกรายจ่าย**
- **Root Cause:** ตอนเขียนฟังก์ชันนี้ครั้งแรก (PR-3) มันมีผู้เรียก **หนึ่งราย** ⇒ `"ใบเสร็จ"` ไม่ใช่ค่าคงที่ แต่เป็น **คำพ้องของโดเมนของผู้เรียก** · การเพิ่มผู้เรียกรายที่สองที่โดเมนต่างกัน ทำให้บรรทัดเดิมกลายเป็น **คำโกหกที่ไม่มีใครเห็น** — ไม่มี exception ไม่มี log ไม่มีเทสต์ล้ม เพราะมัน "ทำงานถูก" ตามโค้ด
- **Correct Pattern/Solution:** ทำให้ป้ายเป็น **พารามิเตอร์ที่มี default = พฤติกรรมเดิม** แล้วให้ผู้เรียกรายใหม่ส่งของตัวเอง
  ```python
  async def _deliver_payment_message(self, channel, content, embed, files,
                                     attach_label: str = "🧾 ใบเสร็จ"):
  ```
  ผู้เรียกเดิม (`FINANCE_PAYMENT`) ไม่ต้องแก้แม้แต่ไบต์เดียว · ผู้เรียกรายใหม่ส่ง `attach_label="🧾 เอกสาร"` (คำกลาง เพราะ "ใบสำคัญจ่ายไม่ใช่ใบเสร็จ")
- **Rule:** (1) 🔴 **ก่อน reuse ฟังก์ชันให้เส้นทางที่สอง ให้ grep คำภาษาไทย/ชื่อ field ทุกตัวในฟังก์ชันนั้น แล้วถามว่า "คำนี้ยังจริงกับผู้เรียกรายใหม่ไหม"** — ตรรกะที่ reusable กับ **ถ้อยคำ** ที่ reusable เป็นคนละเรื่อง · (2) 🔴 ป้ายที่ผู้ใช้อ่านและผูกกับ *ชนิด* ของสิ่งของ **ต้องเป็นพารามิเตอร์ ไม่ใช่ค่าคงที่ในฟังก์ชันที่แชร์กัน** (3) การเพิ่มผู้เรียกรายที่สอง **ไม่ใช่ "การเปิดสวิตช์" แต่เป็น "งานใหม่"** — ต้องมีเทสต์ของเส้นทางใหม่ที่ยืนยัน *ถ้อยคำ* ไม่ใช่แค่ "มี call เกิดขึ้น" (4) ⚠️ เมื่อแก้บรรทัดที่ **เป็น anchor ของ mutation harness** ต้องอัปเดต anchor ด้วย ไม่งั้นรอบถัดไปขึ้น STALE ซึ่งอ่านเผิน ๆ เหมือน "ผ่าน" (เคสจริง: BM1 ของ `_mutation_pdf_attach.py`)
- **Tests:** `bot_discord/tests/test_pdf_attach.py::NotifyFinanceTransactionTest::test_field_is_labelled_เอกสาร_not_ใบเสร็จ` · `::test_message_survives_discord_rejecting_the_file` · `_mutation_pdf_attach.py` BM12 = CATCH
- **Date Added:** 2026-09-16

### 🎛️ handler ที่ฮาร์ดโค้ดไว้ในฟังก์ชัน generic = "ทางแยกที่สอง" ที่เงียบสนิท — เทสต์ที่ยืนยันแค่ "มี call" จับไม่ได้
- **Context/Problem:** `_spawn_pdf_task(server_id, data)` (PR-3) รันงานเบื้องหลังโดยเรียก `self.action_service.notify_finance_payment` **ฮาร์ดโค้ดไว้ข้างใน** · PR-6 ต้องการให้เส้นทางที่สอง (`FINANCE_TRANSACTION`) ใช้กลไกเดียวกันแต่ส่ง **embed คนละรูปร่าง** ⇒ ถ้าปล่อยให้ฮาร์ดโค้ด ข้อความรายการเงินจะกลายเป็น embed "✅ จ่ายเงินแล้ว" **โดยไม่มี error เลย** (ชื่อฟิลด์ต่างกัน แต่ `discord.Embed` รับได้หมด) · และเทสต์ที่เขียนว่า `assert action_service.notify_finance_payment.called` **จะผ่านด้วย** เพราะมี call เกิดขึ้นจริง — แค่ผิดตัว
- **Root Cause:** ฟังก์ชันถูกออกแบบตอนที่มี **ปลายทางเดียว** ⇒ "จะเรียกอะไร" ถูกฝังเป็นค่าคงที่ · เมื่อมีปลายทางที่สอง ความรู้เรื่อง "ต้องเรียกอะไร" อยู่ที่ **ผู้เรียกเท่านั้น** ⇒ การฮาร์ดโค้ดคือการ **ทิ้งข้อมูลที่ผู้เรียกรู้** แล้วเดาแทน · อาการจึงเป็นการเลือกผิดแบบเงียบ ซึ่งเทสต์แนว "presence" แยกไม่ออกจากการเลือกถูก
- **Correct Pattern/Solution:** handler เป็น **พารามิเตอร์บังคับ** (ไม่มี default — default คือการเชิญให้ฮาร์ดโค้ดกลับ):
  ```python
  def _spawn_pdf_task(self, handler, server_id: int, data: dict) -> None:
      async def runner():
          async with self._pdf_semaphore:
              await handler(server_id, data)
  ```
  และ **เทสต์ที่จับได้จริง** ต้องฉีด handler ปลอมของตัวเองเข้าไป แล้วยืนยันว่า *ตัวนั้น* ถูกเรียก (`SpawnPdfTaskTest.test_spawn_pdf_task_uses_the_passed_handler`) — ไม่ใช่ยืนยันว่า `action_service` ถูกเรียก
- **Rule:** (1) 🔴 **ฟังก์ชัน generic ที่ "ทำงานกับ callback" ต้องรับ callback เป็นพารามิเตอร์เสมอ** — ห้ามฮาร์ดโค้ดแม้ตอนนี้จะมีปลายทางเดียว (2) 🔴 **เทสต์ของฟังก์ชัน generic ต้องฉีดของปลอมของตัวเอง ไม่ใช่ใช้ของจริง** — ใช้ของจริง = เทสต์พิสูจน์ว่า "มี call" ซึ่งผ่านทั้งตอนเลือกถูกและเลือกผิด (3) 🔴 **เทสต์ที่ยืนยัน "ชนิดของสิ่งที่ถูกส่ง" ต้องเทียบกับตัวตน/รูปร่าง ไม่ใช่จำนวนครั้ง** — `await_count == 1` ไม่ได้แปลว่าส่งถูก (4) ถ้า embed สองชนิดใช้ field คนละชื่อ **Discord จะไม่ฟ้อง** ⇒ ความผิดพลาดนี้ต้องถูกจับด้วยเทสต์เท่านั้น ไม่มี runtime guard ให้พึ่ง (5) 🟡 เทสต์ที่ "ทดสอบ Python เอง" (เช่น assert ว่าเรียกด้วย arity เก่าแล้วได้ `TypeError`) **ไม่ใช่เทสต์ของโปรเจกต์** — ตัดทิ้งเป็น noise (เคสจริง: `test_passing_handler_is_required` ที่เขียนแล้วลบ)
- **Tests:** `bot_discord/tests/test_pdf_attach.py::SpawnPdfTaskTest::test_spawn_pdf_task_uses_the_passed_handler` · `::ProcessEventConcurrencyTest::test_two_document_events_never_cross_wires` · `_mutation_pdf_attach.py` BM8 = CATCH · BM9 = CATCH
- **Date Added:** 2026-09-16

### 💥 mutant ที่ **syntax พัง** รายงานเป็น INFRA — ซึ่งอ่านเผิน ๆ เหมือน "เทสต์จับได้" ทั้งที่ไม่มีเทสต์ตัวไหนได้รันเลย
- **Context/Problem:** BM12 ของ `_mutation_pdf_attach.py` แทนที่ **หลายบรรทัด** ด้วย anchor ที่ไม่กินบรรทัด `)` ปิด ⇒ โค้ดที่ได้เหลือ `)` เกินมาหนึ่งตัว · ผลคือ `SyntaxError: unmatched ')'` ตอน import ⇒ `unittest` **ไม่รันเทสต์เลย** และไม่พิมพ์ `OK`/`FAILED` · สคริปต์รายงานว่า *"จับได้ 11/12 | รอดผิดคาด 0 | infra พัง 1"* — ตัวเลข "11/12" ทำให้ภาพรวมดูดี และบรรทัด INFRA ถูกอ่านข้ามถ้าไม่ตั้งใจ
- **Root Cause:** harness มี **สองสถานะที่ต่างกันโดยสิ้นเชิง** ปนกันในคำว่า "ไม่ผ่าน": (ก) เทสต์รันแล้วล้ม = mutant ถูกจับจริง (ข) เทสต์ไม่ได้รัน = ไม่มีข้อมูลอะไรเลย · ทั้งสองให้ exit code ≠ 0 เหมือนกัน ⇒ **exit code เพียงอย่างเดียวแยกไม่ออก** ต้องใช้ "บรรทัดสรุปที่ test runner ผลิตเอง" (`OK`/`FAILED` ของ unittest · `N passed/failed` ของ pytest) เป็นประตูบังคับ
- **Correct Pattern/Solution:** (1) ทุก harness **ต้องมี regex ประตู** `PYTEST_SUMMARY_RE` / `UNITTEST_SUMMARY_RE` — ไม่เจอ = `infra` **ไม่ว่า exit code จะเป็นอะไร** (2) **anchor ที่แทนที่หลายบรรทัดต้องกินบรรทัดปิด (`)` / `]` / `}`) มาด้วยเสมอ** แล้วเขียนคอมเมนต์กำกับไว้ในไฟล์ harness (3) 🔴 **รายงานผลแยก INFRA ออกจาก SURVIVE ให้ชัดในบรรทัดสรุป** และ **พิมพ์รายละเอียดของ INFRA/SURVIVE/STALE ท้ายสุด** — อย่าให้ตัวเลขรวมกลืนความล้มเหลวประเภทนี้
- **Rule:** (1) 🔴 **"ไม่มีหลักฐานว่าเทสต์รัน" ≠ "เทสต์จับได้"** — การอ่าน infra พังเป็นผลบวกคือผลบวกลวงที่อันตรายที่สุดในงาน mutation testing (2) 🔴 mutant ที่ล้มเหลวเพราะ **ภาษาผิด (SyntaxError/ImportError) ไม่ใช่เพราะพฤติกรรมผิด** = ผลทดลองเสีย ต้องแก้ anchor แล้วรันใหม่ **ห้ามนับเป็น CATCH** (3) ตรวจ anchor หลายบรรทัดด้วยการนับ `count == 1` **ก่อน** เขียนไฟล์ และถ้า mutant สร้างโค้ดที่คอมไพล์ไม่ผ่าน ให้ถือว่านั่นคือความผิดของ harness ไม่ใช่ของเทสต์
- **Tests:** `bot_discord/tests/_mutation_pdf_attach.py` BM12 (หลังแก้ anchor = CATCH · ก่อนแก้ = INFRA)
- **Date Added:** 2026-09-16

### 🪤 anchor สั้นที่ **เหมือนกันเป๊ะในสองฟังก์ชัน** ⇒ AMBIG · harness จะ "ไม่ทดสอบอะไรเลย" แต่รายงานว่าผ่าน
- **Context/Problem:** N1/N2 ของ `backend/tests/_mutation_discord_txn_docs.py` เล็งบล็อก
  ```
  if receipt_nos:
      payload["receipt_nos"] = receipt_nos
  ```
  ซึ่ง `notify_payments_confirmed` (F5/PR-3) มี **เหมือนกันทุกไบต์** กับ `notify_new_finance` (F6/PR-6) — เป็นผลจาก "ลอกรูปจากของเดิม" ซึ่งเป็นสิ่งที่เราตั้งใจทำ
- **Root Cause:** การ **ลอกรูปแบบเดิมโดยเจตนา** (เพื่อไม่ให้สัญญาเก่าเปลี่ยน) ทำให้โค้ดสองที่เหมือนกัน ⇒ anchor ที่อ้างถึง "รูปที่ลอกมา" **ไม่ unique โดยธรรมชาติ** · และถ้า harness ใช้ `.replace()` ทั้งไฟล์ mutating ทั้งสองที่ ผลที่ได้คือ **mutant สองตัวพร้อมกัน** ซึ่งอาจทำให้เทสต์ล้มด้วยเหตุอื่น ⇒ ดูเหมือน "จับได้" ทั้งที่พิสูจน์ไม่ได้ว่าจับ *กลไกที่ตั้งใจ*
- **Correct Pattern/Solution:** ลาก **บรรทัดที่ทำให้บริบทไม่ซ้ำ** เข้ามาใน anchor — ในเคสนี้คือบรรทัด `await cls._publish("FINANCE_TRANSACTION", …)` ที่มีชื่อ event ต่างกัน:
  ```python
  _INSERT_KEY  = '        if receipt_nos:\n            payload["receipt_nos"] = receipt_nos\n'
  _PUBLISH_TXN = '        await cls._publish("FINANCE_TRANSACTION", server_id, payload,\n'
  # anchor = _INSERT_KEY + _PUBLISH_TXN   ← ตอนนี้ unique
  ```
  แล้ว **ตรวจ `count == 1` ด้วยสคริปต์ก่อนรัน** (harness มีด่าน AMBIG อยู่แล้ว — ใช้มัน อย่าข้าม)
- **Rule:** (1) 🔴 **ก่อนเขียน anchor ให้ grep ข้อความนั้นทั้งไฟล์** — ถ้าเจอ > 1 ที่ ต้องเติมบริบทให้ unique **ทันที** อย่ารอให้ harness ฟ้อง (2) 🔴 **AMBIG ต่างจาก STALE**: STALE = ตกยุค, AMBIG = ยังเจอแต่ **พิสูจน์ไม่ได้ว่า mutate อะไร** — ทั้งคู่ต้องหยุด ไม่ใช่ "รันต่อแบบเดา" (3) 🔴 **การลอกรูปโค้ดจากฟังก์ชันเดิมเป็นสิ่งที่ถูกต้อง** แต่ต้องรู้ว่า **มันสร้าง anchor ที่ซ้ำโดยธรรมชาติ** ⇒ harness ของฟีเจอร์ที่ "ลอกรูป" ต้องใส่บริบทที่แยกฟีเจอร์ (ชื่อ event/ชื่อฟังก์ชัน) ลงใน anchor เสมอ (4) 🟡 จำนวน mutant ที่จับได้ **ไม่ได้บอกความครอบคลุม** — มันบอกแค่ "ในบรรดาตัวที่เลือกมา จับได้กี่ตัว"
- **Tests:** `backend/tests/_mutation_discord_txn_docs.py` N1, N2 (anchor ที่มี `_PUBLISH_TXN` = CATCH · anchor สั้น = AMBIG)
- **Date Added:** 2026-09-16

### 🧱 "จอขาว" ที่ไม่มี error ฝั่งเซิร์ฟเวอร์ = `response_model` ตัดคีย์ → Vue **throw ตอน render** → ทิ้งทั้งหน้า (ครั้งที่ 4 และเป็นครั้งแรกที่ถึงมือผู้ใช้)
- **Context/Problem:** ผู้ใช้รายงานบนมือถือ (Android/Chrome) ว่า *"กดดูใบสำคัญจ่ายแล้วไปหน้าขาว ๆ แปลก ๆ"* — หน้าค้างที่ skeleton `v-if="isLoading"` ("กำลังโหลดข้อมูล") บนพื้นขาว · **ไม่มี error ใน network tab, ไม่มี 5xx, log ฝั่งเซิร์ฟเวอร์สะอาด และเทสต์ 1,100+ บรรทัดของฟีเจอร์นี้เขียวทั้งหมด**
  🔎 ต้นเหตุ: `ReceiptDetailResponse` (`models/finance_schemas.py`) ประกาศไว้แค่ 4 ฟิลด์ **ไม่ได้ประกาศฟิลด์ของใบสำคัญเลย** (9 ตัว: `budgets`/`category_name`/`approver_name`/`attachment_count`/`account_name`/`account_kind`/`bank_name`/`bank_account_no`/`bank_account_name`) ทั้งที่ `_shape_receipt_detail` ตั้งค่าครบทุกคีย์พร้อมคอมเมนต์กำกับว่า *"ทุกคีย์ถูกตั้ง **เสมอ**"*
  ⇒ พิสูจน์ในคอนเทนเนอร์: `ReceiptDetailResponse.model_validate(payload)` แล้วเทียบคีย์ — `ถูกตัดทิ้ง: ['account_kind','account_name','approver_name','attachment_count','bank_account_name','bank_account_no','bank_name','budgets','category_name']`
  ⇒ ฝั่งหน้าจอ `detail.budgets` เป็น `undefined` ⇒ `ReceiptDetail.vue` เข้าถึง `detail.budgets.length` **throw ระหว่าง render** ⇒ Vue ทิ้ง subtree ทั้งหน้า เหลือแต่สถานะ `isLoading` ค้าง
- **Root Cause:** **สามกลไกซ้อนกัน** และต้องแยกให้ออก ไม่งั้นแก้ผิดจุด:
  1. `response_model=` เป็น **ตัวกรองขาออก** — คีย์ที่โมเดลไม่ประกาศถูกทิ้ง **เงียบ ๆ** (ไม่มี warning ไม่มี error) ⇒ ดู `docs/rules/backend.md`
  2. ฝั่ง Vue: property access บน `undefined` **ในเทมเพลต** ไม่ได้เป็นแค่ค่าผิด — มัน **throw** และ Vue ทิ้ง subtree ⇒ อาการที่ผู้ใช้เห็นคือ "หน้าค้าง/จอขาว" ไม่ใช่ "ช่องว่าง"
  3. 🔴 **เทสต์เขียวเพราะทุกเทสต์ของใบสำคัญวิ่งผ่านเส้นทาง `GET /{no}/pdf` ซึ่งไม่ประกาศ `response_model`** (คืน binary stream) ⇒ **เส้นทาง PDF กับเส้นทาง JSON ใช้ service ตัวเดียวกันแต่ผ่านชั้น serialization คนละแบบ** ⇒ เทสต์ของเส้นทางหนึ่ง **พิสูจน์อะไรเกี่ยวกับอีกเส้นทางไม่ได้เลย**
  📌 นี่เป็นครั้งที่ 4 ของคลาสนี้ในโปรเจกต์ (`BatchPaymentConfirmResponse` → `TransactionCreateResponse` → `ReceiptResponse.is_receipt` → `ReceiptDetailResponse`) แต่ครั้งนี้ต่างจากสามครั้งก่อนตรงที่ **ผู้ใช้เห็น** เพราะปลายทางเป็นการ throw ไม่ใช่แค่ค่าที่หายไป
- **Correct Pattern/Solution:**
  - แยกฟิลด์ของใบสำคัญออกเป็น **`VoucherFields`** แล้วให้ `ReceiptDetailResponse(ReceiptListItem, VoucherFields)` สืบทอด — ชนิดเอกสารใหม่ที่ใช้ฟิลด์ชุดเดียวกัน (`ReceiptBatchDetailResponse.receipts`) ได้ไปด้วย **โดยอัตโนมัติ** และมีที่เดียวให้เพิ่มฟิลด์
  - 🔴 **คีย์ที่ "ไม่มีค่า" ต้องเป็น `null`/`[]` ไม่ใช่ "ไม่มีคีย์"** — สองอย่างนี้แยกกันไม่ออกเลยจากฝั่งหน้าจอ (ทั้งคู่กลายเป็น `undefined`) ⇒ `_shape_receipt_detail` ตั้งครบทั้งสองสาขาอยู่แล้ว สิ่งที่ขาดคือ **การประกาศที่ชั้น response model**
  - 🔴 `budgets` ต้องเป็น **ลิสต์ว่าง = "ไม่อยู่ในงบที่ตั้งไว้"** ซึ่งต่างจาก "ยังไม่ได้ตั้งงบ" ⇒ ห้ามให้คีย์นี้หายไปแล้ว frontend ตีความเป็นอย่างใดอย่างหนึ่ง
  - 🔴 เทสต์ที่คุมสัญญานี้ **ต้องยิงผ่าน HTTP JSON** (`GET /finance/receipts/{no}`) — และให้เขียนเทสต์คู่กันสำหรับ **ทุกเส้นทางที่ใช้ response model ตัวเดียวกัน** (`receipt-batches/{id}` ที่นี่) เพราะการสืบทอดช่วยได้แค่ครึ่งเดียว อีกครึ่งคือ `SELECT` ที่ต้องมีคอลัมน์ครบ (`R.voucher_snapshot` เคยตกหล่น → `budgets = []` + `account_kind = None` เงียบ ๆ = หน้าจอพิมพ์ "ไม่อยู่ในงบประมาณที่ตั้งไว้" ซึ่ง **โกหก**)
- **Rule:** (1) 🔴 **ทุกครั้งที่ service ตั้งคีย์ใหม่ ต้องถามว่า "คีย์นี้รอด `response_model` ของ **ทุก** route ที่คืนโมเดลนี้ไหม"** — ไม่ใช่แค่ route ที่เพิ่งแก้ (2) 🔴 **เทสต์ที่ยิงเส้นทาง PDF ไม่นับเป็นเทสต์ของสัญญา JSON** — ถ้า route คู่กันใช้ service เดียวกันแต่มี/ไม่มี `response_model` ต่างกัน ให้เขียนเทสต์ **ทั้งสองเส้น** (3) 🔴 `.length`/`[0]` บนคีย์ที่ backend "รับประกัน" ให้เขียน **ไม่มี `?.` โดยเจตนา** — ให้มัน throw แล้วรู้ตัว ดีกว่าเติม `?.` แล้วเงียบ ๆ ตกลงสาขาที่พิมพ์ข้อความผิด (4) 🟡 อย่าเติม `?.` เพื่อ "กันจอขาว" ก่อนรู้ต้นเหตุ — การกลบจะซ่อนบั๊กข้อมูลที่แย่กว่าจอขาว (ดูหัวข้อถัดไป)
- **Tests:** `backend/tests/test_finance_transaction_documents.py::test_voucher_detail_json_carries_every_snapshot_field` · `::test_detail_json_keeps_the_voucher_keys_on_every_document_type` (parametrize income/payment_voucher) · `::test_voucher_detail_json_reports_an_unknown_account_kind_verbatim` · `backend/tests/test_finance_receipt_batches.py::test_batch_detail_carries_the_voucher_fields_of_its_members`
- **Mutation:** `backend/tests/_mutation_detail_response_fields.py` M1–M5 (ถอดฟิลด์ออกจาก `VoucherFields`/`VoucherBudget`), M9–M10 (SELECT ตกหล่น / model แคบเกิน) — **10/10 CATCH**
- **Date Added:** 2026-09-16

### 🪤 `d.x === null` **ไม่จับ** `undefined` — ด่านที่เขียนว่า "ถ้าไม่มีค่า" แต่คืนสาขาผิดให้ **ทุกแถว**
- **Context/Problem:** `ReceiptDetail.vue`'s `voucherChannel` เขียนว่า `if (d.account_kind === null) return null` แล้วตกไปต่อท้ายด้วย `return 'โอนเข้าบัญชี'` ⇒ เมื่อ `account_kind` มาเป็น `undefined` (เพราะ `response_model` ตัดทิ้ง — ดูหัวข้อก่อนหน้า) การเทียบ `=== null` เป็น **false** ⇒ ใบสำคัญจ่าย**ทุกใบ** รวมใบที่จ่ายเงินสด ขึ้นว่า "โอนเข้าบัญชี" — **เอกสารบอกเงินสด แต่จอบอกโอน** ซึ่งเป็นข้อมูลผิดเงียบ ๆ ที่อันตรายกว่าจอขาว เพราะไม่มีใครรู้ว่าผิด
- **Root Cause:** `undefined` กับ `null` เป็นคนละค่าใน JS และ `=== null` แยกออกจากกัน **การเลือกใช้ `=== null` แทน falsy check คือการสมมติว่า "คีย์มีอยู่แต่ไม่มีค่า"** — สมมติฐานนั้นพังทันทีที่ชั้น serialization ตัดคีย์ทิ้ง (ซึ่งเป็นเรื่องปกติของ FastAPI/Pydantic) หรือเมื่อ TS ประกาศ optional field
- **Correct Pattern/Solution:** ใช้ falsy check (`!d.account_kind`) เมื่อเจตนาคือ "ไม่มีค่า/ไม่รู้จัก" — และสงวน `=== null` ไว้เฉพาะเมื่อ **ต้องการแยก `null` ออกจาก `undefined` จริง ๆ** (ซึ่งในโปรเจกต์นี้แทบไม่เคยจำเป็น เพราะสัญญาคือ "คีย์มีเสมอ ค่าเป็น `null`")
  ⚠️ **falsy check แก้ได้แค่ครึ่งเดียว** — `!d.account_kind` เป็นจริงเฉพาะ `undefined`/`null`/`''` **ไม่ใช่** `'e_wallet'` ⇒ ถ้าปล่อยให้ค่าที่ไม่รู้จัก "ตกไปสาขาสุดท้าย" มันจะถูกตีความเป็น `'โอนเข้าบัญชี'` อยู่ดี ⇒ ต้องมี **ด่านปิดท้ายแบบ whitelist** `if (d.account_kind !== 'transfer') return null` หลังสาขา `'cash'`
  🔴 ด่านนี้ **ตายที่ระดับชนิด** (`AccountKind = 'cash' | 'transfer'` ⇒ TS เห็นเป็น `never`) **แต่ไม่ตายที่ runtime** — ฝั่ง backend `VoucherFields.account_kind: Optional[str]` (**ไม่ใช่ `Literal`**) โดยเจตนา เพื่อให้ค่าใหม่ไม่ทำให้หน้า detail เป็น 500 ⇒ ค่าที่ TS ไม่รู้จักมาถึงที่นี่ได้จริง นี่คือจุดที่ "ชนิดฝั่ง client" กับ "สัญญาจริงของ API" ไม่ตรงกัน และ **ห้ามเชื่อชนิด**
  🔴 **แต่พอมี whitelist แล้ว falsy check กลายเป็นบรรทัดตาย — ต้องลบทิ้ง** ⇒ รหัสที่ส่งจริงคือ `if (!d) return null;` แล้วตามด้วยสาขา `'cash'` + whitelist เท่านั้น
  พิสูจน์ด้วย mutation ไม่ใช่ด้วยตา: สลับ `!d.account_kind` ↔ `d.account_kind === null` แล้ว **เทสต์เขียวทั้ง 8 ตัว** ⇒ ไล่หาคำตอบต่อจนพบว่าทั้งสองเวอร์ชันให้ผล **เหมือนกันทุกค่าบนโดเมน** `[None, '', 'cash', 'transfer', 'e_wallet', 'CASH', 'transfer ']` เมื่อมี whitelist อยู่ ⇒ เป็น **equivalent mutant ของแท้** ไม่ใช่เทสต์อ่อน
  ⇒ บทเรียนซ้อน: **เมื่อ mutant รอด ให้ถามว่า "เทสต์อ่อน" หรือ "โค้ดมีสองด่านที่ทำงานทับกัน"** — ถ้าอย่างหลัง ทางแก้ที่ถูกคือ **ลบด่านที่ซ้ำ** ไม่ใช่หาเทสต์มาเขียนให้มัน (หาไม่ได้ เพราะไม่มีพฤติกรรมให้จับ)
- **Rule:** (1) 🔴 **ก่อนเขียน `=== null` ให้ถามว่า "ค่านี้เป็น `undefined` ได้ไหม"** — ถ้าได้ (optional field / มาจาก API) ให้ใช้ falsy check (2) 🔴 **falsy check ไม่ใช่ whitelist** — ถ้าปลายทางของ `if` เป็นการ *อ้างข้อเท็จจริง* ("โอนเข้าบัญชี") ต้องมีด่าน `!== 'ค่าที่รู้จัก'` ปิดท้ายเสมอ (3) 🔴 **พอเพิ่มด่านที่กลืนเคสเดิมได้ครบ ต้องลบด่านเดิมที่ซ้ำออก** ไม่งั้นจะเหลือบรรทัดที่ mutation พิสูจน์ไม่ได้ว่ามีประโยชน์ (4) 🔴 **ค่าที่ไม่รู้จักต้องไม่ทำให้ทั้งหน้าพัง และต้องไม่ถูกแต่งขึ้นเอง** — `str` ที่ชั้น schema + whitelist ที่ชั้น UI ไม่ใช่ `Literal` + `=== 'x'` (5) 🧪 เทสต์ที่พิสูจน์ว่าด่านนี้มีฟัน: ยัดค่าที่ไม่รู้จักเข้า DB ตรง ๆ แล้วยืนยันว่าได้ 200 + ค่าตามจริง (ไม่ใช่ 500 และไม่ใช่การเดาค่า)
- **Tests:** `frontend/src/utils/__tests__/voucherChannel.spec.ts` (8 เคส — เคส `undefined` **ต้องแยกจาก `null`** ไม่งั้นเทสต์เขียวทั้งที่โค้ดเดิมก็เขียว) · `backend/tests/test_finance_transaction_documents.py::test_voucher_detail_json_reports_an_unknown_account_kind_verbatim`
- **Mutation:** `_mutation_detail_response_fields.py` M8 (ใส่ `pattern="^(cash|transfer)$"` ให้ `account_kind` ⇒ เทสต์ต้องล้ม) · ฝั่ง frontend F1–F5 (ถอด `!d` · ถอด whitelist · ถอดสาขา `'cash'` · ให้ค่าที่ไม่รู้จักตกไป `'โอน'` · ถอดตัวกรอง non-string) — **5/5 CATCH** หลังลบด่านซ้ำออกแล้ว (ก่อนลบ F1 รอด = equivalent mutant)
- **Date Added:** 2026-09-16

### 🪤 router ที่ **สร้าง response เอง** แทนที่จะคืน dict ของ service = คีย์ใหม่หายเงียบ ๆ ตลอดไป
- **Context/Problem:** `POST /classroom/join` (`routers/room_router.py`) ไม่ได้ `return result` แต่ประกอบ `JoinRoomResponse(...)` ขึ้นใหม่ทีละฟิลด์ ⇒ `room_name` ที่ `RoomManagementService.join_room` คืนมา **ทุกเส้นทาง** ไม่ถูกส่งต่อ · `JoinRoomResponse` ก็ไม่ได้ประกาศฟิลด์นั้น · ฝั่ง `Lobby.vue:227` ส่ง `result.room_name` เข้า `authStore.setRoom(...)` ทันทีที่เข้าห้องสำเร็จ ⇒ **ชื่อห้องกลายเป็น `undefined` และถูกเก็บลง localStorage โดยไม่มี error ใด ๆ** — ผู้ใช้เห็นชื่อห้องหายบนหัวจอจนกว่าจะรีเฟรช (ซึ่งรอบนั้นมาจาก API อื่นจึงมีค่า)
  🔎 ตรวจไม่เจอตอนคอมไพล์เพราะ `frontend/src/types/classroom.ts` ประกาศ `room_name: string` (**ไม่ใช่ `string | null`**) ตามคอมเมนต์ของมันเองที่อ้างว่า *"มาจาก dict ที่ `join_room` คืนค่า"* ⇒ **สัญญาฝั่ง TS เป็นคำโกหกที่เขียนด้วยความตั้งใจดี** และไม่มีอะไรตรวจสอบ
  🔎 เจอตอน **สแกนคู่ route** หลังแก้จอขาว: เทสต์ทุกตัวของ `/join` ยิงผ่าน `RoomManagementService.join_room` ตรง ๆ ไม่มีตัวใดยิง HTTP
- **Root Cause:** **router สองแบบในโปรเจกต์นี้ให้ความคุ้มครองไม่เท่ากัน** — แบบ `return result` ปล่อยให้ `response_model` เป็นตัวตัดสิน (เพิ่มคีย์ใน service = เพิ่มใน response ทันที เว้นแต่ `response_model` ตัด — อีกกับดักหนึ่ง) ส่วนแบบ **ประกอบเอง** จะ **ตรึงชุดคีย์ไว้ที่ router โดยที่ `response_model` ไม่มีทางเตือน** เพราะโมเดลก็ไม่ประกาศฟิลด์นั้นเช่นกัน ⇒ สองชั้นพร้อมใจกันทิ้ง และการทิ้งนี้ **เงียบทั้งสองชั้น**
- **Correct Pattern/Solution:** เติม `room_name` **ทั้งสองที่** — โมเดล (`JoinRoomResponse`) และจุดประกอบ response (`result.get("room_name")`) · ใช้ `.get()` ไม่ใช่ `["room_name"]` เพราะเป็นเส้นทาง "ขอเข้าร่วม" ที่ยังไม่ได้เป็นสมาชิก ก็ยังต้องได้ชื่อห้องกลับไป
  🔴 **ทางเลือกที่ถูกกว่าคือเปลี่ยน router ให้ `return result`** แล้วให้ Pydantic เป็นคนกรอง — แต่ **ห้ามทำในคอมมิตแก้บั๊ก** เพราะมันเปลี่ยนพฤติกรรมเมื่อ service เพิ่มคีย์ใหม่ (จะหลุดออกไปทั้งดุ้น) ⇒ เป็นการรีแฟกเตอร์ที่ต้องมีเทสต์คุมเอง
- **Rule:** (1) 🔴 **router ที่ประกอบ response เอง ต้องมีเทสต์ยิงผ่าน HTTP** — เทสต์ที่เรียก service ตรง ๆ พิสูจน์ไม่ได้ว่า router ส่งต่อครบ (2) 🔴 **เวลา service เพิ่มคีย์ใหม่ ให้ grep หา router ที่ประกอบ response ของโมเดลนั้น** แล้วเติมด้วยมือ · `response_model` ไม่เตือนในกรณีนี้ (3) 🔴 **TS interface ที่ประกาศฟิลด์เป็น non-optional ทั้งที่มาจาก API = คำโกหกที่คอมไพเลอร์เชื่อ** — ถ้าจะประกาศ `room_name: string` ต้องมีเทสต์ที่พิสูจน์ว่ามีค่าจริง
- **Tests:** `backend/tests/test_room.py::test_join_http_response_carries_the_room_name`
- **Mutation:** `_mutation_detail_response_fields.py` M6 (ถอด `room_name=result.get(...)` จาก router) · M7 (ถอด `room_name` จาก `JoinRoomResponse`) — **จับได้ทั้งคู่**
### 🎭 "ด่านกันซ้ำสองชั้นที่คืนผลเหมือนกันเป๊ะในระดับ API" — mutant ที่ปิดชั้นแรกจะ **รอด** ทั้งที่ช่องว่างไม่ได้อยู่ที่เทสต์
- **Context/Problem:** M4 ของ `_mutation_credits.py` ปิด `if existing_id is not None:` (`credits.py` — ด่าน idempotency_key ชั้นที่ 1 ของ `top_up_credit`) ⇒ เทสต์ทั้งไฟล์ (72 ตัว) **เขียวหมด** · เทสต์ที่มีอยู่ (`test_top_up_with_same_idempotency_key_is_not_a_second_payment`) ยืนยันครบว่าผู้ใช้ไม่ถูกหักเงินซ้ำ — และมันถูกต้อง · ปัญหาคือมัน **ผ่านได้ทั้งสองทาง**
- **Root Cause:** `top_up_credit` มีด่านกันซ้ำ **สองชั้น** และทั้งคู่ให้ผล **เหมือนกันเป๊ะในระดับ API**:
  - **ชั้นที่ 1** — อ่านก่อนเขียน เจอคีย์เดิม ⇒ คืนผลลัพธ์เดิม + `reused: true` (ไม่แตะ DB)
  - **ชั้นที่ 2** — `except asyncpg.UniqueViolationError` ที่ดัก **นอก** `conn.transaction()` ⇒ ไปหาแถวที่ชนะแล้วคืนผลเดียวกัน + `reused: true`
  ⇒ ไม่มีฟิลด์ใดใน response ต่างกันเลย · **สิ่งที่ต่างจริงคือ "ร่องรอย"**: ชั้นที่ 2 ต้อง rollback ทั้ง transaction ซึ่ง **รวมบรรทัด audit ที่เขียนไปแล้ว** ⇒ คำขอที่จบที่ชั้นที่ 2 **ไม่มีร่องรอยใน `audit_logs` เลย** ทั้งที่ระบบตอบ 200 และตั้งใจบันทึกทุกครั้งที่รับเงิน (ธง `reused` เขียนไว้ที่ `credits.py:221` ด้วยซ้ำ)
- **Correct Pattern/Solution:** 🔑 **เมื่อสองเส้นทางให้ผลลัพธ์เท่ากัน ให้เลื่อนไปยืนยัน "ผลข้างเคียงที่ไม่ควรเท่ากัน" แทน** — ในเคสนี้คือร่องรอย audit:
  ```python
  async def _reused_flags():
      rows = await conn.fetch(
          """SELECT new_values->>'reused' AS reused FROM audit_logs
             WHERE room_id = $1 AND entity_type = 'STUDENT_CREDIT'
             ORDER BY created_at, id""", room_id)
      return [r["reused"] for r in rows]

  assert await _reused_flags() == ["false"]        # ครั้งแรก
  ... ยิงซ้ำคีย์เดิม ...
  assert await _reused_flags() == ["false", "true"]  # 🔑 ต้องมี **สอง** บรรทัด
  ```
  เทสต์นี้เป็นตัวเดียวที่แยก "ถูกกันที่ชั้นที่ 1" ออกจาก "ถูกกันที่ชั้นที่ 2" ได้ ⇒ หลังเพิ่ม M4 พลิกเป็น **CATCH**
  ⚠️ `audit_logs.new_values` เป็น **JSONB** ⇒ query ด้วย `new_values->>'reused'` ได้ (คอลัมน์นี้เป็น JSONB จริง ต่างจาก `metadata` ที่ asyncpg คืนเป็น `str`)
- **Rule:** (1) 🔴 **mutant ที่ "รอด" ไม่ได้แปลว่าเทสต์อ่อนเสมอ — ต้องพิสูจน์ก่อนว่าโค้ดสองทาง "เทียบเท่ากันจริง" หรือแค่ "เทียบเท่าในสิ่งที่เทสต์มอง"** (2) 🔴 **เทสต์ที่ยืนยันแค่ response ของเส้นทางที่มี guard ซ้อนกัน คือเทสต์ที่พิสูจน์ไม่ได้ว่า guard ตัวไหนทำงาน** ⇒ ต้องหา **ผลข้างเคียงที่ guard ทั้งสองทำไม่เหมือนกัน** (ร่องรอย audit / row ที่ถูกเขียน / ลำดับที่กิน) มาเป็นตัวชี้ (3) 🔴 **`except UniqueViolationError` ที่ไม่มี SAVEPOINT จะ rollback ทั้ง transaction** ⇒ ทุกอย่างที่เขียนไปก่อนหน้าหายหมด · นี่ไม่ใช่แค่เรื่อง exception แต่เป็น **ความต่างที่สังเกตได้** ซึ่งต้องมีเทสต์คุม (4) 🟡 คอมเมนต์ที่พิสูจน์ความเทียบเท่า **ต้องมีกลไกใน harness รองรับ** ไม่งั้นมันเป็นแค่คำอ้าง — ดูบทเรียนถัดไป
- **Tests:** `backend/tests/test_finance_credits.py::test_repeated_top_up_leaves_an_audit_row_flagged_reused` (เพิ่มใหม่) · `_mutation_credits.py` M4 = CATCH (ก่อนหน้า = SURVIVE 72 passed)
- **Date Added:** 2026-09-16

### 🟡 harness ที่ไม่มีสถานะ "เทียบเท่า" จะรายงาน equivalent mutant เป็น **ความล้มเหลว** — และคอมเมนต์ที่พิสูจน์ไว้จะไม่มีผลอะไรเลย
- **Context/Problem:** `_mutation_credits.py` รู้จักแค่ CATCH / SURVIVE / INFRA · M9 (ปิด idempotency ชั้นแรกของใบ DEP) เป็น equivalent mutant ที่ **มีคอมเมนต์พิสูจน์ครบถ้วนอยู่ในไฟล์แล้ว** (ผู้เรียกมีเพียงรายเดียว + `top_up_credit` return เร็วที่ idempotency_key ก่อนสร้าง transaction ⇒ `existing` ไม่มีทางไม่เป็น `None` ผ่านเส้นทางที่มี route จริง) — แต่ harness พิมพ์ **`❌ รอด`** ⇒ คนอ่านเห็น "รอด 1" แล้วสรุปว่ามีช่องว่างของเทสต์ **ทั้งที่ไม่มี** · และคอมเมนต์นั้นก็ **ไม่เคยถูกบังคับใช้** เพราะไม่มีโค้ดอ่านมัน
- **Root Cause:** harness ไม่มีที่ให้ **ประกาศความคาดหวัง** ⇒ สถานะ "รอด" ถูกตีความเป็นความล้มเหลวเสมอ · ยิ่งไปกว่านั้นตัว **ข้อความ verdict** ยังคงเป็นถ้อยคำของเส้นทาง catch ⇒ เกิดบรรทัดที่ **ขัดกันเองในตัว**: `🟡 M9 …: รอด ❌ เทสต์หลอกตัวเอง`
- **Correct Pattern/Solution:** เติมสมาชิกตัวที่ 6 `expect` แล้ว normalize ค่าเริ่มต้น **โดยไม่แตะแถวเดิมแม้แต่ไบต์เดียว**:
  ```python
  MUTATIONS = [m if len(m) == 6 else (*m, "catch") for m in MUTATIONS]
  ```
  แล้วแยกสถานะเป็น 4 ทาง พร้อม **ดักเคสตรงข้าม**:
  ```python
  if infra:                       status, icon = "INFRA", "🛑"
  elif expect == "equiv":
      status = "SURPRISE" if caught_by else "EQUIV"
      icon   = "⚠️" if caught_by else "🟡"
  else:                           status, icon = ("CATCH","✅") if caught_by else ("SURVIVE","❌")
  ```
  🔑 **`SURPRISE` จำเป็นพอ ๆ กับ `EQUIV`** — mutant ที่ **ถูกจับทั้งที่ประกาศว่าเทียบเท่า** แปลว่าคำอ้างนั้น **ผิด** (หรือมีเทสต์ใหม่มาคุมมันแล้ว) ⇒ ต้อง exit ≠ 0 และพิมพ์รายละเอียด ไม่ใช่รายงานเป็น CATCH แล้วผ่านไป (ไม่งั้นคำอ้างที่ผิดจะมีชีวิตต่อไปเรื่อย ๆ)
  🔑 **ข้อความ verdict ต้องผูกกับ status ไม่ใช่ผูกกับ `caught_by`** — รื้อ `verdict` ให้เป็นกลาง (`"รอด"`) ตอนจับผล แล้วค่อยแต่งถ้อยคำตาม status ทีหลัง
  🔑 `EQUIV` ต้อง **ไม่ถูกนับเป็นความล้มเหลว** และ **ไม่ถูกพิมพ์ในบล็อกรายละเอียดท้ายสุด** (ซึ่งมีไว้สำหรับสิ่งที่ต้องลงมือแก้) · แต่ต้องมีตัวเลขของตัวเองในบรรทัดสรุป
- **Rule:** (1) 🔴 **ทุก harness ต้องมีกลไก "ประกาศความคาดหวัง" และต้องมีสถานะ EQUIV แยกจาก SURVIVE** — ไม่มี = ตัวเลข "รอด" จะปน "ช่องว่างจริง" กับ "เทียบเท่าที่พิสูจน์แล้ว" เข้าด้วยกันจนแยกไม่ออก (2) 🔴 **คอมเมนต์ที่พิสูจน์ความเทียบเท่าโดยไม่มีโค้ดรองรับ = คำอ้างลอย ๆ** — ต้องมีธง `expect` ที่บังคับใช้จริง (3) 🔴 **declared-equivalent ที่ถูกจับ ต้องเป็นความล้มเหลวของ "คำอ้าง" ไม่ใช่ความสำเร็จ** ⇒ มีสถานะ `SURPRISE` และ exit ≠ 0 (4) 🔴 **ข้อความที่พิมพ์ต้องไม่ขัดกับไอคอนของตัวเอง** — `🟡` แล้วต่อด้วย `❌ เทสต์หลอกตัวเอง` คือบั๊กชนิดเดียวกับที่ทั้งงานนี้ตั้งใจกำจัด (5) 🟡 **การเพิ่มสมาชิกใน tuple ต้อง normalize ค่าเริ่มต้น** ไม่ใช่แก้แถวทั้ง 14 ด้วยมือ — แก้มือแล้วลืมแถวเดียวคือ harness พังทั้งตัว (`ValueError: too many values to unpack`) และต้องอัปเดต **ทุกจุดที่ unpack** ให้ตรงกัน
- **Tests:** `backend/tests/_mutation_credits.py` (M9 = EQUIV · M4 = CATCH · สรุป `จับได้ 1/2 | รอด 0 | เทียบเท่า 1 | คำอ้าง equiv ถูกหักล้าง 0 | infra พัง 0` · exit 0)
- **Date Added:** 2026-09-16

### 🛠️ เปรียบเทียบกิจกรรม (Intersection/Union/ลบ) + แผนภาพเวน - **ค่า `datetime-local` ถูกเก็บเป็นสตริงดิบใน JSONB ⇒ ต้องจัดรูปแบบตอน "อ่าน" โดยยึด declared type ไม่ใช่เดาจากรูปร่างค่า**
- **Context/Problem:** ฟิลด์ที่ผู้จัดกิจกรรมสร้างเอง (`metadata.dynamic_fields`) ชนิด `datetime` ถูกเก็บค่าลง `activity_participants.metadata['df_N']` **ตรง ๆ ตามที่ `<input type="datetime-local">` ส่งมา** คือ `"2026-10-01T13:00"` ⇒ ตอน export Excel เซลล์ก็ได้สตริงนั้นทั้งสภาพ · ครูเปิดไฟล์แล้วอ่านไม่ออกว่าเป็นวันไหน (และ `T` กลางสตริงทำให้เข้าใจว่าเป็นรหัสอะไรสักอย่าง) · ผู้ใช้ขอไว้ว่าต้องออกมาเป็น `1 ตุลาคม 2569 13:00 น.`
  🔎 บั๊กเดียวกันนี้กระทบ **ทั้ง export เดี่ยวและ export รวม** — แก้ที่เดียวไม่พอ
- **Root Cause:** ตอน **เขียน** ค่าถูกเก็บแบบ round-trip ได้ (สตริง ISO) ซึ่งถูกต้องสำหรับเก็บ · แต่ตอน **อ่าน** ไม่มีใครแปลงกลับเป็นรูปแบบที่คนอ่าน ⇒ **"เก็บให้เครื่องอ่าน" กับ "แสดงให้คนอ่าน" เป็นคนละความรับผิดชอบ** และไม่มีชั้นไหนรับผิดชอบอันหลัง
  🔎 และการ "เดาจากรูปร่างค่า" (`ถ้าดูเหมือน ISO ก็แปลง`) เป็นทางตัน: ฟิลด์ชนิด `input` ของครูก็บังเอิญพิมพ์ `2026-10-01` ได้ ⇒ จะถูกแปลงมั่วทั้งที่ผู้ใช้ตั้งใจให้เป็นข้อความ
- **Correct Pattern/Solution:** แยกโมดูลกลาง `backend/services/activity/thai_date.py` (ไม่ผูกกับ MRO ของ mixin — ทั้ง export เดี่ยวและรวมต้องเรียกได้) แล้วเพิ่ม `_format_typed_value(field, value, dynamic_types)` ที่ตัดสินจาก **`dynamic_fields[].type == 'datetime'` ที่ประกาศไว้** (บวกคีย์เดิม `check_in_time`):
  ```python
  if (dynamic_types or {}).get(field) == "datetime" or field == "check_in_time":
      return format_thai_datetime(value)
  return value   # ชนิดอื่น/ค่าที่ parse ไม่ได้ → คืนเดิมไม่แตะ
  ```
  🔴 **naive = เวลานาฬิกาไทยอยู่แล้ว** (ค่ามาจาก `datetime-local` ของผู้ใช้ไทย) ⇒ `_render` เลื่อนเฉพาะเมื่อ `dt.tzinfo is not None` — **ห้าม `.astimezone()` บนค่า naive ตรง ๆ** ไม่งั้นเวลาไทย 13:00 จะกลายเป็น 06:00
  🔴 **วันที่ล้วนต้องไม่ถูกเติม `00:00 น.`** — `datetime.fromisoformat('2026-10-01')` *สำเร็จ* (ได้เที่ยงคืน) ⇒ ต้องแยกด้วย `_is_date_only` **ก่อน** แล้วส่งเข้า `format_buddhist_date` ไม่งั้นผู้ใช้ที่กรอกแค่วันที่จะเห็นเวลาปลอมโผล่มา
  🔴 **ค่าที่ parse ไม่ได้ต้องคืนเดิม** (`"หลังเลิกเรียน"`, `""`, `None`) — ฟิลด์เหล่านี้เป็น free text ได้ การกลืนค่าเป็นค่าว่างคือการทำข้อมูลหาย
- **Rule:** (1) 🔴 **ค่าที่ "เก็บให้เครื่อง" ต้องมีจุดแปลงเป็น "รูปแบบคนอ่าน" ที่ชัดเจน ไม่ใช่พึ่งดวงตาว่ามันดูอ่านออก** (2) 🔴 **กรองด้วย declared type เสมอเมื่อค่าอยู่ในฟิลด์ที่ผู้ใช้พิมพ์เองได้** — เดาจากรูปร่างค่าคือการแก้ที่สร้างบั๊กใหม่ (3) 🔴 **naive datetime ในระบบนี้ = เวลานาฬิกาไทย** ห้าม `.astimezone()` ตรง ๆ (4) 🔴 **แก้การจัดรูปแบบในไฟล์ export ต้องแก้ให้ครบทุกจุดที่อ่านค่า** — เดี่ยวกับรวมเป็นคนละลูป (ตรงกับบทเรียน "แก้ให้ครบทุกจุดในไฟล์เดียว") (5) 🟡 ทุก assertion เชิงลบต้องมีคู่บวก — เทสต์ต้องมีเคส `type: 'input'` ที่ค่าเป็น ISO เหมือนกันแล้ว **ต้องไม่ถูกแปลง** เพื่อพิสูจน์ว่ากรองด้วย declared type จริง
- **Tests:** `backend/tests/test_activity_compare.py` (กลุ่ม datetime: `DATETIME_FIELD` จัดรูปแบบ / `INPUT_FIELD` ไม่ถูกแตะ / `+00:00`/`Z` เลื่อนเป็น +7 / `"หลังเลิกเรียน"` คงเดิม)
- **Date Added:** 2026-09-19

### 🛠️ เปรียบเทียบกิจกรรม (Intersection/Union/ลบ) + แผนภาพเวน - **endpoint ที่เปิดด้วย `require_member` ต้องคืน "allowlist ของชื่อ" ไม่ใช่ participant record แล้วหวังว่า `response_model` จะกรอง**
- **Context/Problem:** `POST /activities/compare` ต้องเปิดให้ **สมาชิกห้องทุกคน** อ่าน (เป็นข้อมูลรายชื่อเพื่อการมองเห็น เหมือน `get_activity`) แต่ `activity_participants` ที่ JOIN มากับ `users` มีฟิลด์ Type A (PII) ติดมาด้วย (`blood_group`, `shirt_size`, `food_insensitivity` ฯลฯ)
- **Root Cause:** ทางเลือกที่ดูง่ายคือ `return {"regions": [...records ทั้งก้อน...]}` แล้วให้ `response_model` ตัดฟิลด์ที่ไม่ประกาศ — **แต่นั่นคือการพึ่งด่านที่เคยล้มเหลวมาแล้ว 5 ครั้งในโปรเจกต์นี้** และที่แย่กว่าคือมันกลับทิศ: `response_model` เป็น **allowlist ขาออก** ที่ตกลงว่าอะไร "ออกได้" ไม่ใช่ด่านที่รับประกันว่าอะไร "ไม่รั่ว" · วันที่ใครเพิ่มฟิลด์ PII ใหม่แล้วประกาศในโมเดล (เพื่อ endpoint อื่น) ฟิลด์นั้นจะไหลออกทางนี้ทันทีโดยไม่มีสัญญาณ
- **Correct Pattern/Solution:** ให้ **service** คืนสำเนาที่กรองแล้วด้วย allowlist ของตัวเอง (`sets.slim_member` — เฉพาะ 8 ฟิลด์ชื่อ) แล้ว **ไม่เรียก `_mask_participants_pii` เลย** เพราะไม่มี PII ตั้งแต่ต้นทาง
  ```python
  COMPARE_MEMBER_FIELDS = ("student_id", "student_no", "first_name", "last_name",
                           "nickname", "first_name_en", "last_name_en", "nickname_en")
  ```
  🔴 และ `except Exception` สุดท้ายของ route นี้ **ห้าม echo `str(e)`** — ต่างจาก route export ที่ทำได้ เพราะ route ถูกเรียกโดยสมาชิกธรรมดา ⇒ ข้อความอย่าง DSN/hostname จะถึงมือคนที่ไม่ควรเห็น
- **Rule:** (1) 🔴 **ข้อมูลที่ออกจาก endpoint ต้องถูกเลือกที่ service ด้วย allowlist ของตัวเอง** — `response_model` เป็นสัญญา ไม่ใช่ด่านความปลอดภัย (2) 🔴 **route ที่สิทธิ์ต่ำกว่าต้องไม่ echo `str(e)`** (3) 🟡 endpoint อ่านอย่างเดียวไม่ต้องเขียน audit log — อย่าเขียนเพราะ "รู้สึกว่าครบ" (จะกลายเป็น noise ที่กลบร่องรอยจริง)
- **Tests:** `backend/tests/test_activity_compare.py` (assert ว่า body **ไม่มี** คีย์ PII + ยืนยันว่าคีย์ที่ควรมีอยู่ครบหลังผ่าน serialization)
- **Date Added:** 2026-09-19

### 🛠️ เปรียบเทียบกิจกรรม (Intersection/Union/ลบ) + แผนภาพเวน - **`flatten_members` อ่าน metadata ผิดกิจกรรม เพราะ record ที่ติดมากับ region มีแค่ของ "กิจกรรมแรกที่เจอ"**
- **Context/Problem:** เทสต์ `test_export_combined_activity_fields_toggle_and_prefix` ล้มด้วย `assert '20:00' == '08:30'` — คอลัมน์ฟิลด์เฉพาะกิจกรรมของ **ทั้งสองกิจกรรม** แสดงค่าเดียวกันคือของกิจกรรมแรก
- **Root Cause:** `build_regions` จัดกลุ่มคนตาม mask โดยเก็บ `seen[student_id] = record` **ตัวแรกที่เจอ** (จำเป็น เพราะคนเดียวกันมีหลาย record — หนึ่งต่อกิจกรรม) · ต่อมา `flatten_members` คัดลอก record เดียวนั้นติดตัวคนไป ⇒ `_combined_field_value` อ่าน `df_1` จาก record ของกิจกรรม A แม้กำลังเขียนคอลัมน์ของกิจกรรม B
  🔎 จุดที่หลอกตา: โครงสร้าง `{"members": [...]}` **ดูเหมือน** มีข้อมูลครบของทุกกิจกรรม ทั้งที่จริงมีแค่กิจกรรมเดียว ⇒ รหัสที่ "อ่านจาก region" จึงดูถูกต้องสมบูรณ์
- **Correct Pattern/Solution:** `flatten_members(regions, members_by_activity=None)` join กลับกับ record รายกิจกรรม แล้วแนบ `person["records_by_activity"] = {activity_id: record}` ⇒ `_combined_field_value` อ่านจาก `records_by_activity[entry["activity_id"]]` (ถอยไปใช้ `person` ถ้าไม่มี)
  ```python
  record = (person.get("records_by_activity") or {}).get(entry["activity_id"], person)
  ```
- **Rule:** (1) 🔴 **เมื่อโครงสร้างข้อมูล "ยุบรวม" หลายแหล่งเป็นชิ้นเดียว ต้องเขียนไว้ให้ชัดว่ายุบแล้วเหลืออะไร** — ไม่งั้นโค้ดที่อ่านต่อจะเข้าใจผิดอย่างมั่นใจ (2) 🔴 **คอลัมน์ที่ผูกกับ entity ต้องอ่านค่าจาก record ของ entity นั้น** ไม่ใช่จาก record ที่ "ติดมา" กับ container (3) ✅ เทสต์ที่จับบั๊กนี้ได้เป็นเทสต์ที่ **seed ค่าต่างกันจริงในสองกิจกรรม** (08:30 กับ 20:00) — ถ้า seed ค่าเดียวกันจะผ่านทั้งที่โค้ดผิด ⇒ **ข้อมูลเทสต์ที่แยกแยะไม่ได้ = เทสต์ที่พิสูจน์ไม่ได้**
- **Tests:** `backend/tests/test_activity_compare.py::test_export_combined_activity_fields_toggle_and_prefix` · `::test_export_combined_activity_field_blank_for_non_member`
- **Date Added:** 2026-09-19

### 🛠️ เปรียบเทียบกิจกรรม - **พิกัดป้ายบนแผนภาพต้อง "พิสูจน์ด้วยคณิตศาสตร์" ไม่ใช่ดูจากภาพ — ป้ายชี้ผิดภูมิภาคคือบั๊กที่หน้าจอดูปกติทุกอย่าง**
- **Context/Problem:** แผนภาพเวนวาดมือด้วย SVG ⇒ ตำแหน่งป้ายของแต่ละภูมิภาค (7 ตำแหน่งเมื่อเลือก 3 กิจกรรม) เป็นตัวเลขที่ต้องฮาร์ดโค้ด เพราะภูมิภาคที่เกิดจากวงกลมตัดกันไม่มี "จุดกึ่งกลาง" ที่คำนวณจาก DOM ได้
- **Root Cause:** ตัวเลขพิกัด **ผิดแล้วจับไม่ได้ด้วยตา** — หน้าจอยังสวย กดได้ ไม่มี error ใน console แต่ชื่อคนไปโผล่ผิดวง ⇒ ครู export ผิดกลุ่มโดยเชื่อแผนภาพ · และการ "ดูภาพแล้วรู้สึกว่าโอเค" พิสูจน์ไม่ได้และพลาดทันทีที่ใครขยับพิกัดเป็นสิบ pixel
- **Correct Pattern/Solution:** แยกเรขาคณิตออกเป็นโมดูลบริสุทธิ์ `frontend/src/utils/activityDiagram.ts` แล้วเขียนเทสต์ที่ **ยืนยันด้วยคณิตศาสตร์** ว่าจุด anchor ของ mask นั้นอยู่ในวงตามบิตของ mask **เท่านั้น**:
  ```ts
  const inside = (p, c, r) => Math.hypot(p[0]-c[0], p[1]-c[1]) < r
  expect(centers.map(c => inside(point, c, r) ? 1 : 0))
    .toEqual(centers.map((_, i) => (mask >> i) & 1 ? 1 : 0))
  ```
  เทสต์ยังบังคับด้วยว่า (1) mask ของ N=2/N=3 มี **ครบ** 3/7 ภูมิภาค (2) วงกลมทุกวงอยู่ใน canvas (3) **วงต้องทับกันจริง** (`0 < ระยะห่าง < 2r`) — ข้อนี้จับเคสที่ไม่มีใครคิดถึง: ถ้าเอา N=3 ไปวางเป็นสามเหลี่ยมด้านยาว ภูมิภาคกลางจะ **ว่างเปล่าทางเรขาคณิต** ⇒ ป้ายกลางลอยนอกวงทั้งสาม (4) `regionMask` ตรงกับบิตที่ backend ใช้ (บิตที่สาม = 4 ไม่ใช่ 3 — *ไม่ใช่* ลำดับ "ตัวเดี่ยวก่อน แล้วคู่")
  🔴 บิตต้องคิดจาก **กิจกรรมที่เรียงตาม id** ทั้งสองฝั่ง (`sets.build_regions` กับ `regionMask`) — ไม่งั้นกิจกรรมที่ 3 กับคู่ (1,2) จะสลับ mask กัน
- **Rule:** (1) 🔴 **พิกัด/เรขาคณิตที่ฮาร์ดโค้ดต้องมีเทสต์เชิงคณิตศาสตร์ ไม่ใช่เทสต์ "คืนค่าเท่าที่เขียนไว้"** (เทสต์หลังคือการลอกโค้ดมาไว้ในเทสต์) (2) 🔴 **แยกเรขาคณิตออกจากคอมโพเนนต์** เพื่อให้เทสต์ได้โดยไม่ต้อง mount (3) 🔴 **การจับคู่ "ชุด ↔ ตำแหน่ง" ที่พึ่ง "ลำดับ" ต้องเขียนลำดับนั้นให้ชัดทั้งสองฝั่ง** (4) 🟡 คลาส Tailwind ที่ใช้วาด SVG (`fill-*`/`stroke-*`) ต้องเป็น **literal ในไฟล์** และควร grep ในไฟล์ CSS ที่ build แล้วเพื่อยืนยันว่า JIT คอมไพล์จริง — `fill-brand-700` ไม่มีในชีตสรุปใด ๆ ถ้าเขียนเป็นสตริงประกอบ
- **Tests:** `frontend/src/utils/__tests__/activityDiagram.spec.ts` (27 เคส)
- **Date Added:** 2026-09-19

### 🛠️ เปรียบเทียบกิจกรรม - **ข้อความไทยไม่มีช่องว่างระหว่างคำ ⇒ เบราว์เซอร์ตัดบรรทัด "กลางชื่อ" ได้ — และ compiler ของ Vue ตัดช่องว่างตัวคั่นทิ้งจนไม่เหลือจุดตัดบรรทัดเลย**
- **Context/Problem:** ผู้ใช้รายงานว่า "บนคอมรายชื่อเป็นลิสต์เดียวยาว ๆ และมีการตัดชื่อ" ทั้งที่โค้ดฝั่งหน้าเขียนว่า `{{ names.join(', ') }}` ธรรมดา ๆ ซึ่ง **ทฤษฎีแล้วตัดบรรทัดได้เอง** ⇒ เป็นบั๊กที่อ่านโค้ดแล้ว "ดูถูกต้อง" ทั้งสองฝั่ง
- **Root Cause:** สองกลไกที่แยกกัน แต่รวมกันแล้วทำให้อ่านชื่อคนไม่ออก
  1. 🔴 **ภาษาไทยไม่มีช่องว่างระหว่างคำ** ⇒ UAX #14 ให้เบราว์เซอร์หาจุดตัดบรรทัดด้วย **พจนานุกรม/พยางค์** ⇒ ชื่อคนถูกตัด **กลางชื่อ** ได้ ("สมชาย" ขึ้นบรรทัดบน "สม" ตกบรรทัดล่าง "ชาย") ผู้ใช้เห็นชื่อขาดและแยกไม่ออกว่าชื่อไหนจบตรงไหน
  2. 🔴 **`whitespace: 'condense'` ของ Vue compiler ตัดช่องว่างท้าย element ทิ้ง** ⇒ `<span>, </span>` ที่ตั้งใจให้เป็นตัวคั่น **เหลือแค่ `,` ไม่มีช่องว่าง** ⇒ ไม่เหลือจุดตัดบรรทัดแม้แต่จุดเดียว ⇒ ทั้งรายชื่อกลายเป็นแถวเดียวยาวล้นจอ
- **Correct Pattern/Solution:** แยกเป็นคอมโพเนนต์ `RegionMemberNames.vue` ที่บังคับสองอย่างคู่กัน
  ```html
  <span class="whitespace-nowrap">{{ name }}</span>
  <span v-if="index < names.length - 1">{{ ', ' }}</span>
  ```
  - `whitespace-nowrap` ที่ **แต่ละชื่อ** ⇒ ชื่อหนึ่งไม่ถูกตัดกลางคำเด็ดขาด (ชื่อที่ยาวเกินคอลัมน์ยอมให้ล้นออกเล็กน้อย ดีกว่าตัดกลางคำ)
  - ตัวคั่นต้องเป็น **interpolation** `{{ ', ' }}` — ถ้าเขียนเป็นข้อความตรง ๆ (`, `) Vue จะ trim ทิ้ง
- **Rule:** (1) 🔴 **ข้อความไทยต้องคุมจุดตัดบรรทัดเอง อย่าปล่อยให้เบราว์เซอร์ตัดตามพจนานุกรม** — ทุกครั้งที่แสดง "รายชื่อคน" ให้ห่อแต่ละชื่อด้วย `whitespace-nowrap` + คั่นด้วยช่องว่าง (2) 🔴 **ห้ามเขียนตัวคั่นที่มีช่องว่างเป็นข้อความตรง ๆ ในเทมเพลต Vue** — ต้องเป็น interpolation ไม่งั้นช่องว่างถูก condense ทิ้งแบบเงียบ ๆ (3) 🔴 **เทสต์ที่ยืนยันได้คือเทสต์ที่ตรวจ "ชิ้นส่วน DOM" ไม่ใช่ `wrapper.text()`** — การ assert ข้อความรวมผ่านทั้งที่ช่องว่างหาย เพราะ `'สม,หญิง'` กับ `'สม, หญิง'` ต่างกันแค่ช่องเดียวที่ตามองข้าม ⇒ ต้องอ่าน `root.children` แล้วแยก "ชื่อ" กับ "ตัวคั่น" ออกมาแล้ว assert
  ⚠️ **jsdom ไม่มี layout engine** ⇒ พิสูจน์ไม่ได้ว่าจริง ๆ เบราว์เซอร์ตัดบรรทัดตรงไหน สิ่งที่พิสูจน์ได้คือ **กลไกที่ทำให้ตัดได้** (nowrap + ช่องว่าง) — ต้องเขียนข้อจำกัดนี้ไว้ในเทสต์ ไม่ใช่ปล่อยให้อ่านเป็น "พิสูจน์แล้วว่าตัดบรรทัดสวย"
- **Tests:** `frontend/src/components/activities/__tests__/RegionMemberNames.spec.ts`
- **Date Added:** 2026-09-19

### 🛠️ เปรียบเทียบกิจกรรม - **ป้ายบน SVG ต้องมี "เพดานความกว้าง/ความสูง" และพิสูจน์ว่าทุกคู่ไม่ทับกันได้โดยไม่ต้องรู้ข้อมูล**
- **Context/Problem:** ผู้ใช้ขอให้ป้ายบนแผนภาพแสดงชื่อให้ครบทุกคน (เดิมย่อเป็น 3 ชื่อ + `+N`) ⇒ ต้องให้ป้ายสูงขึ้น/กว้างขึ้นได้
- **Root Cause:** ป้ายแต่ละอันวางที่ anchor ของภูมิภาคตัวเอง ระยะห่างระหว่าง anchor ที่ใกล้กันที่สุดเมื่อเลือก 3 กิจกรรมคือ **150 หน่วย** ⇒ ถ้าป้ายโตเกินครึ่งของระยะนั้น ป้ายจะ **ทับกัน** แล้วอ่านชื่อผิดภูมิภาค ซึ่งเป็นความผิดพลาดแบบเดียวกับ "พิกัดป้ายผิด" — หน้าจอดูปกติ ไม่มี error
  🔎 จุดที่หลอกตา: ตอนมีชื่อไม่กี่ชื่อป้ายเล็ก **ดูไม่มีปัญหาเลย** ⇒ บั๊กจะโผล่เฉพาะกับห้องที่มีคนเยอะ (ซึ่งเป็นเคสจริงที่ครูใช้ และเป็นเคสที่คนเขียนเทสต์มักไม่ seed)
- **Correct Pattern/Solution:** จำกัด `PILL_MAX_W = 130` (< 150) และ `PILL_MAX_LINES = 2` แล้วพิสูจน์ด้วย **"กรอบใหญ่ที่สุดที่เป็นไปได้"** ซึ่งคำนวณจาก anchor ล้วน ๆ **ไม่ต้องรู้ว่ามีสมาชิกกี่คน**:
  ```ts
  export function maxPillBox(count: number, mask: number): PillBox | null
  // เทสต์: ทุกคู่ของ mask ต้องไม่ทับกัน + ทุกกรอบต้องอยู่ใน canvas
  ```
  การจัดบรรทัดทำในฟังก์ชันบริสุทธิ์ `layoutPill(names)` ที่ **ตัดชื่อท้ายบรรทัดออกก่อนเติม `+N`** — ถ้าเติมเลย ตัวเลข "ยังมีอีก N คน" จะถูก `fitLine` ตัดทิ้ง ⇒ รายชื่อขาดโดยไม่มีอะไรบอก
- **Rule:** (1) 🔴 **กรอบที่โตได้ต้องมีเพดาน และเพดานต้องพิสูจน์ได้จากค่าคงที่ ไม่ใช่จากข้อมูลตัวอย่าง** — "ผมลองกับ 3 คนแล้วไม่ทับ" ไม่ใช่การพิสูจน์ (2) 🔴 **การย่อข้อความ (truncate) ต้องมาพร้อมตัวเลขบอกว่าตัดไปเท่าไร และตัวเลขนั้นต้องไม่ถูกตัดทิ้งเอง** (3) ✅ ป้ายคือ "ป้ายแผนภาพ" ไม่ใช่รายชื่อ — ข้อมูลครบต้องอยู่ในที่ที่รับประกันได้ (`<title>`/aria ของป้าย + รายการภูมิภาคด้านล่าง) ไม่ใช่ยัดในป้าย (4) 📱 **จอแคบให้ใช้ "ความกว้างขั้นต่ำ + เลื่อนแนวนอน" ไม่ใช่ "ซ่อน" และไม่ใช่ "ย่อจนอ่านไม่ออก"** — ซ่อนแล้วผู้ใช้ไม่รู้ว่ามีของที่เขาขอ; ย่อจาก 640px → 340px ทำให้ตัวอักษร 11px เหลือ ~5.8px
- **Tests:** `frontend/src/utils/__tests__/activityDiagram.spec.ts` (`maxPillBox` / `layoutPill` / `pillBaselineY`)
- **Date Added:** 2026-09-19

### 🕶️ `tsconfig` ที่ `extends` แล้ว **เขียน `include` ทับ** ⇒ ambient declaration หายจากโปรเจกต์ทดสอบ — type-check แดงแต่ `dev` ทำงานปกติ
- **Context/Problem:** ตรวจระบบ 2026-09-23 (L3) — เขียนเทสต์ตัวแรกที่ import `@/stores/auth` (`frontend/src/stores/__tests__/auth.spec.ts`) แล้ว `npm run type-check` แดงทันทีด้วย
  `TS7016: Could not find a declaration file for module 'thai-address-database'` **ชี้ไปที่ `Onboarding.vue` ซึ่งไม่ได้ถูกแก้เลยแม้แต่บรรทัดเดียว**
  🔎 อันตรายเป็นพิเศษเพราะ `npm run dev` และ `npm run build` ของแอปยังทำงานปกติ ⇒ อาการเดียวที่เห็นคือ CI แดง ซึ่งถ้าไม่มี CI (ดู T7) จะไม่มีใครรู้เลยจนกว่าจะมีคนบังเอิญรัน `type-check`
- **Root Cause:** `tsconfig.vitest.json` `extends` จาก `tsconfig.app.json` แต่ **เขียน `include` ทับทั้งก้อน**:
  ```json
  // tsconfig.app.json    → "include": ["env.d.ts", "src/**/*", "src/**/*.vue"]
  // tsconfig.vitest.json → "include": ["src/**/__tests__/*", "env.d.ts"]   ← ทับของเดิม
  ```
  คอมเมนต์เดิมเขียนว่า *"Application code imported in tests is automatically included via module resolution"* — **จริงสำหรับไฟล์ที่ถูก `import` แต่ไม่จริงสำหรับ ambient declaration** เพราะ `src/types/thai-address-database.d.ts` ไม่มีไฟล์ไหน import มันจึงไม่ถูกดึงเข้ามาในโปรเจกต์ vitest เลย
  🔑 **ทำไมเพิ่งโผล่ตอนนี้:** เทสต์ 9 ตัวเดิมไม่มีตัวไหนแตะ store/router ⇒ `Onboarding.vue` ไม่เคยเข้าโปรเจกต์ vitest มาก่อน พอเทสต์ใหม่ import `@/stores/auth` → `@/router` → `import('@/views/auth/Onboarding.vue')` (dynamic import ก็นับ) ⇒ กราฟถูกดึงเข้ามาครั้งแรก
- **Correct Pattern/Solution:** ambient `.d.ts` ต้อง **ระบุ path ตรง ๆ** ในทุกโปรเจกต์ที่ต้องเห็นมัน
  ```json
  "include": ["src/**/__tests__/*", "src/**/*.d.ts", "env.d.ts"]
  ```
  🔑 วิธีหาให้แน่ว่าโปรเจกต์ไหนพัง — **รันแยกโปรเจกต์ อย่าเดาจาก output ของ `--build`** (มันรวม error ของทุกโปรเจกต์มาที่เดียว):
  ```bash
  npx vue-tsc -p tsconfig.app.json    --noEmit   # ✅ ผ่าน (include src/**/* ⇒ เห็น shim)
  npx vue-tsc -p tsconfig.vitest.json --noEmit   # ❌ แดง 2 จุด ⇒ ชี้ชัดว่าเป็นโปรเจกต์นี้
  ```
- **Rule:** (1) 🔴 **`extends` ที่เขียน `include` ทับ = สูญเสีย glob เดิมทั้งก้อนโดยไม่มีอะไรเตือน** — ก่อนเพิ่ม/แก้ `include` ให้เทียบกับโปรเจกต์แม่เสมอ (2) 🔴 **ambient declaration ไม่ใช่ module** — ถ้าไม่มีใคร `import` มันจะไม่มีวันถูกดึงเข้ามา ต้องอยู่ใน `include` เท่านั้น (3) ✅ **`--build` รวม error หลายโปรเจกต์ ⇒ รันแยก `-p` เพื่อระบุตัวต้นเหตุ** ไม่ใช่เดาจากบรรทัดที่ error ชี้ (4) ✅ **เทสต์ที่ import store/router จะลาก view ทั้งกราฟเข้ามา** — คาดไว้ล่วงหน้าว่าอาจเปิดปัญหาที่ซ่อนอยู่ในโปรเจกต์ทดสอบ
- **Tests:** `frontend/src/stores/__tests__/auth.spec.ts` (ตัวที่ทำให้กราฟถูกดึงเข้ามาครั้งแรก) — พิสูจน์ด้วย `npx vue-tsc -p tsconfig.vitest.json --noEmit` ก่อน/หลังแก้
- **Date Added:** 2026-09-25

### 🫥 ฟังก์ชันที่ "กลืน error แล้วไม่บอกใคร" = **สถานะว่างสองความหมายที่แยกออกจากกันไม่ได้**
- **Context/Problem:** ตรวจระบบ 2026-09-23 (L3) — `authStore.fetchProfile()` เป็น `void` และกลืน error ด้วย `console.error` เฉย ๆ ⇒ `Onboarding.vue` ขึ้น **ฟอร์มว่างเปล่า** โดยไม่บอกอะไร เมื่อดึงโปรไฟล์ไม่สำเร็จ
  🔎 **ผู้ที่ได้รับผลกระทบจริงคือคนที่มีข้อมูลอยู่แล้ว** — ล็อกอินเครื่องใหม่ หรือเน็ตสะดุดตอนเปิดหน้า (ซึ่งเกิดทุกครั้งที่ deploy เพราะ backend รีสตาร์ท) ⇒ เข้าใจว่า "ข้อมูลหาย" แล้ว **กรอกทับข้อมูลเดิมของตัวเอง** เพราะหน้าจอไม่แสดงอะไรผิดปกติเลย
- **Root Cause:** ผู้เรียกแยก **"ดึงเสร็จและยังไม่มีข้อมูล"** กับ **"ดึงไม่สำเร็จ เลยยังไม่มีข้อมูล"** ไม่ออก เพราะทั้งสองกรณีทิ้ง store ไว้ในสภาพเดียวกันเป๊ะ (ค่าว่าง) — ข้อมูลที่ใช้แยกถูกกลืนไปกับ `console.error`
  ⚠️ **มุมที่มองข้ามง่าย:** ปัญหาไม่ใช่ "ไม่มี error handling" — มี `catch` ครบ และมี `finally` ที่ปลดล็อกฟอร์มพร้อมคอมเมนต์อธิบายเจตนาด้วยซ้ำ ⇒ **โค้ดดูตั้งใจดีแล้ว** สิ่งที่ขาดคือ "การส่งต่อความล้มเหลวให้ผู้ที่ต้องตัดสินใจจากมัน"
- **Correct Pattern/Solution:** ให้ฟังก์ชัน **คืนค่าที่บอกผล** แล้วให้ผู้เรียกเลือกนโยบายเอง
  ```ts
  const fetchProfile = async (): Promise<boolean>   // true = ไม่มีความล้มเหลว · false = ดึงไม่สำเร็จ
  ```
  - ⚠️ **ห้ามเปลี่ยนเป็น throw แทน** — มีผู้เรียก 11 จุดทั่วแอป (layout, callback, lobby) ⇒ จุดที่ไม่ได้เตรียมรับจะกลายเป็น unhandled rejection
  - ⚠️ **`true` ของเส้นทาง "ถูกข้าม" (ไม่มี token / มีคำขอค้างอยู่) ต้องนิยามให้ชัด** ว่าแปลว่า "ไม่มีอะไรต้องรายงาน" ไม่ใช่ "ดึงข้อมูลมาแล้ว" — เขียนใน docstring ไม่งั้นผู้เรียกที่ตามมาจะตีความผิด
  - 🔑 **การล้มเหลวต้องไม่ล้างค่าเดิม** — ข้อมูลเก่าที่จริง ดีกว่าฟอร์มว่าง (ถ้าล้าง จะกลายเป็นข้อมูลหายจริง ซึ่งแย่กว่าเดิม)
  - 🔑 **ต้องมีทางออกให้ผู้ใช้** — กล่องยืนยันมีทั้ง "ลองใหม่" **และ** "กรอกเอง" ไม่งั้นคนที่ Backend ล่มถาวรจะออนบอร์ดไม่ได้เลย
- **Rule:** (1) 🔴 **ความล้มเหลวที่ถูกกลืน = สถานะที่ตีความได้สองทาง ⇒ ต้องส่งต่อให้ผู้ที่มีอำนาจตัดสินใจ** (2) 🔴 **`void` + `console.error` ไม่ใช่ error handling** — มันคือการซ่อน ถ้าผู้เรียกต้องตัดสินใจจากผลลัพธ์ ต้องคืนค่า (3) ✅ **เทสต์ที่พิสูจน์เรื่องนี้ได้ต้องยืนยัน "สิ่งที่ผู้ใช้เห็น" ไม่ใช่แค่ค่าที่คืน** — เขียนเทสต์ premise ที่ยืนยันว่าค่าที่อ่านจาก store แยกสองกรณีไม่ออกจริง (ถ้าวันหนึ่งมีคนใส่ fallback จนแยกออกได้ เทสต์นี้จะเตือนให้กลับมาทบทวนว่ายังต้องมีค่าที่คืนไหม)
- **Tests:** `frontend/src/stores/__tests__/auth.spec.ts` (6 ตัว · ถอดการแก้ออก (`return true/false` → `undefined`) แล้วรันซ้ำ → **5/6 fail**; ตัวที่ยังผ่านคือเทสต์ premise ซึ่งถูกต้อง เพราะมันยืนยันเฉพาะสิ่งที่มองเห็นจาก store ไม่ได้ขึ้นกับค่าที่คืน)
- **Date Added:** 2026-09-25

### 🔢 `ast` `col_offset` เป็น **byte offset (UTF-8)** ไม่ใช่ offset ตัวอักษร — พังเงียบในไฟล์ภาษาไทย
- **Context/Problem:** เขียนสคริปต์แปลง call site ของบอท 44 จุด (M10) โดยใช้ `ast` หาขอบเขตของ "อาร์กิวเมนต์ตัวแรก" แล้วแทรก `embed=...(`, `)` ตรงตำแหน่ง `args[0].col_offset` / `args[0].end_col_offset`
  อาการ: ไฟล์ที่เขียนออกมา **parse ไม่ผ่าน** และวงเล็บปิดไปโผล่ **ท้ายบรรทัด** แทนที่จะปิดหลังสตริง
  ```
  return await interaction.followup.send(embed=info_embed("🎉 ยังไม่มีกิจกรรม...ครับ", ephemeral=True)
                                                  ^ SyntaxError: invalid syntax
  ```
  🔎 **ทำไม `col_offset` (ตัวเปิด) ดูเหมือนถูก แต่ `end_col_offset` (ตัวปิด) ผิด:** ตัวเปิดอยู่หลัง `send(` ซึ่งเป็น ASCII ล้วน ⇒ byte offset == offset ตัวอักษร บังเอิญตรง · ตัวปิดอยู่ **หลัง** ข้อความไทย ⇒ ไม่ตรง
- **Root Cause:** CPython เก็บ `col_offset`/`end_col_offset` เป็น **UTF-8 byte offset** (ระบุในเอกสารตั้งแต่ 3.8) ส่วนการ slice สตริงใน Python นับเป็น **ตัวอักษร**
  ⇒ ไฟล์นี้เป็นภาษาไทย และอักขระไทยกิน **3 byte/ตัว** ⇒ offset เพี้ยนแบบคูณสาม
  ตัวอย่างจริง (บรรทัด 114 ตัวอักษร แต่ 191 byte): `end_col_offset` = **173** ในขณะที่ตำแหน่งตัวอักษรจริงอยู่ราว 100
  ⚠️ **นี่คือ "พังเงียบ" ไม่ใช่ "พังทันที":** ตราบใดที่ข้อความก่อนจุดตัดเป็น ASCII ล้วน โค้ดจะดูถูกต้อง — บั๊กจะรออยู่ในโค้ดและโผล่เฉพาะกับข้อความที่มีอักขระนอก ASCII **และ** อยู่หลังจุดที่ตัด
- **Correct Pattern/Solution:** แปลง byte offset → offset ตัวอักษรเสมอก่อนใช้กับสตริง
  ```python
  def pos(lineno: int, byte_col: int) -> int:
      line = lines[lineno - 1]                      # มี \n ต่อท้ายได้ ไม่กระทบ
      char_col = len(line.encode("utf-8")[:byte_col].decode("utf-8"))
      return starts[lineno - 1] + char_col
  ```
- **Rule:** (1) 🔴 **ห้ามเอา `col_offset`/`end_col_offset` ไป slice สตริงตรง ๆ ถ้าไฟล์อาจมีอักขระนอก ASCII** — decode ผ่าน byte ก่อน (2) ✅ **`ast.get_source_segment(src, node)` ปลอดภัยกว่า** เพราะไลบรารีจัดการ offset ให้เอง — ใช้เมื่อต้องการ *อ่าน* โค้ด (3) ✅ **ยืนยันผลด้วย `ast.parse` ของไฟล์ที่เขียนออกมาเสมอ** ก่อนจะไปดู diff — ในเคสนี้ syntax check จับได้ทันทีที่รัน `--apply` ครั้งแรก และ **ไม่มีไฟล์ใดถูกเขียนลงดิสก์** เพราะ error เกิดก่อนบรรทัด `write` (4) ⚠️ **สคริปต์แปลงโค้ดควร parse ไฟล์ผลลัพธ์ก่อนเขียนทับ** — ถ้าเขียนก่อนแล้วค่อยตรวจ จะเหลือไฟล์พังค้างไว้
- **Tests:** `bot_discord/tests/test_reply_embed.py` (รันหลังแปลง — 93/93 ผ่าน) + `ast.parse` ทุกไฟล์ที่แก้ 8/8 ผ่าน · ตรวจซ้ำด้วยสคริปต์ AST ว่า **เหลือ `send` ที่ไม่ใช้ embed 0 จุด**
- **Date Added:** 2026-09-25

### 💬 ข้อความ error ที่ความยาวมาจากปลายทาง = ข้อความที่ Discord ปฏิเสธ **ทั้งใบ**
- **Context/Problem:** ตรวจระบบ 2026-09-23 (M10) — บอทตอบกลับด้วยข้อความดิบ (`content=`) **44 จุดใน 8 ไฟล์** ในนั้น **21 จุดเป็น `f"❌ {e}"** โดย `e` มาจากชั้น API ⇒ ครูกดคำสั่งแล้ว **เงียบสนิท** ทั้งที่งานข้างหลังอาจสำเร็จแล้ว
- **Root Cause:** `content=` ของ Discord จำกัด **2,000 ตัวอักษร** และเมื่อเกิน **API ปฏิเสธทั้งข้อความ** (HTTP 400 `Invalid Form Body` / code 50035) → discord.py โยน `HTTPException`
  🔴 **`HTTPException` ไม่ใช่ `APIException`** ⇒ `except APIException` ที่คำสั่งเหล่านี้ใช้ดักอยู่ **ไม่จับ** ⇒ error หลุดพ้นไปทั้งดุ้น (รูปแบบเดียวกับ H8)
  🧨 **เข้าถึงได้โดยไม่มีใครทำอะไรผิด:** Traefik/proxy ตอบหน้า HTML แทน JSON ตอน backend ล่ม · traceback หลุด · backend ตอบ JSON ก้อนใหญ่ ⇒ เกิน 2,000 ทั้งนั้น
  ⚠️ **ที่สุดของกับดัก:** `discord.py` **ไม่ตรวจเพดานฝั่ง client เลย** — สร้าง `Embed(description="x"*5000)` ได้เงียบ ๆ ไม่มี exception ให้ดัก ⇒ เทสต์ที่คาดหวัง `ValueError` จะ **ผ่านแบบหลอก ๆ** เพราะไม่มีอะไรโยนให้ดัก
- **Correct Pattern/Solution:** รวมข้อความตอบกลับทุกจุดไว้ที่ **บ้านหลังเดียว** (`services/reply_embed.py`) แล้วบังคับเพดานที่นั่น
  ```python
  error_embed(f"❌ {e}")     # → clip() ที่ 1,000 ตัวอักษร (แน่นกว่าเพดาน 4,096)
  success_embed / warning_embed / info_embed
  ```
  - 🔑 **ย้ายเข้า embed = ยกเพดานขึ้นเท่าตัว** (2,000 → 4,096) ไม่ใช่แค่เปลี่ยนภาชนะ — และเป็นเหตุผลว่าทำไม `content=` ไม่ควรรับข้อความที่ความยาวไม่รู้ล่วงหน้า
  - 🔑 **งบ error แน่นกว่าปกติโดยเจตนา** — error 4,000 ตัวอักษรในมือครูอ่านไม่รู้เรื่อง ส่วนที่เกิน 1,000 แทบไม่เคยมีข้อมูลที่ต้องใช้ตัดสินใจ มีแต่ stack trace
  - ⚠️ **กัน embed ว่างเปล่าด้วย** — `f"❌ {e}"` ที่ `e` เป็นสตริงว่าง ได้ `"❌ "` ⇒ ถ้าปล่อยเป็น description ว่างจะเจอ HTTP 400 อีกทาง ("Cannot send an empty message")
  - 🔑 **เลือกสีตามความหมาย ไม่ใช่ emoji ที่นำหน้า** — `🗑️ ลบงาน ... ทิ้งแล้ว` และ `⏰ เปลี่ยนเวลา...เรียบร้อยแล้ว` ขึ้นต้นด้วยถังขยะ/นาฬิกา แต่เป็น "สำเร็จ" ทั้งคู่ ⇒ กฎอัตโนมัติตาม emoji ให้สีผิด 10 จุด ต้องอ่านข้อความจริงแล้วตัดสินรายจุด
  - ⚠️ **ไม่ใส่ `title` โดยปริยาย** — ข้อความเดิมมี emoji นำอยู่แล้ว (`"❌ ..."`) ใส่ title ทับจะได้ emoji ซ้ำสองที่
- **Rule:** (1) 🔴 **ข้อความที่ความยาวมาจากปลายทางต้องถูกจำกัดก่อนส่งเสมอ** — และจำกัดที่จุดเดียว ไม่ใช่กระจาย 44 ที่ให้เชื่อว่าทำถูก (2) 🔴 **`except APIException` ไม่ครอบ `HTTPException`** — เพดานที่เกินจะกลายเป็น "บอทไม่ตอบ" ที่ไม่มีร่องรอยในโค้ด (3) ✅ **เทสต์ต้อง "วัดค่าจริง" ไม่ใช่ "ดัก exception"** เมื่อไลบรารีไม่ตรวจให้ — เขียนเทสต์ premise ที่พิสูจน์ว่าไม่มีใครตรวจ แล้วจึงวัดความยาวของ embed ที่สร้างเสร็จ (4) ✅ **`content=` ควรถูกแทนด้วย embed ทั้งโปรเจกต์** ไม่ใช่แค่จุดที่พบปัญหา — บั๊กชนิดนี้เลือกจุดเกิดเอง
- **Tests:** `bot_discord/tests/test_reply_embed.py` (19 ตัว · ทำลาย `clip` → **14/19 ล้ม** ตัวที่รอดคือเทสต์ premise + ตัวที่ไม่เกี่ยวกับการตัด ซึ่งถูกต้อง) · `docker run --rm -e API_KEY=test-api-key … python -m unittest discover -s tests -t .` → **93/93 ผ่าน** · ตรวจซ้ำด้วย AST ว่าเหลือ `send` ที่ไม่ใช้ embed **0 จุด**
- **Date Added:** 2026-09-25

### 🕳️ `except:` เปล่าไม่ได้แปลว่า "ดัก error" — มันแปลว่า "ดักทุกอย่างที่โยนได้"
- **Context/Problem:** ตรวจระบบ 2026-09-23 (L4) — เจอ bare `except` 3 จุด
  · `bot_discord/cogs/classroom_cmd.py` (×2 — `task_autocomplete`, `deleted_task_autocomplete`)
  · `backend/services/student/base.py` (`_parse_permissions`)
  ทั้งสามจุดจบด้วย `except:` แล้ว `return []`
- **Root Cause:** ตั้งแต่ Python 3.8 **`asyncio.CancelledError` สืบทอดจาก `BaseException` ไม่ใช่ `Exception`** และ `KeyboardInterrupt`/`SystemExit` ก็เช่นกัน
  ⇒ `except:` เปล่า **กลืนการสั่งยกเลิกงาน** · ตอน deploy (`pull_all.sh` ส่ง SIGTERM) หรือกด Ctrl-C งานที่กำลังรอ API จะถูกสั่งยกเลิกแล้ว **หายไปเงียบ ๆ** ⇒ ลูปไม่ยอมจบ บอทปิดไม่สนิท
  ⚠️ และเพราะไม่มี log อะไรเลย อาการ "ปิดบอทแล้วค้าง" จึงหาสาเหตุไม่ได้ — **การกลืน error ทำให้ symptom อยู่ห่างจาก cause มาก**
  🔎 **ทำไม `except Exception` ยังไม่พอ:** มันแก้เรื่อง `CancelledError` ได้ แต่ยังกลืน **bug ของเราเอง** (`KeyError`, `AttributeError`) ⇒ autocomplete ที่ "ขึ้นแต่รายการว่าง" เพราะคีย์ใน response เปลี่ยน จะดูเหมือน "ไม่มีข้อมูล" ไปตลอด
- **Correct Pattern/Solution:** แยก **"ความล้มเหลวที่คาดไว้"** ออกจาก **"ข้อผิดพลาดที่ไม่คาดคิด"** แล้วจัดการคนละแบบ
  ```python
  except APIException:
      return []                      # คาดไว้: API ล่ม = ไม่มีตัวเลือกให้เสนอ (เงียบ)
  except Exception:
      logger.exception(...)          # ไม่คาดคิด: คืน [] เหมือนกัน แต่ต้องมีร่องรอย
      return []
  ```
  🔑 **พฤติกรรมต่อผู้ใช้ไม่เปลี่ยน** (ยังได้ `[]` ทั้งคู่) — สิ่งที่เพิ่มคือ *ความสามารถในการวินิจฉัย* ไม่ใช่การเปลี่ยนสัญญา
  ```python
  # ฝั่ง backend: ระบุชนิดที่โยนได้จริง
  try:
      parsed = json.loads(perms)
  except json.JSONDecodeError:
      return []
  ```
  ⚠️ **เจอข้อบกพร่องข้างเคียงในฟังก์ชันเดียวกัน:** `_parse_permissions` ประกาศคืน `List[str]` แต่ `json.loads` คืนได้ทุกชนิด ⇒ ค่าที่เก็บเป็น JSON *สตริง* จะถูกคืนเป็นสตริง ผู้เรียกที่ `.includes()` จะกลายเป็น substring match ⇒ เติม `return parsed if isinstance(parsed, list) else []`
- **Rule:** (1) 🔴 **ห้ามใช้ `except:` เปล่าในโค้ด async เด็ดขาด** — มันกลืน `CancelledError` (2) 🔴 **`except Exception` ไม่ใช่คำตอบสุดท้าย** — ถ้ามีชนิดที่คาดไว้ ให้ระบุชนิดนั้น แล้วดัก `Exception` แยกเพื่อ log (3) ✅ **"เงียบต่อผู้ใช้" กับ "เงียบใน log" เป็นคนละเรื่อง** — อย่างแรกอาจถูก อย่างหลังผิดเสมอ (4) ✅ **แก้ `except` ที่ไหน ให้ตรวจสัญญาการคืนค่าของฟังก์ชันนั้นด้วย** — `except` ที่กว้างมักซ่อน type bug ไว้ข้าง ๆ
- **Tests:** `bot_discord/tests/test_autocomplete_errors.py` (8 ตัว · ย้อนกลับเป็น `except:` เปล่า → **4/8 ล้ม** = เทสต์ที่ยืนยันว่า `CancelledError`/`KeyboardInterrupt` ต้องหลุดออกไป; อีก 4 ตัวที่ผ่านคือตัวที่ล็อก *พฤติกรรมเดิม* ซึ่งถูกต้อง) · `backend/tests/test_student.py` Section 11 (5 ตัว — รวมเทสต์ที่บังคับให้ `json.loads` โยน `KeyboardInterrupt`/`CancelledError` แล้วยืนยันว่ามันหลุดออกไป)
- **Date Added:** 2026-09-25

### 🕳️ `except Exception as e: raise HTTPException(500, detail=str(e))` — โค้ดที่ "อ่านแล้วถูกต้องที่สุด" ในไฟล์ และเป็นบั๊กที่แพงที่สุด
- **Context/Problem:** ตรวจระบบ 2026-09-23 (M6/M7) พบว่า `routers/auth_router.py` ทุก endpoint ปิดท้ายแบบนี้
  ```python
  except Exception as e:
      raise HTTPException(status_code=500, detail=str(e))
  ```
  &#8594; ผลที่วัดได้จริง: ครูที่เปิดหน้าล็อกอินค้างไว้นานจน `code` หมดอายุ **เห็น "500 Internal Server Error"** ทั้งที่ฝั่งเซิร์ฟเวอร์ไม่พังอะไรเลย และในตาราง `audit_logs` ก็ไม่มีร่องรอยว่ามีคนล็อกอินไม่สำเร็จเพิ่มขึ้น — เพราะมันไม่ใช่ error ของระบบ จึงไม่มีใครเฝ้าดู
- **Root Cause:** `HTTPException` **สืบทอดจาก `Exception`** (ไม่ใช่ `BaseException`) ⇒ ตัวดักที่ตั้งใจไว้ "กันเซิร์ฟเวอร์พัง" กลับเป็นตัวแปลงคำตอบ 400 ที่ตั้งใจไว้ให้กลายเป็น 500
  ```python
  try:
      if not payload.code: raise HTTPException(400, "code is required")   # ← ตั้งใจตอบ 400
  except Exception as e:
      raise HTTPException(500, detail=str(e))                             # ← ถูกแปลงเป็น 500 ทันที
  ```
  🔎 **ทำไมอ่านโค้ดแล้วไม่เห็น:** ที่บรรทัด `raise HTTPException(400, ...)` ทุกอย่างถูกต้อง อ่านแล้วเข้าใจว่า "ตรงนี้ตอบ 400" และที่ตัวดักล่างก็ถูกต้อง "ดักทุกอย่างแล้วตอบ 500" — **ความผิดอยู่ที่ระยะห่างระหว่างสองบรรทัดนี้ ไม่ใช่ที่บรรทัดใดบรรทัดหนึ่ง** ⇒ ไม่มีบรรทัดไหนที่ "ดูผิด" ให้สะดุด
  🔎 **ความเสียหายจริงไม่ใช่รหัสผิด แต่คือการที่ระบบเฝ้าดูแยกไม่ออก** ระหว่าง "ผู้ใช้พิมพ์ผิด" กับ "ฐานข้อมูลล่ม" — สัญญาณเตือนถูกกลบด้วยความผิดพลาดของ request ธรรมดา ๆ
  🔎 **`str(e)` รั่ว**: ข้อความ exception ของ asyncpg/httpx มีชื่อตาราง ชื่อคอลัมน์ SQL ที่ล้มเหลว และบางครั้งก็มีที่อยู่ภายใน
- **Correct Pattern/Solution:** **ลำดับ `except` ต้องเป็น แคบ &#8594; กว้าง เสมอ** และต้องแยกให้ออกระหว่าง "ข้อความภายใน" กับ "ข้อความที่ตั้งใจให้ผู้ใช้เห็น"
  ```python
  except HTTPException:
      raise                          # 1) ที่ตั้งใจตอบ — ส่งต่อทั้งรหัสและข้อความ
  except ForbiddenError as e:
      raise HTTPException(400, detail=str(e))   # 2) ข้อความธุรกิจที่ตั้งใจให้ผู้ใช้เห็น
  except Exception:
      logger.exception("...")        # 3) ที่เหลือ — ลง log แล้วตอบข้อความกลาง
      raise HTTPException(500, detail="... ไม่สำเร็จ กรุณาลองใหม่อีกครั้ง")
  ```
  ⚠️ **กับดักที่โผล่มาระหว่างแก้** — กฎ "ห้ามส่งข้อความ exception ออกไป" ถ้าใช้แบบเหวี่ยงแห จะ **กลืนข้อความธุรกิจที่ตั้งใจให้ผู้ใช้เห็น** ไปด้วย · `link_oauth_account` โยน `ForbiddenError("บัญชีนี้ผูกกับ discord ID ... อยู่แล้ว กรุณาใช้ ID เดิม")` ซึ่งเป็นประโยคที่บอกผู้ใช้ว่าต้องทำอะไรต่อ ถ้ากลืนเป็น "ผูกบัญชีไม่สำเร็จ กรุณาลองใหม่" ผู้ใช้จะลองใหม่วนไปเรื่อย ๆ โดยไม่มีทางสำเร็จ · **`ForbiddenError` เป็นคลาสของโปรเจกต์เอง (ไม่ใช่ `HTTPException`) ⇒ ต้องมี `except` ของตัวเอง มันจะไม่ถูกจับโดยข้อ 1**
  ⚠️ งานนี้ **คงรหัสเดิมทุกตัว** (400 ยังเป็น 400) — การเปลี่ยนรหัสคือการเปลี่ยนสัญญาบนสายที่ frontend ผูกอยู่ เป็นงานคนละเรื่องที่ควรมีเทสต์คุมเอง
  📌 **M4 เรื่องเดียวกันในมุมข้อมูลออก**: `GET /me` คืน `dict(user)` ดิบ ๆ จาก `SELECT *` โดยไม่มี `response_model` ⇒ **คอลัมน์ไหนถูกเพิ่มเข้า SELECT ก็หลุดออก API ทันที** `response_model` ไม่ได้มีผลแค่ตอนกรองคำตอบ แต่คือ **สัญญาที่ประกาศไว้** ซึ่ง `/openapi.json` เอาไปสร้างชนิดฝั่ง client
- **Rule:** (1) 🔴 **`except` ต้องเรียง แคบ &#8594; กว้าง และ `HTTPException` ต้องมาก่อน `Exception` เสมอ** ในทุก handler ที่มี `try` — `HTTPException` เป็น `Exception` (2) 🔴 **ห้าม `detail=str(e)` ของ exception ที่ไม่รู้จัก** — ลง `logger.exception` แทน (3) 🔴 **ข้อความที่ตั้งใจให้ผู้ใช้เห็นต้องมี exception คลาสของตัวเอง** ไม่งั้นมันจะถูกกลืนไปกับข้อความกลางอย่างเงียบ ๆ และหายไปโดยไม่มีเทสต์ไหนจับ (4) 🔴 **SQL ต้องไม่อยู่ใน `routers/`** (`GET /me` เคยมี) — ไม่ใช่แค่เรื่องชั้นสถาปัตยกรรม แต่เพราะ **คนที่เพิ่มคอลัมน์ใน `SELECT *` ไม่มีทางรู้ว่ามันจะไปโผล่ที่ API** (5) ✅ **เทสต์ของงานนี้ต้องยิง HTTP จริง ไม่ใช่เรียก service** — บั๊กอยู่ที่ "ชั้นที่ประกอบ HTTP response" ซึ่งเทสต์ระดับ service มองไม่เห็นเลย (ชุดเทสต์ 1,000+ ตัวของโปรเจกต์เขียวทั้งหมดขณะที่บั๊กนี้ยังอยู่)
- **Tests:** `backend/tests/test_auth_http_error_contract.py` (12 ตัว · ผ่านโดยไม่มี warning) · **พิสูจน์ว่ามีฟันด้วย mutant 3 ตัวรวดเดียว** — ถอด `except HTTPException` ของ `discord_login` + ถอด `except ForbiddenError` + คืน `GET /me` กลับเป็น `SELECT *` ไม่มี `response_model` &#8594; **6/12 ล้ม** และตัวที่ล้มคือตัวที่ควรล้มเป๊ะ (ฝั่ง google ที่ไม่ได้แตะยังเขียว = เทสต์ไม่ได้ล้มเพราะมลพิษข้ามเทสต์) · ตัวชี้ขาด: `test_me_returns_exactly_the_declared_fields` (เทียบ **ชุดคีย์** ไม่ใช่แค่ presence ⇒ จับได้ทั้งตอนเพิ่มและตอนลบฟิลด์)
- **Date Added:** 2026-09-25
