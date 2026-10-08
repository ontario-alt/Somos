"""
Client concentration, sources of creditable non-billable time, seasonality
of client hours, and LLP operating economics for a measuring period --
all from the labor detail export (FY history for seasonality comes from the
firm's monthly hours workbooks).

"Client" is the matter until a matter -> client mapping is supplied
(reference/matter_clients.csv, column `client`): the labor export carries
no client field, and general matters (e.g. "General Advisory") are separate
engagements under different clients.
"""
from __future__ import annotations

import pandas as pd

import config
from dashboard.client_service import _matter_clients
from dashboard.data import query, table_exists

ENTITY_SHORT = {"Somos Law Group LLP": "LLP", "Somos Group LLC": "LLC", "Somos Group Mexico": "Somos MX"}


def _entries(fy_start, fy_end) -> pd.DataFrame:
    e = query("SELECT * FROM labor_detail WHERE transaction_date BETWEEN ? AND ?", [fy_start, fy_end])
    e["transaction_date"] = pd.to_datetime(e["transaction_date"])
    e["Entity"] = e["entity"].map(ENTITY_SHORT).fillna("Other")
    return e


# ---------------------------------------------------------------------------
# Concentration
# ---------------------------------------------------------------------------
def concentration(fy_start, fy_end, top_n: int = 10) -> tuple[pd.DataFrame, dict] | None:
    """(top clients table, summary metrics) by client hours, with billing value."""
    if not table_exists("labor_detail"):
        return None
    e = _entries(fy_start, fy_end)
    cl = e[e["hours_category"] == "client"].copy()
    if cl.empty:
        return None
    mc = _matter_clients()
    if mc is not None and "client" in mc:
        cl["Client"] = cl["matter_code"].map(mc.set_index("matter_code")["client"]).fillna(cl["matter_name"])
        by_client = True
    else:
        cl["Client"] = cl["matter_name"] + " (" + cl["matter_code"] + ")"
        by_client = False
    lead = (cl.groupby(["Client", "employee_name"])["hours"].sum().reset_index()
            .sort_values("hours", ascending=False).drop_duplicates("Client").set_index("Client"))
    end = pd.Timestamp(fy_end)
    t = cl.groupby("Client").agg(
        Entity=("Entity", lambda s: "/".join(sorted(set(s)))), Hours=("hours", "sum"),
        Value=("standard_value", "sum"), Matters=("matter_code", "nunique"), People=("name_key", "nunique"),
        First=("transaction_date", "min"), Last=("transaction_date", "max"),
        Last_Qtr=("hours", lambda s: s[cl.loc[s.index, "transaction_date"] > end - pd.Timedelta(days=91)].sum()),
    ).sort_values("Hours", ascending=False)
    total_h, total_v = t["Hours"].sum(), t["Value"].sum()
    t["Share of Hours %"] = t["Hours"] / total_h * 100
    t["Cumulative %"] = t["Share of Hours %"].cumsum()
    t["Share of Value %"] = t["Value"] / total_v * 100 if total_v else None
    t["Lead Timekeeper"] = lead["employee_name"]
    t["Lead Share %"] = lead["hours"] / t["Hours"] * 100
    # Run rate in the last quarter vs. the period average (1.0 = steady; ~0 = winding down).
    t["Last-Quarter Pace"] = t["Last_Qtr"] / (t["Hours"] / 4)
    shares = t["Hours"] / total_h
    vshares = t["Value"] / total_v if total_v else shares * 0
    metrics = {
        "by_client": by_client, "clients": len(t), "client_hours": total_h, "value": total_v,
        "top1": shares.iloc[0] * 100, "top5": shares.head(5).sum() * 100, "top10": shares.head(10).sum() * 100,
        "top10_value": vshares.sort_values(ascending=False).head(10).sum() * 100,
        "hhi": (shares ** 2).sum() * 10000,
        "to50": int((t["Cumulative %"] < 50).sum() + 1), "to80": int((t["Cumulative %"] < 80).sum() + 1),
        "winding_down": t.head(top_n)[t.head(top_n)["Last-Quarter Pace"] < 0.25].index.tolist(),
        "key_person": t.head(top_n)[t.head(top_n)["Lead Share %"] >= 50].index.tolist(),
    }
    out = t.head(top_n).reset_index()
    out.insert(0, "Rank", range(1, len(out) + 1))
    return out.drop(columns=["Last_Qtr"]), metrics


