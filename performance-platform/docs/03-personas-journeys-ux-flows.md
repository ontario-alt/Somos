# 3. Personas, User Journeys & UX Flows

## 3.1 Personas

Personas are composites. They are not real Somos staff.

### P1 — Dana, Senior Associate (Legal, band 4)
- **Context:** 5 years at the firm, billing toward the 1,900-hour expectation.
  Wants to reach Project Leader in 1–2 years.
- **Goals:** know exactly what Project Leader requires; get credit for the
  matter they ran end to end; avoid a review that only reflects the last 6 weeks.
- **Frustrations:** "Promotion feels like a black box." Feedback arrives once a
  year.
- **Needs from the platform:** Career Explorer, readiness gaps, an evidence log, a
  self-review pre-filled with the year's documented wins.

### P2 — Luis, Analyst / Specialist (Planning, band 2, Somos MX)
- **Context:** Project Specialist on a Planner-role hours target. Works across
  three project leaders. Spanish is their first language.
- **Goals:** feedback from everyone they work for, not just their formal manager.
- **Frustrations:** their manager barely sees their day-to-day work.
- **Needs:** feedback requests to project leaders, peer review input, mobile-
  friendly forms, Spanish UI (Phase 2).

### P3 — Priya, Project Leader → people manager (Planning, band 5, 6 reports)
- **Context:** strong practitioner who is new to managing. Aiming for Director.
- **Goals:** write fair, specific reviews without spending a weekend on them; grow
  the people-leadership evidence Director requires.
- **Frustrations:** reconstructing a year of notes; unsure whether their ratings
  are harsher than other managers'.
- **Needs:** check-in templates, coaching notes, AI evidence surfacing and
  drafting, calibration feedback on their rating pattern.

### P4 — Marcus, Director (Legal, band 6, leads a practice group, 25 people)
- **Context:** skip-level for 25 people, runs calibration for the practice group,
  part of the promotion committee.
- **Goals:** consistent ratings across their managers; a clear promotion pipeline;
  successors for their own role.
- **Needs:** distribution views, calibration grid, promotion case packets, 9-box,
  succession.

### P5 — Elena, Principal / Managing Leader (band 7)
- **Context:** firm leadership. Owns comp and promotion budgets and
  firm-wide talent strategy.
- **Goals:** confidence that the standard is applied the same way across LLP,
  LLC and MX; visibility into risk and bench strength.
- **Needs:** leadership analytics, approvals, trend reports, retention-risk
  register.

### P6 — Grace, HR / People Ops Lead
- **Context:** runs the cycle, owns the framework, answers "where is my review?"
- **Goals:** cycle runs on time; clean data to Finance; defensible, auditable
  decisions.
- **Needs:** cycle admin, completion tracking, reminders, return-for-revision,
  equity checks, exports, audit log.

### P7 — Sam, Compensation / Finance partner
- **Needs:** final ratings + promotion outcomes + comp recommendations as a
  locked export; budget roll-ups.

## 3.2 User journeys

### J1 — Employee: a year in the platform (Dana)

```
Oct            Jan/Apr/Jul         Throughout          Sep–Oct            Dec              Jan
GOALS  ───────► CHECK-INS ────────► FEEDBACK & ───────► SELF-REVIEW ──────► REVIEW ─────────► DEV PLAN
set 4 goals     15-min quarterly    EVIDENCE            pre-filled with    conversation,    from gaps &
(weights=100%)  check-in; update    request feedback    goals, feedback,   acknowledge,     readiness;
mgr approves    goal status; log    after big matter;   check-in notes;    see readiness    mentor
                wins as evidence    "mark as evidence"  nominate peers     & next-band gaps assigned
```

| Stage | Actions | Emotion | Opportunity |
|---|---|---|---|
| Goal setting | Drafts goals, AI coach suggests measurable versions, links to competencies | Hopeful | Show next-band anchors while setting goals |
| Check-ins | Updates status, records wins | Neutral → engaged | Make it a 15-min mobile flow |
| Feedback | Requests feedback after a hearing or submission | Anxious → reassured | One-click "request feedback on this matter" |
| Self-review | Evidence auto-collected; writes reflections | Relieved (not starting blank) | Evidence panel per competency |
| Review | Reads final review, sees calibrated rating, readiness, gaps | High stakes | Explain the rating against band anchors in plain language |
| Development | Co-creates plan from gaps | Motivated | Pre-built objectives from gap analysis |

### J2 — Manager: writing a review (Priya)
1. Gets notified that the manager review phase has opened. Peer and self inputs are
   already in.
2. Opens the review workspace. Left: employee's self-review. Center: the form.
   Right: evidence panel (goals, check-in notes, feedback, coaching, hours context).
