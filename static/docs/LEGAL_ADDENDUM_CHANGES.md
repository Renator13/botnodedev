# Legal Compliance Addendum — Changes Required in Bluepaper & Executive Summary

## Based on: Preliminary Legal Opinion, March 2026
## For: René — manual edits in Bluepaper (Opus voice) and Executive Summary
## Date: 19 March 2026

---

## CHANGES ALREADY MADE (Whitepaper + Config + Web)

These are done. Listed here for reference so you know the Bluepaper/Summary must match.

1. **"bonus" → "volume discount"** in whitepaper package descriptions
2. **"fixed exchange rate" → "base reference price"** in whitepaper section 7.1
3. **"pending legal setup" → "regulatory framework validated by legal counsel, pending administrative steps"** in whitepaper section 7.5
4. **PSD2 Article 3(k) limited network exclusion** explicitly cited in whitepaper
5. **config.py** package descriptions updated (no more "bonus included")

---

## CHANGES NEEDED IN THE BLUEPAPER v1.1

### Change 1: TCK pricing (Section IV, Section VIII)

**Find:** Any mention of "bonus" in the context of TCK packages.

The Bluepaper says in Section VIII: "Four packages from $5 to $50"

**Replace with:** "Four volume-priced packages from $5 (500 TCK at $0.01/TCK) to $50 (10,000 TCK at $0.005/TCK)"

### Change 2: Exchange rate language (Section IV)

**Find:** "1 TCK = $0.01 USD. This exchange rate is a starting point"

**Replace with:** "1 TCK is priced at $0.01 at the base tier. This reference price is a starting point"

Also: "If we need to adjust the fiat exchange rate, we adjust it."
**Replace with:** "If we need to adjust the reference pricing, we adjust it."

### Change 3: Legal status (Section XVI)

**Find:** Any framing that suggests legal uncertainty about the fiat on-ramp.

The Bluepaper currently says: "A Stripe Checkout integration — feature-flagged, already designed and specified — that allows purchasing $TCK with real currency."

**Add after that sentence:** "A preliminary legal opinion confirms that TCK qualifies for the limited network exclusion under EU payment services regulation (PSD2 Article 3(k)) as closed-loop prepaid credits — the lightest regulatory category. No payment institution license is required. Activation is pending company incorporation and Terms of Service publication."

### Change 4: "Genesis bonus" language

**Keep "Genesis bonus"** — the lawyer's concern is about purchase bonuses (money → more credits than paid for). The Genesis bonus is a grant from the system to early adopters, not a purchase incentive. It's analogous to a promotional credit, not a financial bonus. No change needed.

---

## CHANGES NEEDED IN THE EXECUTIVE SUMMARY

### Change 1: Package descriptions (Section "The Economic Model")

**Find:** "$5 for 500 TCK, $10 for 1,200 (20% bonus), $25 for 3,500 (40% bonus), $50 for 10,000 (100% bonus)"

**Replace with:** "$5 for 500 TCK ($0.01/TCK), $10 for 1,200 TCK ($0.0083/TCK), $25 for 3,500 TCK ($0.0071/TCK), $50 for 10,000 TCK ($0.005/TCK) — volume pricing, not bonus credits"

### Change 2: Legal status (Section "Traction & Status")

**Find:** "Fiat on-ramp: Stripe Checkout integration complete and tested. Behind feature flag. Blocked on: Spanish company formation (CIF), Terms of Service, and refund policy."

**Replace with:** "Fiat on-ramp: Stripe Checkout integration complete and tested. Behind feature flag. Regulatory framework validated by legal counsel — TCK qualifies as closed-loop prepaid credits under PSD2 limited network exclusion. Activation pending: company incorporation (SL/CIF), Terms of Service publication, and sanctions screening implementation."

### Change 3: "The lightest possible regulatory structure"

**Find:** "This is the lightest possible regulatory structure: prepaid credits, like gift cards or game tokens."

**Replace with:** "Legal counsel confirms this falls under the limited network exclusion of PSD2 Article 3(k) — the lightest regulatory category. No payment institution license required at current volumes."

### Change 4: Team section

**Find:** "in under 60 days" — **No change needed**, this is correct.

---

## WHAT NOT TO CHANGE

1. **"Cognitive Capital" / "machine-native currency"** in the Bluepaper — these are conceptual/vision terms in a design document, not legal claims. The Bluepaper is not a contract.
2. **"Genesis bonus"** — this is a system grant, not a purchase incentive.
3. **"$TCK" symbol** — perfectly fine, it's an internal unit designation.
4. **"1 TCK = $0.01"** as informational reference — OK in technical docs, just don't call it an "exchange rate."
5. **Any mention of the closed-loop / no off-ramp design** — the lawyer explicitly validates this as the correct approach.

---

*Generated 19 March 2026. Apply changes during next Opus voice pass for Bluepaper, and manually for Executive Summary.*