# ---------------------------------------------------------------------------
# Creditable non-billable sources
# ---------------------------------------------------------------------------
def creditable_sources(fy_start, fy_end, sc: pd.DataFrame | None, people: pd.DataFrame) -> dict | None:
    if not table_exists("labor_detail"):
        return None
    e = _entries(fy_start, fy_end)
    cr = e[e["hours_category"] == "creditable"]
    if cr.empty:
        return None
    by_activity = cr.pivot_table(index="matter_name", columns="Entity", values="hours", aggfunc="sum", fill_value=0.0)
    by_activity["Total"] = by_activity.sum(axis=1)
    by_activity = by_activity.sort_values("Total", ascending=False).reset_index().rename(columns={"matter_name": "Activity"})
    pk = people.drop_duplicates("name_key").set_index("name_key")
    who = cr.groupby("name_key").agg(Hours=("hours", "sum")).reset_index()
    who["Timekeeper"] = who["name_key"].map(pk["full_name"]).fillna(
        who["name_key"].map(cr.groupby("name_key")["employee_name"].first()))
    top_act = cr.groupby(["name_key", "matter_name"])["hours"].sum().reset_index().sort_values("hours", ascending=False)
    who["Main Activity"] = who["name_key"].map(top_act.drop_duplicates("name_key").set_index("name_key")["matter_name"])
    scored = sc.set_index("name_key") if sc is not None and not sc.empty else pd.DataFrame()
    who["Has Requirement"] = who["name_key"].isin(scored.index)
    who["Counted"] = who["name_key"].map(scored["Creditable NB (counted)"]) if not scored.empty else None
    who["Over Cap"] = who["name_key"].map(scored["Creditable NB (over cap)"]) if not scored.empty else None
    who = who.sort_values("Hours", ascending=False)
    monthly = cr.groupby([cr["transaction_date"].dt.to_period("M").dt.to_timestamp(), "matter_name"])["hours"].sum().reset_index()
    return {"by_activity": by_activity, "by_person": who.drop(columns="name_key"), "monthly": monthly,
            "total": cr["hours"].sum(), "by_entity": cr.groupby("Entity")["hours"].sum()}


# ---------------------------------------------------------------------------
# Seasonality
# ---------------------------------------------------------------------------
def _workdays(month: pd.Timestamp) -> int:
    return len(pd.bdate_range(month, month + pd.offsets.MonthEnd(0)))


def seasonality(fy_start, fy_end, people: pd.DataFrame) -> dict | None:
    """FY monthly client hours by practice, per workday and per active
    timekeeper; PTO by month; day-of-week; and a multi-year comparison of
    billable hours per requirement holder per workday (workbook history +
    this period's labor detail)."""
    if not table_exists("labor_detail"):
        return None
    e = _entries(fy_start, fy_end)
    e["Month"] = e["transaction_date"].dt.to_period("M").dt.to_timestamp()
    cl = e[e["hours_category"] == "client"]
    if cl.empty:
        return None
    by_practice = cl.pivot_table(index="Month", columns="Entity", values="hours", aggfunc="sum", fill_value=0.0)
    m = pd.DataFrame({"Client Hours": cl.groupby("Month")["hours"].sum(),
                      "Active Timekeepers": cl.groupby("Month")["name_key"].nunique(),
                      "PTO / Holiday": e[e["hours_category"] == "time_off"].groupby("Month")["hours"].sum()}).fillna(0.0)
    m["Workdays"] = [_workdays(x) for x in m.index]
    m["Per Workday"] = m["Client Hours"] / m["Workdays"]
    m["Per Timekeeper"] = m["Client Hours"] / m["Active Timekeepers"]
    dow = cl.groupby(cl["transaction_date"].dt.dayofweek)["hours"].sum()
    dow.index = dow.index.map(dict(enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])))

    # Multi-year: billable hours per requirement holder per workday, by fiscal month.
    years = []
    req = set(people.loc[people["role"].notna(), "name_key"]) if "role" in people else set()
    if table_exists("monthly_hours"):
        wb = query("SELECT name_key, month, billable_to_clients AS h FROM monthly_hours")
        wb["month"] = pd.to_datetime(wb["month"])
        wb = wb[wb["month"] < pd.Timestamp(fy_start)]
        if not wb.empty:
            years.append(wb)
    pk = people.drop_duplicates("name_key").set_index("name_key")
    start = pd.to_datetime(cl["name_key"].map(pk["start_date"]), errors="coerce")
    end = pd.to_datetime(cl["name_key"].map(pk["end_date"]), errors="coerce")
    in_role = cl["name_key"].isin(req) & ~(start.notna() & (cl["transaction_date"] < start)) \
        & ~(end.notna() & (cl["transaction_date"] > end))
    cur = cl[in_role].groupby(["name_key", "Month"])["hours"].sum().reset_index()
    years.append(cur.rename(columns={"Month": "month", "hours": "h"}))
    hist = pd.concat(years, ignore_index=True)
    hist = hist[hist["h"] > 0]
    hist["FY"] = hist["month"].map(lambda d: f"FY{(d.year + 1) if d.month >= config.FISCAL_YEAR_START_MONTH else d.year}")
    g = hist.groupby(["FY", "month"]).agg(h=("h", "sum"), n=("name_key", "nunique")).reset_index()
    g["Workdays"] = g["month"].map(_workdays)
    g["Per Timekeeper per Workday"] = g["h"] / g["n"] / g["Workdays"]
    g["Fiscal Month"] = g["month"].dt.strftime("%b")
    g["fm"] = (g["month"].dt.month - config.FISCAL_YEAR_START_MONTH) % 12
    return {"monthly": m.reset_index(), "by_practice": by_practice.reset_index(), "dow": dow,
            "history": g.sort_values(["FY", "fm"])}


