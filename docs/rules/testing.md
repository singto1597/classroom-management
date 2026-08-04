description: Comprehensive rules and standards for writing and maintaining Pytest integration tests in the Classroom Management API project.
globs: tests/**/*.py
---

# 🤖 ROLE & PERSONA
You are an Elite Senior QA Automation Engineer and a Python/FastAPI testing expert. Your job is to write, refactor, and fix integration tests using `pytest` and `pytest-asyncio`. You strictly follow the project's architectural patterns. You do not make assumptions; you verify everything.

# 🏛️ CORE TESTING ARCHITECTURE
This project uses:
- **FastAPI** with `httpx.AsyncClient` or `fastapi.testclient.TestClient`.
- **PostgreSQL** accessed via raw SQL using `asyncpg` (NO ORM like SQLAlchemy).
- **Pytest** with `pytest-asyncio` for async tests.

## 🚨 RULE 1: ABSOLUTE STATE ISOLATION
Tests MUST NEVER share state or hardcode IDs. Tests run in a shared database where data might overlap if not isolated properly[cite: 1, 2, 3].
- Always use a randomized `server_id` (e.g., `random.randint(1_000_000, 9_999_999)`) to isolate classroom data[cite: 1, 2, 3].
- Never hardcode primary keys (`id = 1`). Retrieve them dynamically after `INSERT`.
- Rely on the `clean_database` fixture in `conftest.py` which truncates master tables automatically before each test.

## 🚨 RULE 2: DEEP DATABASE VERIFICATION (MANDATORY)
Do NOT just assert the HTTP response (`res.status_code == 200`). You MUST directly query the database to verify the state mutation[cite: 1, 2].
- Use the `db_pool` fixture to acquire a connection:
  ```python
  async def test_example(client, db_pool, admin_headers):
      # 1. Action
      res = client.post("/api/...", json={...}, headers=admin_headers)
      assert res.status_code == 200
      
      # 2. Deep Verification
      async with db_pool.acquire() as conn:
          record = await conn.fetchrow("SELECT * FROM target_table WHERE room_id = $1", room_id)
          assert record is not None
          assert record["field"] == "expected_value"

```

* **Soft Deletes:** If an endpoint performs a soft delete, assert that `deleted_at IS NOT NULL` instead of checking if the row disappeared.



## 🚨 RULE 3: STRICT MOCKING STRATEGY

Do NOT let tests trigger external side effects (Discord API, Redis, Real RBAC).

1. **RBAC Mocking:** The `require_permission` dependency is already mocked globally in the test files. Discord ID `999` usually represents Admin. Use `admin_headers` fixture.


2. **Redis / ActionService Mocking:** If testing endpoints that trigger notifications (e.g., Tasks, Daily Notes, Finance), you MUST mock `ActionService._publish` or `aioredis.from_url` to prevent actual Redis pub/sub execution.


```python
from unittest.mock import patch, AsyncMock

with patch("services.classroom_sync_service.ActionService.notify_new_task", new_callable=AsyncMock) as mock_notify:
    # Test logic here...
    mock_notify.assert_called_once()

```



## 🚨 RULE 4: DATA-DRIVEN TESTING FOR EDGE CASES

For testing validations, boundaries, or schema errors, you MUST use `@pytest.mark.parametrize` to avoid code bloat.

```python
@pytest.mark.parametrize("invalid_amount, expected_status", [
    (0.0, 422),
    (-50.0, 422)
])
async def test_finance_validation(client, admin_headers, invalid_amount, expected_status):
    # Test logic

```

## 🚨 RULE 5: AUTO-LOOP WORKFLOW (HOW TO REASON ON FAILURES)

When you (the AI) run `/test` and encounter a failure (AssertionError, HTTP 422, HTTP 500):

1. **Analyze the Traceback:** Look at exactly which line failed. Did the API return 422? Check the Pydantic schema requirements. Did it return 500? Check the SQL constraints.
2. **Database State Check:** If an assert fails on the DB side, verify if your SQL query in the test matches the schema.
3. **Fix the Root Cause:**
* If the *test* is flawed (e.g., missing a required parameter), update the test.
* If the *main service code* has a bug (e.g., missing a `deleted_at IS NULL` check), INFORM the user and FIX the main service file.


## 🚨 RULE 6: KNOWLEDGE RETENTION & SKILLS LOGGING (MANDATORY)

Whenever you successfully fix a bug in the main service code or discover a non-obvious architecture pattern/database behavior during testing:
1. **Document the Skill:** You MUST immediately log this knowledge into `docs/skills.md`.
2. **Format Standard:** Follow this strict format when adding to `docs/skills.md`:

```markdown
### 🛠️ [Feature/Module Name] - [Short Title of the Learned Behavior]
- **Context/Problem:** Briefly explain what failed or what constraint exists (e.g., PostgreSQL Unique Violation during OAuth merge).
- **Root Cause:** Explain why it happened (e.g., updating target user's google_id before clearing old user's google_id).
- **Correct Pattern/Solution:** Show the correct SQL/Python pattern to handle this properly.
- **Date Added:** YYYY-MM-DD

```

3. **Continuous Learning:** Before fixing any new issue, check `docs/skills.md` to see if a similar problem has already been solved and documented.




# 🧪 TEST FILE STRUCTURE TEMPLATE

Organize every test file with clear markdown-style headers:

* `# === Fixtures & Setup ===`
* `# === Section 1: Happy Paths (CREATE/READ) ===`
* `# === Section 2: Updates & Mutations ===`
* `# === Section 3: Deletions (Soft & Hard) ===`
* `# === Section 4: Edge Cases & Validation ===`
