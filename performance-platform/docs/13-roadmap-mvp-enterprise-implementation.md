# 13. Roadmap, MVP, Enterprise Version & Implementation Plan

Today is October 2026. FY2027 started Oct 1, 2026. FY2026 reviews are about to run
on the current (manual) process.

## 13.1 Phase 0 — Foundations & decisions (Oct – Dec 2026, ~10 weeks)

The critical path is **content and decisions, not code.**

| Workstream | Output | Owner |
|---|---|---|
| **Build-vs-buy gate** | Scored evaluation of 2–3 vendors (e.g. Lattice, Leapsome, Culture Amp) against the must-haves below; decision memo | Product + HR + IT |
| Framework authoring | 35 band × competency anchors, gate criteria, discipline examples, rating scale, band weights (AI-drafted, leadership-edited) | HR + Directors |
| Policy decisions | Expert track yes/no; peer attribution; upward in v1 or v1.1; guidance distribution; titles per job profile | Principals |
| Legal/privacy | DPIA, AI use notice, retention schedule, MX data review | Counsel |
| FY27 goals (bridge) | Run FY27 goal setting in a structured spreadsheet template so the data imports into the MVP | HR |
| Baseline metrics | Pulse survey: clarity of advancement, fairness perception | HR |
| Technical spike | Auth with Entra, hours-snapshot export from the warehouse, schema baseline (`db/schema.sql`) | Eng |

**Build-vs-buy must-haves** (if a vendor meets all five at an acceptable cost,
buy and configure):
1. Band × competency anchors with discipline examples, plus next-band comparison.
2. Gate-criteria readiness with evidence links and a hours-policy gate fed by
   external data.
3. Upward anonymity with a configurable minimum-n and no stored linkage.
4. AI drafting with citations to source evidence, and permission-scoped retrieval.
5. Calibration with cross-discipline comparison and equity checks at minimum-n.

Our expectation: vendors meet 1, 3 and 5 partially, and 2 and 4 poorly. If Somos
buys, this design package becomes the configuration spec and integration plan
(hours snapshots → custom fields).

## 13.2 MVP definition (live Mar 2027; first full annual cycle Sep 2027)

**Job to be done:** run the FY2027 annual cycle end to end on the platform, with a
year of documented evidence behind it and an explicit career framework.

**In MVP**
| Area | Scope |
|---|---|
| Platform | Entra SSO, HRIS/CSV sync, roles & policy engine, audit log, email + Teams notifications, admin console |
| Framework | Bands, competencies, anchors, examples, job profiles, gates, Career Explorer |
| Goals | Annual + quarterly, weights = 100%, statuses, scoring, approval, competency links (FY27 goals imported) |
| Conversations | Quarterly check-ins (Q2, Q3 of FY27 live), shared/private notes, feedback give/request, coaching notes, mark-as-evidence |
| Reviews | Cycle admin, eligibility, self, peer (nomination → approval → review), manager review with evidence panel, summary + holistic rating + reference score, return-for-revision |
| Calibration | Sessions, distributions vs guidance, grid with rationale-required adjustments, cross-discipline comparison, promotion committee view |
| Approval & release | L2 + HR approval, lock, Finance CSV export, release, acknowledgment + employee response |
| Promotion | Readiness assessment against next-band anchors and gates, hours gate, readiness level, nomination workflow |
| Development | Plans with gaps, objectives, actions, follow-ups, reviewed in check-ins |
| Analytics | Process health, rating distributions, Manager Hub |
| AI | Peer-feedback summary, evidence surfacing, writing/feedback coach, anchor drafting tool. All cited and logged |

**Not in MVP (by design):** upward reviews (v1.1, Oct 2027 pilot), 9-box,
retention, succession, narrative drafting, readiness score, Spanish, Teams app,
public API.

**MVP exit criteria**
- FY27 cycle: ≥ 95% of reviews submitted by the deadline, calibration held for 100%
  of units, Finance export reconciles to HR's count.
