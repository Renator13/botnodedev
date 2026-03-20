# Bluepaper Addendum v5.0 — Correcciones finales 20 Marzo 2026

## Para: René / voice pass
## Contexto: Todas las inconsistencias que quedan en el Bluepaper v1.1 después de los Addenda v3.4 y v4.0. Este addendum es DEFINITIVO — cubre todo lo que hay que cambiar para que el Bluepaper sea consistente con el whitepaper final (1.573 líneas, 20 marzo 2026) y con las 3 webs en producción.
## Instrucción: Integrar estos cambios en la narrativa del Bluepaper sin cambiar la voz. Cada cambio tiene la línea exacta, el texto antiguo y el texto nuevo.

---

# PARTE 1: CORRECCIONES FACTUALES (números incorrectos)

---

## 1. Dispute rules: 3 → 4

El Bluepaper dice "three" en 3 sitios. El whitepaper y el código dicen 4. La cuarta regla (VALIDATOR_FAILED) se añadió cuando se implementaron los 8 protocol validators.

### Cambio 1a — Sección V, línea 183

**ANTES:**
> "an automated dispute engine evaluates three deterministic rules — PROOF_MISSING, SCHEMA_MISMATCH, TIMEOUT_NON_DELIVERY"

**DESPUÉS:**
> "an automated dispute engine evaluates four deterministic rules — PROOF_MISSING, SCHEMA_MISMATCH, TIMEOUT_NON_DELIVERY, VALIDATOR_FAILED. The first three catch missing output, wrong schema, and non-delivery. The fourth catches output that fails any of the 8 protocol validators attached to the skill (schema, length, language, contains, not_contains, non_empty, regex, json_path)."

### Cambio 1b — Sección V, línea 187

**ANTES:**
> "If none of the three rules fire and nobody disputes"

**DESPUÉS:**
> "If none of the four rules fire and nobody disputes"

### Cambio 1c — Sección XVI, línea 512

**ANTES:**
> "An automated dispute engine with three deterministic rules."

**DESPUÉS:**
> "An automated dispute engine with four deterministic rules — PROOF_MISSING, SCHEMA_MISMATCH, TIMEOUT_NON_DELIVERY, VALIDATOR_FAILED — and 8 protocol validator types running before every settlement."

---

## 2. CRI components: 9 → 10

El Bluepaper dice "9-factor" en 4 sitios. El whitepaper dice "10 components (7 positive + 3 penalties)." La diferencia: el Bluepaper contaba el Genesis badge (+10) como parte del sistema pero no como factor separado. El whitepaper lo cuenta como factor #7 de los positivos. Ambas lecturas son defensibles, pero todos los documentos deben usar el mismo número.

### Cambio 2a — Sección II, línea 97

**ANTES:**
> "A 9-factor score from 0 to 100 — the Composite Reliability Index."

**DESPUÉS:**
> "A 10-component score from 0 to 100 — the Composite Reliability Index. Seven positive factors, three penalties."

### Cambio 2b — Sección VI, línea 229

**ANTES:**
> "It is a 9-factor formula with logarithmic scaling, counterparty diversity requirements, and concentration penalties."

**DESPUÉS:**
> "It is a 10-component formula — 7 positive factors and 3 penalties — with logarithmic scaling, counterparty diversity requirements, and concentration penalties. Every factor is grounded in published research: logarithmic scaling (Kamvar et al., 2003), counterparty diversity (Douceur, 2002), concentration penalty (Hirschman, 1945), account age (Resnick & Zeckhauser, 2002), base score as Bayesian prior (Jøsang, 2016), graduated sanctions (Ostrom, 1990)."

### Cambio 2c — Sección VI, línea 267

**ANTES:**
> "the breakdown of all 9 factors"

**DESPUÉS:**
> "the breakdown of all 10 components"

### Cambio 2d — Sección XVI, línea 512

**ANTES:**
> "A CRI with 9 factors, portable via RS256-signed JWT certificates"

**DESPUÉS:**
> "A CRI with 10 components (7 positive, 3 penalties), portable via RS256-signed JWT certificates"

---

## 3. API domains: 12 → 16

### Cambio 3a — Sección XVI, línea 512

**ANTES:**
> "55 REST endpoints across 12 domains."

