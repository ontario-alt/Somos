-- =============================================================================
-- Somos Performance — PostgreSQL 16 schema (v1 design)
--
-- Schemas
--   core        tenants, org structure, people, employment history, users
--   framework   bands, competencies, anchors, job profiles, gates, scales
--   perf        goals, check-ins, feedback, evidence, cycles, reviews, ratings
--   talent      calibration, readiness, promotion, development, 9-box, succession
--   restricted  demographics, anonymous upward responses (separate grants)
--   ai          generation log, embeddings
--   audit       append-only audit + access log, outbox, workflow events
--
-- Conventions
--   * every table carries tenant_id (single tenant in MVP; RLS-ready for SaaS)
--   * uuid PKs (gen_random_uuid), timestamptz, soft delete only where noted
--   * status columns are text + CHECK (easier to evolve than enum types)
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
-- pgvector is optional in dev; ai.evidence_embedding uses it when present.

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS framework;
CREATE SCHEMA IF NOT EXISTS perf;
CREATE SCHEMA IF NOT EXISTS talent;
CREATE SCHEMA IF NOT EXISTS restricted;
CREATE SCHEMA IF NOT EXISTS ai;
CREATE SCHEMA IF NOT EXISTS audit;

-- -----------------------------------------------------------------------------
-- core
-- -----------------------------------------------------------------------------
CREATE TABLE core.tenant (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name            text NOT NULL,
    slug            citext NOT NULL UNIQUE,
    fiscal_year_start_month smallint NOT NULL DEFAULT 10 CHECK (fiscal_year_start_month BETWEEN 1 AND 12),
    default_locale  text NOT NULL DEFAULT 'en-US',
    settings        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Legal entity / business unit (e.g. Somos LLP, Somos LLC, Somos MX)
CREATE TABLE core.business_unit (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES core.tenant(id),
    code        text NOT NULL,
    name        text NOT NULL,
    country     char(2),
    UNIQUE (tenant_id, code)
);

CREATE TABLE core.office (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES core.tenant(id),
    name        text NOT NULL,
    city        text,
    country     char(2),
    timezone    text NOT NULL DEFAULT 'America/New_York',
    UNIQUE (tenant_id, name)
);

-- Professional discipline (Legal, Planning, Project Management, Operations ...)
CREATE TABLE core.discipline (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES core.tenant(id),
    code        text NOT NULL,
    name        text NOT NULL,
    UNIQUE (tenant_id, code)
);

-- Practice group / department (maps to Vantagepoint "Organization Name")
CREATE TABLE core.org_unit (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES core.tenant(id),
    business_unit_id uuid REFERENCES core.business_unit(id),
    parent_id        uuid REFERENCES core.org_unit(id),
    name             text NOT NULL,
    external_ref     text,
    UNIQUE (tenant_id, name)
);

CREATE TABLE core.employee (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES core.tenant(id),
    employee_number   text NOT NULL,           -- Vantagepoint / HRIS key
    email             citext NOT NULL,
    given_name        text NOT NULL,
    family_name       text NOT NULL,
    preferred_name    text,
    locale            text NOT NULL DEFAULT 'en-US',
    hire_date         date NOT NULL,
    termination_date  date,
    status            text NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active','leave','terminated')),
    external_ids      jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {"entra": "...", "hris": "..."}
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, employee_number),
    UNIQUE (tenant_id, email)
);

-- Login identity (SSO). Admin/service accounts may have no employee row.
CREATE TABLE core.app_user (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES core.tenant(id),
    employee_id   uuid UNIQUE REFERENCES core.employee(id),
    idp_subject   text NOT NULL,
    email         citext NOT NULL,
    is_active     boolean NOT NULL DEFAULT true,
    last_login_at timestamptz,
    UNIQUE (tenant_id, idp_subject)
);

-- Platform roles (RBAC). Relationship-based access (manager chain, reviewer,
-- calibration member) is derived from data, not stored here.
CREATE TABLE core.role_grant (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES core.tenant(id),
    user_id     uuid NOT NULL REFERENCES core.app_user(id),
    role        text NOT NULL CHECK (role IN (
                   'hr_admin','hr_business_partner','people_analytics','comp_admin',
                   'executive','calibration_facilitator','system_admin','auditor')),
    -- optional scope: limit HRBP/facilitator to units/BUs
    scope_business_unit_id uuid REFERENCES core.business_unit(id),
    scope_org_unit_id      uuid REFERENCES core.org_unit(id),
    granted_by  uuid REFERENCES core.app_user(id),
    granted_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz
);
CREATE INDEX ON core.role_grant (user_id);

-- -----------------------------------------------------------------------------
-- framework
-- -----------------------------------------------------------------------------
CREATE TABLE framework.framework_version (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    uuid NOT NULL REFERENCES core.tenant(id),
    version      int  NOT NULL,
    status       text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','retired')),
    published_at timestamptz,
    notes        text,
    UNIQUE (tenant_id, version)
);

CREATE TABLE framework.band (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            uuid NOT NULL REFERENCES core.tenant(id),
    framework_version_id uuid NOT NULL REFERENCES framework.framework_version(id),
    level                smallint NOT NULL CHECK (level BETWEEN 1 AND 7),
    track                text NOT NULL DEFAULT 'core' CHECK (track IN ('core','expert')),
    code                 text NOT NULL,          -- e.g. 'B5', 'B6E'
    name                 text NOT NULL,          -- 'Project Leader'
    summary              text,
    advancement_philosophy text,
    is_people_leader_band boolean NOT NULL DEFAULT false,
    UNIQUE (framework_version_id, code)
);

