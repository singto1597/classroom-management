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
