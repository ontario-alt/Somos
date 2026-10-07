# 6. Entity Relationship Model & Database Design

The authoritative DDL is [`../db/schema.sql`](../db/schema.sql) (PostgreSQL 16).
The starting framework content is [`../db/seed_framework.sql`](../db/seed_framework.sql).
Both load into a clean database. The seed checks that band weights total 100%, and
a test confirms that the upward-review view suppresses reviewees with fewer than 3
responses.

## 6.1 Domain map

```
┌────────────── core ──────────────┐   ┌──────────── framework ────────────┐
│ tenant ─┬─ business_unit         │   │ framework_version                 │
│         ├─ office                │   │   ├─ band (level, track)          │
│         ├─ discipline ───────────┼───┼─► job_profile (band × discipline) │
│         ├─ org_unit (tree)       │   │   ├─ competency (C1..C5, S)       │
│         └─ employee              │   │   ├─ band_competency (weight,     │
│              ├─ employment_record┼───┼─►     anchors) ─ anchor_example   │
│              │   (effective-dated│   │   └─ gate_criterion (per target   │
│              │    band/manager)  │   │       band)                       │
│              ├─ work_relationship│   │ rating_scale ─ rating_scale_point │
│              └─ app_user ─ role_grant                                    │
└──────────────────────────────────┘   └───────────────────────────────────┘

┌──────────────────────────── perf ────────────────────────────────────────┐
│ goal ─┬─ key_result         check_in ─ note (shared/private)             │
│       ├─ goal_update        feedback_request ─ feedback                  │
│       └─ goal_competency    evidence ─ evidence_competency (→competency  │
│                                         or gate_criterion)               │
│ hours_snapshot (from warehouse)    attachment                            │
│                                                                          │
│ review_cycle ─┬─ cycle_phase                                             │
│               └─ cycle_participant (band/manager snapshot)               │
│                    ├─ peer_nomination                                    │
│                    ├─ review_assignment ─ review_response                │
│                    │      (self/mgr/peer/upward*/contributor)            │
│                    │          ├─ competency_rating ─ rating_evidence ─► evidence
│                    │          └─ review_response_version                 │
│                    └─ final_rating                                       │
└──────────────────────────────────────────────────────────────────────────┘
* upward content stored in restricted.upward_response (no reviewer link)

┌──────────────────────────── talent ──────────────────────────────────────┐
│ calibration_session ─┬─ calibration_member                               │
│                      ├─ calibration_subject ─► cycle_participant         │
│                      └─ calibration_adjustment ─► final_rating           │
│ readiness_assessment ─ readiness_criterion_score ─ ..._evidence          │
│ promotion_nomination ─► readiness_assessment                             │
│ comp_recommendation ─► cycle_participant                                 │
│ development_plan ─ skill_gap ─ development_objective ─ development_action│
│ mentorship   talent_review (9-box, retention)   critical_role ─ successor│
└──────────────────────────────────────────────────────────────────────────┘
restricted: demographic (encrypted), upward_response, v_upward_aggregate
ai: generation, flag, evidence_chunk          audit: event, workflow_event, outbox
```

## 6.2 Core ERD (crow's foot, key relationships)

```
employee 1───* employment_record *───1 job_profile *───1 band
    │                 │                       └────────*1 discipline
    │                 └── manager_id ──► employee
    │
    ├──1───* goal 1───* goal_update *───0..1 check_in
    ├──1───* check_in 1───* note
    ├──1───* feedback (as subject)
    ├──1───* evidence 1───* evidence_competency *───1 competency | gate_criterion
    │
review_cycle 1───* cycle_participant *───1 employee
                        │ 1
                        ├───* review_assignment 1───1 review_response 1───* competency_rating
                        │                                                    └──* rating_evidence *──1 evidence
                        ├───1 final_rating 1───* calibration_adjustment
                        ├───0..1 comp_recommendation
                        └───* peer_nomination

employee 1───* readiness_assessment 1───* readiness_criterion_score ─► band_competency | gate_criterion
employee 1───* promotion_nomination ─► readiness_assessment
employee 1───* development_plan 1───* skill_gap 1───* development_objective 1───* development_action
```

## 6.3 Key design decisions

| Decision | Why |
|---|---|
| **Effective-dated `employment_record`**, with band/manager **snapshotted** on `cycle_participant` | Reviews must reflect the band and manager *at the time*. Later HRIS corrections must not rewrite history. |
| **`job_profile` separates band from title** | Fixes the "Associate" naming collision and allows discipline-specific titles. |
| **Framework is versioned** and cycles pin a version | Editing anchors mid-cycle must not change what people were rated against. |
| **Polymorphic `evidence`** with link tables to competencies/gates | One evidence store feeds reviews, readiness, AI retrieval and gap analysis. |
| **`final_rating` separate from `review_response`** | The manager's submitted rating is preserved. Calibration changes are explicit `calibration_adjustment` rows. |
| **Upward responses in `restricted`** with no reviewer FK and a date-only timestamp | Anonymity is enforced by the data model, not only by UI. The aggregate view applies minimum-n. |
| **Demographics encrypted** in `restricted.demographic` | Only the People Analytics service can decrypt, and only into aggregates. |
| **`text + CHECK` statuses** | Easier to evolve than Postgres enums. Mirrored as enums in the app layer. |
| **`tenant_id` everywhere + RLS** | Single tenant at MVP, but the SaaS/multi-entity path needs no re-keying. |
| **Append-only audit** (trigger blocks UPDATE/DELETE) | Defensibility for employment decisions. |
| **Transactional outbox** | Notifications and AI jobs are consistent with state changes. |
| **`hours_snapshot` is imported, not computed** | The DuckDB warehouse stays the single source of truth for the hours policy. |

## 6.4 Data lifecycle & retention (defaults, configurable)

| Data | Retention |
|---|---|
| Final ratings, reviews, promotions | 7 years after separation (counsel to confirm by jurisdiction) |
| Private notes | Author-controlled; deleted 2 years after the author or subject leaves |
| Upward responses | 3 cycles, then deleted. Aggregates kept |
| AI generation logs | 2 years (output), 90 days (full prompt payloads) |
| Audit events | 7 years, immutable |
| Demographics | Until withdrawn by the employee or 1 year after separation |

Legal hold overrides deletion (`legal_hold` flag in the enterprise phase).

## 6.5 Indexing & scale notes

- Hot paths: `review_assignment(reviewer_id, status)` for the inbox,
  `evidence(subject_id, occurred_on)` for the evidence panel, and manager chain
  lookups (`employment_record(manager_id) where current`).
- `core.v_manager_chain` is a recursive view. At enterprise scale, replace it with
  a materialized closure table (`org_closure(ancestor, descendant, depth)`) that is
  refreshed on HRIS sync.
- Calibration queries for 300–2,000 people are a single indexed join. No special
  handling is needed below ~50k participants per cycle.
- Analytics never read OLTP directly at scale. See doc 10 for the star schema.