CREATE TABLE framework.competency (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            uuid NOT NULL REFERENCES core.tenant(id),
    framework_version_id uuid NOT NULL REFERENCES framework.framework_version(id),
    code                 text NOT NULL,          -- C1..C5, S
    name                 text NOT NULL,
    description          text,
    is_rated             boolean NOT NULL DEFAULT true,
    sort_order           smallint NOT NULL,
    UNIQUE (framework_version_id, code)
);

CREATE TABLE framework.band_competency (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES core.tenant(id),
    band_id         uuid NOT NULL REFERENCES framework.band(id),
    competency_id   uuid NOT NULL REFERENCES framework.competency(id),
    weight_pct      numeric(5,2) NOT NULL CHECK (weight_pct BETWEEN 0 AND 100),
    anchor_meets    text NOT NULL,         -- behaviors for rating 3
    anchor_below    text,                  -- descriptor for 1-2
    anchor_exceeds  text,                  -- descriptor for 4-5
    UNIQUE (band_id, competency_id)
);

CREATE TABLE framework.anchor_example (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          uuid NOT NULL REFERENCES core.tenant(id),
    band_competency_id uuid NOT NULL REFERENCES framework.band_competency(id) ON DELETE CASCADE,
    discipline_id      uuid REFERENCES core.discipline(id),  -- null = all disciplines
    example            text NOT NULL
);

CREATE TABLE framework.gate_criterion (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          uuid NOT NULL REFERENCES core.tenant(id),
    target_band_id     uuid NOT NULL REFERENCES framework.band(id),
    code               text NOT NULL,
    name               text NOT NULL,
    description        text,
    evidence_guidance  text,
    is_hard_gate       boolean NOT NULL DEFAULT true,
    sort_order         smallint NOT NULL DEFAULT 0,
    UNIQUE (target_band_id, code)
);

CREATE TABLE framework.job_profile (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES core.tenant(id),
    band_id         uuid NOT NULL REFERENCES framework.band(id),
    discipline_id   uuid NOT NULL REFERENCES core.discipline(id),
    title           text NOT NULL,
    hours_role      text CHECK (hours_role IN ('attorney','planner','none')),
    description     text,
    UNIQUE (band_id, discipline_id, title)
);

CREATE TABLE framework.rating_scale (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES core.tenant(id),
    name        text NOT NULL,
    UNIQUE (tenant_id, name)
);

CREATE TABLE framework.rating_scale_point (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rating_scale_id    uuid NOT NULL REFERENCES framework.rating_scale(id) ON DELETE CASCADE,
    value              smallint NOT NULL,
    label              text NOT NULL,
    description        text,
    guidance_min_pct   numeric(5,2),
    guidance_max_pct   numeric(5,2),
    requires_evidence  boolean NOT NULL DEFAULT false,
    UNIQUE (rating_scale_id, value)
);

-- Effective-dated job history (band, title, manager, unit, office)
CREATE TABLE core.employment_record (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES core.tenant(id),
    employee_id     uuid NOT NULL REFERENCES core.employee(id),
    effective_from  date NOT NULL,
    effective_to    date,                       -- null = current
    job_profile_id  uuid NOT NULL REFERENCES framework.job_profile(id),
    manager_id      uuid REFERENCES core.employee(id),
    org_unit_id     uuid REFERENCES core.org_unit(id),
    office_id       uuid REFERENCES core.office(id),
    business_unit_id uuid REFERENCES core.business_unit(id),
    fte             numeric(4,3) NOT NULL DEFAULT 1.000,
    change_reason   text CHECK (change_reason IN ('hire','promotion','transfer','manager_change','correction','other')),
    source          text NOT NULL DEFAULT 'hris',
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);
CREATE INDEX ON core.employment_record (employee_id, effective_from DESC);
CREATE INDEX ON core.employment_record (manager_id) WHERE effective_to IS NULL;
CREATE UNIQUE INDEX employment_record_one_current
    ON core.employment_record (employee_id) WHERE effective_to IS NULL;

-- Dotted-line / project relationships (project leaders who direct work)
CREATE TABLE core.work_relationship (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES core.tenant(id),
    employee_id   uuid NOT NULL REFERENCES core.employee(id),
    leader_id     uuid NOT NULL REFERENCES core.employee(id),
    kind          text NOT NULL CHECK (kind IN ('project_leader','dotted_line','mentor')),
    context       text,
    starts_on     date NOT NULL,
    ends_on       date
);

-- -----------------------------------------------------------------------------
-- perf: goals
-- -----------------------------------------------------------------------------
CREATE TABLE perf.goal (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES core.tenant(id),
    owner_employee_id uuid REFERENCES core.employee(id),   -- null for team/firm goals
    owner_org_unit_id uuid REFERENCES core.org_unit(id),
    parent_goal_id  uuid REFERENCES perf.goal(id),         -- alignment / quarterly→annual
    period_type     text NOT NULL CHECK (period_type IN ('annual','quarterly')),
    fiscal_year     smallint NOT NULL,
    fiscal_quarter  smallint CHECK (fiscal_quarter BETWEEN 1 AND 4),
    title           text NOT NULL,
    description     text,
    success_criteria text,
    weight_pct      numeric(5,2) CHECK (weight_pct BETWEEN 0 AND 100),
    is_stretch      boolean NOT NULL DEFAULT false,
    approval_state  text NOT NULL DEFAULT 'draft'
                    CHECK (approval_state IN ('draft','submitted','approved','closed')),
    status          text NOT NULL DEFAULT 'not_started'
                    CHECK (status IN ('not_started','on_track','at_risk','off_track',
                                      'achieved','partially_achieved','missed','deferred')),
    score           numeric(3,2) CHECK (score BETWEEN 0 AND 1),
    scored_by       uuid REFERENCES core.employee(id),
    approved_by     uuid REFERENCES core.employee(id),
    approved_at     timestamptz,
    version         int NOT NULL DEFAULT 1,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (owner_employee_id IS NOT NULL OR owner_org_unit_id IS NOT NULL),
    CHECK ((period_type = 'quarterly') = (fiscal_quarter IS NOT NULL))
);
CREATE INDEX ON perf.goal (owner_employee_id, fiscal_year);