# ---------------------------------------------------------------------------
# LLP economics
# ---------------------------------------------------------------------------
def llp_economics(service: pd.DataFrame, sc: pd.DataFrame | None, fy_start, fy_end,
                  people: pd.DataFrame | None = None) -> dict | None:
    """Who delivers LLP client hours and at what billing value per hour; how
    Group 1 attorneys spend their time; staffing breadth on LLP matters."""
    llp = service[service["Client Type"] == "Law (LLP) clients"]
    if llp.empty:
        return None
    by_pool = llp.groupby("Pool").agg(Hours=("hours", "sum"), Value=("value", "sum"), People=("name_key", "nunique"))
    by_pool["Value / Hour"] = by_pool["Value"] / by_pool["Hours"]
    by_pool["Share of LLP Hours %"] = by_pool["Hours"] / by_pool["Hours"].sum() * 100
    by_pool = by_pool.sort_values("Hours", ascending=False).reset_index()

    by_tk = llp.groupby(["Timekeeper", "Pool"]).agg(Hours=("hours", "sum"), Value=("value", "sum")).reset_index()
    by_tk["Value / Hour"] = by_tk["Value"] / by_tk["Hours"]
    by_tk = by_tk[by_tk["Hours"] >= 50].sort_values("Hours", ascending=False)

    e = _entries(fy_start, fy_end)
    g1 = set(sc.loc[(sc["Role"] == "Attorney") & (sc.get("Employment", "Current") == "Current"), "name_key"]) \
        if sc is not None and not sc.empty else set()
    att = e[e["name_key"].isin(g1)]
    if people is not None:  # only time while in Group 1 (e.g. not as a contractor before a start date)
        start = pd.to_datetime(att["name_key"].map(people.drop_duplicates("name_key").set_index("name_key")["start_date"]),
                               errors="coerce")
        att = att[~(start.notna() & (att["transaction_date"] < start))]
    labels = {"client": "Client", "pro_bono": "Pro bono", "creditable": "Creditable NB", "other": "Other NB",
              "time_off": "PTO / holiday", "leave": "Leave", "foa": "Firm's Own Account"}
    mix = att.groupby(att["hours_category"].map(labels))["hours"].sum().sort_values(ascending=False)
    other = att[att["hours_category"] == "other"].groupby("matter_name")["hours"].sum().sort_values(ascending=False)

    mat = llp[llp["hours_category"] == "client"].groupby(["matter_code", "matter_name"]).agg(
        Hours=("hours", "sum"), People=("name_key", "nunique"), Value=("value", "sum")).reset_index()
    mat["Hours / Person"] = mat["Hours"] / mat["People"]
    small = mat[mat["Hours"] < 20]
    return {"by_pool": by_pool, "by_timekeeper": by_tk, "g1_mix": mix, "g1_other": other,
            "matters": mat.sort_values("People", ascending=False), "n_matters": len(mat),
            "small_matters": len(small), "small_hours": small["Hours"].sum(),
            "g1_count": len(g1)}
