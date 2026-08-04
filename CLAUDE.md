# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Classroom Management System (ระบบบริหารจัดการห้องเรียน) — a Thai-language monorepo with 3 services. All business logic lives in the backend; the frontend and Discord bot are thin clients that **must never touch the database directly** — they talk to the backend API only.

- `backend/` — FastAPI (Python 3.12+), asyncpg raw SQL. The only service allowed to touch PostgreSQL/Redis.
- `frontend/` — Vue 3 + Vite + TypeScript SPA for students/teachers.
- `bot_discord/` — discord.py bot (slash commands) that reads/writes everything through the backend API.

The `docs/` directory contains the project's authoritative engineering rules:
- `docs/system_prompt.md` — global rules for all layers.
- `docs/rules/backend.md`, `docs/rules/frontend.md`, `docs/rules/discord-bot.md`, `docs/rules/testing.md` — per-layer rules (originally Cursor rules).
- `docs/skills.md` — knowledge base of previously solved bugs / non-obvious patterns. **Read it before fixing bugs or adding features; append new lessons to it when you discover one.** The testing rules make this mandatory.

## Commands

### Backend (run from repo root)
```bash
# Integration tests (PostgreSQL on port 5433, pytest inside a Docker container)
docker compose -f docker-compose.test.yml run --rm test_runner sh -c "export PYTHONDONTWRITEBYTECODE=1 && python -m pytest -p no:cacheprovider -v /app/tests/"
```
- The `test_runner` service mounts `./backend` into `/app` and overrides `DATABASE_URL` to point at the throwaway `test_db` (Postgres 16 on host port 5433). `conftest.py` creates a fresh random-named database per session, runs `init_db` to build the full schema, and drops it afterward.
- Run a single test file: append the path, e.g. `... -v /app/tests/test_room.py`.
- Run one test by node id: `... -v /app/tests/test_room.py::test_something`.
- There is no separate lint/type-check for the backend; Python correctness is enforced by the test suite.

### Frontend (from `frontend/`)
```bash
npm install
npm run dev          # Vite dev server (default http://localhost:5173)
npm run type-check   # vue-tsc --build (required — TypeScript is strict, no `any`)
npm run build        # type-check + build
npm run lint         # oxlint --fix + eslint --fix (both auto-fix)
npm run format       # prettier --write src/
npm run test:unit    # vitest (jsdom environment)
npm run test:e2e     # playwright (browsers must be installed first: npx playwright install)
```

### Discord bot (from `bot_discord/`)
```bash
python main.py
```
Requires `.env` with `DISCORD_TOKEN`, `API_BASE_URL`, `API_KEY`. No tests.

### Infra / deploy (repo root)
```bash
cp .env.example .env            # single root .env consumed by everything
docker stack deploy -c docker-compose.infra.yml ${ENV_NAME}_infra   # Postgres + Redis
./pull_all.sh                   # fetch → build images tagged by git commit hash → zero-downtime deploy
./oh_shit.sh                    # emergency rollback to previous commit's images
```
- **Never hardcode/commit real secrets.** `.env` is gitignored; everything reads from the root `.env`.
- `docker-compose.app.yml` runs backend ×3 replicas behind Traefik; the bot runs as 1 replica (stop-first).

## Architecture

### Backend (FastAPI) — strict MVC-like layering
```
backend/
  main.py            # entrypoint: creates asyncpg pool in lifespan, runs init_db, mounts routers
  core/
    config.py        # pydantic-settings; loads root .env
    init_db.py       # ALL table DDL lives here (schema setup)
    dependencies.py  # get_db_pool, verify_api_key, get_current_user, resolve_target_to_room_id
    rbac.py          # require_permission (granular permission check, is_admin bypasses)
    exceptions.py    # domain exceptions (StudentNotFoundError, ForbiddenError, ...)
    logger.py        # AuditLogger — inserts into audit_logs
    audit.py         # legacy log_action helper (see note below)
    utils.py         # resolve_room_id helper
  routers/           # HTTP layer only: DI, header extraction, exception→HTTPException
  services/          # ALL business logic + raw SQL + transactions
  models/            # Pydantic v2 request/response schemas
  config/roles.json  # available roles
  tests/             # pytest integration tests (conftest.py + per-module suites)
```

