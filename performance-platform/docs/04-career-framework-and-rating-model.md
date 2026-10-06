# 4. Career Framework & Rating Model

This is the domain core. Every module (reviews, readiness, development, AI) is
measured against it.

## 4.1 Bands

| Band | Name | Primary advancement basis | Typical scope |
|---|---|---|---|
| 1 | Clerk | Accuracy, reliability, learning the work | Defined tasks, close supervision |
| 2 | Analyst / Specialist | Technical skill, timely execution | Workstreams within a project |
| 3 | Associate | Independent execution, quality | Significant parts of matters/projects |
| 4 | Senior Associate | Technical depth, owning complex work, guiding juniors | Complex matters, informal leadership |
| 5 | Project Leader | Project ownership, client delivery, quality of team output | Leads projects/matters end to end |
| 6 | Director | **People leadership, strategy, staff development, external relationships, BD, multiple complex initiatives** | Practice/team leadership |
| 7 | Principal / Leader | **Organizational leadership, market visibility, business generation, firm-wide influence** | Firm-level |

**The philosophy changes at the 5 → 6 transition.** Through Project Leader,
advancement is about *the work*. From Director on, it is about *people, clients
and the firm*. The platform shows this explicitly in two ways:

- **Band gate criteria** (below) must be demonstrated, with evidence, before
  someone can be rated "Ready now" for Director or Principal.
- **Band competency weights** shift toward Client and People/Self-Management at
  higher bands.

### Recommended: Expert track (optional, Phase 2)
An optional band **6E — Technical Director / Senior Expert** for practitioners with
firm-recognized expertise who don't lead teams. Its gates: recognized subject-matter
authority, quality standard-setting, mentoring, external technical reputation. It
keeps people from being forced into management to advance. Leadership decides in
Phase 0; the schema supports tracks either way (`band.track`).

### Band vs. title
`job_profile` = discipline × band → title + hours role. For example:

| Band | Legal (LLP) | Planning (LLC) | Operations |
|---|---|---|---|
| 1 | Legal Clerk | Planning Clerk | Office Clerk |
| 2 | Paralegal / Legal Specialist | Project Specialist | Analyst |
| 3 | Associate | Planner II | Associate |
| 4 | Senior Associate | Senior Planner | Senior Associate |
| 5 | Project Leader | Project Leader | Manager |
| 6 | Director | Director | Director |
| 7 | Principal | Principal | Principal |

(Illustrative. HR confirms the titles in Phase 0.)

## 4.2 Competencies

Five **rated** competencies, plus the **Summary** section (category 6 in the brief).

| Code | Competency | What it covers |
|---|---|---|
| C1 | Skills & Technical Excellence | Domain expertise, quality, accuracy, judgment, staying current |
| C2 | Client Service & Value | Responsiveness, understanding client goals, delivering value, relationships, (6+) business development |
| C3 | Communication & Professional Skills | Written/oral communication, presence, negotiation, collaboration |
| C4 | Work, People & Self-Management | Planning, prioritization, efficiency, delegation, (5+) team leadership, (6+) staff development |
| C5 | Professional Responsibility & Citizenship | Ethics, compliance, firm contribution, recruiting, mentoring, DEI, knowledge sharing |
| S | Developmental & Summary Feedback | Not rated per se. Strengths, development priorities, overall narrative, **holistic overall rating** |

Each rated competency captures: **numeric rating · narrative · evidence links ·
development recommendation**, as the brief requires.

### Anchors
For each band × competency there is an anchor: 3–6 observable behaviors describing
**fully meets (3)** at that band, plus short descriptors for 1 and 5.

Example: **C4 Work, People & Self-Management**

| Band | Anchor (meets expectations) |
|---|---|
| 3 Associate | Plans own work across concurrent assignments; flags risks early; meets deadlines without reminders; manages own hours to expectation. |
| 5 Project Leader | Plans and staffs projects; delegates appropriately and reviews work; manages budget/hours on matters; gives timely feedback to team members. |
| 6 Director | Builds and leads teams; sets goals for and develops direct reports; holds regular check-ins; resolves performance issues; balances multiple complex initiatives. |

Each anchor carries **discipline examples**, for example "Legal: runs the closing
checklist on a multi-party transaction"; "Planning: runs the entitlement schedule
across three municipal approvals".

## 4.3 Rating scale

Ratings are **relative to current-band expectations**.

| Value | Label | Meaning | Guidance distribution* |
|---|---|---|---|
| 5 | Exceptional | Consistently exceeds band expectations; operating at the next band here | ~5–10% |
| 4 | Strong | Exceeds expectations in significant ways | ~20–30% |
| 3 | Fully Meets | Solidly delivers what the band requires. **A good result.** | ~50–60% |
| 2 | Developing | Partially meets; specific gaps | ~5–15% |
| 1 | Does Not Meet | Significant gaps; improvement plan required | ~0–5% |
| N/A | Insufficient evidence | Not observed this period | — |

