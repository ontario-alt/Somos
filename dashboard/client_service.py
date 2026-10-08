"""
Client service hours: the pool of hours the firm delivered to clients in a
measuring period, by who delivered them (Group 1 / Group 2 timekeepers,
departed timekeepers, owners, contractors, other staff) and by client type.

Built from the labor detail export only -- the summary exports have no
matter, so neither split is possible from them.

Client type: until a matter -> client type mapping is supplied
(reference/matter_clients.csv: matter_code, client, client_type), the type
is the practice the matter belongs to -- Law (LLP) or Advisory (LLC) -- read
from the matter number, with pro bono and Firm's Own Account separate.
"""
from __future__ import annotations

import re

import pandas as pd

import config
from dashboard.data import query, table_exists

# Who delivered the hours. Requirement holders go by their group; everyone
# else by staff_group in employee_targets.csv (first match wins).
POOL_ORDER = ["Group 1 — Attorneys", "Group 2 — Professional staff", "Departed timekeepers", "Owners",
              "Contractors", "Advisory", "Interns / externs", "Somos MX", "Administrative", "Other staff"]
_STAFF_GROUP_POOL = {"owner": "Owners", "contractor": "Contractors", "advisory": "Advisory",
                     "intern/extern": "Interns / externs", "somos mx": "Somos MX", "administrative": "Administrative"}
_ROLE_POOL = {"Attorney": "Group 1 — Attorneys", "Planner": "Group 2 — Professional staff",
              "Custom": "Group 2 — Professional staff"}

CLIENT_TYPE_ORDER = ["Law (LLP) clients", "Advisory (LLC) clients", "Somos MX clients", "Pro bono",
                     "Firm's Own Account", "Other client work"]
_ENTITY_TYPE = {"Somos Law Group LLP": "Law (LLP) clients", "Somos Group LLC": "Advisory (LLC) clients",
                "Somos Group Mexico": "Somos MX clients"}
# Client service = time on client matters (incl. pro bono) and Firm's Own Account.
_SERVICE_CATEGORIES = ("client", "pro_bono", "foa")


def _staff_pool(staff_group) -> str | None:
    for part in re.split(r"[;,]", staff_group) if isinstance(staff_group, str) else []:
        pool = _STAFF_GROUP_POOL.get(part.strip().lower())
        if pool:
            return pool
    return None


def _matter_clients() -> pd.DataFrame | None:
    path = config.REFERENCE_DIR / "matter_clients.csv"
    if not path.exists():
        return None
    m = pd.read_csv(path, dtype=str).rename(columns=str.strip)
    if "matter_code" not in m or "client_type" not in m:
        return None
    m["matter_code"] = m["matter_code"].str.strip()
    return m.drop_duplicates("matter_code")


