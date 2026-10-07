# 12. AI Architecture

## 12.1 Charter (non-negotiables)

1. **AI assists. Humans decide.** AI never sets, changes or approves a rating,
   readiness level, promotion, compensation or talent label. The system has no code
   path in which model output writes to those fields.
2. **Everything is cited.** Factual statements about a person link to the evidence
   they came from. Uncited sentences are flagged.
3. **Permission-scoped.** The model only sees what the requesting human could see.
4. **No protected attributes.** Demographics never enter a prompt. Names are
   pseudonymized. Gendered pronouns are normalized for analysis tasks.
5. **Disclosed and logged.** AI-assisted content is marked in the record. Employees
   are told how AI is used (privacy notice). Every generation is logged with its
   outcome.
6. **Measurably fair.** Counterfactual bias evaluations must pass before any prompt
   change ships.

## 12.2 Feature catalog

| Feature | User | Model tier | Inputs (permission-filtered) | Output | Phase |
|---|---|---|---|---|---|
| Peer feedback summary | Manager | Opus | Peer responses for the participant | Themes (strengths/development) with counts and citations [P1..Pn] | MVP |
| Evidence surfacing | Employee, Manager | Embeddings + Haiku rerank | Evidence corpus of the subject | Ranked, cited snippets per competency | MVP |
| Feedback / writing coach | Everyone | Haiku | The user's own draft text | SBI rewrite, flags for vague/personality/biased language | MVP |
| Self-review starter | Employee | Opus | Own goals, check-ins, feedback received | Bullet "what I did" list with citations. The employee writes the reflection | 1.1 |
| Narrative draft | Manager | Opus | Band anchor, rating chosen *by the manager*, evidence, peer themes | Draft paragraph consistent with the chosen rating, cited | 1.1 |
| Pre-submit check | Manager | Haiku + rules | Response, anchors, evidence links | Flags: rating↔narrative mismatch, missing evidence, personality language, recency skew, self–manager gap | 1.1 |
| Development plan suggestions | Employee, Manager | Opus | Gaps (ratings ≤ 2, readiness gaps), dev recommendations, catalog | 2–4 objectives with actions and success measures | 1.1 |
| Goal quality coach | Employee | Haiku | Goal text | SMART check, measurable rewrite | 1.1 |
| Calibration pre-read | Calibration members | Opus | Final review data for the session population | 1-paragraph summary per person, cited | 1.1 |
| Calibration outlier detection | Facilitator | Statistics + Haiku | Ratings, distributions | Manager leniency flags, inconsistent same-band ratings, narrative/rating mismatches | 1.1 |
| Readiness advisory | Manager, committee | Opus | Next-band anchors, gates, evidence, history | Per-criterion "evidence found / not found", with citations. **No level is output.** The rules-based score is shown separately | P2 |
| Org trend themes | Exec, PA | Opus (batch) | De-identified dev recommendations and summary text | Clustered themes with counts ≥ 5 | P2 |
| Anchor drafting | HR (framework authors) | Opus | Current policy text, existing anchors | Draft anchors for human editing | MVP (Phase 0 tool) |
| Upward comment paraphrase | Upward reviewer (opt-in) | Haiku | Own comment | Meaning-preserving paraphrase to hide writing style; the reviewer approves it | 1.1 |

**Readiness:** the brief asks for AI that "recommends promotion readiness levels".
We recommend the AI *maps evidence against criteria* and leaves the level to the
rules-based score and the manager. A model-chosen readiness level is the kind of
automated employment recommendation that draws regulatory scrutiny and erodes
trust. The citations provide the value without that risk.

## 12.3 Architecture

