# Somos Performance — Performance Review Management Platform

Design package for **Somos Performance**, a performance-management platform built
around Somos's seven-band career framework and its six-category review standard.

It covers the full year: goals, check-ins, continuous feedback, the annual review,
calibration, promotion readiness, development plans and leadership analytics. AI
assists throughout, but **AI never makes or finalizes an employment decision.**

## Document map

| # | Document | Covers deliverables |
|---|---|---|
| 0 | [Executive summary & challenged assumptions](#executive-summary) (below) | — |
| 1 | [Product Requirements Document](docs/01-prd.md) | 1 PRD |
| 2 | [Feature inventory](docs/02-feature-inventory.md) | 2 Feature inventory |
| 3 | [Personas, journeys & UX flows](docs/03-personas-journeys-ux-flows.md) | 3 Personas · 4 Journeys · 10 UX flows |
| 4 | [Career framework & rating model](docs/04-career-framework-and-rating-model.md) | Bands, competencies, scale, readiness model |
| 5 | [Workflow architecture](docs/05-workflow-architecture.md) | Cycle, state machines, Workflow architecture |
| 6 | [Entity relationship model & database design](docs/06-data-model.md) + [`db/schema.sql`](db/schema.sql) | 5 ERD · 6 Database design |
| 7 | [API architecture](docs/07-api-architecture.md) | 7 API |
| 8 | [Product & system architecture, tech stack](docs/08-system-architecture-and-stack.md) | Product architecture · System architecture · 8 Stack |
| 9 | [Roles, permissions & security](docs/09-roles-permissions-security.md) | User roles · Permission model · 13 Security |
| 10 | [Reporting, analytics & dashboards](docs/10-reporting-and-dashboards.md) | 11 Reporting model · Dashboard design |
| 11 | [Wireframes](docs/11-wireframes.md) | 9 Wireframes |
| 12 | [AI architecture](docs/12-ai-architecture.md) | 12 AI architecture · AI features |
| 13 | [Roadmap, MVP, enterprise & implementation plan](docs/13-roadmap-mvp-enterprise-implementation.md) | 14 Roadmap · 15 MVP · 16 Enterprise · 17 Implementation plan |

`db/schema.sql` is a runnable PostgreSQL 16 schema. It was loaded into a clean
database as part of this work.

---

## Executive summary

**The product.** It is a system of record for performance evidence that collects
material all year, so the annual review can summarize it. The **Career Framework**
sits at the center: each band × competency cell has written behavioral anchors.
Everything is measured against it, including ratings, readiness, gap analysis,
development plans and AI drafting. That is how one company-wide standard stays fair
across Legal, Planning, Project Management and Operations.

**What makes it Somos-specific rather than another Lattice clone:**

1. **Band-relative ratings, next-band readiness.** People are rated against the
   expectations of their *current* band and assessed for readiness against the
   anchors of the *next* band. Lattice and others merge these two questions.
2. **Explicit band gates.** Director and Principal have gate criteria such as people
   leadership, business development, market visibility and firm-wide influence. The
   criteria are visible to everyone, scored with evidence, and shown as a gap
   analysis.
3. **Objective evidence from the hours warehouse.** The existing Vantagepoint/DuckDB
   pipeline already scores Hours Expectation, Total Activity and the 2-year promotion
   lookback, with proration for leave. Reviews and promotion cases show this as
   *context*. It is never an automatic input to a rating.
4. **Calibration built for a professional-services firm.** Calibration compares
   across disciplines and offices, measures manager leniency, and runs equity checks
   with minimum-group-size protection.
5. **AI with citations.** Every AI-drafted sentence links back to the check-in, note,
   feedback or goal it came from. Uncited claims are flagged before a human can
   accept the text.

## Challenged assumptions & recommended improvements

These are the founding team's pushbacks on the brief. Each one is reflected in the
detailed documents.

| # | Assumption in the brief | Concern | Recommendation |
|---|---|---|---|
| 1 | "Developmental & Summary Feedback" is a sixth rated category | It is a synthesis, not a competency. Rating it double-counts the other five. | Keep five **rated** competencies. Category 6 becomes the **Summary section**: strengths, development priorities, overall narrative, and a *holistic* overall rating that is not an average. |
| 2 | Step 4 Manager Review comes before Step 5 Peer Review Collection | The manager would write the review without peer input, which defeats "summary of documented evidence". | Collect peer and upward input **in parallel with self-assessment**. The manager review opens once peer input is in. See [05](docs/05-workflow-architecture.md). |
| 3 | The ladder runs straight from Project Leader to Director, and Director requires people leadership | Strong technical experts get pushed into management to advance, and the firm loses its best practitioners. | Add an optional **Expert track** above Project Leader, e.g. *Senior Project Leader / Technical Director*, with expertise, reputation and mentoring gates instead of headcount ownership. It is optional; leadership decides in Phase 0. |
| 4 | One rating scale gives fairness across disciplines | A "4" in Legal and a "4" in Planning only mean the same thing if the anchors are shared and written down. | Shared anchors per band × competency, with **discipline-specific examples** attached. Calibration compares across disciplines. |
| 5 | The 9-box comes out of review data | Without a separately assessed potential axis, the 9-box just re-plots performance. | Assess **growth trajectory** (aspiration, learning agility, scope) separately at calibration. Visibility is restricted and the result is never shown to the employee as a label. |
| 6 | Upward reviews are "anonymous" | Small teams make anonymity fragile: 2 direct reports means no anonymity at all. | Show results only when **n ≥ 3**. Store no reviewer linkage, coarsen timestamps, and offer an optional AI paraphrase to hide writing style. Otherwise the reviews roll up to the skip-level. |
| 7 | "Associate" is a band name | At an LLP, "Associate" is also the attorney *title* at several levels, so the two collide. | Separate **Band** (level 1–7) from **Job Title** (discipline × band). Example: Legal band 3 = "Associate", Planning band 3 = "Planner II". The schema has `job_profile` for this. |
| 8 | Compensation decisions run in the same window as development | Pay talk drowns out development talk. | Hold the development conversation ≥ 2 weeks after or before the comp letter. Development plans are due within 30 days of the review conversation. |
| 9 | Goal scoring feeds the rating | Mechanical scoring rewards sandbagging and punishes stretch goals. | Goal attainment is **evidence** shown next to the rating, not a formula. Stretch goals are marked and calibrated. |
| 10 | Hours targets measure performance | Hours measure input, not quality, and leave or part-time status skews them. | Show prorated hours compliance (already built) as context and as a **promotion gate for hours-required roles**, matching the existing Promotion & Bonus Policy: a 2-year average of ≥ 90%. Never fold hours into competency ratings. |
| 11 | Retention risk is an analytics feature | Predictive "flight risk" scores built from personal data carry legal and trust risk. | Managers enter retention risk and impact of loss as a structured assessment with a reason code. The system flags signals for human review and does no opaque prediction. |
| 12 | Build a Lattice-class platform | Somos is a mid-sized firm. Buying could cover ~70% of the need. | Hold a **build-vs-buy gate in Phase 0**. Build only if the band-gated readiness, hours-evidence integration and AI citations can't be configured in a vendor product. If building, use a **modular monolith**, not microservices. See [13](docs/13-roadmap-mvp-enterprise-implementation.md). |
| 13 | English only | Somos MX staff are part of the firm. | Design for i18n from day one and ship Spanish (es-MX) in Phase 2. Data residency and Mexican privacy law (LFPDPPP) need review. |
| 14 | The annual cycle is generic | The fiscal year runs **Oct 1 – Sep 30** and hours close on Sep 30. | Align the cycle to the fiscal year: self-assessments open mid-September and calibration runs in November. Full calendar in [05](docs/05-workflow-architecture.md). |

## Guiding principles

1. **Evidence over memory.** Every rating should be traceable to documented evidence.
2. **Explicit expectations.** Anyone can see what every band expects and what the next one requires.
3. **One standard, many disciplines.** Shared anchors, discipline-specific examples, cross-discipline calibration.
4. **Humans decide.** AI drafts, summarizes and flags. Humans rate, approve and decide, and the system records who did.
5. **Privacy by design.** Least privilege, real anonymity where promised, minimum-n aggregation, full audit.
6. **Low ceremony.** A quarterly check-in takes 15 minutes. A self-review starts pre-filled with the year's evidence.
