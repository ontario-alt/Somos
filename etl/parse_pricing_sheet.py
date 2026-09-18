"""
Parses project pricing/budget workbooks -- the scoping/proposal-budget
layout used for pricing new engagements, distinct from the Vantagepoint
exports the rest of etl/ handles.

These aren't a fixed export format like Vantagepoint's -- they're
hand-built per proposal, and two real samples already look quite
different (a single hours-matrix vs. a multi-firm, multi-phase budget
with its own rate-escalation table on a separate tab). Rather than
matching exact cell addresses, this parser locates:

  1. A role/rate row pair -- the two adjacent rows, anywhere near the
     top of the sheet, with the most columns where the upper row holds
     text (a role name) and the lower row holds a number directly below
     it (that role's $/hr). This works whether roles are one contiguous
     block ("Principal, Director, Manager...") or several blocks side by
     side (a "SOMOS: ..." block followed by an "S&A ..." block).

  2. A label column -- whichever of the first few columns has the most
     text entries below the rate row; that's where task/phase and
     subtask/activity names live.

  3. Task vs. subtask, by numbering shape rather than position: a label
     starting "<n>.<n>" (e.g. "1.1", "2.3") is a subtask under the most
     recent task; anything else non-blank in the label column (e.g.
     "Task 1: ...", "Phase 2 - ...") starts a new task. Any other
     numeric/summary columns in the row (pre-computed $ totals, hours
     totals) are intentionally ignored -- the dashboard recomputes cost
     live from hours x current rate so toggling a role/task/subtask on
     or off, or editing a rate, always reflects the current state rather
     than a total baked in at parse time.

Only the first worksheet is read (the primary budget grid) -- a workbook
with a separate "Assumptions + Rates" or "Exclusions" tab is fine; those
are supplementary and not scraped.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

_SUBTASK_RE = re.compile(r"^\d+\.\d+\b")

# Generic role-title vocabulary used to split a column header like
# "S&A Sr. Associate 2" into firm="S&A", role="Sr. Associate 2": the
# first token that looks like a role word marks where the role name
# starts: anything before it is a firm/subcontractor name.
_ROLE_WORDS = {
    "principal", "director", "manager", "associate", "analyst", "designer",
    "coordinator", "controls", "graphics", "web", "project", "lead",
    "senior", "sr", "1", "2", "3",
}


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def split_firm_role(title: str) -> tuple[str, str]:
    """Best-effort split of a role-column header into (firm, role). Roles
    with no discernible firm prefix are attributed to config.HOME_FIRM_NAME
    (Somos's own rates)."""
    title = title.strip()
    if ":" in title:
        firm, _, role = title.partition(":")
        return firm.strip(), role.strip()
    tokens = title.split()
    for i, tok in enumerate(tokens):
        if tok.lower().strip(".,") in _ROLE_WORDS:
            if i > 0:
                return " ".join(tokens[:i]), " ".join(tokens[i:])
            return config.HOME_FIRM_NAME, title
    return config.HOME_FIRM_NAME, title


def _find_role_rate_rows(rows: list[list[Any]]) -> tuple[int, int]:
    """Returns (role_row_idx, rate_row_idx): the adjacent row pair, within
    the first 15 rows, with the most columns where the upper row is text
    and the lower row is a number in the same column."""
    best = (0, 1, -1)
    limit = min(len(rows) - 1, 15)
    for i in range(limit):
        upper, lower = rows[i], rows[i + 1]
        count = sum(
            1
            for u, l in zip(upper, lower)
            if isinstance(u, str) and u.strip() and _is_number(l)
        )
        if count > best[2]:
            best = (i, i + 1, count)
    if best[2] < 1:
        raise ValueError("couldn't find a role-name row followed by a $/hr rate row")
    return best[0], best[1]


def _role_columns(role_row: list[Any], rate_row: list[Any]) -> list[tuple[int, str, float]]:
    cols = []
    for c, (title, rate) in enumerate(zip(role_row, rate_row)):
        if isinstance(title, str) and title.strip() and _is_number(rate):
            cols.append((c, title.strip(), float(rate)))
    return cols


def _label_col(rows: list[list[Any]], start_row: int) -> int:
    ncols = max((len(r) for r in rows), default=1)
    best_col, best_count = 0, -1
    for c in range(min(3, ncols)):
        count = sum(
            1 for r in rows[start_row:] if c < len(r) and isinstance(r[c], str) and r[c].strip()
        )
        if count > best_count:
            best_col, best_count = c, count
    return best_col


def parse_pricing_sheet(path: str | Path) -> dict:
    """Parses one pricing workbook into a plain-dict structure:

    {
      "project_name": str,
      "source_file": str,
      "roles": [{"title": str, "rate": float}, ...],
      "tasks": [
        {"id": str, "name": str,
         "subtasks": [{"id": str, "name": str, "hours": {role_title: hours}}]},
        ...
      ],
    }
    """
    path = Path(path)
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]

    rows = [[c.value for c in row] for row in ws.iter_rows()]
    if not rows:
        raise ValueError(f"{path.name}: empty sheet")

    project_name = next(
        (c for c in rows[0] if isinstance(c, str) and c.strip()), path.stem
    )

    role_row_idx, rate_row_idx = _find_role_rate_rows(rows)
    role_cols = _role_columns(rows[role_row_idx], rows[rate_row_idx])
    if not role_cols:
        raise ValueError(f"{path.name}: found a role/rate row pair but no aligned columns")

    data_start = rate_row_idx + 1
    label_col = _label_col(rows, data_start)

    tasks: list[dict] = []
    current_task: dict | None = None
    fallback_hours: dict[int, dict[str, float]] = {}

    for row in rows[data_start:]:
        if len(row) <= label_col:
            continue
        label = row[label_col]
        if not isinstance(label, str) or not label.strip():
            continue
        label = label.strip()
        if label.lower().startswith("total"):
            continue

        hours = {
            title: float(row[c]) if c < len(row) and _is_number(row[c]) else 0.0
            for c, title, _ in role_cols
        }

        if _SUBTASK_RE.match(label):
            if current_task is None:
                current_task = {"id": "Task 1", "name": "Ungrouped", "subtasks": []}
                tasks.append(current_task)
            sub_id, _, sub_name = label.partition(" ")
            if ":" in sub_id:
                sub_id = sub_id.rstrip(":")
            current_task["subtasks"].append(
                {"id": sub_id, "name": (sub_name.strip() or label), "hours": hours}
            )
        else:
            task_id, sep, task_name = label.partition(":")
            if not sep:
                task_id, task_name = task_id.split(" ", 1) if " " in task_id else (task_id, "")
            current_task = {
                "id": task_id.strip() or f"Task {len(tasks) + 1}",
                "name": (task_name.strip() or label),
                "subtasks": [],
            }
            tasks.append(current_task)
            fallback_hours[id(current_task)] = hours

    # A task with no numbered subtasks under it still needs a line item to
    # price -- use its own row's hours as a single implicit subtask. A task
    # that does have subtasks skips this: its own row is normally just an
    # aggregate of those subtasks, and keeping it too would double-count.
    for task in tasks:
        if not task["subtasks"]:
            hours = fallback_hours.get(id(task), {})
            if any(hours.values()):
                task["subtasks"].append({"id": task["id"], "name": task["name"], "hours": hours})

    roles = []
    for _, title, rate in role_cols:
        firm, role_name = split_firm_role(title)
        roles.append({"firm": firm, "title": role_name, "rate": rate, "raw_title": title})

    return {
        "project_name": str(project_name).strip(),
        "source_file": path.name,
        "roles": roles,
        "tasks": tasks,
    }