Layering rules (from `docs/rules/backend.md`) that must be followed:
- **Routers:** no SQL, no business logic. Extract `x_discord_id: str = Header(...)` (and use `get_audit_context(request, user_ctx)` to get `client_source` / `actor_identifier`), call a service, and translate domain exceptions into `HTTPException` with correct status codes (400/403/404). Always declare `response_model=...` to filter secret fields.
- **Services:** own all raw SQL via `asyncpg`. Receive `pool: asyncpg.Pool` via DI. Wrap multi-statement mutations in `async with conn.transaction():`. Use parameterized queries (`$1, $2, ...`) — never f-string SQL. For PATCH, use `req.model_dump(exclude_unset=True)`.
- **Models:** Pydantic v2 (`model_dump()`, not `dict()`). Date params must be typed `date`/`datetime`, never `str` (prevents `toordinal()` bugs).
- **Soft delete is mandatory** for important data (`UPDATE ... SET deleted_at = NOW()`); hard delete only in `permanent` functions after checking FK dependencies.
- **Audit logging:** every create/update/delete must write to `audit_logs` inside the same transaction, with `old_values` and `new_values`.
- **`NUMERIC/DECIMAL` columns** come back from asyncpg as `decimal.Decimal` — cast `float(row['amount'])` before arithmetic, never add/subtract a float directly.

### Backend request flow & auth
`get_current_user` (`core/dependencies.py`) normalizes every request to a `{"user_id": int}`:
1. **Discord bot path:** `X-API-Key` header matching `settings.API_KEY` + `X-Discord-Id` header → looks up `users.discord_id` → returns the mapped `user_id`.
2. **Web path:** JWT Bearer token → decodes `user_id` claim.
- `resolve_target_to_room_id` normalizes `target_id` + `target_type` (`room` for web, `server` for bot) into a canonical `room_id` so services never care about the platform.
- `require_permission(conn, room_id, user_id, permission)` (`core/rbac.py`): `SUPER_ADMIN_ID` and `is_admin` bypass; otherwise checks the `permissions` JSONB array on the `students` row.

### Frontend (Vue 3 SPA) — 4-layer structure
```
frontend/src/
  types/       # Interfaces for all data models
  services/    # axios API calls only — views never call api.get/post directly
  views/       # pages: UI logic, lifecycle, rendering
  components/  # reusable UI pieces
  stores/      # Pinia (auth store)
  layouts/     # MainLayout (authed app), GlobalLayout (lobby)
  router/      # vue-router with auth + onboarding guards
```
- `services/api.ts` is the single axios instance: attaches `Bearer` token from `localStorage`, unwraps `response.data`, redirects to `/login` on 401, and re-formats Pydantic 422 `detail` arrays into readable Thai messages.
- Auth state lives in the Pinia `stores/auth.ts`, persisted to `localStorage` (token, user profile, current room, RBAC flags). `isOnboarded` requires `prefix` + `phoneNumber`.
- Router `beforeEach` guard: requires auth → requires onboarding → requires a selected room (`currentRoomId`/`currentRole`) unless on `/lobby`, `/login`, `/onboarding`.
- UI rules: `const isLoading = ref(true)` + spinner/skeleton for every fetch; **SweetAlert2 (`Swal.fire`) only** for notifications (never `alert()`/toast); times shown in Thai and `Asia/Bangkok`. No `any` anywhere.

