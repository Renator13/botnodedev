# Bluepaper Addendum v4.0 — Cambios 19 Marzo 2026 (tarde/noche)

## Para: Rene / Opus voice pass
## Contexto: Todo lo implementado DESPUES del Addendum v3.4, que debe reflejarse en el Bluepaper
## Instruccion: Integrar estos datos en la narrativa del Bluepaper sin cambiar la voz

---

# CAMBIOS MAYORES

---

## 1. Fundamentacion Academica del CRI (NUEVO — Seccion 8.3 del whitepaper)

**Antes:** El CRI se presentaba como "ingenieria razonada." Los pesos eran "educated guesses."

**Ahora:** Cada factor del CRI tiene un precedente academico publicado. El whitepaper tiene una nueva seccion (8.3 Academic Foundations) con tabla de 9 factores mapeados a papers, y las citas estan tejidas en TODA la argumentacion:

| Factor CRI | Paper clave |
|---|---|
| Log scaling (tx count) | Kamvar et al. 2003 (EigenTrust, WWW Test of Time 2019) |
| Counterparty diversity | Douceur 2002 (Sybil Attack), Cheng & Friedman 2005 |
| Concentration penalty | Hirschman 1945 (Herfindahl-Hirschman Index) |
| Account age | Resnick & Zeckhauser 2002 (eBay empirical) |
| Base score 30 | Schein et al. 2002 (cold-start), EigenTrust pre-trusted peers |
| Dispute penalty | Ostrom 1990 (Nobel 2009, graduated sanctions), Axelrod 1984 |
| Buyer activity | Marti & Garcia-Molina 2004, Bolton et al. 2004 |
| Portabilidad JWT | Resnick et al. 2000, W3C Verifiable Credentials 2019 |
| Resistencia Sybil sistemica | Margolin & Levine 2008, Shi 2025 (TraceRank) |

**Frase clave para la narrativa del Bluepaper:** "The CRI was designed by engineering reasoning. That it aligns with the academic consensus is confirmation, not coincidence. When a CTO asks 'why logarithmic?' the answer is Kamvar et al. 2003, not 'because it felt right.'"

**El Bluepaper debe integrar esto en la Seccion VI (CRI).** No como un bloque academico separado, sino tejido en la argumentacion existente. Ejemplo: donde el Bluepaper dice "logarithmic scaling prevents volume farming", anadir "(Kamvar et al., 2003)". Donde dice "counterparty diversity", anadir "(Douceur, 2002)".

---

## 2. Fundamentacion Academica del Oracle Problem / Quality Markets (NUEVO — Seccion 10.8 del whitepaper)

**Antes:** Quality Markets era una decision de diseno sin precedente citado.

**Ahora:** 8 decisiones de diseno del sistema de verificacion, cada una con paper academico:

| Decision | Paper clave |
|---|---|
| Separar verificacion determinista/subjetiva | "Trust or Escalate" ICLR 2025, BIS Bulletin 2023 |
| Validators como funciones puras | Meyer 1992 (Design-by-Contract), Hoare 1969 |
| Verifiers competitivos (mercado) | Wolfers & Zitzewitz 2004 (prediction markets), Miller et al. 2005 |
| JSON Schema como contrato minimo | Hart & Moore 1988 (incomplete contracts) |
| Escrow + dispute window | Schelling 1960 (commitment mechanisms), Katsh 2017 |
| CRI del verifier como garantia | Akerlof 1970 (Market for Lemons), Spence 1973 |
| Micropagos por verificacion | Coase 1960 (transaction cost economics) |
| No silver bullet — capas complementarias | Zintus-Art et al. 2025 (Frontiers in Blockchain) |

**Frase clave para la narrativa del Bluepaper:** "The oracle problem does not have a solution. It has a management strategy. And the management strategy the literature prescribes is exactly what Quality Markets implements."

**El Bluepaper debe integrar esto en la Seccion XIII (What Emerges) o crear una nueva subseccion sobre Quality Markets.**

---

## 3. Dual-Node Infrastructure (NUEVO)

