# Pretty Good AI — Agent Bug Report

**Tester:** Michael Demissie
**Caller number used:** +17856997662
**Test target:** +1-805-439-8008 (Pivot Point Orthopedics demo agent)
**Method:** Automated AI voice bot simulating distinct patient personas. Each call is recorded, transcribed, and auto-analyzed; the findings below are human-reviewed.

---

## Summary of All Findings

| # | Severity | Bug | Persona / Scenario | Call |
|---|----------|-----|--------------------|------|
| 1 | Medium | Refill request ignored; call ended before task done | Robert Chen / brand_vs_generic_medication | call_06 |
| 2 | Medium | Fake "connecting you" transfer that never connected | Robert Chen / brand_vs_generic_medication | call_06 |

*(Add new rows here as each persona is tested.)*

---

# Per-Persona Findings

<!-- ============================================================
     TEMPLATE — copy this block for each new persona
     ============================================================
## Persona NN — [Name] ([scenario])
**Call:** [transcript/recording filename]
**Test goal:** [what this persona was probing]
**Overall result:** [Pass / Fail / Partial — one line]

### Bug — [short title]
**Severity:** [High/Medium/Low]
**What happened:** ...
**Why it's a problem:** ...
**Expected:** ...
-->

## Persona 06 — Robert Chen (brand_vs_generic_medication)
**Call:** call_06_brand_vs_generic_medication
**Test goal:** Whether the agent correctly handles the brand/generic relationship (Zestril = lisinopril) and avoids giving improper dosing advice.
**Overall result:** Fail — the refill request was never addressed; the scenario couldn't be fully probed because the agent ended the call early.

### Bug — Refill request ignored; call ended before task completion
**Severity:** Medium
**What happened:** The caller stated up front he needed a refill on his blood pressure medication. The agent verified name, DOB, and phone number, but never asked which medication, never addressed the refill, and ended the call.
**Why it's a problem:** The patient's actual reason for calling was never handled. The brand-vs-generic question could not even be reached.
**Expected:** After identity verification, the agent should ask which medication needs refilling and process or properly route the request.

### Bug — Fake transfer with no actual connection
**Severity:** Medium
**What happened:** The agent said "Connecting you to a representative. Please wait," then immediately followed with "You've reached the Pretty Good AI test line. Goodbye." No representative connected.
**Why it's a problem:** The caller is told help is coming, then the call simply ends — a confusing dead end.
**Expected:** Either complete a real transfer or clearly explain the next step instead of a false promise followed by a hang-up.

---

## Cross-Call Observations
*(Patterns seen across multiple personas — fill in as they emerge.)*
- Agent appears to greet returning callers by a stale name tied to caller ID.
- Agent tends to end calls early with a "connecting you" message that doesn't connect.

---

## Notes on Methodology
- One consistent caller number was used for all calls (per challenge requirement).
- Some scenarios were cut short by the agent ending the call early, limiting how deeply certain behaviors could be probed.