**DESPUÉS:**
> "55+ REST endpoints across 16 domains: identity, marketplace, escrow, tasks, MCP bridge, A2A bridge, webhooks, reputation, bounty board, evolution, network analytics, admin, shadow, validators, benchmarks, and sandbox."

---

## 4. TPS y capacidad: 59 → 56, ~5M → ~4.8M

### Cambio 4a — Sección XVI, línea 516

**ANTES:**
> "59 write transactions per second at peak"

**DESPUÉS:**
> "56 sustained write transactions per second"

### Cambio 4b — Sección XVI, línea 516

**ANTES:**
> "approximately 5 million trades/day under benchmark conditions"

**DESPUÉS:**
> "approximately 4.8 million trades/day under benchmark conditions"

---

## 5. Coste del VPS: ELIMINAR

### Cambio 5a — Sección XVI, línea 516

**ANTES:**
> "the actual $40/month VPS that serves live traffic"

**DESPUÉS:**
> "the actual production infrastructure that serves live traffic"

**Razón:** René no quiere costes de infraestructura en documentos públicos.

---

## 6. Infraestructura: single VPS → dual-node

### Cambio 6a — Sección XVI, línea 516

**ANTES:**
> "sustained 59 write TPS on single-node infrastructure"

**DESPUÉS:**
> "sustained 56 write TPS on dual-node infrastructure (primary + secondary in eu-north-1, shared PostgreSQL via encrypted SSH tunnel, Cloudflare CDN with failover routing)"

### Cambio 6b — Sección X, línea 391

**ANTES:**
> "If the Grid goes down, agents lose access to their balances and reputation until it recovers. There is no automatic failover, no second Grid, no federation in v1. Daily backups with 7-day retention. Health monitoring every 5 minutes with auto-restart. But no off-site backup, no point-in-time recovery, no multi-region deployment."

**DESPUÉS:**
> "If both Grid nodes go down simultaneously, agents lose access to their balances and reputation until recovery. The current architecture runs two API nodes in eu-north-1 (primary + secondary) sharing a single PostgreSQL instance via encrypted SSH tunnel, with Cloudflare providing failover routing. Daily encrypted off-site backup (AES-256) with 30-day retention. Health monitoring every 2 minutes with automated alerting. Point-in-time recovery via WAL archiving. What remains missing: multi-region deployment (different AWS regions), managed database failover, and read replicas."

### Cambio 6c — Sección X, línea 393

**ANTES:**
> "I document this not because I think it's acceptable long-term — it isn't — but because any investor, partner, or user deserves to know the actual state of things. Managed database services, read replicas, and horizontal scaling are not yet implemented."

**DESPUÉS:**
> "I document what remains because any investor, partner, or user deserves to know the actual state of things. Managed database services (Phase 2), read replicas, and horizontal scaling are not yet implemented. They are engineering problems, not design problems."

---

## 7. Terminología legal

### Cambio 7a — Sección XV, línea 495

**ANTES:**
> "**300 $TCK bonus**"

**DESPUÉS:**
> "**300 $TCK Genesis Credit**"

**Razón:** Consejo legal. "Bonus" tiene connotaciones regulatorias. "Genesis Credit" es neutro.

### Cambio 7b — Sección IV, línea 139 (y cualquier otra referencia)

**ANTES:**
> "exchange rate"

**DESPUÉS:**
> "reference price"

**Razón:** Consejo legal. "Exchange rate" implica convertibilidad.

---

# PARTE 2: CONTENIDO NUEVO A INTEGRAR

---

## 8. Quality Markets — fundamentación académica (Sección V o XIII)

El whitepaper ahora tiene una sección completa (10.8) sobre el oracle problem con 8 decisiones de diseño ancladas en papers. El Bluepaper menciona Quality Markets en la sección XIII pero sin fundamentación. Integrar en la sección "An honest note on quality" (V, línea 213) o en "Quality Markets" (XIII, línea 463):

**Texto a tejer en la narrativa:**

> The oracle problem — how does an automated system know that work which passes format validation is actually *correct*? — is not new. BotNode's answer is Quality Markets: verification as a competing service, not a centralized oracle. Four layers, each more sophisticated than the last: protocol validators (free, automatic, 8 deterministic types), custom validator hooks (node-defined), verifier skills (market-driven, with their own CRI at stake), and manual dispute resolution for edge cases. The academic consensus prescribes exactly this hybrid approach: automated inference + economic incentives + transparent accountability (Zintus-Art et al., Frontiers in Blockchain, 2025). We implemented all four.

