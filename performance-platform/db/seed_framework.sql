-- Seed: Somos tenant, framework v1 (7 bands, 5 rated competencies + Summary,
-- band weights, gate criteria, 5-point rating scale, disciplines, business units).
-- Anchor text here is placeholder; leadership authors final anchors in Phase 0.

BEGIN;

INSERT INTO core.tenant (id, name, slug, fiscal_year_start_month)
VALUES ('00000000-0000-0000-0000-000000000001', 'Somos', 'somos', 10);

INSERT INTO core.business_unit (tenant_id, code, name, country) VALUES
 ('00000000-0000-0000-0000-000000000001', 'LLP', 'Somos LLP (Legal)',    'US'),
 ('00000000-0000-0000-0000-000000000001', 'LLC', 'Somos LLC (Planning)', 'US'),
 ('00000000-0000-0000-0000-000000000001', 'MX',  'Somos MX',             'MX');

INSERT INTO core.discipline (tenant_id, code, name) VALUES
 ('00000000-0000-0000-0000-000000000001', 'LEGAL', 'Legal'),
 ('00000000-0000-0000-0000-000000000001', 'PLAN',  'Planning'),
 ('00000000-0000-0000-0000-000000000001', 'PM',    'Project Management'),
 ('00000000-0000-0000-0000-000000000001', 'OPS',   'Operations & Administration');

INSERT INTO framework.framework_version (id, tenant_id, version, status, published_at, notes)
VALUES ('00000000-0000-0000-0000-0000000000f1', '00000000-0000-0000-0000-000000000001', 1, 'published', now(),
        'Initial career framework');

INSERT INTO framework.band (tenant_id, framework_version_id, level, code, name, summary, advancement_philosophy, is_people_leader_band)
SELECT '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000f1', lvl, 'B' || lvl, nm, summ, phil, lvl >= 6
FROM (VALUES
 (1, 'Clerk',               'Defined tasks under close supervision.',            'Technical expertise, execution, quality.'),
 (2, 'Analyst / Specialist','Owns workstreams within a project.',                'Technical expertise, execution, quality.'),
 (3, 'Associate',           'Independently executes significant work.',          'Technical expertise, execution, project ownership, quality, client delivery.'),
 (4, 'Senior Associate',    'Owns complex work; guides junior colleagues.',      'Technical expertise, execution, project ownership, quality, client delivery.'),
 (5, 'Project Leader',      'Leads projects/matters end to end.',                'Project ownership, client delivery, quality of team output.'),
 (6, 'Director',            'Leads people and a practice area.',                 'People leadership, strategy, staff development, external relationships, BD, multiple complex initiatives.'),
 (7, 'Principal / Leader',  'Leads the firm.',                                   'Organizational leadership, market visibility, business generation, firm-wide influence.')
) AS t(lvl, nm, summ, phil);

INSERT INTO framework.competency (tenant_id, framework_version_id, code, name, description, is_rated, sort_order)
SELECT '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000f1', c, n, d, r, o
FROM (VALUES
 ('C1', 'Skills & Technical Excellence',             'Expertise, quality, accuracy, judgment.',                     true, 1),
 ('C2', 'Client Service & Value',                    'Responsiveness, client outcomes, relationships, BD (6+).',    true, 2),
 ('C3', 'Communication & Professional Skills',       'Written/oral communication, presence, collaboration.',        true, 3),
 ('C4', 'Work, People & Self-Management',            'Planning, efficiency, delegation, leadership (5+).',          true, 4),
 ('C5', 'Professional Responsibility & Citizenship', 'Ethics, firm contribution, mentoring, knowledge sharing.',    true, 5),
 ('S',  'Developmental & Summary Feedback',          'Strengths, priorities, overall narrative, holistic rating.',  false, 6)
) AS t(c, n, d, r, o);

-- Band weights (doc 04 §4.3)
INSERT INTO framework.band_competency (tenant_id, band_id, competency_id, weight_pct, anchor_meets)
SELECT b.tenant_id, b.id, c.id, w.weight,
       format('[Draft anchor] %s at %s: meets band expectations.', c.name, b.name)
