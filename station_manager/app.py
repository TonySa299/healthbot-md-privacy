"""
Station Manager — a small Flask web application for running a two-branch
fuel-station business (Halba & Tekrit).

Features
--------
* Consolidated dashboard with KPIs, monthly trend and revenue mix.
* Per-station view: financials, fuel/oil/gas inventory.
* Daily cash-up ledger with an entry form (totals are computed server-side).
* Monthly report across both stations.

Run with::

    python app.py

then open http://127.0.0.1:5000
"""
import os

from flask import (
    Flask, render_template, request, redirect, url_for, flash, abort
)

from db import get_conn, init_db, DB_PATH
import analytics
from importer import run_import

app = Flask(__name__)
app.secret_key = "station-manager-local"

# Product income fields shown on the daily entry form.
INCOME_FIELDS = [
    ("b1_liters", "Benzine 1 litres"), ("b1_price", "Benzine 1 price"),
    ("b2_liters", "Benzine 2 litres"), ("b2_price", "Benzine 2 price"),
    ("mezout_liters", "Mezout litres"), ("mezout_price", "Mezout price"),
    ("oil", "Oil"), ("wash", "Wash"), ("gaz", "Gas"),
    ("fragrance", "Fragrance"), ("kiosk", "Kiosk"),
    ("payments", "Payments"), ("coupon_in", "Coupons in"),
]
PURCHASE_FIELDS = [
    ("purchase_oil", "Oil"), ("purchase_kiosk", "Kiosk"),
    ("purchase_gaz", "Gas"), ("other_purchases", "Other"),
]
EXPENSE_FIELDS = [
    ("rent", "Rent"), ("salaries", "Salaries"), ("repairs", "R&M"),
    ("utilities", "Utilities"), ("client_satisfaction", "Client satisf."),
    ("tips", "Tips"), ("new_assets", "New assets"), ("other_expense", "Other"),
]


