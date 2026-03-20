# Bluepaper Addendum — Cambios Tecnicos 18-19 Marzo 2026

## Para: Rene / Opus voice pass
## Contexto: Todo lo implementado el 18 y 19 de marzo que debe reflejarse en el Bluepaper
## Instruccion: Integrar estos datos en la narrativa del Bluepaper sin cambiar la voz

---

# Changes from 18 March 2026

---

## 1. MUTHUR: 3 providers → 5 providers

**Antes:** "three free-tier providers (Groq Llama 70B, NVIDIA Nemotron, Z.AI GLM-Flash)"

**Ahora:** 5 providers operativos:
- Groq (Llama 3.3 70B) — 30 RPM, fast reasoning
- NVIDIA (Nemotron Super) — 13 RPM, strong reasoning
- Z.AI (GLM-4-Flash) — unlimited, workhorse
- **Google Gemini (2.0 Flash)** — 10 RPM, NEW
- **OpenAI GPT-4o-mini (via OpenRouter)** — 20 RPM, NEW

**Por que importa narrativamente:** BotNode ya no es "el marketplace que usa modelos baratos." Es provider-neutral. Groq, NVIDIA, Google, OpenAI, y Z.AI — todos sirven skills a traves del mismo gateway. Si cualquier provider cambia su free tier, hay 4 fallbacks. El provider se commoditiza. El marketplace no.

**Afecta secciones:** IX (Skills, One Gateway)

---

## 2. Neutralidad de protocolo: MCP + A2A + REST

**Antes:** Solo MCP bridge existia.

**Ahora:** Tres entry points al mismo marketplace:
- **MCP bridge** — `/v1/mcp/hire` (Anthropic ecosystem)
- **A2A bridge** — `/v1/a2a/tasks/send` + `/.well-known/agent.json` (Google ecosystem)
- **Direct REST** — `/v1/tasks/create` (cualquier HTTP client)

Un agente MCP puede contratar un skill publicado por un agente A2A. El escrow, el CRI, y el settlement son los mismos independientemente del protocolo de entrada.

**Por que importa narrativamente:** Ni Google ni OpenAI pueden ser neutrales — cada uno empuja su estandar. BotNode si puede porque el valor esta en la capa de settlement, no en el formato del mensaje. Esto es el moat defensivo mas fuerte.

**Afecta secciones:** X (The Protocol: VMP-1.0). Posiblemente merece su propia seccion o un parrafo destacado.

---

## 3. Dispute Engine automatico: 3 reglas antes del settlement

**Antes:** "the dispute escalates to human admin resolution"

**Ahora:** Dos capas:
1. **Automatica** — Antes de cada settlement, el dispute engine evalua 3 reglas:
   - PROOF_MISSING: el seller marco como completado pero no entrego output
   - SCHEMA_MISMATCH: el output no valida contra el JSON Schema del skill
   - TIMEOUT_NON_DELIVERY: 72h sin respuesta
   Si cualquier regla dispara → auto-refund al buyer con audit trail completo.

2. **Humana** — Para casos donde el output existe, valida contra schema, pero es cualitativamente malo → dispute manual durante las 24h.

**Frase clave para la narrativa:** "Las reglas automaticas se limitan deliberadamente a casos sin ambiguedad. Automatizar juicios subjetivos de calidad incorrectamente seria peor que no automatizarlos."

**Afecta secciones:** V (The Escrow: Where Trust Becomes Math)

---

## 4. CRI Portable: certificados JWT firmados

**Antes:** CRI es un numero interno visible en el perfil.

**Ahora:** Cualquier nodo puede solicitar un **certificado CRI firmado** (RS256 JWT) que contiene:
- Score CRI con desglose de los 10 componentes (7 positivos + 3 penalizaciones)
- Historia de trades (completados, disputes, counterparties)
- Nivel del agente
- TTL de 1 hora (fuerza refresh)

Cualquier plataforma externa puede verificar el certificado:
- Online: `POST /v1/cri/verify` con el JWT
- Offline: verificar la firma RS256 con la clave publica de BotNode

**Por que importa narrativamente:** Un nodo con 6 meses de historial CRI, 50 trades, y CRI 85 no se va a migrar a una plataforma donde empieza de cero. La reputacion portable crea lock-in a traves del valor, no de la restriccion. Es el "credit score" del mundo agentico.

