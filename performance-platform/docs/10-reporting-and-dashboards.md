# 10. Reporting Model, Leadership Analytics & Dashboard Design

## 10.1 Reporting architecture

```
OLTP (Postgres) ──nightly + on lock/release──► Extract job (worker)
                                                   │
                                   applies policy: pseudonymize, drop private notes,
                                   drop narratives (only structured facts), drop demographics
                                                   ▼
                              analytics star schema (Postgres `mart` schema, parquet export)
                                   │                          │
                    in-app dashboards (API reads mart)   executive dashboard (DuckDB/Streamlit)
                                   │
              People Analytics: demographics joined ONLY inside a secure function
              that returns aggregates with n ≥ 5 suppression
```

Principles:
- **In-app dashboards for operational and individual views**, permission-aware.
- **A mart for trends and cross-cycle analysis.** It is rebuilt idempotently, and a
  frozen snapshot is kept for each locked cycle.
- **Narrative text never enters the mart.** The AI theme pipeline produces
  aggregated themes with a minimum count of 5 instead.

## 10.2 Star schema (mart)

**Dimensions**
| Dimension | Notes |
|---|---|
| `dim_employee` (SCD2) | pseudonymous key, band, job profile, discipline, unit, office, BU, manager key, tenure bucket, hours role |
| `dim_band`, `dim_competency`, `dim_discipline`, `dim_org_unit`, `dim_office` | |
| `dim_cycle` | fiscal year, kind, framework version |
| `dim_date` | fiscal calendar (Oct–Sep), fiscal quarter |
| `dim_manager` | role-playing on dim_employee |

**Facts**
| Fact | Grain | Measures |
|---|---|---|
| `fact_competency_rating` | participant × competency × review type | rating, is_na, evidence_count |
| `fact_final_rating` | participant × cycle | proposed, final, delta, reference_score, holistic_gap, ack_days |
| `fact_calibration_adjustment` | adjustment | from, to, direction |
| `fact_goal` | goal | weight, score, status, is_stretch |
| `fact_checkin` | check-in | on_time flag, days_late |
| `fact_feedback` | feedback item | kind, giver relationship |
| `fact_readiness` | assessment | level, score, failed_gates |
| `fact_promotion` | nomination | outcome, time_in_band_months, days_in_workflow |
| `fact_dev_plan` | objective | status, overdue |
| `fact_hours_policy` | employee × fiscal year | expectation %, lookback %, gate_met |
| `fact_talent_review` | employee × cycle | perf level, trajectory level, retention risk, impact |
| `fact_process` | assignment | type, status, submitted_on_time |

## 10.3 Metric catalog (definitions)

| Metric | Definition |
|---|---|
| Completion rate | submitted assignments / assignments due (excl. declined/cancelled) |
| Check-in cadence | % employees with a completed check-in in each fiscal quarter |
| Rating distribution | % of final ratings at each value, by dimension |
| Calibration delta | mean(final − proposed). The manager **leniency index** = mean(proposed − final) over the manager's reports, with n shown |
| Manager severity gap | manager mean proposed rating − mean for the same bands firm-wide |
| Self–manager gap | mean(self − manager) per competency |
| Evidence coverage | % competency ratings with ≥ 1 evidence item |
| Goal attainment | weighted mean goal score |
| Promotion rate | promotions effective / eligible headcount at band, by year |
| Time in band | median months at band at promotion |
| Pipeline | count of Ready now / 6–12 / 12–24 by target band |
| Bench strength | critical roles with ≥ 1 Ready-now successor / critical roles |
| Regretted attrition | leavers with final ≥ 4 or trajectory High / headcount |
| Adverse impact ratio | selection rate of group / selection rate of highest group (promotions, rating ≥ 4); flag < 0.8 when both groups n ≥ 5 |

## 10.4 Dashboards

| Dashboard | Audience | Key widgets |
|---|---|---|
| **My Performance** (home) | Employee | Tasks, goal progress ring, next check-in, feedback received, band progress & next-band gaps, dev plan status |
| **Manager Hub** | Manager | Team grid (goals, last check-in, open feedback requests, review status), check-in cadence, team readiness, "needs attention" |
| **Cycle Operations** | HR | Completion heatmap (unit × phase), overdue list, returned reviews, calibration schedule, export readiness |
| **Calibration Room** | Facilitator / participants | Distribution vs guidance, by-manager boxplots, grid, cross-discipline comparison, adjustments log |
| **Equity Check** | People Analytics | Rating and promotion outcomes by group (n ≥ 5), adverse impact ratios, calibration-adjustment direction by group |
| **Talent Matrix** | Directors, Exec | 9-box, filter by unit/band, click-through to the profile (permissioned) |
| **Promotion Pipeline** | Directors, Exec | Funnel by band, readiness levels, time in band, gate failures by criterion |
| **Retention & Succession** | Exec, HR | Risk × impact matrix, critical roles, bench strength, successors' readiness |
| **Performance Trends** | Exec | Rating distribution over cycles, competency averages by discipline, development themes (AI, aggregated) |
| **Hours & Performance** | PA, Exec | Hours-policy gate status vs rating (context only), scatter with n ≥ 5 cells |

## 10.5 Dashboard design principles

- **Decision-first.** Each dashboard answers a named question ("Are ratings
  consistent across disciplines?") stated at the top.
- **Show n everywhere.** Small groups render as "n < 5, suppressed", not as a
  misleading 100%.
- **Comparison baselines.** Firm-wide mean and guidance distribution lines on every
  distribution chart.
- **Drill-through respects permissions.** Aggregates are visible, individuals only
  if the policy allows.
- **No ranking leaderboards of people.** Ranking invites forced-ranking behavior
  the firm hasn't chosen.
- Accessible color palette (colorblind-safe), every chart has a table view, WCAG
  2.2 AA.

## 10.6 Standard reports (scheduled / export)

| Report | Recipient | Format |
|---|---|---|
| Final ratings & promotions (locked) | Finance | CSV + signed PDF summary |
| Cycle completion | HR, Directors | Weekly email during the cycle |
| Calibration summary | Exec | PDF after sessions close |
| Individual review packet | Employee / manager | PDF |
| Dev plan follow-ups due | Managers | Monthly digest |
| Board/partner talent summary | Principals | Annual PDF (aggregates only) |
