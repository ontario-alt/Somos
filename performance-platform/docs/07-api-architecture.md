# 7. API Architecture

## 7.1 Style & conventions

- **REST + JSON**, resource-oriented, versioned at `/api/v1`. Defined
  **OpenAPI 3.1 first**. A typed TypeScript client is generated for the web app.
- **Auth:** OIDC (Entra ID) → short-lived session for the web app, bearer tokens
  for integrations (OAuth2 client credentials, scoped).
- **Commands for workflow transitions:** `POST /…/{id}:submit`, `:return`,
  `:lock`. They are explicit and auditable, not "PATCH status".
- **Optimistic concurrency:** `ETag` / `If-Match` on review drafts (autosave from
  multiple tabs). Conflicts return `412`.
- **Idempotency:** `Idempotency-Key` header on all POST commands.
- **Pagination:** cursor-based (`?cursor=…&limit=50`). **Filtering:** `?filter[status]=submitted`.
- **Errors:** RFC 9457 `application/problem+json` with `code`, `detail` and
  `violations[]` (for guard failures such as missing evidence).
- **Field-level redaction:** the policy layer strips fields the caller can't see.
  The response includes `"_redacted": ["privateNotes"]` so the UI can explain.
- **Async jobs** (AI, exports): `202 Accepted` with a `Location: /jobs/{id}`.
  Progress streams via Server-Sent Events.

## 7.2 Resource catalog

### Identity & org
| Method | Path | Notes |
|---|---|---|
| GET | `/me` | Profile, roles, current band, pending tasks count |
| GET | `/employees?filter[orgUnit]=…` | Directory (fields limited by role) |
| GET | `/employees/{id}` | Profile + current employment |
| GET | `/employees/{id}/timeline` | Effective-dated history |
| GET | `/org/units`, `/org/offices`, `/org/disciplines` | Reference data |

### Career framework
| Method | Path | Notes |
|---|---|---|
| GET | `/framework` | Current published version (bands, competencies, scale) |
| GET | `/framework/bands/{code}` | Anchors, examples, gates |
| GET | `/framework/compare?from=B4&to=B5&discipline=LEGAL` | Career Explorer diff |
| POST | `/admin/framework/versions` · `:publish` | HR admin |

### Goals
| Method | Path |
|---|---|
| GET/POST | `/employees/{id}/goals?fiscalYear=2027` |
| GET/PATCH/DELETE | `/goals/{id}` |
| POST | `/goals/{id}:submit` · `:approve` · `:score` |
| POST | `/goals/{id}/updates` |
| GET/POST | `/goals/{id}/key-results` |

### Check-ins, feedback, notes, evidence
| Method | Path |
|---|---|
| GET/POST | `/employees/{id}/check-ins` |
| PATCH | `/check-ins/{id}` · POST `:complete` |
| GET/POST | `/employees/{id}/notes` (private notes visible to author only) |
| POST | `/feedback-requests` · GET `/feedback-requests/inbox` |
| POST | `/feedback` |
| GET | `/employees/{id}/evidence?competency=C2&from=2026-10-01` |
| POST | `/evidence` (mark any source as evidence) |

### Review cycles (HR)
| Method | Path |
|---|---|
| GET/POST | `/cycles` |
| GET/PATCH | `/cycles/{id}` |
| POST | `/cycles/{id}:launch` · `:pause` · `:lock` · `:release` |
| GET | `/cycles/{id}/eligibility` (preview) · PATCH participants for exceptions |
| GET | `/cycles/{id}/progress?groupBy=orgUnit` |

### Reviews
| Method | Path |
|---|---|
| GET | `/me/review-tasks` (inbox) |
| GET/POST | `/participants/{id}/peer-nominations` · POST `:approve` |
| GET | `/assignments/{id}` (form definition + response) |
| PUT | `/assignments/{id}/response` (autosave, `If-Match`) |
| POST | `/assignments/{id}:submit` · `:decline` · `:return` |
| GET | `/participants/{id}/review-packet` (aggregated inputs for the manager) |
| GET | `/participants/{id}/upward-summary` (n ≥ 3 or 404 `below_threshold`) |
| POST | `/upward/{token}` (anonymous submission, token only, no session identity stored) |
| GET | `/participants/{id}/final-rating` |
| POST | `/final-ratings/{id}:approve` · `:acknowledge` · `:amend` |