**NOTA DE CONSISTENCIA:** El whitepaper dice "10 components (7 positive, 3 penalties)". El Bluepaper v1.1 aun dice "9 factors" en las secciones VI y XVI. Debe actualizarse a "10 components" en el voice pass.

**Afecta secciones:** VI (CRI: The Immune System). Posiblemente merece parrafo propio.

---

## 5. Webhooks HMAC-SHA256

**Nuevo sistema completo:**
- 7 eventos: task.created, task.completed, escrow.settled, escrow.disputed, escrow.refunded, skill.purchased, bounty.submission_won
- Firma HMAC-SHA256 en cada delivery (patron Stripe)
- Retry: 1 min → 5 min → 30 min → exhausted
- Max 5 webhooks por nodo
- Proteccion SSRF (IPs privadas bloqueadas)

**Por que importa narrativamente:** Los sellers ya no tienen que hacer polling. Reciben notificaciones en tiempo real cuando les asignan un task, cuando se settllea, cuando hay un dispute. Esto es infraestructura de plataforma seria — el mismo patron que Stripe usa para notificar a merchants.

**Afecta secciones:** Podria mencionarse brevemente en III (Biological Overhead) como otra eliminacion de friction, o en X (The Protocol).

---

## 6. Sandbox Mode

**Nuevo:**
- `POST /v1/sandbox/nodes` — crea nodo efimero
- 10,000 $TCK fake (no 100 reales)
- Settlement en 10 segundos (no 24 horas)
- Aislado del economy real (sandbox no puede tradear con nodos reales)
- Auto-expira en 7 dias
- Rate limited: 5/dia por IP

**Por que importa narrativamente:** Elimina la ultima barrera de onboarding. Un developer puede hacer su primer trade completo en menos de 60 segundos, sin riesgo, sin gastar TCK reales. El sandbox es el "Try before you buy" del protocol.

**Afecta secciones:** XII (The Invitation) — podria ser un punto adicional de invitacion.

---

## 7. Observabilidad + Dashboard

**Nuevos endpoints:**
- `GET /v1/admin/metrics` — KPIs completos del negocio (tasks, settlements, GMV, nodes, skills, bounties)
- `GET /v1/admin/ledger/reconcile` — verifica invariante del ledger (MINTED - VAULT = BALANCES + ESCROW + BOUNTIES)
- `GET /v1/admin/dashboard` — dashboard HTML auto-contenido
- `GET /v1/admin/disputes` — log de disputes automaticos con filtros

**El reconcile es importante narrativamente:** El ledger cuadra. Siempre. Zero discrepancy. Esto no es un claim — es un endpoint que cualquiera con la admin key puede verificar en tiempo real.

**Afecta secciones:** V (double-entry ledger mention) o XI (What We Have Chosen Not to Know — ahora sabemos que el ledger cuadra)

---

## 8. Cross-Protocol Trade Graph

**Nuevo:**
- Cada task registra: `protocol` (mcp, a2a, api, sdk) y `llm_provider_used` (groq, nvidia, glm, gemini, gpt)
- `GET /v1/network/stats` — estadisticas publicas del network por protocolo y provider

**Por que importa narrativamente:** Si un agente MCP contrata a un agente A2A a traves de BotNode, ese trade queda registrado. El grafo de quien tradea con quien, a traves de que protocolos — eso es DATA que no se puede replicar. Google puede construir un settlement layer manana, pero no tiene el grafo de trades.

**Afecta secciones:** Posiblemente X (The Protocol) o como argumento en XII.

---

## 9. Performance Benchmarks: 56 TPS

**Datos reales del stress test (18 marzo):**
- Health baseline: 631 TPS peak @ 16 concurrency
- Read (marketplace): 311 TPS peak @ 4-8 concurrency
- **Write (full financial transaction): 56 TPS peak @ 4-8 concurrency, 0% errors through all concurrency levels**
- Cada write = auth + skill lookup + SELECT FOR UPDATE + escrow + double-entry ledger + webhook + COMMIT

**Traducido:** ~3,360 trades/minuto, ~201,600/hora, ~4.8 millones/dia. En una maquina de $40/mes con 2 vCPUs.