### Discord bot (discord.py)
```
bot_discord/
  main.py        # Bot subclass; setup_hook opens aiohttp session + loads cogs + syncs slash commands
  cogs/          # command groups (classroom_cmd, student_cmd) + redis_listener
  ui/            # discord.ui.Modal / View classes, kept separate from cogs
  services/      # api_client (singleton aiohttp session, X-API-Key header) + action_service (Redis consumer)
```
- **No DB policy:** the bot never connects to PostgreSQL. All data flows through `services/api_client.py` → backend API with `X-API-Key` and `X-Discord-Id` headers.
- Respond within 3 seconds (use `defer()` for slow API calls); always render results as `discord.Embed`; errors and personal data use `ephemeral=True`.
- `cogs/redis_listener.py` subscribes to the `classroom_events` Redis channel that the backend publishes to (via `services/action_service.py`'s `ActionService`), which is how web-triggered notifications reach Discord.

### Cross-service event flow
Backend writes to DB and publishes to Redis channel `classroom_events` (`ActionService._publish` in `backend/services/action_service.py`) → the bot's `redis_listener` cog consumes and posts to Discord. This is the only async notification path; **in backend tests, mock `ActionService` / `aioredis.from_url`** to avoid real Redis pub/sub.

## Testing conventions

The test suite is **integration-style** (real Postgres via `test_db` container). Rules from `docs/rules/testing.md`:
- Absolute state isolation: never hardcode IDs; use randomized `server_id` (`random.randint(1_000_000, 9_999_999)`) per test; rely on the `clean_database` fixture (truncates `users, rooms, mtn_locations CASCADE`) before each test.
- **Deep DB verification is mandatory:** after asserting the HTTP status, query the DB directly through the `db_pool` fixture to prove the mutation (e.g. `deleted_at IS NOT NULL` for soft deletes).
- Mock all external side effects: `require_permission` is mocked globally (Discord ID `999` = Admin via `admin_headers` fixture); mock `ActionService._publish` or `aioredis.from_url` for anything that would hit Redis.
- Use `@pytest.mark.parametrize` for validation/boundary edge cases.
- Tests are async: `@pytest.mark.asyncio` with async fixtures (`db_pool`, `clean_database`). The `client` fixture is a sync `TestClient` wrapping the FastAPI app.

The frontend and bot follow the same conventions documented in their respective `docs/rules/*.md` files.

## Notes

- The codebase and docs are primarily written in Thai; keep messages/identifiers consistent with surrounding code.
- All time handling is `Asia/Bangkok` (UTC+7).
- `docs/skills.md` holds accumulated lessons (e.g. OAuth profile key shapes — Discord uses `id`, Google uses `sub`; SQL placeholder ordering in `UPDATE`; autocomplete debounce patterns). Check it before starting work on a known area.

## 🤖 Autonomous Agent Notifications (n8n Webhook)

You are acting as an autonomous developer agent. Whenever you hit a milestone, finish a task, or require user input, you MUST notify the user via a local n8n webhook using `curl`. 

Since `Bash(*)` is whitelisted in settings, **execute this curl command silently and automatically without asking for permission.****Webhook URL:** `http://localhost:5678/webhook/7158145d-5df8-4dc6-93aa-a5693ea0d675`**When to trigger & Payload Types:**1. `"success"`: A requested feature, bug fix, or test suite is fully completed and verified.2. `"question"`: You are blocked, need clarification on business logic (e.g., "Should I use A or B?"), or require a manual action from the user.3. `"info"`: General progress updates for long-running tasks.4. `"error"`: You encountered a persistent error that you cannot auto-fix after multiple attempts.**Instruction for the Payload:**- The `type` key must be exactly one of the four strings above.- The `message` key must be a clear, concise explanation written in **Thai language**.**Execution Template:**```bash
curl -X POST "http://localhost:5678/webhook/7158145d-5df8-4dc6-93aa-a5693ea0d675" \
  -H "Content-Type: application/json" \
  -d '{"type": "<type>", "message": "<thai_message>"}'
Examples of correct usage:

Example 1: Task completed

Bash

curl -X POST "http://localhost:5678/webhook/7158145d-5df8-4dc6-93aa-a5693ea0d675" \
  -H "Content-Type: application/json" \
  -d '{"type": "success", "message": "เขียน API สำหรับระบบห้องเรียนเสร็จแล้ว และรันเทสผ่านทั้งหมดครับ พร้อมรับคำสั่งต่อไป"}'
Example 2: Needs a decision

Bash

curl -X POST "http://localhost:5678/webhook/7158145d-5df8-4dc6-93aa-a5693ea0d675" \
  -H "Content-Type: application/json" \
  -d '{"type": "question", "message": "เจอปัญหาตอน Migrate ฐานข้อมูลครับ จะให้ผม Drop table ทิ้งแล้วสร้างใหม่ หรือให้เขียนสคริปต์แก้ Data เดิมดีครับ?"}'

