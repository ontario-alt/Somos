"""
Project Pricing tool -- builds project fee estimates from uploaded
budget/pricing workbooks (see etl/parse_pricing_sheet.py) or from
scratch, then lets you toggle roles/firms/phases on or off, edit rates,
and see the total recompute live.

Each project is Somos's own rates by default, plus any subcontracted
firm (e.g. a design partner, a specialty consultant) pulled in on the
same phases -- a role's firm is inferred from its column header on
import (a "SOMOS:" / "S&A" / "Parity" style prefix) and stays editable
afterward. Multiple projects can be marked "active" at once for a
combined view (e.g. comparing scenarios, or totalling a multi-project
pipeline).

A project's own uploaded workbook is read only as a starting point (see
parse_pricing_sheet's docstring for why the parser doesn't chase every
possible layout) -- the numbers actually driving the total always come
from this tool's own rates/hours/toggles, not from whatever the sheet
displayed.

The tool's real deliverable is the client-facing work product: "Export
Excel workbook" and "Export PDF proposal" (dashboard/pricing_export.py)
build a Somos-branded, fully laid-out proposal -- cover page, rates
table, a phase/line-item budget grid with live formulas, a budget
summary, and a scope-exclusions page -- in the same spirit as the real
Western U and Project Eagle budgets this tool was built against.
Anything toggled off in the tool shows up struck through with its
would-be cost rather than disappearing, so the export documents the
choices made, not just the bottom line.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import streamlit as st

import config
from dashboard import pricing_export, pricing_store as ps
from dashboard.charts.kpi_cards import kpi_row
from dashboard.charts.theme import CATEGORICAL, fmt_currency


def render():
    st.title("Project Pricing")
    st.caption(
        "Upload a project budget/pricing workbook, or start from scratch. "
        "Toggle firms, roles, and phases on or off, adjust rates, and the "
        "total recomputes live."
    )

    _section_upload()

    projects = ps.list_projects()
    if not projects:
        st.info("No pricing projects yet -- upload a workbook above, or add a blank one.")
        if st.button("+ Add blank project"):
            ps.save_project(ps.new_blank_project())
            st.rerun()
        return

    st.divider()
    _section_project_list(projects)

    st.divider()
    selected_id = st.session_state.get("pricing_selected_id")
    project = ps.load_project(selected_id) if selected_id else None
    if project is None:
        project = projects[0]
        st.session_state["pricing_selected_id"] = project["id"]

    _section_editor(project)

    if len(projects) > 1:
        st.divider()
        _section_combined_summary([p for p in projects if p.get("active")])


def _section_upload():
    uploaded = st.file_uploader(
        "Upload pricing/budget workbook(s) (.xlsx)",
        type=["xlsx"],
        accept_multiple_files=True,
        key="pricing_uploader",
    )
    if not uploaded:
        return
    added = []
    errors = []
    for f in uploaded:
        try:
            tmp_path = Path(st.session_state.setdefault("pricing_tmp_dir", _tmp_dir())) / f.name
            tmp_path.write_bytes(f.getvalue())
            project = ps.project_from_upload(tmp_path)
            ps.save_project(project)
            added.append(project["project_name"])
        except Exception as e:  # noqa: BLE001 -- surfaced to the user, not swallowed
            errors.append(f"{f.name}: {e}")
    if added:
        st.success(f"Added: {', '.join(added)}")
        st.session_state["pricing_uploader"] = None
        st.rerun()
    for e in errors:
        st.error(e)


def _tmp_dir() -> str:
    import tempfile

    d = tempfile.mkdtemp(prefix="somos_pricing_")
    return d


def _section_project_list(projects: list[dict]):
    st.subheader("Pricing projects")
    for p in projects:
        comp = ps.compute_project(p)
        cols = st.columns([0.5, 3, 2, 1, 1])
        with cols[0]:
            active = st.checkbox(
                "Active", value=p.get("active", True), key=f"active_{p['id']}",
                help="Include in combined summary", label_visibility="collapsed",
            )
            if active != p.get("active", True):
                p["active"] = active
                ps.save_project(p)
        with cols[1]:
            if st.button(p["project_name"], key=f"select_{p['id']}", use_container_width=True):
                st.session_state["pricing_selected_id"] = p["id"]
                st.rerun()
        with cols[2]:
            st.caption(fmt_currency(comp["grand_total"]))
        with cols[3]:
            st.caption(", ".join(comp["firm_total"].keys()) or "--")
        with cols[4]:
            if st.button("🗑", key=f"del_{p['id']}", help="Delete this project"):
                ps.delete_project(p["id"])
                if st.session_state.get("pricing_selected_id") == p["id"]:
                    st.session_state.pop("pricing_selected_id", None)
                st.rerun()


def _section_editor(project: dict):
    st.subheader(f"Editing: {project['project_name']}")
    new_name = st.text_input("Project name", value=project["project_name"], key=f"name_{project['id']}")
    if new_name != project["project_name"]:
        project["project_name"] = new_name
        ps.save_project(project)

    _section_proposal_details(project)
    _section_roles(project)
    _section_phases(project)
    _section_expenses(project)
    _section_totals(project)


def _section_proposal_details(project: dict):
    st.markdown("#### Proposal details")
    st.caption("Feeds the cover page, budget grid, and exclusions page of the client-facing export.")
    changed = False

    client = st.text_input("Client name", value=project.get("client_name", ""), key=f"client_{project['id']}")
    if client != project.get("client_name", ""):
        project["client_name"] = client
        changed = True

    notes = st.text_area(
        "Cover page summary (optional)",
        value=project.get("notes", ""),
        key=f"notes_{project['id']}",
        help="A short paragraph introducing the engagement -- shown on the cover page of both exports.",
        height=80,
    )
    if notes != project.get("notes", ""):
        project["notes"] = notes
        changed = True

    exclusions_text = "\n".join(project.get("exclusions", []))
    new_exclusions_text = st.text_area(
        "Scope exclusions & assumptions (one per line)",
        value=exclusions_text,
        key=f"exclusions_{project['id']}",
        help="Each line becomes one bullet on the export's Exclusions page -- mirrors how Project Eagle's proposal called out scope limits.",
        height=100,
    )
    new_exclusions = [line.strip() for line in new_exclusions_text.split("\n") if line.strip()]
    if new_exclusions != project.get("exclusions", []):
        project["exclusions"] = new_exclusions
        changed = True

    if changed:
        ps.save_project(project)


def _section_roles(project: dict):
    st.markdown("#### Roles & rates")
    st.caption("Add a row to bring in a subcontracted firm. Uncheck Enabled to exclude a role from the total without deleting it.")

    df = pd.DataFrame(project["roles"])
    if df.empty:
        df = pd.DataFrame(columns=["id", "firm", "title", "rate", "enabled"])
    df = df[["firm", "title", "rate", "enabled", "id"]]

    edited = st.data_editor(
        df,
        column_config={
            "firm": st.column_config.TextColumn("Firm", default=config.HOME_FIRM_NAME),
            "title": st.column_config.TextColumn("Role", default="New role"),
            "rate": st.column_config.NumberColumn("Rate ($/hr)", min_value=0.0, format="$%.0f", default=0.0),
            "enabled": st.column_config.CheckboxColumn("Enabled", default=True),
            "id": None,
        },
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key=f"roles_editor_{project['id']}",
    )

    new_roles = []
    existing_ids = {r["id"] for r in project["roles"]}
    kept_ids = set()
    for _, row in edited.iterrows():
        rid = row["id"] if isinstance(row.get("id"), str) and row["id"] in existing_ids else ps._new_id()
        kept_ids.add(rid)
        new_roles.append(
            {
                "id": rid,
                "firm": (row["firm"] or config.HOME_FIRM_NAME).strip(),
                "title": (row["title"] or "Untitled role").strip(),
                "rate": float(row["rate"] or 0),
                "enabled": bool(row["enabled"]) if pd.notna(row["enabled"]) else True,
            }
        )
    removed_ids = existing_ids - kept_ids
    if new_roles != project["roles"]:
        project["roles"] = new_roles
        if removed_ids:
            for phase in project["phases"]:
                for sub in phase["subtasks"]:
                    for rid in removed_ids:
                        sub["hours"].pop(rid, None)
        ps.save_project(project)


def _section_phases(project: dict):
    st.markdown("#### Phases")
    if st.button("+ Add phase", key=f"add_phase_{project['id']}"):
        project["phases"].append(
            {"id": ps._new_id(), "name": f"Phase {len(project['phases']) + 1}", "enabled": True, "note": "", "subtasks": []}
        )
        ps.save_project(project)
        st.rerun()

    if not project["phases"]:
        st.caption("No phases yet.")
        return

    comp = ps.compute_project(project)
    role_by_id = {r["id"]: r for r in project["roles"]}
    comp_phase_by_id = {ph["id"]: ph for ph in comp["phases"]}

    changed = False
    for i, phase in enumerate(project["phases"]):
        comp_phase = comp_phase_by_id[phase["id"]]
        header = f"{'✅' if phase['enabled'] else '⬜'} {phase['name']} -- {fmt_currency(comp_phase['cost'])} ({comp_phase['hours']:.0f} hrs)"
        with st.expander(header, expanded=False):
            top = st.columns([0.4, 3, 1, 1])
            with top[0]:
                en = st.checkbox("On", value=phase["enabled"], key=f"phase_en_{phase['id']}")
                if en != phase["enabled"]:
                    phase["enabled"] = en
                    changed = True
            with top[1]:
                nm = st.text_input("Name", value=phase["name"], key=f"phase_name_{phase['id']}", label_visibility="collapsed")
                if nm != phase["name"]:
                    phase["name"] = nm
                    changed = True
            with top[2]:
                if st.button("+ Subtask", key=f"add_sub_{phase['id']}"):
                    phase["subtasks"].append({"id": ps._new_id(), "name": "New line item", "enabled": True, "hours": {}})
                    changed = True
            with top[3]:
                if st.button("Delete phase", key=f"del_phase_{phase['id']}"):
                    project["phases"].pop(i)
                    ps.save_project(project)
                    st.rerun()

            note = st.text_input(
                "Timing / notes (optional)",
                value=phase.get("note", ""),
                key=f"phase_note_{phase['id']}",
                placeholder="e.g. Months 0-3",
                help="Shown alongside the phase name in both exports, the way Western U's budget noted phase timing.",
            )
            if note != phase.get("note", ""):
                phase["note"] = note
                changed = True

            if not phase["subtasks"]:
                st.caption("No line items in this phase.")
                continue

            role_ids = [r["id"] for r in project["roles"]]
            rows = []
            for sub in phase["subtasks"]:
                row = {"id": sub["id"], "Line item": sub["name"], "Enabled": sub["enabled"]}
                for rid in role_ids:
                    role = role_by_id[rid]
                    row[f"{role['firm']}: {role['title']}"] = sub["hours"].get(rid, 0.0)
                rows.append(row)
            sub_df = pd.DataFrame(rows)
            hour_cols = [c for c in sub_df.columns if c not in ("id", "Line item", "Enabled")]
            col_config = {
                "id": None,
                "Line item": st.column_config.TextColumn("Line item"),
                "Enabled": st.column_config.CheckboxColumn("Enabled"),
                **{c: st.column_config.NumberColumn(c, min_value=0.0, step=1.0) for c in hour_cols},
            }
            edited_sub = st.data_editor(
                sub_df,
                column_config=col_config,
                hide_index=True,
                use_container_width=True,
                key=f"sub_editor_{phase['id']}",
            )
            col_to_role = {f"{role_by_id[rid]['firm']}: {role_by_id[rid]['title']}": rid for rid in role_ids}
            new_subtasks = []
            for _, row in edited_sub.iterrows():
                hours = {col_to_role[c]: float(row[c] or 0) for c in hour_cols if pd.notna(row[c]) and float(row[c] or 0) != 0}
                new_subtasks.append(
                    {
                        "id": row["id"],
                        "name": row["Line item"] or "Untitled",
                        "enabled": bool(row["Enabled"]) if pd.notna(row["Enabled"]) else True,
                        "hours": hours,
                    }
                )
            if new_subtasks != phase["subtasks"]:
                phase["subtasks"] = new_subtasks
                changed = True

    if changed:
        ps.save_project(project)
        st.rerun()


def _section_expenses(project: dict):
    st.markdown("#### Direct expenses (optional)")
    st.caption("Flat costs per firm outside of labor -- materials, travel, printing, markup.")
    df = pd.DataFrame(project.get("expenses", []))
    if df.empty:
        df = pd.DataFrame(columns=["firm", "note", "amount"])
    edited = st.data_editor(
        df,
        column_config={
            "firm": st.column_config.TextColumn("Firm", default=config.HOME_FIRM_NAME),
            "note": st.column_config.TextColumn("Note", default=""),
            "amount": st.column_config.NumberColumn("Amount", min_value=0.0, format="$%.0f", default=0.0),
        },
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key=f"expenses_editor_{project['id']}",
    )
    new_expenses = [
        {"firm": (r["firm"] or config.HOME_FIRM_NAME).strip(), "note": r.get("note") or "", "amount": float(r["amount"] or 0)}
        for _, r in edited.iterrows()
    ]
    if new_expenses != project.get("expenses", []):
        project["expenses"] = new_expenses
        ps.save_project(project)


def _section_totals(project: dict):
    st.markdown("#### Total")
    comp = ps.compute_project(project)

    cards = [{"label": "Project total", "value": fmt_currency(comp["grand_total"])}]
    for firm, total in sorted(comp["firm_total"].items(), key=lambda kv: -kv[1]):
        cards.append({"label": f"{firm} total", "value": fmt_currency(total)})
    kpi_row(cards[:4])
    if len(cards) > 4:
        kpi_row(cards[4:8])

    if comp["firm_labor"]:
        import plotly.graph_objects as go

        from dashboard.charts.theme import apply_layout

        firms = list(comp["firm_total"].keys())
        fig = go.Figure()
        fig.add_bar(
            x=firms,
            y=[comp["firm_labor"].get(f, 0) for f in firms],
            name="Labor",
            marker_color=CATEGORICAL[0],
        )
        if comp["expense_total"]:
            fig.add_bar(
                x=firms,
                y=[comp["firm_expenses"].get(f, 0) for f in firms],
                name="Expenses",
                marker_color=CATEGORICAL[1],
            )
        fig.update_layout(barmode="stack")
        apply_layout(fig, title="Cost by firm")
        st.plotly_chart(fig, use_container_width=True)

    with st.expander("Phase breakdown"):
        rows = [
            {"Phase": p["name"], "Enabled": p["enabled"], "Hours": p["hours"], "Cost": p["cost"]}
            for p in comp["phases"]
        ]
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        else:
            st.caption("No phases yet.")

    st.markdown("##### Client-ready exports")
    st.caption(
        "A Somos-branded proposal built from the current state above -- cover page, rates, "
        "the phase/line-item budget grid, budget summary, and scope exclusions. Excluded "
        "items are shown struck through with their would-be cost, not hidden."
    )
    file_stub = project["project_name"].strip() or "project"
    dl_cols = st.columns(2)
    with dl_cols[0]:
        st.download_button(
            "⬇ Export Excel workbook (.xlsx)",
            data=pricing_export.build_workbook(project, comp),
            file_name=f"{file_stub}_proposal.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with dl_cols[1]:
        st.download_button(
            "⬇ Export PDF proposal (.pdf)",
            data=pricing_export.build_pdf(project, comp),
            file_name=f"{file_stub}_proposal.pdf",
            mime="application/pdf",
            use_container_width=True,
        )


def _section_combined_summary(active_projects: list[dict]):
    st.subheader("Combined summary (active projects)")
    if not active_projects:
        st.caption("No projects marked active.")
        return
    grand = 0.0
    firm_totals: dict[str, float] = {}
    for p in active_projects:
        comp = ps.compute_project(p)
        grand += comp["grand_total"]
        for firm, total in comp["firm_total"].items():
            firm_totals[firm] = firm_totals.get(firm, 0) + total

    kpi_row(
        [{"label": "Combined total", "value": fmt_currency(grand)}]
        + [{"label": f"{firm}", "value": fmt_currency(t)} for firm, t in sorted(firm_totals.items(), key=lambda kv: -kv[1])][:3]
    )
