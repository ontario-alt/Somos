# 1. Product Requirements Document — Somos Performance

| | |
|---|---|
| Status | Draft v1.0 for leadership review |
| Owner | Product (People Systems) |
| Stakeholders | Managing Principals, Directors, HR/People Ops, Finance (comp), IT |
| Target first full cycle | FY2027 annual review (opens Sep 2027) |

## 1.1 Problem statement

Somos has a formal review process across business units (LLP Legal, LLC Planning,
and Somos MX), offices and disciplines. Today:

- Reviews rely on memory. Evidence from the year (check-ins, client wins, coaching)
  sits in email, documents and people's heads.
- Promotion expectations exist in policy and in leaders' heads. Employees can't
  see clearly what separates Senior Associate from Project Leader, or Project
  Leader from Director.
- Fairness across disciplines can't be shown. Nobody can easily answer "Are
  Planning managers rating more harshly than Legal managers?"
- Hours compliance (Vantagepoint → DuckDB) and performance reviews are separate
  worlds, even though the Promotion & Bonus Policy depends on both.
- Talent decisions (comp, promotion, succession) get made without a consistent,
  auditable record.

## 1.2 Vision

> Every Somos professional always knows what is expected of them at their band,
> what it takes to reach the next one, and how they are tracking. Their annual
> review is an accurate summary of a year of documented performance, calibrated
> to one company-wide standard.

## 1.3 Goals and success metrics

| Goal | Metric | Target (end of first full cycle) |
|---|---|---|
| G1 Single company-wide standard | Share of ratings with ≥ 1 linked evidence item per competency | ≥ 80% |
| | Cross-discipline rating-distribution gap (mean overall rating, Legal vs Planning, after calibration) | ≤ 0.25 points or explained |
| G2 Transparency on advancement | Employees who agree "I understand what's required for my next band" (pulse) | ≥ 80% (baseline in Phase 0) |
| | Employees with a readiness assessment on file (Senior Associate+) | 100% |
| G3 Fair evaluation | Calibration sessions with an equity check run and recorded | 100% |
| | Adverse-impact ratio on promotions, per group with n ≥ 5 | ≥ 0.8, or documented review |
| G4 Support talent decisions | Promotions with a complete case packet | 100% |
| | Director+ roles with ≥ 1 identified successor | ≥ 70% by FY2028 |
| Continuous performance | Quarterly check-in completion | ≥ 85% per quarter |
| | Median days from cycle open to all reviews shared | ≤ 75 |
| Efficiency | Median manager time per direct-report review | ≤ 60 min (with AI drafts) |

## 1.4 Non-goals (v1)

- Payroll or compensation administration. The platform outputs comp
  *recommendations* to Finance. It does not run payroll or salary bands.
- An HRIS replacement. Employee master data comes from the HRIS (or Vantagepoint
  employee records in the interim).
- Time entry. Hours stay in Vantagepoint and the platform reads compliance results.
- Automated employment decisions of any kind.
- Engagement surveys (possible in Phase 3; see the roadmap).

## 1.5 Scope summary

| Module | v1 (MVP) | Later |
|---|---|---|
| Career Framework (bands, competencies, anchors, job profiles) | ✅ | Expert track, skills taxonomy |
| Goals & OKRs | ✅ annual + quarterly, weights, status, scoring | Cascading/aligned OKRs, KR integrations |
| Check-ins & 1:1s | ✅ quarterly template, notes, private notes | Weekly pulses, agendas from calendar |
| Continuous feedback | ✅ give/request feedback, private coaching notes | Praise wall, Teams app |
| Annual review cycle | ✅ self, manager, peer, calibration, approval, sharing | Mid-year review, project-end reviews |
| Upward reviews | ⚪ v1.1 (needs anonymity engine) | |
| Calibration | ✅ distributions, grid, adjustments, basic equity check | Live session mode, scenario modelling |
| Promotion readiness | ✅ checklist + nomination workflow | Scored readiness, case packet automation |
| Development plans | ✅ objectives, actions, follow-ups | Learning catalog integration, mentorship matching |
| Leadership analytics | ⚪ core dashboards | 9-box, succession, retention, trends |
| AI | ✅ peer-feedback summary, evidence surfacing, writing coach | Narrative drafts, inconsistency detection, readiness advisory, org trends |

## 1.6 Functional requirements

Priorities: **P0** = MVP-blocking, **P1** = MVP-desirable/v1.1, **P2** = later.

### FR-1 Career Framework
- FR-1.1 (P0) Configure 7 bands with order, name, description and advancement
  philosophy text.
- FR-1.2 (P0) Configure competencies (5 rated categories) with descriptions.
- FR-1.3 (P0) Behavioral anchors per band × competency, with "what good looks
  like" plus examples per discipline.
