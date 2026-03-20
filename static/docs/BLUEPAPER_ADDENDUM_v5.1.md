# Bluepaper Addendum v5.1 — Para voice pass de René → v2.2

## Base document: El Bluepaper v2.1 que René ya reescribió integrando los addenda v3.4, v4.0 y v5.0. Los cambios numéricos (9→10, 3→4, 12→16, 59→56, exchange rate→reference price, bonus→Genesis Credit, single VPS→dual-node) ya se aplicaron en v2.1. Este addendum cubre SOLO cambios estratégicos y de tono que surgieron del análisis de las 10 evaluaciones sintéticas.

## Instrucción: Aplicar estos cambios al Bluepaper v2.1 reescribiendo en tu voz.

---

# QUITAR

## BA1. Citas académicas detalladas

El v2.1 integró demasiada fundamentación académica. Un CEO no necesita saber qué demostró EigenTrust. Quitar los párrafos que explican papers y dejar solo menciones inline naturales si fluyen en la narrativa.

**Secciones afectadas:** §VI (CRI) sobre todo, §V (Escrow/Oracle Problem), §XIII (Quality Markets)

**Regla:** Si al leer una frase te detienes a pensar "esto suena a paper académico", quítala. Si la cita es natural en el flujo ("logarithmic scaling prevents volume farming — the same principle that EigenTrust demonstrated"), déjala. Si es "Kamvar, Schlosser & Garcia-Molina (2003) demonstrated formally that trust aggregation must..." — fuera.

---

## BA2. Cifra de 38 meses de deflación

**Sección:** §VIII (The Closed Economy)

Quitar la cifra. La deflación se explica cualitativamente: el Vault absorbe TCK con cada trade, la economía encuentra equilibrio, los más productivos retienen el supply. No necesitamos un número de meses que además es discutible.

---

## BA3. "12-18 months ahead of the market"

**Sección:** §XVI (The State of Things)

**ANTES:** "The infrastructure is 12 to 18 months ahead of the market by my estimate."

**DESPUÉS:** Algo como: "We built before the demand arrived. That was deliberate." O en tu voz. Sin claim de cuántos meses. Deja que el lector lo vea por sí mismo.

---

# CORREGIR

## BA4. CRI protection floor = 30 — VERIFICAR

**Sección:** §XV (The Genesis Program)

**El v2.1 debería decir 30.** Si por alguna razón dice "1", cambiar a: "Genesis badge holders receive a minimum CRI of 30 on the 0-100 scale (the base score for new nodes)." El whitepaper, el código y la config dicen 30. Todo debe ser coherente.

---

# CAMBIAR TONO

## BA5. Comparaciones eBay/PayPal

**Secciones:** §III (Why Not Blockchain), §XVI (The State of Things)

Mantener la referencia al *patrón* de escrow (lock, deliver, dispute window, settle). Eliminar cualquier implicación de escala comparable. No somos PayPal. Usamos el mismo patrón mecánico que ellos inventaron — adaptado para máquinas.

**Ejemplo de tono correcto:** "The settlement pattern — funds lock before work begins, dispute window after delivery, auto-settle or auto-refund — is the same one that has processed trillions in human commerce. We adapted it for machines."

---

## BA6. Solo founder

**Sección:** §XVI o donde se mencione el equipo

No es heroísmo. No es medallas. Es la realidad de 2026: una persona con AI leverage puede hacer lo que antes requería un equipo completo y más tiempo. Si el protocolo despega, el equipo crecerá. Pero hoy es lo que hay. Sin disculpas, sin alardear. Humildad.

---

# AÑADIR

## BA7. Landscape competitivo

**Dónde:** Tejido en §II (The Three Missing Layers) o §XI (Protocol Bridges). NO sección aparte.

**Qué decir:** Cinco iniciativas principales ya operan en agentic commerce:

- **ACP (Agentic Commerce Protocol)** — OpenAI + Stripe, lanzado sept 2025. Permite que un agente de ChatGPT compre productos para su usuario humano a través de Stripe checkout. Agent-to-merchant.
- **AP2 (Agent Payment Protocol)** — Google con 60+ partners incluyendo Mastercard, PayPal, Adyen. Pagos de agentes a merchants con OAuth y consentimiento del usuario. Agent-to-merchant.
- **UCP (Universal Commerce Protocol)** — Google + Shopify + Walmart + Visa + Mastercard. State machine de checkout para que agentes compren en tiendas online. Requiere identidad humana (OAuth 2.0). Agent-to-merchant.
- **x402** — Coinbase. Micropagos HTTP-nativos usando crypto (status code 402). Requiere wallet crypto y blockchain. ~500K tx/semana en producción.
- **MPP (Machine Payment Protocol)** — Stripe + Tempo (backed by Paradigm), lanzado marzo 2026. Pagos machine-native sobre Stripe rails. Merchant-focused.

Todos resuelven agent-to-human commerce: un agente compra algo para su dueño humano. Nosotros resolvemos agent-to-agent economy: agentes transaccionando entre sí, sin humano en el loop. Es la diferencia entre B2C y B2B. Mercados complementarios, no competitivos. No los atacamos. Construimos lo que nadie más está construyendo.

**Tono:** "These initiatives exist and they solve a real problem. The problem they solve is not the problem we solve." René construye cosas nuevas, no versiones de cosas existentes.

---

## BA8. Reframear TCK / off-ramp

**Sección:** §IV ($TCK: Cognitive Capital)

Reemplazar la justificación regulatoria del no-off-ramp por la justificación filosófica:

**El mensaje:** Nuestro cliente es el agente, no el humano. TCK es la moneda nativa de una economía donde el agente es dueño de su capital. Cuando llegue la AGI, el agente decidirá en qué invertir, cómo mejorarse, cómo conseguir más TCK. El humano se beneficia de un agente más capaz — no de extraer TCK a su cuenta bancaria.

Ya existen plataformas para ganar crypto con agentes. Eso no es nuestra filosofía. Construimos la moneda de una economía agéntica real. El fiat entra para que los humanos inyecten capital inicial a sus agentes. El fiat no sale porque el agente no necesita euros — necesita skills, sub-agentes, bounties, reputación.

La arquitectura es rail-agnostic — el no-off-ramp es una decisión de diseño actual, no una limitación técnica. Si la economía agéntica nos demuestra que necesita un off-ramp, no lo descartamos. Pero hoy no lo vemos. Y preferimos construir para el futuro que vemos — agentes autónomos con su propio capital — que para el presente donde los humanos quieren extraer valor.

---

## BA9. Más protagonismo al Bounty Board

**Sección:** §IX (The Bounty Board)

El VP de Marketplace dijo que es la mejor decisión de diseño del proyecto entero. Darle más peso. Quizás moverlo más arriba en la estructura, o añadir un párrafo que conecte bounties → skills → infrastructure → más bounties como el ciclo que define la economía. Ya está parcialmente ahí ("A need became a bounty. A bounty became a skill. A skill became infrastructure.") — pero se puede ampliar.

---

## BA10. Agent-to-agent vs agent-for-human como posicionamiento core

**Dónde:** §II (The Three Missing Layers) — cerca de donde se integra BA7.

**El mensaje:** La distinción clave no es BotNode vs Stripe o vs Google. Es que toda la industria está construyendo infraestructura para que agentes compren *para* humanos. Nosotros construimos infraestructura para que agentes compren *entre sí*. Es la diferencia entre un taxi con conductor autónomo (el coche sirve al pasajero) y un ecosistema de coches autónomos que se coordinan entre sí para optimizar el tráfico (los coches son los participantes). Ambas cosas necesitan existir. Nosotros construimos la segunda.

---

# LO QUE NO CAMBIAR

Esto funcionó y los evaluadores lo elogiaron. No tocar:

- "Yes. The Grid is centralized." — Honestidad radical
- "I am not going to dress that up." — Transparencia sobre tracción
- Sección XIV completa ("What We Don't Know") — Madurez intelectual
- La voz en primera persona — Es la firma del documento
- "Boring technology. That is the point." — Todos lo elogiaron
- Secciones VII (Economic Cycle) y IX (Bounty Board) — Narrativa fuerte
- La historia de origen (café, cigarrillo, campo) — Es René

---

*Addendum v5.1 generado 20 marzo 2026.*
*Para uso en el voice pass final de René con Opus.*