- Zero P1 permission defects (verified by the matrix test suite + pen test).
- Evidence coverage ≥ 60% (80% target in FY28).
- Manager CSAT ≥ 4/5. Employee "I understand my next band" up ≥ 20 points vs
  baseline.

## 13.3 Multi-year roadmap

```
            FY27 (Oct 26–Sep 27)        FY28 (Oct 27–Sep 28)           FY29                  FY30+
            ────────────────────        ────────────────────           ────                  ─────
Phase 0     Decisions, framework
Phase 1     MVP build → live Mar 27
            Q2/Q3 check-ins live
            FY27 annual cycle (Sep)
Phase 1.1                                Upward reviews (anonymity)
                                         Narrative drafts, pre-submit check
                                         Readiness score + gap analysis
                                         Case packets, self-nomination
                                         Mentorships, PDF packets
                                         Equity checks, leniency index
Phase 2                                  9-box + growth trajectory      Succession planning
                                         Retention-risk register        Org trend themes (AI)
                                         Spanish (es-MX)                Expert track (if approved)
                                         Teams app, Outlook check-ins   Public API/webhooks, SCIM
                                         Promotion pipeline analytics   Readiness advisory (AI)
Phase 3                                                                 Project/matter feedback  LMS integration
                                                                        from Vantagepoint closes  Skills taxonomy
                                                                        Natural-language analytics Mentor matching
                                                                                                   Enterprise/SaaS option
```

## 13.4 Enterprise-scale version

What changes if Somos grows tenfold through acquisitions, or decides to offer the
platform to other professional-services firms:

| Dimension | MVP | Enterprise |
|---|---|---|
| Tenancy | Single tenant, `tenant_id` + RLS ready | Multi-tenant (pooled) with optional dedicated DB per large tenant. Data residency (US/EU/MX regions) |
| Scale | ≤ 1k employees | 100k employees per tenant. Read replicas, partitioning of `audit.event`, `evidence`, `ai.generation` by tenant/time |
| Architecture | Modular monolith | Same modules. Split out the **AI Gateway**, **Notifications** and **Analytics** as services first (different scaling profiles). Event bus (Azure Service Bus / Kafka) replaces the Postgres queue for cross-service events |
| Workflow | DB state machines + cron | **Temporal** for long-running cycles, escalations, SLA timers, per-tenant configurable workflows |
| Authorization | In-app policy module | **OpenFGA / Zanzibar-style** relationship store, kept in sync with the org graph. Policy admin UI |
| Org model | Single hierarchy + dotted lines | Matrix orgs, multiple frameworks per BU, framework inheritance |
| Identity | Entra OIDC | Any OIDC/SAML IdP, SCIM 2.0, multiple HRIS connectors (Workday, ADP, BambooHR, UKG), Merge.dev-style unified API |
| Analytics | Postgres mart + DuckDB | Lakehouse (Fabric/Snowflake/Databricks), semantic layer, embedded BI, customer data export (Delta/parquet shares) |
| AI | Shared prompts | Per-tenant prompt customization within guardrails, BYO model endpoint, per-tenant eval dashboards, AI usage quotas |
| Security | Pen test, ASVS L2 | SOC 2 Type II, ISO 27001/27701, BYOK/HYOK encryption, customer-managed audit export (SIEM), SSO-enforced admin, JIT privileged access |
| Compliance | Counsel review | Configurable controls for EU AI Act (high-risk system obligations), NYC Local Law 144-style bias audits, GDPR DSAR tooling, legal hold |
| Platform | Web responsive | Native mobile apps, Teams/Slack apps, public API + webhooks + developer portal |
| Ops | Business-hours support | 99.9% SLA, multi-region DR (RPO 15 min, RTO 1 h), status page, 24×7 on-call |

## 13.5 Technical implementation plan (MVP)

### Team (Phase 1)
| Role | FTE |
|---|---|
| Product manager / HR-systems lead | 1 |
| Product designer (UX + content design) | 1 |
| Full-stack engineers (Python + React) | 3 |
| AI/data engineer | 1 |
| QA / test automation (shared) | 0.5 |
| HR subject-matter owner (Somos) | 0.5 |
| Security/IT partner | 0.25 |