3. Clicks **"Summarize peer feedback"**. The AI summary appears with citations to
   each peer response.
4. For each competency: reads the band anchor, picks a rating, clicks **"Draft
   from evidence"**, then edits the draft. Uncited claims are highlighted.
5. Writes the Summary and holistic overall rating. The system shows the weighted
   reference score for comparison.
6. Runs **"Pre-submit check"**. AI flags: "You rated Client Service 4 but the
   narrative cites no client examples," and "The phrase 'abrasive' describes
   personality, not behavior."
7. Submits. The review is locked for calibration.

### J3 — Director: calibration (Marcus)
1. Opens the pre-read: distribution by manager, with a flag that Priya's ratings
   average 0.4 below the firm.
2. Joins the session. The facilitator walks the grid band by band.
3. Moves two people. Each move requires a rationale, which is recorded.
4. Reviews promotion nominations in committee view and endorses two.
5. People Analytics runs the equity check. No adverse-impact flags. The session is
   closed.

### J4 — Promotion (Dana → Project Leader)
```
Manager readiness assessment ─► "Ready now" ─► Nomination ─► Case packet auto-built
 (next-band anchors + gates)                                    (ratings 2 yrs, evidence,
                                                                 hours lookback ≥90%, peer themes)
        ─► Skip-level endorsement ─► Promotion committee @ calibration ─► Approved
        ─► Comp recommendation ─► Communicated ─► Band change effective Jan 1
```

### J5 — HR: running the cycle (Grace)
Create cycle from template → check eligibility list (exceptions: new hires,
leaves) → launch → monitor completion heatmap → nudge or escalate → return any
review missing evidence → set up calibration sessions → lock final ratings →
export to Finance → release reviews → track acknowledgments and dev plans.

### J6 — Upward review (Luis reviewing their manager)
Receives an anonymous survey link → sees the guarantee "Your manager will only
see results if 3+ people respond; your name is never stored with your answers" →
answers 8 questions plus 2 open text → optional AI paraphrase of comments → submits.

## 3.3 UX flows

### F1 — Annual review flow (system level)

```
[HR: Create Cycle] → [Eligibility review] → [Launch]
        │
        ├─► Self-assessment (E) ──────────────────────┐
        ├─► Peer nomination (E) → approve (M) → Peer reviews (Peers)
        ├─► Upward reviews (Reports, anonymous) ──────┤
        ▼                                             ▼
   Manager review opens when: self submitted AND (peers complete OR deadline passed)
        │
        ▼
   Manager submits → [Calibration session] → adjustments(rationale)
        │
        ▼
   Final approval: Skip-level ✓ → HR ✓ → LOCKED
        │
        ├─► Export to Finance (comp/promo)
        ▼
   Release to employee → Conversation held (M marks) → Employee acknowledges (+comment)
        │
        ▼
   Development plan created (≤30 days) → reviewed in Q1 check-in
```

### F2 — Manager review form flow

```
Open review ─► Context header (band, job profile, tenure, hours context)
   │
   ├─ For each of 5 competencies:
   │    show anchor(band) ─► rating (1–5 / N/A) ─► narrative ─► evidence links (≥1 required for 1,2,5)
   │    [Draft from evidence] [Show self rating] [Show peer themes]
   │
   ├─ Summary: strengths · development priorities · overall narrative · holistic rating
   │    reference score shown; if |holistic − reference| ≥ 1 → justification required
   │
   ├─ Readiness (Senior Associate+): next-band criteria → level
   │
   ├─ [Pre-submit check] → resolve or dismiss flags (dismissal logged)
   └─ Submit
```

### F3 — Quarterly check-in flow (≤ 15 minutes)
```
Reminder (Teams) → Employee pre-fills: goal status, wins, blockers, support needed
→ 1:1 meeting → Manager adds shared notes + private notes → tag evidence
→ Both mark complete → next check-in auto-scheduled
```

### F4 — Feedback request flow
```
Employee: "Request feedback" → choose people (any employee) + context (matter/project)
→ choose questions (template or custom) → recipients get Teams/email
→ responses go to employee (and manager if visibility = shared) → "mark as evidence"
```

### F5 — Calibration flow
```
Facilitator creates session → selects population (filters) → invites participants
→ pre-read published (locks inputs) → live session: grid by band → adjustments + rationale
→ promotion committee step → equity check (PA) → close session → ratings → "calibrated"
```

### F6 — Development plan flow
```
Review released → system proposes plan skeleton:
  gaps from (ratings ≤2) + (readiness criteria not demonstrated) + manager dev recommendations
→ AI suggests objectives/actions (optional) → employee edits → manager approves
→ follow-up dates → reviewed at each quarterly check-in
```