- FR-1.4 (P0) Job profiles (discipline × band → title, hours role, expectations).
- FR-1.5 (P0) Band gate criteria (for example, Director: people leadership, BD
  participation), each with an evidence requirement.
- FR-1.6 (P0) Career Explorer: any employee can browse all bands and compare their
  band with the next one side by side.
- FR-1.7 (P1) Framework versioning: a cycle locks to a framework version.
- FR-1.8 (P2) Optional Expert track configuration.

### FR-2 Goals & OKRs
- FR-2.1 (P0) Annual and quarterly goals for individuals, with optional team/firm
  goals they align to.
- FR-2.2 (P0) Weighting. An employee's goal weights for a period must total 100%
  before approval.
- FR-2.3 (P0) Status: Not started / On track / At risk / Off track / Achieved /
  Partially achieved / Missed / Deferred.
- FR-2.4 (P0) Scoring on a 0–1.0 scale per goal (or 0–100% per key result), with a
  weighted rollup.
- FR-2.5 (P0) Manager approval of goals. Changes after approval keep their history.
- FR-2.6 (P1) Stretch flag. Key results with numeric targets and progress
  updates.
- FR-2.7 (P1) Goals link to competencies, so achieving a goal becomes evidence for
  those competencies.

### FR-3 Check-ins, feedback & coaching
- FR-3.1 (P0) Quarterly check-in template: progress on goals, wins, challenges,
  support needed, development progress, manager notes.
- FR-3.2 (P0) Shared notes (visible to both) and private notes (author only).
- FR-3.3 (P0) Continuous feedback: give, request (from anyone), mark visibility
  (private to recipient / shared with manager).
- FR-3.4 (P0) Coaching notes from a manager, tagged to a competency, optionally
  shared.
- FR-3.5 (P0) Any note, feedback item or goal update can be tagged as **evidence**
  for one or more competencies.
- FR-3.6 (P1) Reminders and nudges when a check-in is overdue. Manager dashboard
  shows check-in cadence.

### FR-4 Review cycles
- FR-4.1 (P0) HR creates a cycle from a template: phases, dates, eligibility rules
  (hire-date cutoff, leave status, bands, units), forms per band group.
- FR-4.2 (P0) Self-assessment: per-competency rating, narrative and evidence. Goals
  are summarized automatically.
- FR-4.3 (P0) Peer reviews: the employee nominates 3–6 peers, the manager approves
  or edits, and each reviewer is capped (default 5 reviews per cycle). The peer
  form is short (strengths, development areas, optional ratings on competencies the
  peer has seen).
- FR-4.4 (P0) Manager review: per-competency rating, narrative, evidence,
  development recommendations. Summary section with holistic overall rating.
  Manager sees self, peer and goals data side by side.
- FR-4.5 (P1) Upward reviews with an anonymity threshold (n ≥ 3), aggregated, and
  no linkage stored.
- FR-4.6 (P0) Calibration (see FR-5) changes ratings only through recorded
  adjustments that carry a rationale.
- FR-4.7 (P0) Final approval by the second-level leader and HR, then
  release/sharing. Employee acknowledgment, with an optional employee comment
  (and the right to respond).
- FR-4.8 (P0) Autosave, a draft history, and the ability for HR to return a
  submitted form for revision.
- FR-4.9 (P1) Mid-cycle manager change: either the previous manager contributes or
  the review transfers, with a recorded contribution.
- FR-4.10 (P1) Prorated or abbreviated reviews for new hires and long leaves.

### FR-5 Calibration
- FR-5.1 (P0) Calibration sessions with population, facilitator, participants and
  status.
- FR-5.2 (P0) Distribution views by manager, discipline, office, band and unit,
  compared with the firm-wide distribution and the guidance distribution.
- FR-5.3 (P0) Calibration grid: people placed by proposed rating, drag to adjust,
  with a required rationale.
- FR-5.4 (P0) Rating comparison: side by side for people at the same band across
  disciplines.
- FR-5.5 (P1) Equity checks by demographic group (People Analytics role only,
  minimum n = 5): rating distribution, promotion nomination rate, adjustment
  direction.
- FR-5.6 (P1) Manager leniency/severity index: average change applied in
  calibration, and the gap between a manager's mean rating and the firm mean.
- FR-5.7 (P2) Live session mode: shared screen, voting, parking lot.

### FR-6 Promotion readiness
- FR-6.1 (P0) Readiness assessment by manager against next-band anchors and gate
  criteria: Not yet / Emerging / Demonstrated / Consistently demonstrated, with
  evidence links.
- FR-6.2 (P0) Readiness level: Ready now / Ready in 6–12 months / Ready in 1–2
  years / Not currently targeting.
- FR-6.3 (P0) Promotion nomination workflow: nominate → case packet → second-level
  endorsement → promotion committee (at calibration) → HR/comp → approved/declined
  → communicated → effective-dated band change.