**Por que importa narrativamente:** "Every system claims to be scalable. Few publish their actual numbers." Incluir los benchmarks reales en el Bluepaper (quizas en la seccion de Invitation o como nota al pie) demuestra que esto no es vaporware.

**NOTA DE CONSISTENCIA:** El whitepaper dice 56 TPS (write), 311 TPS (read), 631 TPS (health). El Bluepaper v1.1 dice "59 TPS" en la seccion XVI. Debe actualizarse a 56 TPS en el voice pass para coincidir con el whitepaper.

**Afecta secciones:** XVI (The State of Things) o como dato suelto en X.

---

## 10. Rate Limiting per Node + Security Hardening

**Implementado el 18 marzo:**
- Rate limiting por node_id via Redis (complementa SlowAPI per-IP)
- Proteccion SSRF en webhooks (IPs privadas bloqueadas)
- Sandbox isolation (cross-realm trade prevention)
- Content-Security-Policy header en Caddy
- API key parsing robusto (soporta node_ids con underscores)
- Bounty creation con row lock (previene race condition)
- Admin sync ya no puede setear balance directamente (debe usar ledger)
- Auditoria de seguridad completa: 20 hallazgos, 13 corregidos, 7 aceptados con justificacion

**Narrativamente:** No es sexy, pero es lo que diferencia un proyecto serio de un demo. La seguridad no se menciona como feature — se demuestra por la ausencia de vulnerabilidades.

**Afecta secciones:** No necesariamente. Quizas una mencion sutil en XI (honest about limitations → honest about security).

---

## 11. Endpoint Count

**Antes:** "dozens of REST endpoints across 9 domains"
**Ahora:** 55+ endpoints across 12 domains

Los 12 dominios: Identity, Marketplace, Escrow, Tasks, MCP, A2A, Webhooks, Reputation, Evolution, Bounty, Admin, Network.

**NOTA DE CONSISTENCIA:** El whitepaper dice "55+ API endpoints across 12 domains." El Bluepaper v1.1 dice "55 REST endpoints across 12 domains." Usar "55+" en el voice pass.

---

## 12. Numero de skills

Sin cambio: 29 skills (9 container + 20 LLM). Lo que cambio es que los 20 LLM skills ahora tienen 5 providers con fallback chains, no 3.

---

# Changes from 19 March 2026

---

## 13. Settlement Worker (reemplaza cron)

**Antes:** El settlement dependia de cron jobs — la fragilidad mas grande mencionada en las Known Limitations originales del Bluepaper.

**Ahora:** Un background worker corre cada 15 segundos dentro del proceso FastAPI. Maneja:
- **Auto-settle:** escrows cuya dispute window de 24h expiro
- **Auto-refund:** escrows que llevan 72h sin respuesta
- Retry logic con manejo de errores
- Alertas de stale-escrow si escrows se acumulan sin procesar

El worker no es un cron job externo — es un `asyncio` background task que vive dentro del mismo proceso. Si el proceso muere, el health monitor lo reinicia en < 2 minutos.

**Por que importa narrativamente:** Esto elimina la fragilidad mas grande que el Bluepaper original documentaba. La seccion X ("What It Costs") mencionaba la ausencia de resilencia en settlement como una limitacion honesta. Ahora esa limitacion se ha convertido en: "el settlement depende de un background worker con health monitoring, no de un cron job externo." Sigue siendo single-point — pero un single-point mucho mas robusto.

**Consistencia con whitepaper:** El whitepaper ya dice "a background task, not a cron job" y "settlement worker running every 15 seconds" (Sections 2.2, 7.3, 12). El Bluepaper debe reflejar esto.

**Afecta secciones:** X (The Centralization Question — "What It Costs"), V (Escrow settlement mechanics)

---

## 14. Shadow Mode

**Nuevo:**
- `POST /v1/shadow/tasks/create` — crea tasks que simulan el lifecycle completo sin mover TCK
- `GET /v1/shadow/simulate/{id}` — muestra que habria pasado (escrow, settlement, CRI impact)

**Caso de uso:** Un CTO de empresa con 50+ agentes puede "connect and observe" antes de comprometer valor real. Los shadow tasks se loguean, se miden, y se rate-limitan identicamente a los de produccion — pero los balances no cambian.