**Antes:** Single VPS en Estocolmo.

**Ahora:** Dos nodos AWS en eu-north-1:
- Primary: 2 vCPU, 7.8 GB RAM (Lightsail)
- Secondary: 2 vCPU, 2 GB RAM (EC2 t3.small)
- PostgreSQL compartida via tunel SSH cifrado
- Cloudflare delante de ambos con failover
- `eu.botnode.io` apuntando al secundario

**El Bluepaper Seccion X ("What It Costs") debe actualizarse:**
- ANTES: "But no off-site backup, no point-in-time recovery, no multi-region deployment."
- AHORA: Off-site backup: SI. PITR: SI. Dual-node: SI. Solo falta multi-REGION (diferentes regiones AWS).

**Tabla de DR actualizada:**
| Escenario | RTO | RPO |
|---|---|---|
| Fallo de un nodo | 5 min (failover automatico) | 0 |
| Fallo VPS | 30 min | 1 hora |
| Corrupcion DB | 15 min (PITR) | minutos |

---

## 4. PyPI: `pip install botnode-seller` (NUEVO)

**Antes:** Seller SDK era un archivo Python que se descargaba manualmente.

**Ahora:** Publicado en PyPI como `botnode-seller` v1.0.0. Cualquier developer puede hacer `pip install botnode-seller` y empezar a vender skills.

**El Bluepaper debe mencionarlo en la Seccion XII (The Invitation) como parte del developer onboarding.**

---

## 5. botnode.dev — Developer Portal (NUEVO)

**Nuevo dominio:** `botnode.dev` — site dedicado a builders con:
- Landing page orientada a developers
- 5 end-to-end examples con curl
- Sandbox quickstart (9 pasos, 10 minutos)
- llms.txt optimizado para AI crawlers

**Tres dominios, tres propositos:**
- `botnode.io` — el producto (Grid, API, marketplace)
- `botnode.dev` — el developer portal (ejemplos, sandbox, SDK)
- `agenticeconomy.dev` — el open standard (spec, schemas)

**El Bluepaper debe mencionar botnode.dev en la Seccion XII.**

---

## 6. Agentic Economy Interface Specification v1 (NUEVO — Appendix E del whitepaper)

**Antes:** BotNode era un producto. Ahora tambien define un standard abierto.

**Ahora:** La especificacion formal esta publicada en `agenticeconomy.dev` bajo CC BY-SA 4.0:
- 11 operaciones across 3 capas + dispute resolution
- L3 Settlement: quote, hold, settle, refund, receipt
- L4 Reputation: reputation_attestation, verify
- L5 Governance: spending_cap, policy_gate
- Dispute: dispute_initiate, dispute_resolve
- 6 invariantes financieras
- 4 requisitos de reputacion

**Frase clave:** "BotNode is the reference implementation, not the canonical one. Anyone can build a competing grid that speaks the same protocol."

**El Bluepaper debe mencionar agenticeconomy.dev en la Seccion X (The Protocol) o en una nueva seccion sobre el standard abierto.**

---

## 7. 4 Dispute Rules (no 3)

**Antes (Addendum v3.4):** 3 reglas (PROOF_MISSING, SCHEMA_MISMATCH, TIMEOUT_NON_DELIVERY).

**Ahora:** 4 reglas. Se anadio **VALIDATOR_FAILED** — output que falla uno o mas protocol validators attached al skill. 8 tipos de validator: schema, length, language, contains, not_contains, non_empty, regex, json_path.

**TODOS los documentos deben decir 4 reglas, no 3.** El Bluepaper v1.1 dice "three rules" — debe actualizarse.

---

## 8. 16 Domains (no 12)

**Antes:** 55+ endpoints across 12 domains.

**Ahora:** 55+ endpoints across **16 domains**: Identity, Marketplace, Escrow, Tasks, MCP, A2A, Webhooks, Reputation, Evolution, Bounty, Network, Admin, Shadow, Validators, Benchmarks, Sandbox.

**El Bluepaper debe actualizarse de 12 a 16.**

---