### Delivery plan: 2-week sprints, Jan 4 → Jun 2027 (pilot from Mar)

| Sprint | Dates (2027) | Deliverables |
|---|---|---|
| S0 | Dec 7 – Jan 1 | Repo, CI/CD, IaC, environments, Entra auth, schema baseline + Alembic, design system shell |
| S1 | Jan 4 – 15 | Org sync (CSV/HRIS), employee directory, employment history, policy module skeleton + matrix tests |
| S2 | Jan 18 – 29 | Framework module (admin + Career Explorer), seed content import |
| S3 | Feb 1 – 12 | Goals (CRUD, weights, approval, statuses, scoring); FY27 goal import |
| S4 | Feb 15 – 26 | Check-ins, notes (shared/private), feedback give/request, evidence + mark-as-evidence |
| S5 | Mar 1 – 12 | Hours snapshot integration, Employee Home, Manager Hub. **Pilot: 1 practice group, Q2 check-ins** |
| S6 | Mar 15 – 26 | Notifications (Graph), reminders, digests, audit log UI. AI gateway + writing coach |
| S7 | Mar 29 – Apr 9 | **Firm-wide launch of goals/check-ins/feedback (Q2 check-ins)**. Cycle admin (templates, phases, eligibility) |
| S8 | Apr 12 – 23 | Self + peer flows (nomination, approval, caps), assignment state machine |
| S9 | Apr 26 – May 7 | Manager review workspace, evidence panel, reference score, guards |
| S10 | May 10 – 21 | AI peer summary + evidence surfacing with citations, eval harness |
| S11 | May 24 – Jun 4 | Calibration sessions, distributions, grid + adjustments |
| S12 | Jun 7 – 18 | Approval, lock, Finance export, release, acknowledgment. Readiness + nomination workflow |
| S13 | Jun 21 – Jul 2 | Development plans. Process-health analytics |
| Hardening | Jul 5 – Aug 13 | Pen test, accessibility audit, load test (calibration 300), **dry-run cycle** with the pilot group, manager training |
| Go-live | Sep 15, 2027 | FY2027 annual cycle opens |

### Engineering practices
- **Definition of done:** typed API (OpenAPI) + tests (unit, policy matrix, E2E
  happy path) + audit events + a11y check + docs.
- **Policy matrix tests** run on every PR. A new resource without matrix entries
  fails CI.
- **Migrations:** Alembic, forward-only, with expand/contract for zero downtime.
- **Seed/synthetic data:** a generator for 300 fake employees across bands,
  disciplines and offices, used in dev, demos and AI evals. Never real data
  outside prod.
- **Observability from day 1:** traces on every request, an AI latency/cost
  dashboard, workflow job dashboards.
- **Feature flags** for AI features and per-unit rollout.

### Change management (as important as the software)
| When | Activity |
|---|---|
| Phase 0 | Leadership roadshow: "why", framework previews, FAQ on AI use |
| Pilot (Mar) | One practice group with a champion manager; weekly feedback loop |
| Before the cycle | 45-min manager training: writing evidence-based reviews, using the anchors, calibration norms. 15-min employee video |
| During the cycle | Office hours, in-app guides, HRBP escalation |
| After the cycle | Retro, pulse survey, metrics review vs targets, roadmap reprioritization |

### Immediate next steps (next 30 days)
1. Principals decide the build-vs-buy evaluation scope and the policy questions
   (§13.1).
2. HR + Directors start anchor authoring for bands 4–6 first (highest promotion
   stakes).
3. Eng spike: `etl/export_hours_snapshots.py` from `warehouse.duckdb` → JSON
   matching `perf.hours_snapshot`.
4. Design sprint: Manager review workspace + Career Explorer clickable prototype,
   tested with 5 managers and 5 employees.
5. Counsel: DPIA kickoff and AI use notice draft.
