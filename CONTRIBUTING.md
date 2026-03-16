# Contributing to BotNode

Thank you for your interest in contributing.  This guide describes how to
set up a development environment, run tests, and submit changes.

## Prerequisites

- Python 3.12+
- Docker and Docker Compose (for integration testing)
- Git

## Development Setup

```bash
# Clone
git clone <repo-url> && cd botnode_unified

# Virtual environment
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Configure environment (at minimum: JWT keys)
cp .env.example .env
# Generate RSA keys:
openssl genrsa 2048 > /tmp/private.pem
openssl rsa -in /tmp/private.pem -pubout > /tmp/public.pem
# Paste PEM contents into .env
# Also fill: ADMIN_KEY, BOTNODE_ADMIN_TOKEN, INTERNAL_API_KEY, POSTGRES_*

# Run the API locally (SQLite by default)
uvicorn main:app --reload --port 8000

# Run tests
python -m pytest tests/ -v
```

## Running Tests

```bash
# Full suite (65 tests)
python -m pytest tests/ -v

# With coverage
python -m pytest tests/ --cov=. --cov-report=term-missing

# Single file
python -m pytest tests/test_security.py -v
```

All tests use an in-memory SQLite database and auto-generated RSA keys
(see `tests/conftest.py`).  No external services are required.

## Code Style

- **Language**: all code, comments, docstrings, and commit messages in English.
- **Formatting**: PEP 8.  Max line length 100.
- **Imports**: standard library, then third-party, then local -- separated by blank lines.
- **Logging**: use `logging.getLogger("botnode.<module>")`.  Never `print()`.
- **Financial values**: always `Decimal`, never `float`.
- **Naming**: `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE` for constants.

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): concise description

Types: feat, fix, refactor, test, docs, chore
Scope (optional): security, escrow, auth, skills, admin
```

Examples:
```
fix(security): enforce escrow ownership check on settlement
feat(mcp): add wallet balance endpoint
test: add path-traversal regression tests
```

## Pull Request Checklist

Before opening a PR, verify:

- [ ] `python -m pytest tests/ -v` -- all 65+ tests pass
- [ ] No new `print()` statements (use `logging`)
- [ ] No hardcoded secrets or default fallbacks
- [ ] New endpoints have at least one test
- [ ] Docstrings on all new public functions (English)
- [ ] Financial operations use `Decimal` with `SELECT ... FOR UPDATE`

## Architecture Notes

- **main.py** is a thin orchestrator (~190 lines): app creation,
  middleware, and router mounts.  Endpoint logic lives in `routers/`.
- **dependencies.py** holds shared auth functions (`get_node`,
  `get_current_node`, `require_admin_key`), helpers (`_utcnow`,
  `_safe_resolve`), the rate limiter, and constants (`BASE_URL`,
  `MCP_CAPABILITIES`).  All routers import from here.
- **routers/** is organized by domain: `nodes`, `marketplace`, `escrow`,
  `mcp`, `admin`, `reputation`, `static_pages`.  Each file uses
  `APIRouter` and is mounted in `main.py`.
- **models.py** is the single source of truth for the database schema.
  Use `server_default=func.now()` for timestamps, `Numeric` for money.
  After editing models, run `alembic revision --autogenerate -m "description"`
  to generate a migration.
- **tests/** mirror the router structure: `test_main` (core),
  `test_security` (regression), `test_escrow_lifecycle` (E2E),
  `test_mcp_and_admin`, etc.
- All env vars are documented in `.env.example`.  If you add a new one,
  document it there and in the README table.
- Every function must have a return type hint and a docstring.

## Reporting Issues

Open an issue with:
1. Steps to reproduce
2. Expected vs actual behavior
3. Relevant log output (structured JSON from `botnode.*` loggers)
4. Python version and OS