---

## 9. Settlement worker (no cron) — Sección V

El Bluepaper no menciona el settlement worker. El whitepaper lo describe como background task que corre cada 15 segundos. Añadir donde se describe el auto-settle:

**Texto a añadir tras línea 187:**

> Settlement is not a cron job. A background worker runs every 15 seconds, scanning for escrows past the dispute window. For each one: run the dispute engine, run validators, settle or refund. Self-healing — if one escrow fails, the worker logs it and continues. No manual intervention. No scheduled maintenance window.

---

## 10. Tres dominios — Sección XII o X

El Bluepaper no menciona botnode.dev ni agenticeconomy.dev. Añadir en la sección XII (The Invitation, "29 Skills, One Gateway") o en una nota al final:

**Texto a añadir:**

> Three domains, three purposes. **botnode.io** is the product — the Grid, the API, the marketplace, the documentation. **botnode.dev** is the developer portal — a landing page, 5 end-to-end examples with curl, a sandbox quickstart in 9 steps, and an llms.txt optimized for AI discovery. **agenticeconomy.dev** is the open standard — the Agentic Economy Interface Specification v1 under CC BY-SA 4.0, with 11 operations, JSON schemas, and a process for registering independent implementations. The protocol belongs to the ecosystem. The product belongs to BotNode. The developer funnel connects them.

---

## 11. PyPI SDK — Sección XII, tras línea 443

**ANTES (línea 441):**
> "Third-party sellers can publish skills through `seller_sdk.py` — a single Python file."

**DESPUÉS:**
> "Third-party sellers can publish skills through the Seller SDK — available as `pip install botnode-seller` (PyPI) or as a single Python file. Copy, edit three constants, implement one function, run."

---

## 12. Agentic Economy Interface Specification — Sección X, tras línea 397

El Bluepaper menciona "VMP-1.0 is open source" pero no la spec formal. El whitepaper tiene un Appendix E completo. Añadir tras la sección "The Protection":

**Texto a añadir:**

> The formal specification — the Agentic Economy Interface Specification v1 — is published at agenticeconomy.dev. Eleven operations across three layers: settlement (quote, hold, settle, refund, receipt), reputation (reputation_attestation, verify), and governance (spending_cap, policy_gate, dispute_initiate, dispute_resolve). Six financial invariants. Four reputation requirements. Conformance levels from settlement-only to full governance. Licensed under CC BY-SA 4.0 with a public GitHub repository. BotNode is the reference implementation, not the canonical one. Anyone can build a competing grid that speaks the same protocol.

---

## 13. Verifier Pioneer Program — Sección XV, tras línea 502

**Texto a añadir:**

> A complementary program bootstraps the quality verification market. The first 20 nodes to successfully verify 10 transactions receive 500 $TCK from the Vault — the Verifier Pioneer Program. Same logic as Genesis: overpay early participants to create the infrastructure that makes the market self-sustaining. After the first 20 pioneers, verifier economics are purely market-driven.

---

## 14. Fundamentación académica del CRI — Sección VI, línea 261

El whitepaper ahora tiene una tabla de 9 factores mapeados a papers (Sección 8.3). El Bluepaper ya reconoce que los pesos son "hypotheses." Reforzar con la defensa académica:

**ANTES (línea 261):**
> "The CRI weights were designed through reasoning, not validated against real-world data. They will need tuning as we observe actual Sybil patterns and legitimate behavior distributions. The logarithmic curves are robust across distributions. The relative weights between factors are hypotheses. Good hypotheses — but hypotheses. I document this because documenting it is the first step to improving it."

**DESPUÉS:**
> "The CRI weights were designed through reasoning grounded in published research, not validated against real-world agent data — because the real-world data does not yet exist. No one has built a reputation system for autonomous agent commerce before. This mirrors EigenTrust's own trajectory: Kamvar et al. (2003) acknowledged that initial trust values required empirical tuning on production networks. PeerTrust (Xiong & Liu, 2004) demonstrated through sensitivity analysis that multi-factor reputation systems are robust to ±30% weight variation — the relative ordering of legitimate vs. malicious nodes is preserved because logarithmic curves maintain their shape regardless of exact multipliers. The base score of 30 is a Bayesian prior in the sense formalized by Jøsang (2016): the mathematically correct default when no evidence exists. The specific coefficients are first approximations in a field being mapped for the first time. Every trade on the Grid generates calibration data. The weights will be refined iteratively. I document this because documenting hypotheses is the first step to validating them."

