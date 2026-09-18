"""
Data model, persistence, and cost computation for the Project Pricing
tool. Each pricing project (one engagement/proposal) is a plain-dict
"document" saved as its own JSON file under config.PRICING_DATA_DIR --
real client budget data, gitignored like the rest of data/.

Shape of a saved project:

{
  "id": str,
  "project_name": str,
  "active": bool,               -- included in the cross-project summary
  "source_files": [str, ...],   -- uploaded workbook(s) this was built from
  "roles": [
    {"id": str, "firm": str, "title": str, "rate": float, "enabled": bool}
  ],
  "phases": [
    {"id": str, "name": str, "enabled": bool,
     "subtasks": [
       {"id": str, "name": str, "enabled": bool, "hours": {role_id: float}}
     ]}
  ],
  "expenses": [{"firm": str, "amount": float, "note": str}],
}

Costs are never stored -- compute_project() derives them fresh every time
from (hours x rate) for whatever's currently enabled, so a rate edit or a
toggle always takes effect immediately rather than needing a re-save/
re-parse step.
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from etl.parse_pricing_sheet import parse_pricing_sheet


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "project"


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _path_for(project_id: str) -> Path:
    return config.PRICING_DATA_DIR / f"{project_id}.json"


def list_projects() -> list[dict]:
    config.PRICING_DATA_DIR.mkdir(parents=True, exist_ok=True)
    projects = []
    for f in sorted(config.PRICING_DATA_DIR.glob("*.json")):
        try:
            projects.append(_ensure_defaults(json.loads(f.read_text())))
        except (json.JSONDecodeError, OSError):
            continue
    return sorted(projects, key=lambda p: p.get("project_name", ""))


_PROJECT_DEFAULTS = {
    "client_name": "",
    "notes": "",
    "exclusions": [],
}
_PHASE_DEFAULTS = {"note": ""}


def _ensure_defaults(project: dict) -> dict:
    """Backfills fields added after a project was first saved, so an older
    saved project (or one built by project_from_upload before these
    existed) still opens and exports cleanly."""
    for key, default in _PROJECT_DEFAULTS.items():
        project.setdefault(key, default)
    for phase in project.get("phases", []):
        for key, default in _PHASE_DEFAULTS.items():
            phase.setdefault(key, default)
    return project


def load_project(project_id: str) -> dict | None:
    path = _path_for(project_id)
    if not path.exists():
        return None
    return _ensure_defaults(json.loads(path.read_text()))


def save_project(project: dict) -> None:
    config.PRICING_DATA_DIR.mkdir(parents=True, exist_ok=True)
    _path_for(project["id"]).write_text(json.dumps(project, indent=2))


def delete_project(project_id: str) -> None:
    path = _path_for(project_id)
    if path.exists():
        path.unlink()


def new_blank_project(project_name: str = "New Project") -> dict:
    return {
        "id": _new_id(),
        "project_name": project_name,
        "active": True,
        "source_files": [],
        "client_name": "",
        "notes": "",
        "exclusions": [],
        "roles": [
            {"id": _new_id(), "firm": config.HOME_FIRM_NAME, "title": "Principal", "rate": 300.0, "enabled": True},
        ],
        "phases": [],
        "expenses": [],
    }


def project_from_upload(path: str | Path) -> dict:
    """Parses an uploaded pricing workbook into a new saved project."""
    parsed = parse_pricing_sheet(path)

    role_id_by_raw_title: dict[str, str] = {}
    roles = []
    for r in parsed["roles"]:
        rid = _new_id()
        role_id_by_raw_title[r["raw_title"]] = rid
        roles.append(
            {"id": rid, "firm": r["firm"], "title": r["title"], "rate": r["rate"], "enabled": True}
        )

    phases = []
    for task in parsed["tasks"]:
        subtasks = []
        for sub in task["subtasks"]:
            hours_by_role_id = {
                role_id_by_raw_title[raw_title]: hrs
                for raw_title, hrs in sub["hours"].items()
                if hrs
            }
            subtasks.append(
                {"id": _new_id(), "name": f"{sub['id']} {sub['name']}".strip(), "enabled": True, "hours": hours_by_role_id}
            )
        phases.append({"id": _new_id(), "name": f"{task['id']}: {task['name']}".strip(": "), "enabled": True, "note": "", "subtasks": subtasks})

    return {
        "id": _new_id(),
        "project_name": parsed["project_name"],
        "active": True,
        "source_files": [parsed["source_file"]],
        "client_name": "",
        "notes": "",
        "exclusions": [],
        "roles": roles,
        "phases": phases,
        "expenses": [],
    }


def compute_project(project: dict) -> dict:
    """Recomputes cost from current rates/hours and enabled flags. Returns:

    {
      "role_cost": {role_id: $},
      "firm_labor": {firm: $},
      "firm_hours": {firm: hours},
      "firm_expenses": {firm: $},
      "firm_total": {firm: $},   -- labor + expenses
      "phases": [{..phase.., "cost": $, "hours": h,
                  "subtasks": [{..subtask.., "cost": $, "hours": h}]}],
      "labor_total": $,
      "expense_total": $,
      "grand_total": $,
    }
    """
    roles_by_id = {r["id"]: r for r in project["roles"]}

    role_cost: dict[str, float] = defaultdict(float)
    firm_labor: dict[str, float] = defaultdict(float)
    firm_hours: dict[str, float] = defaultdict(float)
    phase_rows = []

    for phase in project["phases"]:
        sub_rows = []
        phase_cost = phase_hours = 0.0
        for sub in phase["subtasks"]:
            sub_cost = sub_hours = 0.0
            if phase["enabled"] and sub["enabled"]:
                for role_id, hrs in sub["hours"].items():
                    role = roles_by_id.get(role_id)
                    if not role or not role["enabled"] or not hrs:
                        continue
                    cost = hrs * role["rate"]
                    role_cost[role_id] += cost
                    firm_labor[role["firm"]] += cost
                    firm_hours[role["firm"]] += hrs
                    sub_cost += cost
                    sub_hours += hrs
            sub_rows.append({**sub, "cost": sub_cost, "hours": sub_hours})
            phase_cost += sub_cost
            phase_hours += sub_hours
        phase_rows.append({**phase, "cost": phase_cost, "hours": phase_hours, "subtasks": sub_rows})

    firm_expenses: dict[str, float] = defaultdict(float)
    for e in project.get("expenses", []):
        firm_expenses[e["firm"]] += float(e.get("amount") or 0)

    all_firms = set(firm_labor) | set(firm_expenses) | {r["firm"] for r in project["roles"] if r["enabled"]}
    firm_total = {firm: firm_labor.get(firm, 0.0) + firm_expenses.get(firm, 0.0) for firm in all_firms}

    return {
        "role_cost": dict(role_cost),
        "firm_labor": dict(firm_labor),
        "firm_hours": dict(firm_hours),
        "firm_expenses": dict(firm_expenses),
        "firm_total": firm_total,
        "phases": phase_rows,
        "labor_total": sum(firm_labor.values()),
        "expense_total": sum(firm_expenses.values()),
        "grand_total": sum(firm_total.values()),
    }