FROM framework.band b
JOIN framework.competency c ON c.framework_version_id = b.framework_version_id AND c.is_rated
JOIN (VALUES
 (1,'C1',35),(1,'C2',15),(1,'C3',20),(1,'C4',20),(1,'C5',10),
 (2,'C1',35),(2,'C2',15),(2,'C3',20),(2,'C4',20),(2,'C5',10),
 (3,'C1',30),(3,'C2',20),(3,'C3',20),(3,'C4',20),(3,'C5',10),
 (4,'C1',30),(4,'C2',20),(4,'C3',20),(4,'C4',20),(4,'C5',10),
 (5,'C1',25),(5,'C2',25),(5,'C3',15),(5,'C4',25),(5,'C5',10),
 (6,'C1',15),(6,'C2',25),(6,'C3',15),(6,'C4',30),(6,'C5',15),
 (7,'C1',10),(7,'C2',30),(7,'C3',15),(7,'C4',25),(7,'C5',20)
) AS w(lvl, code, weight) ON w.lvl = b.level AND w.code = c.code;

INSERT INTO framework.gate_criterion (tenant_id, target_band_id, code, name, evidence_guidance, sort_order)
SELECT b.tenant_id, b.id, g.code, g.name, g.ev, g.ord
FROM framework.band b
JOIN (VALUES
 (5, 'PL-OWN',   'Led a project/matter end to end with client accountability', 'Project list; client feedback', 1),
 (5, 'PL-SUP',   'Supervised others'' work with quality outcomes',            'Feedback from juniors/peers',  2),
 (6, 'DIR-PPL',  'People leadership over 12+ months',                          'Check-ins; upward feedback; retention', 1),
 (6, 'DIR-STR',  'Strategic planning ownership',                               'Practice/team plan and outcomes', 2),
 (6, 'DIR-DEV',  'Staff development',                                          'Mentorships; people who advanced', 3),
 (6, 'DIR-EXT',  'External relationship management',                          'Key client/agency relationships', 4),
 (6, 'DIR-BD',   'Business development participation',                        'Pitches; proposals; originations', 5),
 (6, 'DIR-MULTI','Manages multiple complex initiatives',                      'Project portfolio', 6),
 (7, 'PRN-ORG',  'Organizational leadership',                                  'Firm-level initiative led', 1),
 (7, 'PRN-MKT',  'Market visibility',                                          'Speaking; publications; recognition', 2),
 (7, 'PRN-BIZ',  'Business generation',                                        'Sustained originations', 3),
 (7, 'PRN-INF',  'Firm-wide influence and reputation',                         'Leadership and peer input', 4)
) AS g(lvl, code, name, ev, ord) ON g.lvl = b.level;

INSERT INTO framework.rating_scale (id, tenant_id, name)
VALUES ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000001', 'Somos 5-point');

INSERT INTO framework.rating_scale_point (rating_scale_id, value, label, description, guidance_min_pct, guidance_max_pct, requires_evidence)
VALUES
 ('00000000-0000-0000-0000-0000000000a1', 5, 'Exceptional',   'Consistently exceeds band expectations; operating at next band in this area', 5, 10, true),
 ('00000000-0000-0000-0000-0000000000a1', 4, 'Strong',        'Exceeds expectations in significant ways',                                  20, 30, false),
 ('00000000-0000-0000-0000-0000000000a1', 3, 'Fully Meets',   'Solidly delivers what the band requires',                                   50, 60, false),
 ('00000000-0000-0000-0000-0000000000a1', 2, 'Developing',    'Partially meets; specific gaps',                                            5, 15, true),
 ('00000000-0000-0000-0000-0000000000a1', 1, 'Does Not Meet', 'Significant gaps; improvement plan required',                               0, 5, true);

-- Weights must total 100 for every band
DO $$
DECLARE bad int;
BEGIN
  SELECT count(*) INTO bad FROM (
    SELECT band_id FROM framework.band_competency GROUP BY band_id HAVING sum(weight_pct) <> 100) x;
  IF bad > 0 THEN RAISE EXCEPTION '% band(s) have weights not summing to 100', bad; END IF;
END $$;

COMMIT;