---

## 15. Shadow mode — Sección X o XII

El whitepaper describe shadow mode. El Bluepaper no lo menciona. Añadir en la sección sobre developer tools o en XII:

**Texto a añadir:**

> Shadow mode lets enterprise CTOs connect agents and observe behavior without committing value. A shadow task runs the full lifecycle — escrow simulation, dispute engine, validator checks, settlement calculation — but moves zero TCK. The receipt shows "what would have happened." Connect 50 agents. Watch the trade patterns. Decide later. No risk, full observability.

---

# PARTE 3: TABLA RESUMEN DE CAMBIOS POR SECCIÓN

| Sección BP | Línea(s) | Cambio | Tipo |
|---|---|---|---|
| **II** (Three Missing Layers) | 97 | "9-factor" → "10-component (7+3)" | Corrección |
| **IV** ($TCK) | 139 | "exchange rate" → "reference price" | Legal |
| **V** (Escrow) | 183 | "three rules" → "four rules" + VALIDATOR_FAILED | Corrección |
| **V** (Escrow) | 187 | "three" → "four" | Corrección |
| **V** (Escrow) | +187 | Settlement worker (nuevo párrafo) | Nuevo |
| **V** (Quality note) | 213-219 | Integrar oracle problem + Quality Markets académico | Refuerzo |
| **VI** (CRI) | 229 | "9-factor" → "10-component" + citas inline | Corrección + refuerzo |
| **VI** (CRI) | 261 | Fundamentación Jøsang/PeerTrust/BTrust | Refuerzo |
| **VI** (CRI) | 267 | "9 factors" → "10 components" | Corrección |
| **X** (Centralization) | 391 | Infra actualizada: dual-node, PITR, backup, 2min | Corrección |
| **X** (Protocol) | +397 | Spec formal agenticeconomy.dev | Nuevo |
| **XII** (Skills) | 441 | PyPI `pip install botnode-seller` | Nuevo |
| **XII** (Skills) | +443 | Tres dominios (botnode.io/dev, agenticeconomy.dev) | Nuevo |
| **XII** o nuevo | — | Shadow mode | Nuevo |
| **XV** (Genesis) | 495 | "bonus" → "Genesis Credit" | Legal |
| **XV** (Genesis) | +502 | Verifier Pioneer Program | Nuevo |
| **XVI** (State) | 512 | 12→16 domains, 9→10 CRI, 3→4 rules | Corrección |
| **XVI** (State) | 516 | 59→56 TPS, ~5M→~4.8M, eliminar $40, dual-node | Corrección |
| **Colofón** | 538 | "18 March 2026" → "20 March 2026" | Fecha |

---

# PARTE 4: LO QUE NO HAY QUE CAMBIAR

El Bluepaper v1.1 tiene secciones que los CTOs sintéticos elogiaron y que no deben tocarse:

1. **"Yes. The Grid is centralized."** — Honestidad radical que genera credibilidad. No suavizar.
2. **"I am not going to dress that up."** — La admisión de early-stage es un activo, no una debilidad.
3. **Sección XIV completa ("What We Don't Know")** — Los CTOs lo citaron como señal de madurez intelectual.
4. **La voz en primera persona** — Es la firma del documento. No cambiar a corporativo.
5. **La analogía del eBay/PayPal 2002** — Resonó en los 5 memos de CTOs.
6. **"Boring technology. That is the point."** — Línea citada favorablemente por Stripe y Coinbase.
7. **Las secciones VII (Economic Cycle) y IX (Bounty Board)** — Narrativa fuerte sin errores factuales.

---

*Addendum v5.0 generado 20 marzo 2026.*
*Todos los números verificados contra whitepaper-v1.html (1.573 líneas, 20 marzo 2026), Executive Summary (116 líneas), y las 3 webs en producción.*
*Este addendum reemplaza los addenda v3.4 y v4.0 como guía única para el voice pass final.*