- FR-6.4 (P1) Readiness score (0–100) computed from the criteria, the last 2 final
  ratings and hours-policy gates, shown with how it was calculated. This is
  advisory.
- FR-6.5 (P1) Gap analysis: the next-band criteria not yet demonstrated, flowing
  straight into development objectives.
- FR-6.6 (P1) Self-nomination ("I believe I'm ready") that starts a manager
  conversation.

### FR-7 Development plans
- FR-7.1 (P0) Development plan per employee per year: skill gaps (linked to
  competencies or readiness gaps), objectives, actions (training, stretch
  assignment, mentorship, reading, shadowing), owners, due dates and follow-up
  dates.
- FR-7.2 (P0) Status tracking. Objectives are reviewed at each check-in.
- FR-7.3 (P1) Mentorship assignment: mentor, mentee, focus, cadence, end date.
- FR-7.4 (P2) Training catalog / LMS integration.

### FR-8 Leadership analytics
- FR-8.1 (P1) Performance trends over cycles by unit, discipline and band.
- FR-8.2 (P1) Promotion pipeline: readiness counts per band, time in band.
- FR-8.3 (P1) 9-box talent matrix (performance × growth trajectory).
- FR-8.4 (P1) Retention risk & impact of loss, entered by managers, with a
  register view for leadership.
- FR-8.5 (P2) Succession plans: critical roles, successors, readiness, bench
  strength.
- FR-8.6 (P1) Process health: completion, check-in cadence, overdue items.

### FR-9 AI assistance
See [12-ai-architecture.md](12-ai-architecture.md). All AI features must:
- FR-9.1 (P0) Label AI-generated content and require a human to accept or edit it
  before it is saved to a record.
- FR-9.2 (P0) Cite source evidence for factual claims.
- FR-9.3 (P0) Respect the caller's permissions in retrieval.
- FR-9.4 (P0) Never produce or change a rating, a readiness level or a decision on
  its own.
- FR-9.5 (P0) Be logged (prompt version, sources, output, accepted/edited/
  rejected).

### FR-10 Administration & integration
- FR-10.1 (P0) SSO with Microsoft Entra ID. SCIM or a scheduled HRIS sync for
  employees, managers, offices and units.
- FR-10.2 (P0) Import of hours-compliance snapshots from the existing warehouse
  (Hours Expectation %, Total Activity %, Bonus Threshold, 2-year lookback), per
  person per measuring period.
- FR-10.3 (P0) Email and Microsoft Teams notifications.
- FR-10.4 (P0) Audit log of every read of restricted data and every change.
- FR-10.5 (P1) Exports: PDF review packet, CSV for Finance (final ratings, comp
  recommendations).

## 1.7 Non-functional requirements

| Area | Requirement |
|---|---|
| Availability | 99.5% business hours (MVP); 99.9% (enterprise) |
| Performance | p95 page load < 1.5 s; calibration grid with 300 people < 2 s |
| Scale | MVP: 1,000 employees, 1 tenant. Enterprise: 100k employees per tenant, multi-tenant |
| Security | SSO-only, MFA through IdP, encryption at rest and in transit, field-level encryption for restricted data, full audit |
| Privacy | Minimum-n thresholds, anonymity guarantees, data-retention policy (default: reviews kept 7 years after separation, configurable) |
| Accessibility | WCAG 2.2 AA |
| Localization | i18n-ready strings, dates, numbers; en-US at launch, es-MX in Phase 2 |
| Auditability | Every rating change has an actor, a timestamp, the before/after values and a rationale |

## 1.8 Assumptions & dependencies

- Employee master, manager and office data come from the HRIS. Until there is one,
  a CSV/Vantagepoint import is maintained by HR.
- The competency anchors (35 band × competency cells plus gate criteria) are
  **content** that leadership must write in Phase 0. This is the critical path, not
  the code.
- The hours warehouse (`warehouse.duckdb`) keeps producing per-person measuring
  period results. A nightly export job publishes them to the platform.

## 1.9 Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Anchor content isn't ready in time | High | Start in Phase 0. AI drafts first versions from current policy and leaders edit them. Launch with the Director/Principal gates plus generic anchors if needed |
| Manager adoption (seen as "more admin") | Medium | Pre-filled evidence, AI drafts, 15-minute check-ins, Teams nudges |
| Employees distrust AI in reviews | Medium | Transparency notice, human ownership, no AI rating, opt-out of AI drafting per manager |
| Anonymity breach in small teams | Medium | Thresholds, rollup to skip-level, no linkage stored |
| Scope creep toward a full HRIS | Medium | Non-goals enforced. Integrate, don't replicate |
| Legal exposure in AI/analytics | Low–Med | Counsel review, AI advisory only, equity checks, documented decisions |