def service_entries(people: pd.DataFrame, fy_start, fy_end) -> pd.DataFrame | None:
    """Client service hours by person x day x matter, with pool group and
    client type. None when there's no labor detail for the period."""
    if not table_exists("labor_detail"):
        return None
    e = query(
        "SELECT name_key, ANY_VALUE(employee_name) AS employee_name, transaction_date, matter_code, "
        "ANY_VALUE(matter_name) AS matter_name, ANY_VALUE(entity) AS entity, hours_category, "
        "SUM(hours) AS hours, SUM(COALESCE(standard_value, 0)) AS value "
        "FROM labor_detail WHERE transaction_date BETWEEN ? AND ? AND hours_category IN ('client', 'pro_bono', 'foa') "
        "GROUP BY name_key, transaction_date, matter_code, hours_category",
        [fy_start, fy_end])
    if e.empty:
        return None
    e["transaction_date"] = pd.to_datetime(e["transaction_date"])
    # Billing value counts client matters only -- pro bono time isn't billed.
    e["value"] = e["value"].where(e["hours_category"] == "client", 0.0)
    p = people.drop_duplicates("name_key").set_index("name_key")
    e["Timekeeper"] = e["name_key"].map(p["full_name"]).fillna(e["employee_name"])
    role = e["name_key"].map(p["role"]) if "role" in p else pd.Series(None, index=e.index)
    start = pd.to_datetime(e["name_key"].map(p["start_date"]), errors="coerce")
    end = pd.to_datetime(e["name_key"].map(p["end_date"]), errors="coerce")
    staff = e["name_key"].map(p["staff_group"]) if "staff_group" in p else pd.Series(None, index=e.index)
    staff_pool = staff.map(_staff_pool)

    pool = role.map(_ROLE_POOL)
    # Departed requirement holders form their own group.
    pool = pool.where(~(pool.notna() & end.notna() & (end < pd.Timestamp(fy_end))), "Departed timekeepers")
    # Time before a requirement holder's start date (e.g. as a contractor) goes to their staff group.
    before = pool.notna() & start.notna() & (e["transaction_date"] < start)
    pool = pool.where(~before, staff_pool.fillna("Other staff"))
    e["Pool"] = pool.fillna(staff_pool).fillna("Other staff")

    ctype = e["entity"].map(_ENTITY_TYPE).fillna("Other client work")
    ctype = ctype.where(e["hours_category"] != "pro_bono", "Pro bono")
    ctype = ctype.where(e["hours_category"] != "foa", "Firm's Own Account")
    e["Client Type"] = ctype
    mc = _matter_clients()
    if mc is not None:
        mapped = e["matter_code"].map(mc.set_index("matter_code")["client_type"])
        # Pro bono and FOA keep their own type; a mapping refines client matters.
        e["Client Type"] = mapped.where(mapped.notna() & (e["hours_category"] == "client"), e["Client Type"])
        if "client" in mc:
            e["Client"] = e["matter_code"].map(mc.set_index("matter_code")["client"])
    return e


def client_type_order(e: pd.DataFrame) -> list[str]:
    known = [t for t in CLIENT_TYPE_ORDER if t in set(e["Client Type"])]
    return [t for t in e.groupby("Client Type")["hours"].sum().sort_values(ascending=False).index
            if t not in CLIENT_TYPE_ORDER] + known


def pool_summary(e: pd.DataFrame) -> pd.DataFrame:
    """Hours by pool group x client type, plus totals and share."""
    t = e.pivot_table(index="Pool", columns="Client Type", values="hours", aggfunc="sum", fill_value=0.0)
    t = t[[c for c in client_type_order(e) if c in t.columns]]
    t["Client Service Hours"] = t.sum(axis=1)
    t["People"] = e.groupby("Pool")["name_key"].nunique()
    t["Share of Pool %"] = t["Client Service Hours"] / t["Client Service Hours"].sum() * 100
    t["Billing Value"] = e.groupby("Pool")["value"].sum()
    t = t.reindex([g for g in POOL_ORDER if g in t.index] + [g for g in t.index if g not in POOL_ORDER])
    return t.reset_index()


def by_timekeeper(e: pd.DataFrame, min_hours: float = 0.0) -> pd.DataFrame:
    """Hours by timekeeper x client type (a person can appear in two pools,
    e.g. Brian Kim as a contractor before 7/1 and Group 1 after)."""
    t = e.pivot_table(index=["Timekeeper", "Pool"], columns="Client Type", values="hours", aggfunc="sum", fill_value=0.0)
    t = t[[c for c in client_type_order(e) if c in t.columns]]
    t["Client Service Hours"] = t.sum(axis=1)
    t = t[t["Client Service Hours"] >= min_hours].reset_index()
    t["_pool_rank"] = t["Pool"].map({g: i for i, g in enumerate(POOL_ORDER)}).fillna(len(POOL_ORDER))
    return t.sort_values(["_pool_rank", "Client Service Hours"], ascending=[True, False]).drop(columns="_pool_rank")


