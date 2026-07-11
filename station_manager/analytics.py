"""
Business analytics computed from the imported data.

All figures are derived from the ``daily_records`` and inventory tables, so the
dashboard stays consistent with whatever has been entered or imported.
"""
from db import get_conn


def _stations(conn):
    return {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM stations")}


def station_summary(conn, station_id):
    """Headline financials for a single station."""
    row = conn.execute(
        """
        SELECT
            COUNT(*)                          AS days,
            MIN(day)                          AS first_day,
            MAX(day)                          AS last_day,
            COALESCE(SUM(benzine_total),0)    AS benzine_rev,
            COALESCE(SUM(mezout_total),0)     AS mezout_rev,
            COALESCE(SUM(oil),0)              AS oil_rev,
            COALESCE(SUM(wash),0)             AS wash_rev,
            COALESCE(SUM(gaz),0)              AS gaz_rev,
            COALESCE(SUM(kiosk),0)            AS kiosk_rev,
            COALESCE(SUM(fragrance),0)        AS fragrance_rev,
            COALESCE(SUM(total_in),0)         AS total_in,
            COALESCE(SUM(total_purchases),0)  AS purchases,
            COALESCE(SUM(total_expense),0)    AS expenses,
            COALESCE(SUM(profit_sharing),0)   AS profit_sharing,
            COALESCE(SUM(total_out),0)        AS total_out,
            COALESCE(SUM(daily_total),0)      AS net,
            COALESCE(SUM(b1_liters),0)        AS b1_liters,
            COALESCE(SUM(b2_liters),0)        AS b2_liters,
            COALESCE(SUM(mezout_liters),0)    AS mezout_liters,
            COALESCE(SUM(debts),0)            AS debts
        FROM daily_records WHERE station_id = ?
        """,
        (station_id,),
    ).fetchone()
    return dict(row)


def revenue_breakdown(conn, station_id):
    """Revenue by product line, largest first."""
    s = station_summary(conn, station_id)
    parts = [
        ("Benzine", s["benzine_rev"]),
        ("Mezout", s["mezout_rev"]),
        ("Kiosk", s["kiosk_rev"]),
        ("Gas", s["gaz_rev"]),
        ("Oil", s["oil_rev"]),
        ("Wash", s["wash_rev"]),
        ("Fragrance", s["fragrance_rev"]),
    ]
    parts = [(name, val) for name, val in parts if val]
    parts.sort(key=lambda x: x[1], reverse=True)
    total = sum(v for _, v in parts) or 1
    return [(name, val, 100 * val / total) for name, val in parts]


def monthly_trend(conn, station_id=None):
    """Net cash result grouped by calendar month."""
    where = "" if station_id is None else "WHERE station_id = ?"
    args = () if station_id is None else (station_id,)
    rows = conn.execute(
        f"""
        SELECT substr(day, 1, 7) AS month,
               COALESCE(SUM(total_in),0)      AS income,
               COALESCE(SUM(total_out),0)     AS out,
               COALESCE(SUM(daily_total),0)   AS net
        FROM daily_records {where}
        GROUP BY month ORDER BY month
        """,
        args,
    ).fetchall()
    return [dict(r) for r in rows]


def fuel_stock(conn, station_id):
    rows = conn.execute(
        """SELECT fuel_type, initial, total_out, total_in, current
           FROM fuel_stock WHERE station_id = ? ORDER BY id""",
        (station_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def gas_position(conn, station_id):
    row = conn.execute(
        """SELECT COALESCE(SUM(restock),0) AS restocked,
                  COALESCE(SUM(sold),0)     AS sold
           FROM gas_records WHERE station_id = ?""",
        (station_id,),
    ).fetchone()
    on_hand = row["restocked"] - row["sold"]
    return {"restocked": row["restocked"], "sold": row["sold"], "on_hand": on_hand}


def oil_value(conn, station_id):
    row = conn.execute(
        """SELECT COALESCE(SUM(value),0) AS value,
                  COALESCE(SUM(sold),0)  AS sold
           FROM oil_stock WHERE station_id = ?""",
        (station_id,),
    ).fetchone()
    return dict(row)


def cost_of_stock(conn, station_id):
    """Total money spent restocking fuel = sum of every delivery's cost."""
    row = conn.execute(
        "SELECT COALESCE(SUM(total),0) AS c FROM fuel_deliveries WHERE station_id = ?",
        (station_id,),
    ).fetchone()
    return row["c"]


def latest_odometer(conn, station_id):
    """The most recent odometer reading for a station (baseline for the next day)."""
    row = conn.execute(
        """SELECT * FROM odometer_readings WHERE station_id = ?
           ORDER BY id DESC LIMIT 1""",
        (station_id,),
    ).fetchone()
    return dict(row) if row else None


def fuel_margin(conn, station_id):
    """Fuel revenue vs. what fuel restocking cost (a gross-margin indicator)."""
    s = station_summary(conn, station_id)
    fuel_rev = s["benzine_rev"] + s["mezout_rev"]
    cost = cost_of_stock(conn, station_id)
    return {"revenue": fuel_rev, "cost": cost, "margin": fuel_rev - cost}


def company_overview(conn):
    """Consolidated numbers across all stations for the dashboard."""
    stations = _stations(conn)
    per_station = {}
    totals = {"total_in": 0, "purchases": 0, "expenses": 0, "net": 0, "days": 0}
    totals["cost_of_stock"] = 0
    for sid, name in stations.items():
        s = station_summary(conn, sid)
        s["gas"] = gas_position(conn, sid)
        s["oil"] = oil_value(conn, sid)
        s["fuel_stock"] = fuel_stock(conn, sid)
        s["cost_of_stock"] = cost_of_stock(conn, sid)
        per_station[name] = {"id": sid, **s}
        for k in ("total_in", "purchases", "expenses", "net", "days"):
            totals[k] += s.get(k, 0) or 0
        totals["cost_of_stock"] += s["cost_of_stock"]
    return {"stations": per_station, "totals": totals}


if __name__ == "__main__":
    conn = get_conn()
    ov = company_overview(conn)
    print("=== Consolidated ===")
    for k, v in ov["totals"].items():
        print(f"  {k:12}: {v:,.2f}" if isinstance(v, float) else f"  {k:12}: {v}")
    for name, s in ov["stations"].items():
        print(f"\n=== {name} ===")
        print(f"  Days      : {s['days']} ({s['first_day']} -> {s['last_day']})")
        print(f"  Net In    : {s['total_in']:,.2f}")
        print(f"  Purchases : {s['purchases']:,.2f}")
        print(f"  Expenses  : {s['expenses']:,.2f}")
        print(f"  Net result: {s['net']:,.2f}")
        print(f"  Fuel litres sold: B1={s['b1_liters']:,.0f} "
              f"B2={s['b2_liters']:,.0f} Mezout={s['mezout_liters']:,.0f}")