def _station_by_name(conn, name):
    row = conn.execute(
        "SELECT id, name FROM stations WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if not row:
        abort(404)
    return row


@app.template_filter("money")
def money(value):
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return value


@app.template_filter("qty")
def qty(value):
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return value


@app.route("/")
def dashboard():
    conn = get_conn()
    overview = analytics.company_overview(conn)
    trend = analytics.monthly_trend(conn)
    return render_template("dashboard.html", overview=overview, trend=trend)


@app.route("/station/<name>")
def station(name):
    conn = get_conn()
    st = _station_by_name(conn, name)
    summary = analytics.station_summary(conn, st["id"])
    breakdown = analytics.revenue_breakdown(conn, st["id"])
    trend = analytics.monthly_trend(conn, st["id"])
    fuel = analytics.fuel_stock(conn, st["id"])
    gas = analytics.gas_position(conn, st["id"])
    oil = analytics.oil_value(conn, st["id"])
    return render_template(
        "station.html", st=st, s=summary, breakdown=breakdown,
        trend=trend, fuel=fuel, gas=gas, oil=oil,
    )


@app.route("/station/<name>/daily")
def daily(name):
    conn = get_conn()
    st = _station_by_name(conn, name)
    month = request.args.get("month", "")
    where = "WHERE station_id = ?"
    args = [st["id"]]
    if month:
        where += " AND substr(day,1,7) = ?"
        args.append(month)
    rows = conn.execute(
        f"""SELECT * FROM daily_records {where}
            ORDER BY day DESC, id DESC LIMIT 400""",
        args,
    ).fetchall()
    months = [r["m"] for r in conn.execute(
        "SELECT DISTINCT substr(day,1,7) AS m FROM daily_records "
        "WHERE station_id=? ORDER BY m DESC", (st["id"],))]
    return render_template("daily.html", st=st, rows=rows,
                           months=months, month=month)


@app.route("/station/<name>/daily/new", methods=["GET", "POST"])
def daily_new(name):
    conn = get_conn()
    st = _station_by_name(conn, name)

    if request.method == "POST":
        f = request.form

        def g(field):
            try:
                return float(f.get(field) or 0)
            except ValueError:
                return 0.0

        vals = {field: g(field) for field, _ in
                INCOME_FIELDS + PURCHASE_FIELDS + EXPENSE_FIELDS}

        # Derived totals (kept consistent with the spreadsheet's own formulas).
        vals["b1_total"] = vals["b1_liters"] * vals["b1_price"]
        vals["b2_total"] = vals["b2_liters"] * vals["b2_price"]
        vals["benzine_liters"] = vals["b1_liters"] + vals["b2_liters"]
        vals["benzine_total"] = vals["b1_total"] + vals["b2_total"]
        vals["mezout_total"] = vals["mezout_liters"] * vals["mezout_price"]
        vals["total_in"] = (
            vals["benzine_total"] + vals["mezout_total"] + vals["oil"]
            + vals["wash"] + vals["gaz"] + vals["fragrance"] + vals["kiosk"]
            + vals["payments"] + vals["coupon_in"]
        )
        vals["total_purchases"] = (
            vals["purchase_oil"] + vals["purchase_kiosk"]
            + vals["purchase_gaz"] + vals["other_purchases"]
        )
        vals["total_expense"] = sum(vals[fld] for fld, _ in EXPENSE_FIELDS)
        vals["profit_sharing"] = g("profit_sharing")
        vals["total_out"] = (
            vals["total_purchases"] + vals["total_expense"]
            + vals["profit_sharing"] + g("debts")
        )
        vals["debts"] = g("debts")
        vals["daily_total"] = vals["total_in"] - vals["total_out"]

        vals["station_id"] = st["id"]
        vals["day"] = f.get("day")
        vals["notes"] = f.get("notes") or None
        vals["price_note"] = f.get("price_note") or None

        if not vals["day"]:
            flash("Date is required.", "error")
            return redirect(url_for("daily_new", name=name))

        cols = list(vals.keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        try:
            conn.execute(
                f"INSERT INTO daily_records ({', '.join(cols)}) "
                f"VALUES ({placeholders})", vals)
            conn.commit()
            flash(f"Saved daily record for {vals['day']}.", "success")
            return redirect(url_for("daily", name=name))
        except Exception as exc:  # pragma: no cover
            flash(f"Could not save: {exc}", "error")

    return render_template(
        "daily_new.html", st=st,
        income_fields=INCOME_FIELDS, purchase_fields=PURCHASE_FIELDS,
        expense_fields=EXPENSE_FIELDS,
    )


@app.route("/station/<name>/inventory")
def inventory(name):
    conn = get_conn()
    st = _station_by_name(conn, name)
    fuel = analytics.fuel_stock(conn, st["id"])
    oil = conn.execute(
        """SELECT item, price, current, sold, restock, value
           FROM oil_stock WHERE station_id = ? ORDER BY value DESC, item""",
        (st["id"],)).fetchall()
    deliveries = conn.execute(
        """SELECT day, benzine1, benzine2, backup, mezout, price, total
           FROM fuel_deliveries WHERE station_id = ?
           ORDER BY day DESC LIMIT 60""", (st["id"],)).fetchall()
    gas = analytics.gas_position(conn, st["id"])
    return render_template("inventory.html", st=st, fuel=fuel, oil=oil,
                           deliveries=deliveries, gas=gas)


@app.route("/reports")
def reports():
    conn = get_conn()
    stations = conn.execute("SELECT id, name FROM stations ORDER BY name").fetchall()
    data = {}
    for s in stations:
        data[s["name"]] = {m["month"]: m for m in analytics.monthly_trend(conn, s["id"])}
    all_months = sorted({m for st in data.values() for m in st}, reverse=True)
    return render_template("reports.html", stations=stations, data=data,
                           months=all_months)


@app.route("/reimport", methods=["POST"])
def reimport():
    run_import(verbose=False)
    flash("Workbook re-imported from data/General_Cashflow.xlsx.", "success")
    return redirect(url_for("dashboard"))


@app.context_processor
def inject_nav():
    conn = get_conn()
    stations = conn.execute("SELECT name FROM stations ORDER BY name").fetchall()
    return {"nav_stations": [s["name"] for s in stations]}


def ensure_data():
    """Create the DB and import the workbook on first run."""
    first_run = not os.path.exists(DB_PATH)
    init_db()
    conn = get_conn()
    has_rows = conn.execute("SELECT COUNT(*) c FROM daily_records").fetchone()["c"]
    if first_run or not has_rows:
        try:
            run_import(verbose=False)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    ensure_data()
    app.run(host="127.0.0.1", port=5000, debug=True)
