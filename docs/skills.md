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
  1. **Router pattern:** `get_transactions` / `get_summary` / `export_transactions_excel` กลายเป็นตัว route — ตัดสินใจจากจุดเริ่มต้นของช่วงเวลาที่ขอ (`_period_start`): `period_start >= CUTOFF_DATE` → `_get_*_v2` (อ่าน journal), ไม่ใช่ → `_get_*_legacy` (อ่านตารางเก่า) โดยแยก logic เดิมไปเป็น `_legacy` variant เต็ม ๆ (รับ `conn` + `room_id` + `start_time` ผ่าน kwarg) เพื่อให้ error-handling/audit log อยู่ที่ router ชั้นเดียว
  2. **"ไม่ระบุช่วงเวลา" = ทั้งหมด:** ครอบคลุมทั้งสองยุค → ต้องอ่าน legacy เสมอ (ข้อมูลก่อน cutoff มีแค่ตารางเก่า) — อย่าให้ default `_period_start` (เดือนปัจจุบัน) ไปเปลี่ยนผลเมื่อเลยวันที่ตัดตาม wall-clock
  3. **การแปล Dr/Cr กลับเป็น schema เดิม (TransactionResponse):** group journal_lines ตาม journal_entry_id → classify ตาม combination: income (asset Dr + revenue Cr), expense (asset Cr + expense Dr), transfer (asset 2 บัญชี Dr+Cr), opening_balance → income (ยอด = asset Dr) และไม่นับขา equity
  4. **⚠️ id ของ TransactionResponse ต้องเป็น int:** journal_entry.id เป็น UUID → frontend ใช้ `id` เป็น Vue key + เรียก `revert_transaction` (ค้นจาก finance_transactions.id) → สังเคราะห์ int จาก `metadata['legacy_transaction_id']` (หรือ `transfer_group_id`); ถ้าไม่มี (opening_balance) ใช้ค่าลบจาก hash ของ UUID (เป็น id ที่ revert ไม่ได้จริงตามธรรมชาติ)
  5. **ยอดยกมาไม่นับเป็นรายได้:** `_get_summary_v2` / `get_income_statement` ต้อง `JE.reference_type <> 'opening_balance'` ในส่วนรายได้/รายจ่ายของงวด แต่ **Net Worth (asset) ต้องรวม** ยอดยกมาเสมอ
  6. **Excel v2:** ใช้ `_get_transactions_v2` (limit ใหญ่) → `_format_v2_rows` → `_build_finance_workbook` เดิม; ยอดคงเหลือรายบัญชีคำนวณจาก Net Balance ของ ledger สินทรัพย์ (`SUM(debit−credit)`) ไม่ใช่ finance_accounts.balance
  7. **Helper `_ExportPeriodView`** ใช้ส่ง month/year/start_date/end_date เข้า `_resolve_export_period` (เดิมรับ req object) ให้ `_legacy` export variant ใช้ของเดิมได้
- **Tests:** `test_finance_v2_read.py` — 16 service + 4 HTTP: router (ก่อน/หลัง cutoff, no-filter, ข้ามช่วง), classify income/expense/transfer/opening_balance, summary v2 (รวมยอดยกมาใน net worth แต่ไม่นับรายได้), export v2, trial balance (Dr=Cr + as_of_date), income statement (net_income + ไม่นับยอดยกมา), RBAC 403 สำหรับ v2 methods
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