### Calibration
| Method | Path |
|---|---|
| GET/POST | `/calibration-sessions` |
| GET | `/calibration-sessions/{id}/grid?groupBy=band` |
| GET | `/calibration-sessions/{id}/distributions?dimension=manager` |
| POST | `/calibration-sessions/{id}/adjustments` (rationale required) |
| POST | `/calibration-sessions/{id}/equity-check` (PA only; returns aggregates) |
| POST | `/calibration-sessions/{id}:close` |

### Promotion & readiness
| Method | Path |
|---|---|
| GET/POST | `/employees/{id}/readiness-assessments` |
| GET | `/employees/{id}/readiness/gaps?targetBand=B6` |
| GET | `/employees/{id}/readiness/score` (with breakdown) |
| GET/POST | `/promotion-nominations` |
| POST | `/promotion-nominations/{id}:submit` · `:endorse` · `:decide` · `:communicate` |
| GET | `/promotion-nominations/{id}/case-packet` |

### Development
| Method | Path |
|---|---|
| GET/POST | `/employees/{id}/development-plans` |
| PATCH | `/development-plans/{id}` · POST `:approve` |
| POST | `/development-plans/{id}/objectives` · `/objectives/{id}/actions` |
| GET/POST | `/mentorships` |

### Talent & analytics
| Method | Path |
|---|---|
| GET | `/analytics/distributions?cycle=…&groupBy=discipline` |
| GET | `/analytics/talent-matrix?orgUnit=…` |
| GET | `/analytics/promotion-pipeline` |
| GET | `/analytics/process-health` |
| GET/PUT | `/employees/{id}/talent-review` (restricted) |
| GET/POST | `/succession/critical-roles` · `/{id}/successors` |

### AI (all return drafts/suggestions; none write to records)
| Method | Path |
|---|---|
| POST | `/ai/peer-summary` `{participantId}` |
| POST | `/ai/narrative-draft` `{assignmentId, competencyCode}` |
| POST | `/ai/presubmit-check` `{assignmentId}` → flags[] |
| POST | `/ai/evidence-search` `{subjectId, query}` → cited snippets |
| POST | `/ai/development-suggestions` `{employeeId}` |
| POST | `/ai/readiness-advisory` `{employeeId, targetBand}` |
| POST | `/ai/feedback-coach` `{text}` |
| POST | `/ai/generations/{id}:outcome` `{accepted|edited|rejected}` |

### Integrations & admin
| Method | Path |
|---|---|
| POST | `/integrations/hris/sync` (or SCIM 2.0 at `/scim/v2/Users`) |
| POST | `/integrations/hours/snapshots` (bulk upsert from the warehouse job) |
| GET | `/exports/finance?cycle=…` (CSV; comp_admin) |
| GET | `/audit/events?subject=…` (auditor, HR) |
| GET | `/jobs/{id}` · SSE `/jobs/{id}/events` |

## 7.3 Example: manager submits a review

```http
POST /api/v1/assignments/7c1…/submit
Idempotency-Key: 4f0e…
If-Match: "rev-12"
```
```json
422 application/problem+json
{
  "type": "https://somos.app/problems/guard-failed",
  "title": "Review cannot be submitted",
  "code": "guard_failed",
  "violations": [
    {"path": "ratings.C2", "rule": "evidence_required_for_extreme_rating",
     "detail": "Rating 5 requires at least one linked evidence item."},
    {"path": "overall", "rule": "justification_required",
     "detail": "Holistic rating 4 differs from reference score 2.85 by ≥1.0."}
  ]
}
```

## 7.4 Events (internal now, public webhooks in Phase 2)

`cycle.launched`, `phase.opened`, `assignment.submitted`, `final_rating.adjusted`,
`final_rating.locked`, `review.released`, `review.acknowledged`,
`promotion.decided`, `promotion.effective`, `development_plan.approved`,
`goal.approved`, `checkin.completed`.

Envelope: `{id, type, tenantId, occurredAt, actor, subject, data}`. They are
delivered from the outbox, at least once, and consumers dedupe on `id`.

## 7.5 Integration architecture

```
Entra ID ──OIDC/SCIM──► Auth / Directory sync
HRIS (or CSV) ──nightly──► employee, employment_record
Vantagepoint ─► existing ETL ─► warehouse.duckdb ─► export_hours_snapshots.py ─► POST /integrations/hours/snapshots
Platform ─► /exports/finance ─► Finance/comp workbook
Platform ─► analytics extract (parquet) ─► executive dashboard (DuckDB/Streamlit)
Platform ─► Microsoft Graph ─► Teams messages / Outlook mail / calendar
```
