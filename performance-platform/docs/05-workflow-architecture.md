# 5. Workflow Architecture

## 5.1 Revised annual cycle (aligned to fiscal year Oct 1 – Sep 30)

The brief's nine steps are kept, with two changes. **Peer collection moves before
the manager review**, and the **development conversation is separated from the comp
communication**.

| Step | Brief | Revised timing (FY27 example) | Notes |
|---|---|---|---|
| 1 | Goal setting | Oct 1 – Oct 31, 2026 | Annual goals for FY27; quarterly goals for Q1 |
| 2 | Quarterly check-ins | Q1: Jan · Q2: Apr · Q3: Jul (Q4 folds into the annual review) | 2-week windows |
| 3 | Self assessment | Sep 15 – Oct 9, 2027 | Opens before FY close; evidence pre-filled |
| 5 → 3b | Peer review collection | Nominations Sep 15–22; reviews Sep 23 – Oct 14 | **Moved earlier** |
| 3c | Upward reviews (optional) | Sep 23 – Oct 14 | Anonymous |
| 4 | Manager review | Oct 10 – Oct 31 | Hours data final after Sep 30 close (~Oct 15) |
| 6 | Calibration | Nov 3 – Nov 21 | By practice group, then firm-wide for bands 5–7 |
| 7 | Final rating approval | Nov 24 – Dec 5 | Skip-level + HR sign-off; ratings locked |
| 8 | Compensation / promotion decisions | Dec 1 – Dec 15 | Finance export; promotions effective Jan 1 |
| — | Review conversations | Dec 8 – Dec 19 | Review released at the conversation |
| 9 | Development plan creation | by Jan 31, 2028 | ≥ 2 weeks after the conversation; reviewed at the Q1 check-in |

## 5.2 Engine design

A **database-backed state machine** with a durable job queue. No external
workflow engine in the MVP. Temporal is the enterprise option (see doc 13).

```
               ┌─────────────────────────────────────────┐
  API command ─► Domain service (validates transition)   │
               │  - guard checks (permissions, data)     │
               │  - writes new state + workflow_event    │──► outbox row (same TX)
               └─────────────────────────────────────────┘
                                   │
     Scheduler (cron, 1/min) ──────┤ phase auto-open/close, reminders, escalations
                                   ▼
                         Job queue (Postgres-backed)
                     notifications · task generation · AI jobs · exports
```

Principles:
- **Every transition is an event.** `workflow_event` (entity, from, to, actor,
  reason, at) and an immutable audit trail.
- **Transactional outbox.** Notifications and side effects are enqueued in the same
  transaction as the state change, so nothing is lost or duplicated.
- **Idempotent jobs.** Each job has a dedupe key (e.g. `remind:{assignment}:{date}`).
- **Phase-driven task generation.** When a phase opens, the engine creates
  `review_assignment` rows for all eligible participants.

## 5.3 Cycle state machine

```
draft ──launch──► active ──all phases closed──► finalizing ──lock──► locked ──release──► released ──archive──► closed
  │                  │
  └──cancel──► cancelled  (pause/resume allowed in active)
```

Phase types: `goal_setting, self, peer_nomination, peer, upward, manager,
calibration, approval, release, development`. Each phase has `opens_at`, `closes_at`,
`auto_open` and `auto_close`, plus a `grace_days` setting.

## 5.4 Review assignment state machine

(Applies to self, manager, peer, upward and contributor reviews.)

```
         ┌───────────── decline (peer only, w/ reason) ─────────► declined
         │
pending ─┴─open─► in_progress ─submit─► submitted ─(calibration lock)─► locked
   │                    ▲                   │
   │                    └──── return (HR/skip-level, reason) ─┘
   └──expire (phase closed, not started)──► expired
```

Guards:
- `submit` (manager): every rated competency has a rating or N/A; evidence rules
  met (doc 04); justification present when the holistic and reference scores
  diverge.
- Manager `open` is blocked until the self-review is submitted **or** the self
  phase has closed, and peer reviews are complete **or** the peer phase has closed.
- `return` is allowed only before `locked`. It reopens the form with the previous
  version kept.

## 5.5 Final rating state machine (one per participant per cycle)

```
proposed (from manager submit) ─► in_calibration ─► calibrated ─► approved_l2 ─► approved_hr ─► locked ─► released ─► acknowledged
                                        │ adjust (rationale) ↺
```
- `calibration_adjustment` rows record each change (old → new, by, rationale).
- After `locked`, changes need a **post-lock amendment** (HR + Exec), which is
  audited.
- `acknowledged` means "I have read this," not "I agree." The employee can attach
  a response.

## 5.6 Peer nomination flow

```
employee nominates (3–6) ─► manager approves/edits ─► system checks reviewer load (cap 5)
   ─► invitations ─► reviewer accepts/declines ─► if < 3 accepted at T-5 days: alert manager
```

## 5.7 Upward review flow (anonymity engine)

```
eligible reports ─► anonymous token issued per (cycle, reviewee, reviewer)
   - assignment table records completion only (no link to response)
   - response stored with random submission_id, reviewee_id, date-only timestamp
   ─► phase closes ─► if responses ≥ 3: aggregate released to manager (+ skip-level)
                      else: rolled into skip-level-only aggregate or suppressed
```

## 5.8 Promotion nomination state machine

```
draft ─submit─► nominated ─endorse─► endorsed_l2 ─committee─► committee_review
   ─decide─► approved | deferred | declined
approved ─comp─► comp_finalized ─communicate─► communicated ─effective date─► effective (band change written to employment_history)
```

## 5.9 Development plan state machine
```
draft ─► submitted ─► approved ─► active ─► completed | carried_forward
objectives: not_started ─► in_progress ─► completed | dropped   (follow-up date reminders)
```

## 5.10 Goals
```
draft ─► submitted ─► approved ─► (in_progress with status updates) ─► scored ─► closed
change after approval → new goal_version, needs re-approval if weight or target changes
```

## 5.11 Notifications & escalation policy

| Trigger | Channel | Recipient |
|---|---|---|
| Phase opens | Email + Teams | Assignees |
| 3 days before close, not submitted | Teams | Assignee |
| Overdue 2 days | Teams + email | Assignee, CC manager |
| Overdue 5 days | Email | HRBP (dashboard flag) |
| Review returned | Email + Teams | Assignee |
| Review released | Email | Employee |
| Dev plan follow-up date | Teams | Employee + manager |
| Check-in overdue | Teams | Manager |

Digest mode: managers get one daily digest instead of N pings.

## 5.12 Exceptions handled by the engine

| Case | Handling |
|---|---|
| Manager changes mid-cycle | New manager owns the review; old manager gets a **contributor** assignment; both recorded |
| Employee on leave | Eligibility rule excludes them, or gives them an abbreviated form; hours proration from `leave.csv` |
| New hire after cutoff (e.g. Jul 1) | Excluded from ratings; check-in only |
| Termination mid-cycle | Assignments cancelled; data retained per policy |
| Promotion effective mid-year | Rated against the band held for most of the year (configurable) |
| Reviewer conflict (relative, etc.) | Reviewer declines with a conflict reason; HR can reassign |
