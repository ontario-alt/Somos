# 9. User Roles, Permission Model & Security Model

## 9.1 Roles

Access combines three things:

1. **Platform roles (RBAC)**, granted explicitly and optionally scoped to a business
   unit or org unit.
2. **Relationship roles (ReBAC)**, derived from data (manager chain, reviewer
   assignment, calibration membership, mentor).
3. **Data classification**, which sets field-level visibility.

| Role | Type | Who | Core capabilities |
|---|---|---|---|
| Employee | default | Everyone | Own goals, check-ins, feedback, self-review, released reviews, own dev plan, Career Explorer |
| Manager | relationship (direct reports) | Anyone with reports | Reports' goals, check-ins, shared notes, reviews, readiness, dev plans, talent review |
| Senior leader (skip-level+) | relationship (manager chain depth ≥ 2) | Directors, Principals | Read the org subtree. Approve L2. Calibration participation |
| Peer reviewer | relationship (assignment) | Assigned | Write own peer review. Read nothing else about the subject |
| Contributor | relationship (assignment) | Previous manager, project leader | Write a contributor review |
| Mentor | relationship (mentorship) | Assigned mentors | Read the mentee's dev plan objectives they're attached to |
| Calibration participant | relationship (session member) | Session members | Read ratings and review summaries for the session population, **during the session window only** |
| Calibration facilitator | RBAC (scoped) | HRBPs, Directors | Set up sessions, apply adjustments |
| HR Business Partner | RBAC (scoped to BU/unit) | HR | Cycle operations, return reviews, view reviews in scope |
| HR Admin | RBAC | People Ops lead | Framework, templates, cycles, all review content, exports |
| People Analytics | RBAC | 1–2 people | Equity checks, demographic aggregates (n ≥ 5). No individual demographic view |
| Compensation Admin | RBAC | Finance | Final ratings, promotions, comp recommendations. **No narratives** |
| Executive | RBAC | Leadership team | Firm-wide analytics, 9-box, succession, approvals |
| System Admin | RBAC | IT | Config, integrations, SSO. **No access to performance content** (separation of duties) |
| Auditor | RBAC | Internal audit/counsel | Read audit log; time-boxed access to content with a reason |

## 9.2 Visibility matrix (who can read what about employee X)

| Data about X | X | X's manager | Skip-level+ | Peer reviewer | Calib. member (in session) | HRBP (scope) | HR Admin | Comp | PA | Exec |
|---|---|---|---|---|---|---|---|---|---|---|
| Goals & status | ✅ | ✅ | ✅ | — | summary | ✅ | ✅ | — | agg | ✅ |
| Shared check-in notes | ✅ | ✅ | ✅ | — | — | ✅ | ✅ | — | — | — |
| Private notes | author only | author only | — | — | — | — | — | — | — | — |
| Feedback (recipient-only) | ✅ | — | — | — | — | — | break-glass | — | — | — |
| Self-review | ✅ | after submit | after submit | — | summary | ✅ | ✅ | — | — | — |
| Peer review (attributed) | **released synthesis only**¹ | ✅ | ✅ | own only | summary | ✅ | ✅ | — | — | — |
| Upward results (about X as manager) | aggregate n≥3 | — | aggregate n≥3 | — | — | aggregate | aggregate | — | agg | aggregate |
| Manager review draft | — | ✅ | after submit | — | ✅ | ✅ | ✅ | — | — | — |
| Final rating | after release | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ | agg | ✅ |
| Calibration adjustments & rationale | — | ✅ | ✅ | — | ✅ | ✅ | ✅ | — | agg | ✅ |
| Readiness assessment | level + gaps after release | ✅ | ✅ | — | ✅ | ✅ | ✅ | level | agg | ✅ |
| Growth trajectory / 9-box | **never** | ✅ | ✅ | — | ✅ | ✅ | ✅ | — | agg | ✅ |
| Retention risk | **never** | ✅ | ✅ | — | — | ✅ | ✅ | — | agg | ✅ |
| Hours compliance | ✅ | ✅ | ✅ | — | ✅ | ✅ | ✅ | ✅ | agg | ✅ |
| Demographics | own (self-reported) | — | — | — | — | — | — | — | **aggregate only** | — |
| Comp recommendation | after communication | ✅ | ✅ | — | — | ✅ | ✅ | ✅ | agg | ✅ |