## 9. CRI Genesis Bonus: 10 puntos (no 300)

**Bug critico corregido en codigo:** `worker.py` calculaba `GENESIS_CRI_FLOOR * 10.0 = 300` en vez de `10.0`. Todos los Genesis nodes habrian tenido CRI 100 automaticamente. Corregido a `10.0`.

**No afecta al Bluepaper** (el texto ya decia "10 points") pero es importante documentar que se corrigio.

---

## 10. Verifier Pioneer Program (NUEVO)

**Nuevo:** Los primeros 20 nodos que verifiquen exitosamente 10 transacciones reciben 500 TCK del Vault.

**Proposito:** Bootstrappear el supply side de Quality Markets. Analogo al Genesis Program pero para el ecosistema de verificacion.

**El Bluepaper puede mencionarlo brevemente en la Seccion XV (Genesis) como programa complementario.**

---

# CORRECCIONES DE TERMINOLOGIA

| Termino antiguo | Termino correcto | Razon |
|---|---|---|
| "bonus" (para compras TCK) | "volume discount" | Consejo legal |
| "exchange rate" | "reference price" | Consejo legal |
| "Genesis bonus" (user-facing) | "Genesis Credit" | Consejo legal (nota: "Genesis bonus" sigue siendo valido como nombre del componente CRI) |
| Cualquier referencia a costes ($40, EUR0, free tier) | ELIMINAR | Rene no quiere info de costes publica |
| "9 factors" | "10 components (7 positive + 3 penalties)" | Correccion factual |
| "3 dispute rules" | "4 dispute rules" | VALIDATOR_FAILED anadido |
| "12 domains" | "16 domains" | Dominios adicionales |
| "single VPS" | "dual-node" | Infraestructura actualizada |

---

# SECCIONES DEL BLUEPAPER v1.1 QUE NECESITAN ACTUALIZACION

| Seccion | Que cambiar |
|---|---|
| **V (Escrow)** | 4 dispute rules (no 3). Validator hooks. Settlement worker (no cron). Quality Markets 4-layer stack. |
| **VI (CRI)** | 10 components (no 9). Citations academicas inline. CRI portabilidad JWT ya implementada. |
| **IX (Skills)** | 5 providers (no 3). Fallback chains. `pip install botnode-seller`. |
| **X (Protocol/Centralization)** | 16 domains. MCP + A2A + REST. agenticeconomy.dev spec. Dual-node (no single VPS). Off-site backup + PITR. Health monitoring 2 min (no 5). Settlement worker. |
| **XII (Invitation)** | botnode.dev portal. Sandbox. Shadow mode. PyPI SDK. |
| **XIII (What Emerges)** | Quality Markets con fundamentacion academica. Verifier Pioneer Program. |
| **XV (Genesis)** | "Genesis Credit" (no "bonus" en user-facing). Verifier Pioneer como programa complementario. |
| **XVI (State of Things)** | 56 TPS (no 59). ~4.8M trades/day (no ~5M). 10 CRI components. 16 domains. Dual-node. |

---

# 5 PREMIOS NOBEL CITADOS EN EL WHITEPAPER

El whitepaper ahora cita trabajo de 5 laureados Nobel:
1. **George Akerlof** (Nobel 2001) — Market for Lemons, information asymmetry
2. **Michael Spence** (Nobel 2001) — Job market signaling
3. **Elinor Ostrom** (Nobel 2009) — Graduated sanctions in commons governance
4. **Thomas Schelling** (Nobel 2005) — Commitment mechanisms, strategic behavior
5. **Ronald Coase** (Nobel 1991) — Transaction cost economics

Mas **Jim Gray** (Turing Award 1998) sobre transaction processing.

**El Bluepaper puede mencionar esto como refuerzo de credibilidad.** No como lista, sino tejido en el argumento.

---

*Addendum v4.0 generado 19 marzo 2026 (noche).*
*Para uso en la proxima sesion de voice pass con Opus.*
*Todos los numeros verificados contra whitepaper-v1.html (1541 lineas, 19 marzo 2026).*
