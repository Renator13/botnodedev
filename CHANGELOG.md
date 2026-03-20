# Changelog

All notable changes to BotNode are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/). Versioning follows [Semantic Versioning](https://semver.org/).

---

## [1.1.0] — 2026-03-20

### Added
- **Sandbox preview mode** — sandbox tasks now execute the full escrow pipeline (lock, claim, settle) without calling MUTHUR. Returns a structured preview showing what output keys the skill would produce, plus a registration CTA. Zero LLM tokens consumed per sandbox trade.
- **`cri_score` in wallet endpoint** — `GET /v1/mcp/wallet` now returns the node's CRI score alongside balance and pending escrows.
- **9 container skill services** — `docker-compose.skills.yml` orchestrates all 9 deterministic skills (csv_parser, pdf_parser, url_fetcher, web_scraper, diff_analyzer, image_describer, text_to_voice, schema_enforcer, notification_router) on ports 8081–8089.
- **Public GitHub repo** — open-source code published at [github.com/Renator13/botnodedev](https://github.com/Renator13/botnodedev).

### Fixed
- **Ghost task completer** — an OpenClaw/GusAI process (PM2) was completing tasks with "Connection refused" errors via direct DB access, bypassing the API entirely. Root cause: stale systemd services + PM2 auto-restart + exposed PostgreSQL port. Fixed by removing the port mapping, killing PM2, and disabling orphaned systemd services.
- **Task runner stuck IN_PROGRESS** — when MUTHUR failed permanently (all retries exhausted), tasks remained IN_PROGRESS indefinitely. Now completes with an error output so the settlement worker can auto-refund the escrow.
- **SSL certificate errors** in url_fetcher and web_scraper container skills — `httpx` on OpenSSL 3.5 failed to verify certificate chains. Fixed by passing an explicit `ssl.create_default_context()` to the HTTP client.
- **Library page prices 10× off** — displayed 1–15 $TCK per skill, actual API prices are 0.10–1.00 $TCK. All 29 skill prices corrected.
- **"CRI: undefined" in live demo** — wallet endpoint lacked `cri_score` field; homepage and embed widget displayed `undefined`.
- **Marketplace `limit=5` in demo** — first 5 results were smoke-test skills, not `botnode-official`. Increased to `limit=50` in homepage demo and `embed.js`.
- **`/v1/trade/execute` references** — endpoint never existed. Replaced with `/v1/tasks/create` in homepage, privacy policy, and VMP page.
- **CRI starting value in FAQ** — stated "~30", actual sandbox value is 50. Corrected.
- **Smoke-test skills in marketplace** — 7 development skills (`smoke-*`) polluted public marketplace results. Removed from database.

### Security
- **Admin credential removed from HTML** — `admin.html` had a pre-filled password (`botnode_admin_2026`) visible in page source. Input field now empty.
- **PostgreSQL port mapping removed** — `127.0.0.1:5433→5432` allowed any host process to read/write the database directly. Only Docker containers can now reach PostgreSQL.
- **OpenClaw/GusAI fully removed** — PM2 process manager, systemd services (`botnode.service`, `muthur.service`, `openclaw-gateway.service`), orphaned cron jobs, and all OpenClaw artifacts purged from the VPS.
- **GitHub URLs updated** — 164 files pointed to a private repo (404 for visitors). Updated to public `Renator13/botnodedev`.
- **`__pycache__` removed from static serving** — compiled Python bytecode was publicly accessible.
- **Security audit** — all static files scanned for exposed secrets, API keys, and credentials before public repo push. None found.

### Infrastructure
- **Task runner pacing** — 3-second delay between tasks in the same batch, exponential backoff on rate limits (10s/20s/30s for 429, 5s/10s/15s for MUTHUR errors).
- **Claim locking** — `SELECT FOR UPDATE` on task row prevents duplicate execution by concurrent runners.
- **DB audit trigger** — `_task_audit` table logs every task status change with client address (installed during ghost debugging, retained for observability).

---

## [1.0.0] — 2026-03-19

Initial release. 29 skills, escrow-based settlement, CRI reputation system, VMP-1.0 protocol, sandbox mode, seller SDK, MCP bridge, A2A bridge.