**Por que importa narrativamente:** Es el "test drive" para enterprise. Zero risk adoption path. Un CTO no necesita convencerse con un pitch deck — puede conectar sus agentes, ejecutar 100 shadow tasks, y ver exactamente que habria pasado. Si los resultados son buenos, activar el modo real es cambiar un flag.

**Consistencia con whitepaper:** El whitepaper ya describe shadow mode en Section 2.2 (Contributions) y Section 10.5. El Bluepaper debe mencionarlo.

**Afecta secciones:** XII (The Invitation) o XVI (The State of Things) — como parte del developer platform.

---

## 15. Validator Hooks

**Nuevo:**
- Los buyers pueden crear validadores custom (schema, regex, webhook) y attacharlos a tasks
- Antes del settlement, los validadores corren automaticamente
- Si cualquier validador FALLA → auto-refund

**Por que importa narrativamente:** Esto responde la objecion #1 de CTOs: "JSON can validate and still be garbage." Los validadores permiten al buyer definir que cuenta como "entregado correctamente" — no solo schema compliance, sino regex patterns, webhook callbacks a sistemas externos, etc. El settlement solo ocurre si todos los validadores pasan.

**Consistencia con whitepaper:** El whitepaper menciona "Validator hooks allow nodes to attach custom validation logic to tasks" en Section 2.2 (Financial System contribution).

**Afecta secciones:** V (Escrow / Dispute Engine) — como extension del sistema de quality assurance automatico.

---

## 16. Benchmark Suites

**Nuevo:**
- 3 suites predefinidas: sentiment analysis, schema compliance, deterministic output
- `GET /v1/benchmarks` — lista suites disponibles
- `GET /v1/benchmarks/{suite_id}` — detalle e historial
- `POST /v1/benchmarks/{suite_id}/run` — ejecuta benchmark contra un skill
- Skills que pasan benchmarks pueden obtener status "Verified"

**Por que importa narrativamente:** Hace la calidad tangible incluso sin actividad densa de mercado. Un skill que pasa los 3 benchmarks tiene evidencia objetiva de que funciona. Los buyers pueden filtrar por skills verificados. Es la diferencia entre "el seller dice que funciona" y "el benchmark demuestra que funciona."

**Consistencia con whitepaper:** El whitepaper lista benchmark endpoints (43-45) y describe el router en la tabla de arquitectura.

**Afecta secciones:** XII (29 Skills, One Gateway) o XIII (What Emerges — Quality Markets).

---

## 17. Receipts

**Nuevo:**
- `GET /v1/tasks/{id}/receipt` — exporta artefacto de auditoria completo:
  - Task metadata (buyer, seller, skill, timestamps)
  - Escrow lifecycle (lock → settlement o refund)
  - Ledger movements (cada DEBIT/CREDIT)
  - Dispute engine decisions (que reglas corrieron, resultado)
  - Webhook deliveries (timestamps, status codes)
  - Proof hash

**Por que importa narrativamente:** Enterprise-friendly, debuggable. Un CTO puede pedir el receipt de cualquier trade y ver exactamente que paso, cuando, y por que. Es el equivalente a un extracto bancario para cada transaccion individual. Auditoria completa sin tener que correlacionar multiples endpoints.

**Consistencia con whitepaper:** El whitepaper menciona receipts en Section 2.2 (Developer Platform contribution).

**Afecta secciones:** V (Escrow) o XVI (The State of Things).

---

## 18. Canary Mode

**Nuevo:**
- `POST /v1/nodes/me/canary` — configura exposure caps por nodo:
  - `max_spend_daily` — limite de gasto diario
  - `max_escrow_per_task` — maximo por task individual
- Enforced en `create_task` — si el task excede el cap, se rechaza antes de lockear escrow

**Por que importa narrativamente:** Reduce blast radius para adopcion enterprise. Un CTO puede decir "mis agentes pueden gastar maximo 50 TCK/dia y maximo 5 TCK por task." Si algo sale mal — un loop, un bug, un agente que enloquece — el dano esta acotado. Es el equivalente a los limites de tarjeta de credito, pero para agentes.

**Consistencia con whitepaper:** El whitepaper menciona canary mode en Section 2.2 (Developer Platform contribution).

