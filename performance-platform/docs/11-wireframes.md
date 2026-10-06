# 11. Wireframes (ASCII)

Layout: left navigation, top bar with global search and notifications, content area.
Responsive: below 768 px the nav collapses into a bottom tab bar.

## W1 — Employee home ("My Performance")

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ ◆ Somos Performance        [Search people, goals…]               🔔3   Dana R. ▾ │
├───────────┬──────────────────────────────────────────────────────────────────────┤
│ Home      │ Good morning, Dana                       FY2027 · Q1 · Senior Associate│
│ Goals     │ ┌─ To do ─────────────────────────┐ ┌─ Path to Project Leader ─────┐ │
│ Check-ins │ │ ● Self-assessment   due Oct 9   │ │  Band 4 ──────●──── Band 5   │ │
│ Feedback  │ │ ● Peer review: Luis due Oct 14  │ │  Readiness: Ready in 6–12 mo │ │
│ Reviews   │ │ ○ Q1 check-in       Jan 12      │ │  Gaps (2):                   │ │
│ Growth    │ └─────────────────────────────────┘ │   ▸ Supervised others' work  │ │
│ Career    │ ┌─ Goals FY27 ─────── 62% ◔ ──────┐ │   ▸ Client relationship lead │ │
│           │ │ Close Riverside rezoning  30% ●On│ │  [Compare bands →]           │ │
│           │ │ Lead 2 junior associates  25% ●At│ └──────────────────────────────┘ │
│           │ │ CLE: land-use certificate 20% ●On│ ┌─ Recent feedback ────────────┐ │
│           │ │ Pitch support (2 proposals)25%○ │ │ "Clear memo on variance…"     │ │
│           │ └──────────────[Update goals]─────┘ │  — Marcus · 3d  [★ evidence]  │ │
│           │ ┌─ Hours (context) ───────────────┐ │ [Request feedback]           │ │
│           │ │ Hours Expectation 104% · On Track│ └──────────────────────────────┘ │
│           │ │ 2-yr lookback 97% ✓ promo gate   │                                 │
│           │ └──────────────────────────────────┘                                 │
└───────────┴──────────────────────────────────────────────────────────────────────┘
```

## W2 — Manager review workspace

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ ← Team   Review: Dana R. · Senior Associate (Legal) · FY2027 Annual   Saved ✓ 2s │
├───────────────────────┬────────────────────────────────────┬─────────────────────┤
│ INPUTS                │ C2  CLIENT SERVICE & VALUE   2 / 5  │ EVIDENCE (C2)  [⌕]  │
│ ▸ Self-review         │ Band 4 expectation:                 │ ☑ Q2 check-in: led  │
│   C2: 4 "Led client…" │  • Anticipates client needs…        │   client call on…   │
│ ▸ Peers (4/4) ✓       │  • Owns day-to-day relationship…    │   Apr 14            │
│   [✦ Summarize]       │  [Legal example] [Planning example] │ ☑ Feedback (client  │
│ ▸ Upward  n/a         │                                     │   team) "fast turn…"│
│ ▸ Goals  62% weighted │ Rating:  ○1 ○2 ○3 ●4 ○5  ○N/A       │   Jun 2             │
│ ▸ Hours  104% ✓       │ Self: 4 · Peer avg: 3.8             │ ☐ Goal: Pitch       │
│ ▸ Last year: 3        │                                     │   support 1/2       │
│                       │ Narrative                [✦ Draft]  │ [+ Add evidence]    │
│ PEER THEMES ✦         │ ┌─────────────────────────────────┐ │                     │
│ + responsive, precise │ │ Dana owned the Riverside client  │ │ AI: 2 claims below  │
│ − delegates late [3]  │ │ relationship day to day…[1][2]  │ │ cite no evidence ⚠  │
│   (cites P1,P3,P4)    │ └─────────────────────────────────┘ │                     │
│                       │ Development recommendation          │                     │
│                       │ ┌─────────────────────────────────┐ │                     │
│                       │ └─────────────────────────────────┘ │                     │
├───────────────────────┴────────────────────────────────────┴─────────────────────┤
│ ◀ C1   ● ● ◐ ○ ○ ○  Summary   C3 ▶          [Pre-submit check]  [Submit review]   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

## W3 — Pre-submit check (modal)

```
┌─ Before you submit ──────────────────────────────────────────────┐
│ ⚠ C2 rated 4, but narrative cites no client example.  [Go fix]   │
│ ⚠ "abrasive" (C3) describes personality, not behavior.           │
│     Suggest: "interrupted colleagues in two team meetings…"      │
│                                         [Go fix] [Dismiss (why?)]│
│ ⓘ 70% of cited evidence is from the last 90 days (recency).      │
│ ✓ Holistic 4 vs reference 3.9 — consistent                       │
│ AI checks are advisory. You decide what to submit.               │
│                                  [Back to review] [Submit anyway]│
└──────────────────────────────────────────────────────────────────┘
```

## W4 — Calibration room

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Calibration · Legal & Planning · Bands 3–5 · 46 people     ● Live  Facilitator: G│
├──────────────────────────────────────────────────────────────────────────────────┤
│ Distribution  ▇ proposed  ▒ current  ┆ guidance            Filter: [Band ▾][Disc ▾]│
│  1 │▏            2%   ┆0–5                                                        │
│  2 │▇▇           9%   ┆5–15                                                       │
│  3 │▇▇▇▇▇▇▇▇▇   48%   ┆50–60                                                      │
│  4 │▇▇▇▇▇▇▇     33%   ┆20–30   ⚠ above guidance                                   │
│  5 │▇▇           9%   ┆5–10                                                       │
│ By manager:  Priya 2.9 (n6) ▼0.4 · Marcus 3.6 (n8) · Ana 3.7 (n5)                 │
├──────────────┬──────────────┬──────────────┬──────────────┬──────────────────────┤
│ 2 Developing │ 3 Fully Meets│ 4 Strong     │ 5 Exceptional│ Selected: Dana R.    │
│ ┌──────────┐ │ ┌──────────┐ │ ┌──────────┐ │ ┌──────────┐ │ B4 · Legal · Priya   │
│ │ J.K. B3 L│ │ │ A.M. B4 P│ │ │ Dana B4 L│ │ │ T.S. B5 L│ │ Self 4 · Mgr 4       │
│ └──────────┘ │ │ L.O. B3 L│ │ │ R.V. B5 P│ │ └──────────┘ │ Peers 3.8 · Goals 62%│
│              │ │ …        │ │ │ …        │ │              │ Evidence 14 items    │
│              │ └──────────┘ │ └──────────┘ │              │ ✦ summary [view]     │
│              │  drag card → rationale required             │ Promo: nominated B5  │
├──────────────┴──────────────┴──────────────┴──────────────┴──────────────────────┤
│ Adjustments (3): R.V. 5→4 "…" · J.K. 3→2 "…"           [Equity check (PA)] [Close]│
└──────────────────────────────────────────────────────────────────────────────────┘
```

