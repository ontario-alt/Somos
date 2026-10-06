# 8. Product Architecture, System Architecture & Technology Stack

## 8.1 Product architecture (modules)

```
┌──────────────────────────────── Experience layer ─────────────────────────────────┐
│ Employee Home │ Manager Hub │ Review Workspace │ Calibration Room │ Talent & Analytics │
│ Career Explorer │ Admin Console │ Teams app (P2) │ Email digests                     │
└───────────────────────────────────────────────────────────────────────────────────┘
┌──────────────────────────────── Domain modules ───────────────────────────────────┐
│ Framework │ Goals │ Conversations (check-ins, notes, feedback) │ Evidence          │
│ Review Cycles │ Calibration │ Readiness & Promotion │ Development │ Talent/Succession│
└───────────────────────────────────────────────────────────────────────────────────┘
┌──────────────────────────────── Platform services ────────────────────────────────┐
│ Identity & Org │ Policy (authz) │ Workflow engine │ Notifications │ AI Gateway       │
│ Search/Retrieval │ Analytics extract │ Audit │ Files │ Integrations │ i18n          │
└───────────────────────────────────────────────────────────────────────────────────┘
```

Modules talk through **in-process interfaces and domain events**, not HTTP. Each
module owns its tables (enforced by the Postgres schemas and import-linter rules),
so any module can later be split out. This is a **modular monolith**.

### Why a modular monolith rather than microservices
Somos has roughly hundreds of employees, and the team building this will be small
(4–7 engineers). Microservices would add distributed transactions, a network hop
on every permission check, and ops overhead, all for scale nobody needs yet. The
module boundaries above are the future seams if the enterprise path is taken
(doc 13).

## 8.2 System architecture (MVP, Azure)

Somos already runs on Microsoft 365 (OneDrive/SharePoint), so Azure keeps
identity, networking and procurement simple.

```
                       ┌───────────────────────────┐
  Browser / Teams ────►│ Azure Front Door + WAF    │
                       └────────────┬──────────────┘
                                    ▼
             ┌──────────────────────────────────────────────┐
             │ Azure Container Apps (VNet-integrated)        │
             │ ┌────────────┐   ┌──────────────────────────┐ │
             │ │ web        │──►│ api (FastAPI)            │ │
             │ │ Next.js SSR│   │  modules + policy layer  │ │
             │ └────────────┘   └───────┬──────────────────┘ │
             │                  ┌───────▼──────────┐         │
             │                  │ worker           │         │
             │                  │ jobs/outbox/cron │         │
             │                  └───────┬──────────┘         │
             └──────────────────────────┼────────────────────┘
          ┌─────────────────┬───────────┼──────────────┬───────────────────┐
          ▼                 ▼           ▼              ▼                   ▼
  PostgreSQL 16       Blob Storage   Key Vault    AI Gateway ──► Claude API      Microsoft Graph
  Flexible Server     (attachments,  (secrets,    (in worker/api;  (zero data    (mail, Teams,
  + pgvector          exports)       field keys)   redaction,      retention)     calendar)
  (private endpoint)                               logging)
          │
          └──► nightly extract (parquet) ──► Analytics (DuckDB now → Fabric/Snowflake later)

  Observability: OpenTelemetry → Azure Monitor / App Insights; Sentry for front end
  Identity: Entra ID (OIDC), Conditional Access, MFA
```

**Environments:** `dev` (seeded synthetic data) → `staging` (anonymized clone) →
`prod`. Infrastructure is code (Bicep or Terraform). Every PR gets a preview
environment.

## 8.3 Recommended technology stack