¹ Default: peer feedback reaches the employee as a manager-curated synthesis
without attribution. The cycle setting can switch to "attributed peer feedback".

## 9.3 Policy engine design

```python
# platform/policy — every read/write goes through authorize()
decision = policy.authorize(actor, action="review_response.read", resource=resp)
# decision: allow | deny, plus a field mask (e.g. strip private notes)

Rules are pure functions over facts:
  is_self(actor, subject)
  is_manager_of(actor, subject, at=date)          # current or at the cycle snapshot
  in_manager_chain(actor, subject, min_depth=2)
  is_assigned_reviewer(actor, assignment)
  is_calibration_member(actor, subject, session_open=True)
  has_role(actor, "hr_business_partner", scope_contains=subject.org_unit)
```

- **Deny by default**, with an explicit allow list per action.
- **A generated test matrix** of role × resource × action × state (~2,000 cases) is
  required in CI, so a regression in the visibility matrix fails the build.
- **List queries** are filtered in SQL by the same rules (a compiled "visible
  subjects" CTE), never post-filtered in memory.
- **AI retrieval** calls the same policy with `action="evidence.read"` before any
  chunk enters a prompt.
- **Break-glass:** HR Admin can open restricted items (e.g. recipient-only feedback
  in an investigation) only with a reason and second approver. The subject's audit
  trail records it.

## 9.4 Security model

### Identity & access
- SSO only (Entra ID, OIDC). MFA and conditional access come from the IdP. No local
  passwords.
- Session: secure, HttpOnly, SameSite=Lax cookies. 8 h absolute, 30 min idle for
  privileged roles.
- SCIM / nightly sync deactivates leavers within 24 h (SCIM: minutes).
- Privileged role grants are time-boxed (`expires_at`) and reviewed quarterly.

### Data protection
| Control | Implementation |
|---|---|
| In transit | TLS 1.2+ everywhere, HSTS, private endpoints for the DB/Blob |
| At rest | Azure storage encryption (AES-256) |
| Field-level | Envelope encryption (Key Vault keys) for demographics, private notes, retention-risk reasons, upward comments |
| Tenant isolation | `tenant_id` + Postgres RLS (`app.tenant_id` set per transaction) |
| Anonymity | No reviewer linkage for upward. Date-only timestamps. n ≥ 3. Batch release after the phase closes |
| Minimum-n aggregation | Analytics suppress cells with n < 5 (demographics) or n < 3 (upward) |
| Data minimization to AI | Pseudonymize names in prompts (`[Employee A]`). Never send demographics. Zero-data-retention terms with the model provider |
| Backups | PITR 35 days, geo-redundant, restore tested quarterly |

### Application security
- OWASP ASVS L2 as the baseline. Dependency scanning (Dependabot), SAST (CodeQL),
  secret scanning, container scanning.
- CSP with nonces, no inline scripts. Output encoding. Rich text sanitized
  (allow-list).
- Rate limiting per user/IP. Stricter on the anonymous upward endpoint.
- File uploads: type allow-list, size limits, AV scan, served via short-lived SAS.
- Prompt-injection defenses for AI (see doc 12): evidence text is treated as data,
  and tools are never exposed to model output that could mutate records.

### Audit
- Writes: every create/update/transition, with before/after values (`audit.event`,
  append-only).
- Reads of sensitive data (reviews, talent review, retention, comp) are logged.
- Employees can request their own access log ("who viewed my review").
  Recommended as a trust feature (Phase 2).

### Compliance roadmap
| Item | Phase |
|---|---|
| Privacy notice to employees (incl. AI use) | MVP |
| DPIA (data protection impact assessment) | Phase 0 |
| Counsel review: AI-in-employment rules (state laws, NYC AEDT-style rules if applicable, EU AI Act if EU staff are added), Mexico LFPDPPP for Somos MX | Phase 0 / P2 |
| SOC 2 Type II (needed only if offered externally as SaaS) | Enterprise |
| Annual penetration test | From MVP launch |