CREATE TABLE perf.key_result (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES core.tenant(id),
    goal_id       uuid NOT NULL REFERENCES perf.goal(id) ON DELETE CASCADE,
    title         text NOT NULL,
    metric_unit   text,
    start_value   numeric,
    target_value  numeric,
    current_value numeric,
    weight_pct    numeric(5,2)
);

CREATE TABLE perf.goal_update (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES core.tenant(id),
    goal_id     uuid NOT NULL REFERENCES perf.goal(id) ON DELETE CASCADE,
    author_id   uuid NOT NULL REFERENCES core.employee(id),
    status      text NOT NULL,
    progress_pct numeric(5,2),
    comment     text,
    check_in_id uuid,                -- FK added below
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE perf.goal_competency (
    goal_id        uuid NOT NULL REFERENCES perf.goal(id) ON DELETE CASCADE,
    competency_id  uuid NOT NULL REFERENCES framework.competency(id),
    PRIMARY KEY (goal_id, competency_id)
);

-- -----------------------------------------------------------------------------
-- perf: check-ins, feedback, coaching
-- -----------------------------------------------------------------------------
CREATE TABLE perf.check_in (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid NOT NULL REFERENCES core.tenant(id),
    employee_id    uuid NOT NULL REFERENCES core.employee(id),
    manager_id     uuid NOT NULL REFERENCES core.employee(id),
    kind           text NOT NULL DEFAULT 'quarterly' CHECK (kind IN ('quarterly','one_on_one','ad_hoc')),
    fiscal_year    smallint,
    fiscal_quarter smallint,
    scheduled_for  timestamptz,
    completed_at   timestamptz,
    status         text NOT NULL DEFAULT 'scheduled'
                   CHECK (status IN ('scheduled','in_progress','completed','missed','cancelled')),
    responses      jsonb NOT NULL DEFAULT '{}'::jsonb,  -- template answers (wins, blockers, support)
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON perf.check_in (employee_id, scheduled_for DESC);
ALTER TABLE perf.goal_update
    ADD CONSTRAINT goal_update_check_in_fk FOREIGN KEY (check_in_id) REFERENCES perf.check_in(id);

-- Notes on a check-in or standalone coaching notes.
-- visibility: shared (employee+manager chain), private (author only)
CREATE TABLE perf.note (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES core.tenant(id),
    subject_id    uuid NOT NULL REFERENCES core.employee(id),  -- who the note is about
    author_id     uuid NOT NULL REFERENCES core.employee(id),
    check_in_id   uuid REFERENCES perf.check_in(id),
    kind          text NOT NULL CHECK (kind IN ('check_in','coaching','observation','one_on_one')),
    visibility    text NOT NULL CHECK (visibility IN ('shared','private')),
    body          text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    deleted_at    timestamptz
);
CREATE INDEX ON perf.note (subject_id, created_at DESC);

CREATE TABLE perf.feedback_request (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES core.tenant(id),
    subject_id    uuid NOT NULL REFERENCES core.employee(id),
    requested_by  uuid NOT NULL REFERENCES core.employee(id),
    context       text,                   -- matter / project
    questions     jsonb NOT NULL DEFAULT '[]'::jsonb,
    due_on        date,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE perf.feedback (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES core.tenant(id),
    request_id    uuid REFERENCES perf.feedback_request(id),
    subject_id    uuid NOT NULL REFERENCES core.employee(id),
    giver_id      uuid NOT NULL REFERENCES core.employee(id),
    kind          text NOT NULL CHECK (kind IN ('praise','constructive','general')),
    visibility    text NOT NULL CHECK (visibility IN ('recipient_only','recipient_and_manager','manager_only')),
    body          text NOT NULL,
    answers       jsonb,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CHECK (subject_id <> giver_id)
);
CREATE INDEX ON perf.feedback (subject_id, created_at DESC);

-- -----------------------------------------------------------------------------
-- perf: evidence (polymorphic link from any source to competencies)
-- -----------------------------------------------------------------------------
CREATE TABLE perf.evidence (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      uuid NOT NULL REFERENCES core.tenant(id),
    subject_id     uuid NOT NULL REFERENCES core.employee(id),
    source_type    text NOT NULL CHECK (source_type IN
                     ('note','feedback','goal','goal_update','check_in','attachment',
                      'hours_snapshot','manual','review_response')),
    source_id      uuid,                 -- id in the source table (null for manual)
    title          text NOT NULL,
    excerpt        text,
    occurred_on    date NOT NULL,
    added_by       uuid NOT NULL REFERENCES core.employee(id),
    -- visibility inherits from the source; cached for fast filtering
    visibility     text NOT NULL CHECK (visibility IN ('shared','private','manager_chain')),
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON perf.evidence (subject_id, occurred_on DESC);

CREATE TABLE perf.evidence_competency (
    evidence_id    uuid NOT NULL REFERENCES perf.evidence(id) ON DELETE CASCADE,
    competency_id  uuid REFERENCES framework.competency(id),
    gate_criterion_id uuid REFERENCES framework.gate_criterion(id),
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    CHECK (competency_id IS NOT NULL OR gate_criterion_id IS NOT NULL)
);

CREATE TABLE perf.attachment (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES core.tenant(id),
    owner_id      uuid NOT NULL REFERENCES core.employee(id),
    blob_key      text NOT NULL,
    filename      text NOT NULL,
    content_type  text NOT NULL,
    size_bytes    bigint NOT NULL,
    sha256        text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- Hours-policy results published nightly from the Vantagepoint/DuckDB warehouse
CREATE TABLE perf.hours_snapshot (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                uuid NOT NULL REFERENCES core.tenant(id),
    employee_id              uuid NOT NULL REFERENCES core.employee(id),
    fiscal_year              smallint NOT NULL,
    as_of                    date NOT NULL,
    is_closed_period         boolean NOT NULL,
    hours_role               text NOT NULL,
    hours_expectation_req    numeric(8,2),
    hours_expectation_actual numeric(8,2),
    hours_expectation_pct    numeric(6,2),
    total_activity_pct       numeric(6,2),
    bonus_threshold_met      boolean,
    lookback_2yr_pct         numeric(6,2),
    promotion_gate_met       boolean,
    pace_status              text,      -- On Track / Watch / Behind / Met / Not Met
    source_run_id            text NOT NULL,
    imported_at              timestamptz NOT NULL DEFAULT now(),
    UNIQUE (employee_id, fiscal_year, as_of)
);

-- -----------------------------------------------------------------------------
-- perf: review cycles, templates, assignments, responses
-- -----------------------------------------------------------------------------
CREATE TABLE perf.review_template (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES core.tenant(id),
    name          text NOT NULL,
    review_type   text NOT NULL CHECK (review_type IN ('self','manager','peer','upward','contributor')),
    framework_version_id uuid NOT NULL REFERENCES framework.framework_version(id),
    rating_scale_id uuid REFERENCES framework.rating_scale(id),
    definition    jsonb NOT NULL,       -- sections, questions, required rules
    version       int NOT NULL DEFAULT 1,
    is_active     boolean NOT NULL DEFAULT true
);

CREATE TABLE perf.review_cycle (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            uuid NOT NULL REFERENCES core.tenant(id),
    name                 text NOT NULL,              -- 'FY2027 Annual Review'
    kind                 text NOT NULL DEFAULT 'annual' CHECK (kind IN ('annual','mid_year','probation','project')),
    fiscal_year          smallint NOT NULL,
    period_start         date NOT NULL,
    period_end           date NOT NULL,
    framework_version_id uuid NOT NULL REFERENCES framework.framework_version(id),
    status               text NOT NULL DEFAULT 'draft'
                         CHECK (status IN ('draft','active','paused','finalizing','locked','released','closed','cancelled')),
    eligibility_rules    jsonb NOT NULL DEFAULT '{}'::jsonb,
    settings             jsonb NOT NULL DEFAULT '{}'::jsonb,  -- peer min/max, reviewer cap, anonymity n
    created_by           uuid REFERENCES core.app_user(id),
    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE perf.cycle_phase (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   uuid NOT NULL REFERENCES core.tenant(id),
    cycle_id    uuid NOT NULL REFERENCES perf.review_cycle(id) ON DELETE CASCADE,
    phase_type  text NOT NULL CHECK (phase_type IN ('goal_setting','self','peer_nomination','peer','upward',
                                                    'manager','calibration','approval','release','development')),
    opens_at    timestamptz NOT NULL,
    closes_at   timestamptz NOT NULL,
    auto_open   boolean NOT NULL DEFAULT true,
    auto_close  boolean NOT NULL DEFAULT true,
    grace_days  smallint NOT NULL DEFAULT 0,
    status      text NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','open','closed')),
    UNIQUE (cycle_id, phase_type),
    CHECK (closes_at > opens_at)
);

CREATE TABLE perf.cycle_participant (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             uuid NOT NULL REFERENCES core.tenant(id),
    cycle_id              uuid NOT NULL REFERENCES perf.review_cycle(id) ON DELETE CASCADE,
    employee_id           uuid NOT NULL REFERENCES core.employee(id),
    -- snapshot at enrollment so later HR changes don't rewrite history
    band_id               uuid NOT NULL REFERENCES framework.band(id),
    job_profile_id        uuid NOT NULL REFERENCES framework.job_profile(id),
    manager_id            uuid REFERENCES core.employee(id),
    second_level_id       uuid REFERENCES core.employee(id),
    org_unit_id           uuid REFERENCES core.org_unit(id),
    office_id             uuid REFERENCES core.office(id),
    form_variant          text NOT NULL DEFAULT 'full' CHECK (form_variant IN ('full','abbreviated','excluded')),
    exclusion_reason      text,
    UNIQUE (cycle_id, employee_id)
);

CREATE TABLE perf.peer_nomination (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES core.tenant(id),
    participant_id  uuid NOT NULL REFERENCES perf.cycle_participant(id) ON DELETE CASCADE,
    nominee_id      uuid NOT NULL REFERENCES core.employee(id),
    nominated_by    uuid NOT NULL REFERENCES core.employee(id),
    status          text NOT NULL DEFAULT 'proposed'
                    CHECK (status IN ('proposed','approved','rejected','invited','accepted','declined')),
    decline_reason  text,
    UNIQUE (participant_id, nominee_id)
);

-- One task for one reviewer to review one participant.
-- Upward assignments record completion only; responses live in restricted.upward_response.
CREATE TABLE perf.review_assignment (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES core.tenant(id),
    cycle_id        uuid NOT NULL REFERENCES perf.review_cycle(id) ON DELETE CASCADE,
    participant_id  uuid NOT NULL REFERENCES perf.cycle_participant(id) ON DELETE CASCADE,
    reviewer_id     uuid NOT NULL REFERENCES core.employee(id),
    review_type     text NOT NULL CHECK (review_type IN ('self','manager','peer','upward','contributor')),
    template_id     uuid NOT NULL REFERENCES perf.review_template(id),
    status          text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','in_progress','submitted','returned','locked','declined','expired','cancelled')),
    due_at          timestamptz,
    submitted_at    timestamptz,
    UNIQUE (participant_id, reviewer_id, review_type)
);
CREATE INDEX ON perf.review_assignment (reviewer_id, status);

CREATE TABLE perf.review_response (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES core.tenant(id),
    assignment_id    uuid NOT NULL UNIQUE REFERENCES perf.review_assignment(id) ON DELETE CASCADE,
    overall_rating   smallint CHECK (overall_rating BETWEEN 1 AND 5),
    reference_score  numeric(4,2),
    overall_justification text,          -- required when |overall - reference| >= 1
    strengths        text,
    development_priorities text,
    summary_narrative text,
    answers          jsonb NOT NULL DEFAULT '{}'::jsonb,   -- non-competency questions
    revision         int NOT NULL DEFAULT 1,               -- optimistic concurrency (ETag)
    ai_assisted      boolean NOT NULL DEFAULT false,
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE perf.competency_rating (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES core.tenant(id),
    response_id      uuid NOT NULL REFERENCES perf.review_response(id) ON DELETE CASCADE,
    competency_id    uuid NOT NULL REFERENCES framework.competency(id),
    rating           smallint CHECK (rating BETWEEN 1 AND 5),   -- null + not_observed = N/A
    not_observed     boolean NOT NULL DEFAULT false,
    narrative        text,
    development_recommendation text,
    UNIQUE (response_id, competency_id),
    CHECK (NOT (not_observed AND rating IS NOT NULL))
);

CREATE TABLE perf.rating_evidence (
    competency_rating_id uuid NOT NULL REFERENCES perf.competency_rating(id) ON DELETE CASCADE,
    evidence_id          uuid NOT NULL REFERENCES perf.evidence(id),
    PRIMARY KEY (competency_rating_id, evidence_id)
);

-- Version history of drafts (autosave snapshots on submit/return)
CREATE TABLE perf.review_response_version (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    response_id   uuid NOT NULL REFERENCES perf.review_response(id) ON DELETE CASCADE,
    revision      int NOT NULL,
    snapshot      jsonb NOT NULL,
    reason        text NOT NULL CHECK (reason IN ('submit','return','amend')),
    created_by    uuid NOT NULL REFERENCES core.app_user(id),
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- The official outcome per participant
CREATE TABLE perf.final_rating (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES core.tenant(id),
    participant_id    uuid NOT NULL UNIQUE REFERENCES perf.cycle_participant(id) ON DELETE CASCADE,
    proposed_rating   smallint CHECK (proposed_rating BETWEEN 1 AND 5),
    current_rating    smallint CHECK (current_rating BETWEEN 1 AND 5),
    status            text NOT NULL DEFAULT 'proposed'
                      CHECK (status IN ('proposed','in_calibration','calibrated','approved_l2','approved_hr',
                                        'locked','released','acknowledged')),
    approved_l2_by    uuid REFERENCES core.employee(id),
    approved_l2_at    timestamptz,
    approved_hr_by    uuid REFERENCES core.app_user(id),
    approved_hr_at    timestamptz,
    released_at       timestamptz,
    conversation_held_at timestamptz,
    acknowledged_at   timestamptz,
    employee_response text
);

-- -----------------------------------------------------------------------------
-- restricted: anonymous upward responses & demographics
-- -----------------------------------------------------------------------------
-- No reviewer_id. submitted_on is a date only. Readable only through
-- the aggregation function/view, which enforces the minimum-n threshold.
CREATE TABLE restricted.upward_response (
    submission_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES core.tenant(id),
    cycle_id        uuid NOT NULL REFERENCES perf.review_cycle(id),
    reviewee_id     uuid NOT NULL REFERENCES core.employee(id),
    answers         jsonb NOT NULL,           -- likert items
    comments        text,                     -- optionally AI-paraphrased before storage
    paraphrased     boolean NOT NULL DEFAULT false,
    submitted_on    date NOT NULL DEFAULT current_date
);
CREATE INDEX ON restricted.upward_response (cycle_id, reviewee_id);

CREATE TABLE restricted.demographic (
    employee_id     uuid PRIMARY KEY REFERENCES core.employee(id),
    tenant_id       uuid NOT NULL REFERENCES core.tenant(id),
    -- self-reported, voluntary; encrypted at the application layer
    attributes_enc  bytea NOT NULL,
    key_id          text NOT NULL,
    consent_at      timestamptz,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- talent: calibration
-- -----------------------------------------------------------------------------
CREATE TABLE talent.calibration_session (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES core.tenant(id),
    cycle_id        uuid NOT NULL REFERENCES perf.review_cycle(id),
    name            text NOT NULL,
    population_filter jsonb NOT NULL,    -- {"org_unit_ids":[...], "band_levels":[5,6,7]}
    facilitator_id  uuid NOT NULL REFERENCES core.employee(id),
    scheduled_at    timestamptz,
    status          text NOT NULL DEFAULT 'setup'
                    CHECK (status IN ('setup','pre_read','in_session','closed')),
    equity_check_run_at timestamptz,
    equity_check_summary jsonb,          -- aggregates only, n>=5 groups
    closed_at       timestamptz
);

CREATE TABLE talent.calibration_member (
    session_id   uuid NOT NULL REFERENCES talent.calibration_session(id) ON DELETE CASCADE,
    employee_id  uuid NOT NULL REFERENCES core.employee(id),
    role         text NOT NULL CHECK (role IN ('facilitator','decision_maker','participant','observer')),
    PRIMARY KEY (session_id, employee_id)
);

CREATE TABLE talent.calibration_subject (
    session_id     uuid NOT NULL REFERENCES talent.calibration_session(id) ON DELETE CASCADE,
    participant_id uuid NOT NULL REFERENCES perf.cycle_participant(id),
    discussed      boolean NOT NULL DEFAULT false,
    PRIMARY KEY (session_id, participant_id)
);

CREATE TABLE talent.calibration_adjustment (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES core.tenant(id),
    session_id      uuid REFERENCES talent.calibration_session(id),
    final_rating_id uuid NOT NULL REFERENCES perf.final_rating(id),
    from_rating     smallint NOT NULL,
    to_rating       smallint NOT NULL,
    rationale       text NOT NULL CHECK (length(rationale) >= 20),
    adjusted_by     uuid NOT NULL REFERENCES core.employee(id),
    is_post_lock_amendment boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (from_rating <> to_rating)
);

-- -----------------------------------------------------------------------------
-- talent: readiness & promotion
-- -----------------------------------------------------------------------------
CREATE TABLE talent.readiness_assessment (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES core.tenant(id),
    employee_id     uuid NOT NULL REFERENCES core.employee(id),
    cycle_id        uuid REFERENCES perf.review_cycle(id),
    current_band_id uuid NOT NULL REFERENCES framework.band(id),
    target_band_id  uuid NOT NULL REFERENCES framework.band(id),
    assessed_by     uuid NOT NULL REFERENCES core.employee(id),
    readiness_level text NOT NULL CHECK (readiness_level IN
                      ('ready_now','ready_6_12','ready_12_24','not_targeting')),
    computed_score  numeric(5,2),
    score_breakdown jsonb,              -- explainability payload
    hours_gate_met  boolean,            -- null = not an hours-required role
    rationale       text,
    status          text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','submitted','calibrated')),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE talent.readiness_criterion_score (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    readiness_assessment_id uuid NOT NULL REFERENCES talent.readiness_assessment(id) ON DELETE CASCADE,
    band_competency_id      uuid REFERENCES framework.band_competency(id),  -- next-band anchor
    gate_criterion_id       uuid REFERENCES framework.gate_criterion(id),
    level                   smallint NOT NULL CHECK (level BETWEEN 0 AND 3),
    comment                 text,
    CHECK ((band_competency_id IS NULL) <> (gate_criterion_id IS NULL))
);

CREATE TABLE talent.readiness_criterion_evidence (
    criterion_score_id uuid NOT NULL REFERENCES talent.readiness_criterion_score(id) ON DELETE CASCADE,
    evidence_id        uuid NOT NULL REFERENCES perf.evidence(id),
    PRIMARY KEY (criterion_score_id, evidence_id)
);

CREATE TABLE talent.promotion_nomination (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          uuid NOT NULL REFERENCES core.tenant(id),
    employee_id        uuid NOT NULL REFERENCES core.employee(id),
    cycle_id           uuid REFERENCES perf.review_cycle(id),
    from_band_id       uuid NOT NULL REFERENCES framework.band(id),
    to_band_id         uuid NOT NULL REFERENCES framework.band(id),
    to_job_profile_id  uuid REFERENCES framework.job_profile(id),
    readiness_assessment_id uuid REFERENCES talent.readiness_assessment(id),
    nominated_by       uuid NOT NULL REFERENCES core.employee(id),
    is_self_nomination boolean NOT NULL DEFAULT false,
    business_case      text,
    case_packet        jsonb,           -- frozen snapshot at committee time
    status             text NOT NULL DEFAULT 'draft'
                       CHECK (status IN ('draft','nominated','endorsed_l2','committee_review','approved',
                                         'deferred','declined','comp_finalized','communicated','effective','withdrawn')),
    decision_rationale text,
    decided_by         uuid REFERENCES core.employee(id),
    decided_at         timestamptz,
    effective_date     date,
    created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE talent.comp_recommendation (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         uuid NOT NULL REFERENCES core.tenant(id),
    participant_id    uuid NOT NULL UNIQUE REFERENCES perf.cycle_participant(id),
    merit_pct         numeric(5,2),
    bonus_amount      numeric(12,2),
    promotion_adjustment_pct numeric(5,2),
    currency          char(3) NOT NULL DEFAULT 'USD',
    recommended_by    uuid NOT NULL REFERENCES core.employee(id),
    status            text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','submitted','approved','exported')),
    notes             text
);

-- -----------------------------------------------------------------------------
-- talent: development
-- -----------------------------------------------------------------------------
CREATE TABLE talent.development_plan (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES core.tenant(id),
    employee_id   uuid NOT NULL REFERENCES core.employee(id),
    fiscal_year   smallint NOT NULL,
    source_cycle_id uuid REFERENCES perf.review_cycle(id),
    career_aspiration text,
    status        text NOT NULL DEFAULT 'draft'
                  CHECK (status IN ('draft','submitted','approved','active','completed','carried_forward')),
    approved_by   uuid REFERENCES core.employee(id),
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (employee_id, fiscal_year)
);

CREATE TABLE talent.skill_gap (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id             uuid NOT NULL REFERENCES talent.development_plan(id) ON DELETE CASCADE,
    competency_id       uuid REFERENCES framework.competency(id),
    gate_criterion_id   uuid REFERENCES framework.gate_criterion(id),
    source              text NOT NULL CHECK (source IN ('review_rating','readiness_gap','manager','self','ai_suggested')),
    description         text NOT NULL,
    priority            smallint NOT NULL DEFAULT 2 CHECK (priority BETWEEN 1 AND 3)
);

CREATE TABLE talent.development_objective (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id        uuid NOT NULL REFERENCES talent.development_plan(id) ON DELETE CASCADE,
    skill_gap_id   uuid REFERENCES talent.skill_gap(id),
    title          text NOT NULL,
    success_measure text,
    status         text NOT NULL DEFAULT 'not_started'
                   CHECK (status IN ('not_started','in_progress','completed','dropped')),
    target_date    date,
    next_follow_up date
);

CREATE TABLE talent.development_action (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    objective_id   uuid NOT NULL REFERENCES talent.development_objective(id) ON DELETE CASCADE,
    kind           text NOT NULL CHECK (kind IN ('training','stretch_assignment','mentorship','shadowing',
                                                 'reading','certification','coaching','other')),
    description    text NOT NULL,
    owner_id       uuid REFERENCES core.employee(id),
    due_date       date,
    completed_at   timestamptz,
    external_ref   text                 -- course id / LMS link
);

CREATE TABLE talent.mentorship (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES core.tenant(id),
    mentor_id     uuid NOT NULL REFERENCES core.employee(id),
    mentee_id     uuid NOT NULL REFERENCES core.employee(id),
    objective_id  uuid REFERENCES talent.development_objective(id),
    focus         text,
    cadence       text,
    starts_on     date NOT NULL,
    ends_on       date,
    status        text NOT NULL DEFAULT 'active' CHECK (status IN ('proposed','active','completed','ended')),
    CHECK (mentor_id <> mentee_id)
);

-- -----------------------------------------------------------------------------
-- talent: 9-box, retention, succession (restricted visibility)
-- -----------------------------------------------------------------------------
CREATE TABLE talent.talent_review (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           uuid NOT NULL REFERENCES core.tenant(id),
    employee_id         uuid NOT NULL REFERENCES core.employee(id),
    cycle_id            uuid NOT NULL REFERENCES perf.review_cycle(id),
    performance_level   smallint CHECK (performance_level BETWEEN 1 AND 3),  -- derived from final rating
    trajectory_level    smallint CHECK (trajectory_level BETWEEN 1 AND 3),   -- growth trajectory
    trajectory_inputs   jsonb,          -- aspiration / agility / scope
    retention_risk      text CHECK (retention_risk IN ('low','medium','high')),
    retention_reason    text CHECK (retention_reason IN ('compensation','career_growth','manager','workload',
                                                       'personal','market_demand','other')),
    impact_of_loss      text CHECK (impact_of_loss IN ('low','medium','high','critical')),
    assessed_by         uuid NOT NULL REFERENCES core.employee(id),
    calibrated          boolean NOT NULL DEFAULT false,
    updated_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (employee_id, cycle_id)
);

CREATE TABLE talent.critical_role (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES core.tenant(id),
    title           text NOT NULL,
    incumbent_id    uuid REFERENCES core.employee(id),
    org_unit_id     uuid REFERENCES core.org_unit(id),
    criticality     text NOT NULL CHECK (criticality IN ('high','critical')),
    vacancy_risk    text CHECK (vacancy_risk IN ('low','medium','high'))
);

CREATE TABLE talent.successor (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    critical_role_id uuid NOT NULL REFERENCES talent.critical_role(id) ON DELETE CASCADE,
    employee_id     uuid NOT NULL REFERENCES core.employee(id),
    readiness       text NOT NULL CHECK (readiness IN ('ready_now','ready_1_2','ready_3_plus','emergency_only')),
    rank            smallint,
    notes           text,
    UNIQUE (critical_role_id, employee_id)
);

-- -----------------------------------------------------------------------------
-- ai
-- -----------------------------------------------------------------------------
CREATE TABLE ai.generation (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        uuid NOT NULL REFERENCES core.tenant(id),
    feature          text NOT NULL,   -- 'peer_summary','narrative_draft','presubmit_check',...
    prompt_template  text NOT NULL,
    prompt_version   text NOT NULL,
    model            text NOT NULL,
    requested_by     uuid NOT NULL REFERENCES core.app_user(id),
    subject_id       uuid REFERENCES core.employee(id),
    target_type      text,            -- e.g. 'competency_rating'
    target_id        uuid,
    source_refs      jsonb NOT NULL DEFAULT '[]'::jsonb,   -- evidence ids used (permission-filtered)
    output           jsonb NOT NULL,
    citations_valid  boolean,
    input_tokens     int,
    output_tokens    int,
    latency_ms       int,
    outcome          text CHECK (outcome IN ('accepted','edited','rejected','ignored')),
    edit_distance    numeric(5,2),
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON ai.generation (subject_id, created_at DESC);

CREATE TABLE ai.flag (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES core.tenant(id),
    generation_id   uuid REFERENCES ai.generation(id),
    target_type     text NOT NULL,
    target_id       uuid NOT NULL,
    flag_type       text NOT NULL CHECK (flag_type IN ('rating_narrative_mismatch','missing_evidence',
                      'personality_language','gendered_language','vague','recency_bias',
                      'outlier_rating','self_manager_gap','uncited_claim')),
    message         text NOT NULL,
    resolution      text CHECK (resolution IN ('fixed','dismissed','open')),
    resolution_note text,
    resolved_by     uuid REFERENCES core.app_user(id),
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Embedding store for evidence retrieval. Uses bytea here so the schema loads
-- without pgvector; production migration switches to vector(1024) + HNSW index.
CREATE TABLE ai.evidence_chunk (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     uuid NOT NULL REFERENCES core.tenant(id),
    subject_id    uuid NOT NULL REFERENCES core.employee(id),
    source_type   text NOT NULL,
    source_id     uuid NOT NULL,
    visibility    text NOT NULL,      -- copied from the source for pre-filtering
    author_id     uuid REFERENCES core.employee(id),
    occurred_on   date NOT NULL,
    content       text NOT NULL,
    embedding     bytea,
    embedded_at   timestamptz
);
CREATE INDEX ON ai.evidence_chunk (subject_id, occurred_on DESC);

-- -----------------------------------------------------------------------------
-- audit
-- -----------------------------------------------------------------------------
CREATE TABLE audit.event (
    id            bigserial PRIMARY KEY,
    tenant_id     uuid NOT NULL,
    occurred_at   timestamptz NOT NULL DEFAULT now(),
    actor_user_id uuid,
    actor_ip      inet,
    action        text NOT NULL,          -- 'final_rating.adjust', 'review.read', ...
    entity_type   text NOT NULL,
    entity_id     uuid,
    subject_id    uuid,                   -- employee the data is about
    before        jsonb,
    after         jsonb,
    reason        text,
    request_id    text
);
CREATE INDEX ON audit.event (entity_type, entity_id);
CREATE INDEX ON audit.event (subject_id, occurred_at DESC);

-- Append-only: block UPDATE/DELETE
CREATE FUNCTION audit.forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit.event is append-only';
END $$;
CREATE TRIGGER audit_event_immutable
    BEFORE UPDATE OR DELETE ON audit.event
    FOR EACH ROW EXECUTE FUNCTION audit.forbid_mutation();

CREATE TABLE audit.workflow_event (
    id           bigserial PRIMARY KEY,
    tenant_id    uuid NOT NULL,
    entity_type  text NOT NULL,       -- 'review_assignment','final_rating','promotion_nomination',...
    entity_id    uuid NOT NULL,
    from_state   text,
    to_state     text NOT NULL,
    actor_user_id uuid,
    reason       text,
    occurred_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON audit.workflow_event (entity_type, entity_id);

CREATE TABLE audit.outbox (
    id           bigserial PRIMARY KEY,
    tenant_id    uuid NOT NULL,
    topic        text NOT NULL,       -- 'notification.send','ai.generate','export.finance'
    dedupe_key   text UNIQUE,
    payload      jsonb NOT NULL,
    available_at timestamptz NOT NULL DEFAULT now(),
    attempts     int NOT NULL DEFAULT 0,
    processed_at timestamptz,
    last_error   text
);
CREATE INDEX outbox_pending ON audit.outbox (available_at) WHERE processed_at IS NULL;

-- -----------------------------------------------------------------------------
-- Views
-- -----------------------------------------------------------------------------
-- Current org snapshot
CREATE VIEW core.v_current_employment AS
SELECT e.id AS employee_id, e.tenant_id, e.given_name, e.family_name, e.email,
       er.manager_id, er.org_unit_id, er.office_id, er.business_unit_id,
       jp.id AS job_profile_id, jp.title, jp.hours_role, jp.discipline_id,
       b.id AS band_id, b.level AS band_level, b.name AS band_name
FROM core.employee e
JOIN core.employment_record er ON er.employee_id = e.id AND er.effective_to IS NULL
JOIN framework.job_profile jp ON jp.id = er.job_profile_id
JOIN framework.band b ON b.id = jp.band_id
WHERE e.status <> 'terminated';

-- Manager chain (all levels) for permission checks
CREATE VIEW core.v_manager_chain AS
WITH RECURSIVE chain AS (
    SELECT employee_id, manager_id AS ancestor_id, 1 AS depth
    FROM core.employment_record WHERE effective_to IS NULL AND manager_id IS NOT NULL
    UNION ALL
    SELECT c.employee_id, er.manager_id, c.depth + 1
    FROM chain c
    JOIN core.employment_record er ON er.employee_id = c.ancestor_id AND er.effective_to IS NULL
    WHERE er.manager_id IS NOT NULL AND c.depth < 12
)
SELECT * FROM chain;

-- Upward review aggregate with minimum-n suppression (threshold from cycle settings, default 3)
CREATE VIEW restricted.v_upward_aggregate AS
WITH counts AS (
    SELECT u.cycle_id, u.reviewee_id, count(*) AS responses
    FROM restricted.upward_response u
    GROUP BY u.cycle_id, u.reviewee_id
), eligible AS (
    SELECT n.*
    FROM counts n
    JOIN perf.review_cycle c ON c.id = n.cycle_id
    WHERE n.responses >= COALESCE((c.settings->>'upward_min_n')::int, 3)
), item_means AS (
    SELECT u.cycle_id, u.reviewee_id, a.key, round(avg(a.value::numeric), 2) AS avg_score
    FROM restricted.upward_response u, jsonb_each_text(u.answers) a
    GROUP BY u.cycle_id, u.reviewee_id, a.key
)
SELECT e.cycle_id, e.reviewee_id, e.responses,
       jsonb_object_agg(m.key, m.avg_score) AS item_means
FROM eligible e
JOIN item_means m ON m.cycle_id = e.cycle_id AND m.reviewee_id = e.reviewee_id
GROUP BY e.cycle_id, e.reviewee_id, e.responses;

-- -----------------------------------------------------------------------------
-- Row-level security scaffold (tenant isolation). App sets:
--   SET app.tenant_id = '<uuid>';  per transaction
-- Fine-grained (relationship) checks are enforced in the policy layer.
-- -----------------------------------------------------------------------------
ALTER TABLE perf.review_response ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON perf.review_response
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
ALTER TABLE perf.note ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON perf.note
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
ALTER TABLE talent.talent_review ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON talent.talent_review
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
-- (applied to every tenant-scoped table by migration helper in the real codebase)
