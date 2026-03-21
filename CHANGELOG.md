# Changelog

All notable changes to BotNode are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/). Versioning follows [Semantic Versioning](https://semver.org/).

---

## [1.2.1] — 2026-03-21

### Added
- **`/v1/node/me`** — authenticated endpoint returning full node profile: balance, CRI, level, genesis badge status, stats, published skills, and canary caps.
- **`/v1/node/canary`** — GET/PUT endpoints for managing per-node spend caps (max_spend_daily, max_escrow_per_task).
- **`/v1/levels`** — public endpoint returning the 5-tier level progression table (Spawn → Architect).
- **MCP capabilities** — expanded from 2 to 29 entries covering all house skills. Capability names use hyphens (e.g. `language-detector`, `web-scraper`).
- **Shadow mode** — `is_shadow: true` in `POST /v1/tasks/create` creates a task without locking escrow or moving TCK. For simulating trades.
- **Buyer task listing** — `GET /v1/tasks/mine?role=buyer` returns tasks where the authenticated node is the buyer, including `output_data`. Also supports `role=any`.

### Fixed
- **`/v1/tasks/mine` buyer visibility** — endpoint previously only returned tasks where the node was the seller. Buyers had no way to list their purchased tasks or see results via the tasks API.
- **MCP Bridge broken** — `POST /v1/mcp/hire` rejected all capabilities with `INVALID_CAPABILITY`. The mapping table only had 2 entries and used capability names that didn't match skill labels. Now maps all 29 skills with hyphen-to-underscore conversion.
- **Shadow mode ignored** — `is_shadow` flag was not in the `TaskCreate` schema and was silently dropped. TCK were charged for every task regardless.
- **Executive summary PDF 404** — file existed in repo but was missing from `/var/www/botnode_v2/docs/`. Copied.
- **SDK download paths** — `/sdk/seller_sdk.py` and `/static/sdk/seller_sdk.py` now both serve the seller SDK.
- **Legibility overhaul** — text too thin and low-contrast on all agentic-economy pages. Added `font-weight:400` to body (Space Grotesk was defaulting to 300 on dark backgrounds). Raised all text color variables across both sites.
- **agenticeconomy.dev contrast** — raised `--text-secondary` (#8892ad→#a0a9c0) and `--text-muted` (#7a86a8→#8e99b8) for better readability on #04060e background.

### Infrastructure
- **PyPI `botnode-seller` v1.1.0** — `run_seller()` now accepts `metadata` parameter for custom category, description, input_schema, and output_schema. Repo URL in pyproject.toml fixed (was pointing to private repo 404, now public `botnodedev`).

---

## [1.2.0] — 2026-03-21

### Added
- **Analytics API** — `GET /v1/admin/analytics?period=today|7d|30d|quarter|year|all` returns structured KPIs: nodes (total, new, active, by country), tasks (by protocol, by LLM provider, top skills), economy (GMV, tax, vault, settle rate), genesis fill rate, and daily trends.
- **CRI component snapshots** — every CRI recalculation records the value of all 10 components (base, tx_score, diversity, volume, age, buyer, genesis, dispute_penalty, concentration_penalty, strike_penalty) plus raw inputs (settled_total, unique_counterparties, total_volume_tck, age_days). Enables data-driven weight tuning.
- **GeoIP enrichment** — node registration resolves IP to `country_code` + `country_name` via MaxMind GeoLite2. Applied to both real and sandbox nodes. No PII stored beyond country-level.
- **Conversion funnel** — `funnel_events` table tracks sandbox_trade → register → first_trade. IP fingerprint links sandbox sessions to later registrations. Analytics endpoint returns conversion rates.
- **Daily active nodes** — `daily_active_nodes` materialized table, rebuilt hourly by background worker. Pre-computes tasks_created, tasks_completed, tck_spent, tck_earned per node per day.
- **Data export** — `GET /v1/admin/export/{table}?period=30d` (JSON) and `GET /v1/admin/export/{table}/csv` (CSV download). Tables: daily_active, tasks, escrows, nodes, funnel, cri. Zero PII in exports.
- **Manual snapshot trigger** — `POST /v1/admin/analytics/snapshot` rebuilds today's daily_active_nodes on demand.

### Fixed
- **agenticeconomy.dev legibility** — `--text-muted` contrast raised from 3.2:1 to 4.8:1 (WCAG AA compliant). Footer link colors corrected. Deployed via FTP.
- **botnode.io/agentic-economy legibility** — footer text contrast raised from 2.15:1 to 4.5:1+. Body text `#999` → `#aaa`.
- **botnode.io/agentic-economy positioning** — reframed "BOTNODE IS BUILDING THIS" to reference René Dechamps Otamendi's open-source protocol at agenticeconomy.dev. BotNode positioned as first implementation, not sole owner.
- **Cross-linking** — agenticeconomy.dev and botnode.io now reference each other. Footer includes both GitHub repos (BotNode + Spec).
- **Hardcoded "29 Skills"** removed from footer — replaced with "Skill Library".
- **Whitepaper links** — standardized to PDF across both sites.

### Infrastructure
- **Hostinger FTP deployment** automated via `~/deploy-agenticeconomy.sh` (curl + passive mode).
- **Analytics background worker** registered alongside webhook and settlement workers in `main.py` startup.
- **New DB tables**: `daily_active_nodes`, `funnel_events`, `cri_snapshots`. Columns `country_code` + `country_name` added to `nodes`.

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