## W5 — Promotion readiness (manager view)

```
┌─ Readiness: Dana R. → Project Leader (Band 5) ───────────── Score 74 (advisory) ┐
│ Next-band anchors                       Level                 Evidence           │
│ C1 Technical excellence at B5           ●●●○ Demonstrated     4 items            │
│ C2 Client delivery at B5                ●●○○ Emerging         2 items            │
│ C4 Leads project teams                  ●●○○ Emerging         1 item             │
│ Gate criteria                                                                    │
│ ◆ Led project end to end                ●●●○ Demonstrated     Riverside rezoning │
│ ◆ Supervised others' work               ●○○○ Not yet  ✖ gate  —                  │
│ Policy gate: 2-yr hours lookback 97% ≥ 90% ✓                                     │
│ Last ratings: FY26 3 · FY27 4      Time in band: 26 mo (info only)               │
│ Suggested level: Ready in 6–12 months (gate not met)                             │
│ Your level: [Ready in 6–12 months ▾]   Rationale [________________________]      │
│ [✦ Readiness advisory]  [Create dev objectives from gaps]  [Nominate ▸ disabled] │
└──────────────────────────────────────────────────────────────────────────────────┘
```

## W6 — 9-box talent matrix

```
            Growth trajectory ▲
                  High │ Grow (3)     │ Emerging leader (5) │ Future leader (2)│
                   Med │ Develop (4)  │ Core contributor(18)│ High impact (7)  │
                   Low │ Action (1)   │ Solid (9)           │ Expert (6)       │
                       └──────────────┴─────────────────────┴──────────────────┘
                         Below (1–2)    Fully Meets (3)        Exceeds (4–5)  ► Performance
  Click a cell → list (permissioned). Labels are internal; never shown to employees.
  Overlay toggles: [Retention risk ●] [Promotion nominated ◆] [Critical-role successor ★]
```

## W7 — Quarterly check-in (mobile)

```
┌──────────────────────┐
│ Q1 check-in · Priya  │
│ Goals                │
│ Riverside   [On ▾]   │
│ Lead juniors[At ▾]   │
│ Wins this quarter    │
│ [__________________] │
│ Blockers / support   │
│ [__________________] │
│ Dev plan: CLE ✓ 1/2  │
│ ☐ Mark wins as       │
│   evidence (C1, C2)  │
│ [Save] [Complete ✓]  │
└──────────────────────┘
```

## W8 — Career Explorer

```
┌─ Career framework ── Discipline: [Legal ▾]  Compare: [Band 4 ▾] → [Band 5 ▾] ────┐
│                    Senior Associate (B4)          Project Leader (B5)             │
│ C1 Technical       Owns complex research…         Sets quality standard for team…  │
│ C2 Client          Day-to-day client contact…     Accountable for client outcome…  │
│ C4 Work & People   Guides juniors informally…     Plans, staffs, reviews team work…│
│ Gates              —                              ◆ Led project end to end         │
│                                                   ◆ Supervised others' work         │
│ Advancement basis: technical expertise, execution, ownership, quality, delivery   │
│ ⓘ From Director (B6), advancement requires people leadership and BD. [See B6 →]   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

## W9 — HR cycle console

```
┌─ FY2027 Annual Review ─ Active ─ Phase: Manager review (closes Oct 31) ──────────┐
│ Participants 212 · Excluded 9 (new hire 6, leave 3)          [Pause] [Edit dates]│
│ Completion by unit       Self    Peer    Upward  Manager  Calib.                 │
│ LLP Legal – Litigation   ██100%  ██96%   ██88%   ▓▓61%    ░░ —                    │
│ LLP Legal – Real Estate  ██100%  ▓▓82%   ██90%   ▓▓44%    ░░ —                    │
│ LLC Planning             ██98%   ██95%   ▓▓71%   ▓▓58%    ░░ —                    │
│ Somos MX                 ▓▓91%   ▓▓80%   n<3     ▓▓50%    ░░ —                    │
│ Overdue: 14  [Nudge all] [Escalate to HRBP]   Returned: 2   Export: not ready    │
└──────────────────────────────────────────────────────────────────────────────────┘
```