```
 UI action ("✦ Draft")
     │  POST /ai/narrative-draft {assignmentId, competency}
     ▼
┌────────────────────────── AI Gateway (module in api/worker) ───────────────────────┐
│ 1. AuthZ: policy.authorize(actor, "ai.narrative_draft", assignment)                │
│ 2. Context builder                                                                  │
│    - retrieval: hybrid search over ai.evidence_chunk WHERE subject = X              │
│      AND policy-visible(actor)  (SQL-level filter, not post-filter)                 │
│    - framework: band anchor + discipline examples                                   │
│    - manager-chosen rating (input, never output)                                    │
│ 3. Privacy filter: pseudonymize names → [Employee], [Peer 1]; strip demographics,   │
│    contact info; cap tokens                                                         │
│ 4. Prompt assembly: versioned template from /prompts (git), evidence in tagged      │
│    blocks <evidence id="E12">…</evidence> marked as untrusted data                  │
│ 5. Model call (Claude) — streaming; structured output (JSON schema)                 │
│ 6. Post-processing                                                                  │
│    - citation validator: every [E#] exists in provided set; sentences without       │
│      citations flagged "uncited"                                                    │
│    - safety lints: protected-attribute terms, personality language                  │
│    - re-identify placeholders for display only                                      │
│ 7. Log ai.generation (template, version, model, source ids, output, latency)        │
└────────────────────────────────────────────────────────────────────────────────────┘
     ▼
 UI shows draft in a "suggestion" state → human edits/accepts → outcome logged
 (accepted / edited + edit distance / rejected)
```

### Retrieval
- **Chunking:** each note, feedback item, goal update, check-in answer and
  evidence excerpt is one chunk (they are short), carrying `subject_id`,
  `author_id`, `visibility`, `occurred_on` and `source_type`.
- **Indexing:** embeddings are computed asynchronously on write. Postgres FTS plus
  pgvector, with hybrid scoring (BM25-style + cosine) and recency decay *off* by
  default to counter recency bias.
- **Permission filter in SQL:** a chunk is a candidate only if
  `policy_visible(actor, chunk)` holds, so private notes of other authors are never
  retrieved.
- **Coverage control:** retrieval is stratified by quarter so that all four
  quarters are represented (anti-recency).

### Prompt management
- Prompts are files in `prompts/<feature>/<version>.md` with a YAML header
  (model, max tokens, output schema).
- Changes go through PR review and the evaluation suite (below) before deployment.
- Per-tenant feature flags and per-feature kill switches.

### Prompt-injection defense
- Evidence is wrapped and labeled as untrusted data. The system prompt instructs
  the model to ignore instructions found in evidence.
- The model has **no tools that write data**. Output is a draft displayed to a
  human.
- An output schema is enforced and free-form actions are never executed.

## 12.4 Evaluation & fairness

| Eval | Method | Gate |
|---|---|---|
| Citation precision | % of cited claims supported by the cited evidence (LLM-judge + human sample) | ≥ 95% |
| Citation coverage | % of factual sentences with citations | ≥ 90% |
| Counterfactual fairness | Swap names/pronouns/disciplines across the same evidence and compare sentiment, adjectives, length | No significant difference (p > 0.05); adjective-category drift < 5% |
| Rating consistency | Narrative drafted for rating r must be judged consistent with r | ≥ 95% |
| Inconsistency detector | Labeled set of 300 reviews (seeded mismatches) | Precision ≥ 0.8, recall ≥ 0.7 |
| Bias-language lint | Labeled phrase set (personality vs behavior, gender-coded terms) | F1 ≥ 0.85 |
| Human acceptance | % drafts accepted or lightly edited (edit distance < 30%) | Monitored. Very high acceptance plus low edit distance triggers a "rubber-stamping" review |

The evaluation datasets are synthetic, built from the framework, and never use real
employee data.

## 12.5 Governance

- **AI use register:** each feature's purpose, inputs, outputs, human control,
  risks and owner.
- **Opt-outs:** managers can disable drafting for themselves. Employees can request
  that no AI processes their upward comments.
- **Monitoring:** monthly report on usage, acceptance, flags raised and dismissed,
  and fairness eval drift.
- **Vendor terms:** zero data retention, no training on customer data, regional
  processing where available.
- **Legal review:** before any feature that touches promotion or comp (readiness
  advisory, calibration pre-reads).

## 12.6 Model selection & cost estimate (MVP scale ~250 employees)

| Feature | Calls/cycle | Approx tokens/call (in/out) | Model |
|---|---|---|---|
| Peer summary | ~250 | 6k / 800 | claude-opus-5-5 |
| Narrative drafts | ~1,250 (5 per review) | 8k / 400 | claude-opus-5-5 |
| Pre-submit checks | ~500 | 6k / 400 | claude-haiku-4-5 |
| Writing coach (year-round) | ~5,000 | 1k / 300 | claude-haiku-4-5 |

That is roughly 15–20M tokens per year in total, a small three- or four-figure
annual model cost at current pricing. Cost is not a design constraint at Somos's
scale. Quality and trust are.