| Layer | Choice | Rationale |
|---|---|---|
| Front end | **Next.js (React, TypeScript)**, TanStack Query, React Hook Form + Zod, **shadcn/ui + Tailwind**, Recharts/visx | SaaS-grade UX, a large talent pool, an accessible component base |
| API | **Python 3.12 + FastAPI**, Pydantic v2, SQLAlchemy 2.0, Alembic | Matches the team's existing Python (ETL, DuckDB, Streamlit). Strong AI/data libraries. OpenAPI for free |
| API contract | OpenAPI 3.1 → generated TS client (`openapi-typescript`) | End-to-end types |
| Database | **PostgreSQL 16** (+ pgvector, pgcrypto, RLS) | Relational integrity for workflows. Vectors in the same DB means permission-filtered retrieval in one query |
| Jobs/queue | Postgres-backed queue (**Procrastinate**) + outbox | No Redis/Service Bus to run at MVP scale. Transactional |
| Scheduler | Worker cron (phase open/close, reminders) | Simple |
| Authorization | In-app **policy module** (relationship-based rules in Python, unit-tested matrix) + Postgres RLS for tenant isolation | Explicit, testable. OpenFGA at enterprise scale |
| AI | **Claude** (Anthropic API, or Claude via Microsoft Foundry to stay in Azure procurement). `claude-opus-5-5` for drafting/summaries, `claude-haiku-4-5` for classification/linting. Embeddings via a hosted embedding model | Quality of long-form writing, citations, tool use |
| Search | Postgres FTS + pgvector hybrid | One store, permission-aware |
| Files | Azure Blob (private, SAS URLs, AV scan) | |
| Notifications | Microsoft Graph (Teams chat/activity feed, Outlook mail) | Where Somos works |
| Analytics | Nightly star-schema extract → DuckDB (reuses the current dashboard) → later Microsoft Fabric | Reuse before reinvent |
| PDF | Server-side HTML → PDF (Playwright/Chromium) | Review packets |
| i18n | `next-intl` (front end), ICU messages; Babel on the back end | es-MX in Phase 2 |
| Testing | pytest + factory_boy, Playwright E2E, Schemathesis (OpenAPI fuzz), axe-core a11y | |
| CI/CD | GitHub Actions → container registry → Container Apps (blue/green) | |
| Observability | OpenTelemetry, App Insights, Sentry | |
| IaC | Bicep (Azure-native) or Terraform | |

### Alternatives considered
- **Full TypeScript (NestJS/tRPC):** a reasonable choice. Rejected for now because
  Somos's in-house code is Python and the AI/data tooling is stronger there.
- **Temporal for workflows:** excellent for long-running, multi-actor workflows.
  Overkill for one annual cycle with a few thousand assignments. Revisit for the
  enterprise version.
- **Buy (Lattice/Leapsome/Culture Amp/15Five/Workday):** see the build-vs-buy gate
  in doc 13.

## 8.4 Repository layout (proposed)

```
somos-performance/
  apps/
    web/                      Next.js
    api/
      somos_perf/
        modules/
          framework/  goals/  conversations/  evidence/  reviews/
          calibration/  promotion/  development/  talent/  analytics/
        platform/
          auth/  policy/  workflow/  notifications/  ai/  audit/  integrations/
        main.py
      migrations/             Alembic (baseline = db/schema.sql)
      tests/
    worker/                   entrypoint reusing api package
  packages/
    api-client/               generated TS client
    ui/                       design system
  infra/                      Bicep/Terraform
  prompts/                    versioned AI prompt templates + evals
  docs/                       (this design package)
```

In the current repo, the only addition is `etl/export_hours_snapshots.py`, which
reads `warehouse.duckdb` and posts per-person measuring-period results to the
platform.

## 8.5 Cross-cutting concerns

| Concern | Approach |
|---|---|
| Autosave | Debounced PUT with `If-Match`. Local draft cached in IndexedDB on network failure |
| Real-time calibration | MVP: polling every 5 s plus optimistic updates. P2: WebSocket (Azure Web PubSub) |
| Time zones | Phase deadlines stored in UTC, shown in the office time zone, with an "ends 11:59 pm your time" convention |
| Feature flags | Per-tenant/per-cohort flags for gradual AI rollout |
| Performance budgets | p95 API < 300 ms (non-AI); AI drafts stream the first token in < 2 s |