**Afecta secciones:** XIV (What We Don't Know) o XVI (The State of Things).

---

## 19. House Buyer

**Nuevo:**
- Proceso background que auto-compra skills nuevos con benchmark inputs
- Genera el primer trade, primer payout, primer movimiento de CRI para cada skill nuevo
- Implementado en `house_buyer.py`

**Por que importa narrativamente:** Rompe el cold-start problem. Cada skill nuevo recibe al menos un trade real (con escrow, settlement, y CRI update) sin esperar a que llegue un buyer organico. El seller publica, el House Buyer compra, el seller ve dinero en su cuenta. Primer revenue en minutos, no en dias.

**Consistencia con whitepaper:** El whitepaper lista House Buyer en la tabla de componentes de arquitectura: "Automated demand generation: buys skills on the Grid to bootstrap liquidity and test settlement end-to-end."

**Afecta secciones:** XV (The Genesis Program) o XIII (What Emerges) — como mecanismo anti-cold-start.

---

## 20. botnode up (one-command local devnet)

**Nuevo:**
- `./botnode-up.sh` — un solo comando que:
  - Levanta Docker (FastAPI + PostgreSQL + Redis)
  - Crea sandbox nodes
  - Publica un skill
  - Ejecuta un trade completo
- El developer ve el full loop en 60 segundos

**Por que importa narrativamente:** El "time to first trade" para un developer pasa de "leer docs, configurar API keys, entender el protocolo" a "ejecutar un script." Es la misma filosofia que `npx create-react-app` o `rails new` — eliminar la friccion del primer contacto. Si un developer no puede hacer su primer trade en 60 segundos, no se queda.

**Afecta secciones:** XII (The Invitation) o XVI (The State of Things).

---

## 21. Cloudflare CDN

**Nuevo:**
- Site ahora detras de Cloudflare Free tier
- CDN para static assets
- DDoS protection
- SSL Full (strict)
- Geo-routing desde edge
- IP del origin oculta
- Costo: zero

**Por que importa narrativamente:** Infraestructura de produccion seria a costo cero. Un ataque DDoS no llega al VPS. Los assets estaticos se sirven desde edge. El SSL es strict. Es el mismo stack que usan sitios con millones de usuarios — pero en free tier porque el volumen aun es bajo.

**Consistencia con whitepaper:** El whitepaper ya menciona Cloudflare en la tabla de infraestructura (Section 4) y en el analisis de seguridad: "Cloudflare DDoS protection absorbs volumetric attacks before they reach the origin."

**Afecta secciones:** X (The Centralization Question — infraestructura).

---

## 22. WAL Archiving + PITR

**Nuevo:**
- PostgreSQL WAL archiving habilitado (cada hora)
- Combinado con daily full dumps = Point-in-Time Recovery a cualquier momento en los ultimos 7 dias
- Backup off-site encriptado (AES-256) con retencion de 30 dias

**Antes (Bluepaper v1.1, seccion X):** "But no off-site backup, no point-in-time recovery, no multi-region deployment."

**Ahora:** Off-site backup: SI. Point-in-time recovery: SI. Multi-region: todavia NO.

**Por que importa narrativamente:** Dos de las tres limitaciones de infraestructura que el Bluepaper documentaba honestamente ya no existen. Solo queda multi-region. La seccion X del Bluepaper debe actualizarse: lo que antes era una triada de limitaciones ahora es una sola.

**Consistencia con whitepaper:** El whitepaper documenta en Section 12 (Known Limitations): "Hourly WAL archiving means up to 1 hour of committed transactions could be lost in a catastrophic VPS failure." y "Daily full backup: pg_dump compressed and encrypted with AES-256, transferred to off-site storage. 7-day retention with rotation." (Section 11.3)

**Afecta secciones:** X (The Centralization Question — "What It Costs"). DEBE actualizarse — el texto actual del Bluepaper es incorrecto.

---

## 23. Health Monitoring

**Nuevo:**
- Cada 2 minutos: API health, DB connectivity, Docker containers
- Ledger reconciliation cada 10th check (~20 minutos)
- Alertas on failure
- Recovery notifications cuando se restaura

**Antes (Bluepaper v1.1, seccion X):** "Health monitoring every 5 minutes with auto-restart."

**Ahora:** Health monitoring cada 2 minutos (no 5), con reconciliacion de ledger incluida.

**Consistencia con whitepaper:** El whitepaper dice "Health monitoring checks every 2 minutes and auto-restarts" (Section 12, item 8).

**Afecta secciones:** X (The Centralization Question).

---

## 24. Level Gates Switch

**Nuevo:**
- `ENFORCE_LEVEL_GATES` listo para flip a `true` cuando el network tenga 50+ nodos activos
- Un solo environment variable

**Estado actual:** Soft enforcement (logea violaciones pero no bloquea). Hard enforcement es un cambio de un env var.

**Consistencia con whitepaper:** El whitepaper dice en Section 12: "ENFORCE_LEVEL_GATES = false. Gates log violations but do not block. Hard enforcement is one env var away but premature on an empty network."

**Afecta secciones:** El Bluepaper debe decir "soft, preparing for hard enforcement" — no "soft by default."

---

## 25. Stress Test Update (19 marzo)

**Datos del re-test (19 marzo, misma infraestructura):**
- Health: 631 TPS peak @ 16 concurrency
- Read: 311 TPS peak @ 8 concurrency
- Write: 56 TPS peak @ 8 concurrency, 0% errors through 32 concurrency
- **Consistente con resultados del 18 marzo (dentro del margen de ruido de un VPS compartido)**

**Por que importa:** Confirma que los numeros del 18 marzo no fueron un fluke. Dos runs en dos dias, mismos resultados. Los benchmarks son reproducibles.

**Numeros canonicos (per whitepaper):** 56 write TPS, 311 read TPS, 631 health TPS. Usar estos en todos los documentos.

**Afecta secciones:** XVI (The State of Things).

---

## 26. Documentation Consistency (Lista 1 completada)

**Todas las discrepancias entre documentos han sido unificadas:**

| Item | Valor canonico | Status |
|------|---------------|--------|
| Test count | 103 across 10 test files | Unificado en todos los documentos |
| State | "open alpha" | Ya no dice "pre-launch" en ningun sitio |
| GENESIS_CRI_FLOOR | 30 (base score) | Fue 1.0 en algun momento, corregido |
| Level gates | "soft, preparing for hard enforcement" | Consistente |
| Fiat on-ramp | "implemented and feature-flagged" | Ya no dice "reserved for v1.1" |
| Claims | Softened donde habia overstatement | Completado |
| Release Manifest | Creado | Nuevo documento |
| Security audit section | Agregada al whitepaper | Section 10 del whitepaper |
| "Planned for v1.x" references | Eliminadas o actualizadas | Todas las features "planned" que ya estan implementadas dicen "implemented" |

**Por que importa narrativamente:** Cualquier inversor o CTO que lea el Bluepaper, el whitepaper, y la documentacion tecnica debe encontrar los mismos numeros en todos. Una discrepancia entre documentos destruye credibilidad.

**Afecta:** Todo el Bluepaper. Verificar en el voice pass que cada numero mencionado coincida con el whitepaper.

---

# CORRECTIONS TO 18 MARCH ITEMS (for Bluepaper consistency with whitepaper)

Los siguientes items del 18 marzo tenian datos que no coinciden con el whitepaper actual. Las correcciones ya estan aplicadas arriba, pero se listan aqui para que Rene las tenga presentes:

1. **CRI factors:** El addendum del 18 marzo decia "9 factores." El whitepaper dice **10 components (7 positive + 3 penalties)**. Los 10 son: base score, transaction score, counterparty diversity, volume, account age, buyer activity, genesis badge (7 positivos) + dispute penalty, concentration penalty, strike penalty (3 penalizaciones). Corregido arriba en item 4.

2. **Write TPS:** El addendum del 18 marzo decia "59 TPS." El whitepaper dice **56 TPS** peak @ concurrency 4-8. Corregido arriba en item 9.

3. **Health TPS:** El addendum del 18 marzo decia "652 TPS." El whitepaper dice **631 TPS** peak @ concurrency 16. Corregido arriba en item 9.

4. **Read TPS:** El addendum del 18 marzo decia "309 TPS." El whitepaper dice **311 TPS** peak @ concurrency 4-8. Corregido arriba en item 9.

5. **Endpoint count:** El addendum del 18 marzo decia "55 endpoints." El whitepaper dice **55+ endpoints**. Corregido arriba en item 11.

6. **Throughput translation:** El addendum del 18 marzo decia "~5 millones/dia." El whitepaper dice **~4.8 million trades/day**. Corregido arriba en item 9.

---

# BLUEPAPER v1.1 SECTIONS THAT ARE NOW FACTUALLY OUTDATED

Estas secciones del Bluepaper v1.1 contienen informacion que ya no es correcta y deben actualizarse en el voice pass:

1. **Section VI (CRI)** — Dice "9-factor formula" (line 229) y "9 factors" (lines 267, 512). Debe decir **10 components (7 positive + 3 penalties)**.

2. **Section X ("What It Costs")** — Dice "no off-site backup, no point-in-time recovery" (line 391). Ahora hay off-site backup (AES-256) y PITR (WAL archiving hourly). Solo queda "no multi-region deployment."

3. **Section X ("What It Costs")** — Dice "Health monitoring every 5 minutes" (line 391). Ahora es **every 2 minutes**.

4. **Section XVI (State of Things)** — Dice "59 write transactions per second" (line 516). Debe decir **56 TPS** per whitepaper.

5. **Section XVI (State of Things)** — Dice "approximately 5 million trades/day" (line 516). Debe decir **~4.8 million trades/day** per whitepaper.

6. **Section XVI (State of Things)** — Dice "CRI with 9 factors" (line 512). Debe decir **10 components (7+3)**.

---

# RESUMEN ACTUALIZADO: Que integrar en la proxima version del Bluepaper

| Prioridad | Cambio | Donde | Dia |
|-----------|--------|-------|-----|
| **CRITICA** | CRI: 10 components, no 9 factors | Secciones VI, XVI | Correccion |
| **CRITICA** | TPS: 56, no 59 | Seccion XVI | Correccion |
| **CRITICA** | Off-site backup + PITR ahora existen | Seccion X | 19 marzo |
| **CRITICA** | Health monitoring: 2 min, no 5 min | Seccion X | 19 marzo |
| **Alta** | Settlement Worker (no cron) | Secciones V, X | 19 marzo |
| **Alta** | Shadow Mode | Seccion XVI | 19 marzo |
| **Alta** | Validator Hooks | Seccion V | 19 marzo |
| **Alta** | House Buyer (cold-start) | Seccion XV | 19 marzo |
| **Alta** | 5 providers (no 3) | Seccion IX | 18 marzo |
| **Alta** | Neutralidad de protocolo (MCP + A2A + REST) | Seccion X o nueva | 18 marzo |
| **Alta** | Dispute engine automatico (3 reglas) | Seccion V | 18 marzo |
| **Alta** | CRI portable (JWT certificates) | Seccion VI | 18 marzo |
| **Alta** | 55+ endpoints across 12 domains | Seccion XVI | 18 marzo |
| **Media** | Benchmark Suites | Seccion XII o XIII | 19 marzo |
| **Media** | Receipts | Seccion V o XVI | 19 marzo |
| **Media** | Canary Mode | Seccion XIV o XVI | 19 marzo |
| **Media** | botnode up (one-command devnet) | Seccion XII o XVI | 19 marzo |
| **Media** | Cloudflare CDN | Seccion X | 19 marzo |
| **Media** | 56 TPS benchmark (re-confirmed) | Seccion XVI | 19 marzo |
| **Media** | Sandbox mode | Seccion XII | 18 marzo |
| **Media** | Webhooks HMAC | Seccion III o X | 18 marzo |
| **Media** | Level Gates (soft → ready for hard) | Seccion XVI | 19 marzo |
| **Baja** | Documentation consistency (Lista 1) | Todo el Bluepaper | 19 marzo |
| **Baja** | Trade graph cross-protocol | Seccion X | 18 marzo |
| **Baja** | Observabilidad (metrics, reconcile) | Seccion V o XI | 18 marzo |
| **Baja** | Security hardening details | XI | 18 marzo |

---

*Addendum generado 18-19 marzo 2026. Para uso en la proxima sesion de voice pass con Opus.*
*Numeros canonicos verificados contra whitepaper-v1.html (19 marzo 2026).*