def insights(e: pd.DataFrame, sc: pd.DataFrame | None, fy_start, fy_end) -> list[str]:
    """Plain-language observations for leadership, computed from the data."""
    out = []
    total = e["hours"].sum()
    if total <= 0:
        return out
    by_pool = e.groupby("Pool")["hours"].sum()
    req = by_pool.reindex(["Group 1 — Attorneys", "Group 2 — Professional staff", "Departed timekeepers"]).fillna(0).sum()
    out.append(
        f"The firm delivered {total:,.0f} client service hours. Timekeepers with an hours requirement (including "
        f"departed) delivered {req / total * 100:.0f}%; owners {by_pool.get('Owners', 0) / total * 100:.0f}%; "
        f"contractors {by_pool.get('Contractors', 0) / total * 100:.0f}% ({by_pool.get('Contractors', 0):,.0f} hrs)."
    )
    ct = e.groupby("Client Type")["hours"].sum().sort_values(ascending=False)
    out.append("Client mix: " + ", ".join(f"{k} {v / total * 100:.0f}%" for k, v in ct.items() if v / total >= 0.005) + ".")

    client = e[e["hours_category"] == "client"]
    if not client.empty:
        m = client.groupby(["matter_code", "matter_name"])["hours"].sum().sort_values(ascending=False)
        top10 = m.head(10).sum() / m.sum() * 100
        out.append(
            f"{len(m)} client matters had time. The 10 largest took {top10:.0f}% of client hours; the largest, "
            f"{m.index[0][1]} ({m.index[0][0]}), took {m.iloc[0]:,.0f} hrs ({m.iloc[0] / m.sum() * 100:.0f}%).")
        rate = client.groupby("Client Type").apply(lambda g: g["value"].sum() / g["hours"].sum() if g["hours"].sum() else None)
        rate = rate.dropna()
        if len(rate) > 1:
            out.append("Billing value per client hour (at standard rates, before write-downs): "
                       + ", ".join(f"{k} ${v:,.0f}" for k, v in rate.sort_values(ascending=False).items()) + ".")
        # People working across both practices.
        reqs = client[client["Pool"].isin(["Group 1 — Attorneys", "Group 2 — Professional staff"])]
        mix = reqs.pivot_table(index="Timekeeper", columns="Client Type", values="hours", aggfunc="sum", fill_value=0)
        if {"Law (LLP) clients", "Advisory (LLC) clients"} <= set(mix.columns):
            share = mix[["Law (LLP) clients", "Advisory (LLC) clients"]].min(axis=1) / mix.sum(axis=1)
            cross = share[share >= 0.2].sort_values(ascending=False)
            if not cross.empty:
                out.append("Working across both practices (at least 20% of client hours in each): "
                           + ", ".join(f"{n} ({v * 100:.0f}% in the smaller)" for n, v in cross.items()) + ".")
        monthly = client.groupby(client["transaction_date"].dt.to_period("M"))["hours"].sum()
        if len(monthly) >= 3:
            out.append(f"Client hours peaked in {monthly.idxmax().strftime('%B %Y')} ({monthly.max():,.0f}) and were "
                       f"lowest in {monthly.idxmin().strftime('%B %Y')} ({monthly.min():,.0f}).")
    pb = e[e["hours_category"] == "pro_bono"].groupby("Timekeeper")["hours"].sum().sort_values(ascending=False)
    if not pb.empty:
        out.append(f"Pro bono: {pb.sum():,.0f} hrs ({pb.sum() / total * 100:.0f}% of client service), led by "
                   + ", ".join(f"{n} ({v:,.0f})" for n, v in pb.head(3).items()) + ".")
    if sc is not None and not sc.empty:
        cur = sc[sc.get("Employment", pd.Series("Current", index=sc.index)) == "Current"]
        short = (cur["Expectation"] - cur["Credited Hours"]).clip(lower=0)
        if short.sum() > 0:
            fte = short.sum() / config.BILLABLE_HOUR_TARGETS["Attorney"]
            out.append(f"Unused capacity: current timekeepers finished {short.sum():,.0f} credited hours short of their "
                       f"prorated expectations combined (about {fte:.1f} full-time Group 1 timekeepers' worth); "
                       f"{int((short > 0).sum())} of {len(cur)} were short.")
        over = sc["Creditable NB (over cap)"].sum() if "Creditable NB (over cap)" in sc else 0
        if over > 0:
            out.append(f"{over:,.0f} creditable non-billable hours were logged beyond the {config.CREDITABLE_NB_CAP}-hour "
                       f"cap and earned no credit.")
    return out