\*Guidance only. **No forced distribution.** Calibration shows it as a reference
line, and big deviations prompt discussion, not automatic changes.

Evidence rules: ratings of 1, 2 or 5 need ≥ 1 linked evidence item and a narrative
of ≥ 50 words. 3 and 4 are recommended to have evidence too.

### Overall rating
- The manager sets the **holistic overall rating** (1–5) in the Summary.
- The system computes a **reference score** = Σ(weight × competency rating) using
  band weights and shows it next to the holistic rating.
- If |holistic − reference| ≥ 1.0, a justification is required.

Default band weights (%), configurable:

| Band | C1 | C2 | C3 | C4 | C5 |
|---|---|---|---|---|---|
| 1–2 | 35 | 15 | 20 | 20 | 10 |
| 3–4 | 30 | 20 | 20 | 20 | 10 |
| 5 | 25 | 25 | 15 | 25 | 10 |
| 6 | 15 | 25 | 15 | 30 | 15 |
| 7 | 10 | 30 | 15 | 25 | 20 |

## 4.4 Band gate criteria

| Target band | Gate criterion | Evidence expected |
|---|---|---|
| 5 Project Leader | Led ≥ 1 project/matter end to end with client accountability | Project list, client feedback |
| 5 | Supervised others' work with quality outcomes | Feedback from juniors/peers |
| 6 Director | People leadership: direct reports developed over ≥ 12 months | Check-in records, upward feedback, team retention |
| 6 | Strategic planning: authored/owned a practice or team plan | Plan document, outcomes |
| 6 | Staff development: mentored/developed someone who advanced | Mentorship records, promotions |
| 6 | External relationships: owns key client/agency relationships | Client list, feedback |
| 6 | BD participation: contributed to pitches/proposals/originations | Originations data (Vantagepoint), proposals |
| 6 | Manages multiple complex initiatives at once | Project portfolio |
| 7 Principal | Organizational leadership: led a firm-level initiative | Initiative record |
| 7 | Market visibility: speaking, publications, recognized authority | Activity log |
| 7 | Business generation: sustained origination | Originations data |
| 7 | Firm-wide influence & reputation | Leadership/peer input |

**Hours-policy gate** (hours-required roles: Attorney/Associate and Planner roles):
2-year average Hours Expectation ≥ 90%, from the existing measuring-period
warehouse (`dashboard/hours_credit.py` logic, prorated for leave). It is shown as
**Met / Not met / N/A** with a link to the breakdown. It is a *policy gate*, not a
performance rating.

## 4.5 Promotion readiness model

### Readiness assessment (manager, reviewed at calibration)
For each next-band competency anchor and each gate criterion:

| Level | Meaning | Points |
|---|---|---|
| Not yet demonstrated | No evidence | 0 |
| Emerging | Occasional, with support | 1 |
| Demonstrated | Independently, more than once | 2 |
| Consistently demonstrated | Sustained, recognized by others | 3 |

### Readiness score (advisory, 0–100, with full breakdown shown)
```
criteria_score  = Σ points / (3 × #criteria)                          weight 60%
performance     = mean(last 2 final overall ratings) normalized 1→0, 5→1  weight 25%
evidence_depth  = min(1, evidence items linked to next-band criteria / 2×#criteria)  weight 15%
score = 100 × (0.60 × criteria_score + 0.25 × performance + 0.15 × evidence_depth)

Hard gates (any failed → max readiness level = "Ready in 6–12 months"):
  - any gate criterion at "Not yet demonstrated"
  - hours-policy gate Not met (hours-required roles)
  - latest final overall rating < 3
```
Time in band is **shown** but not scored. Scoring it would reward tenure over
capability.

### Readiness levels (human-assigned; score suggests)
| Level | Suggested when |
|---|---|
| Ready now | score ≥ 80 and no failed gates |
| Ready in 6–12 months | 60–79, or gates pending |
| Ready in 1–2 years | 40–59 |
| Not currently targeting | < 40, or employee preference |

## 4.6 Growth trajectory (9-box Y-axis)

Assessed at calibration, separately from performance (Low / Medium / High):
- **Aspiration:** wants larger scope (employee-stated in the career conversation)
- **Learning agility:** speed of ramping into new situations
- **Scope capacity:** has shown effectiveness at broader scope

The result is **never shown to the employee as a label**. Its visibility is limited
to the manager chain, HR and Exec.
