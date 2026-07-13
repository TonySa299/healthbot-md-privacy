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

from db import get_conn, init_db, DB_PATH, resource_path
import analytics
from importer import run_import

# Explicit template/static paths so the app also works when packaged as a
# single .exe (PyInstaller unpacks these into a temporary bundle folder).
app = Flask(__name__,
            template_folder=resource_path("templates"),
            static_folder=resource_path("static"))
app.secret_key = "station-manager-local"

# The six pump counters entered on the daily form (A & B per fuel).
ODOMETER_FIELDS = [
    ("b1_a", "Benzine 1 — pump A"), ("b1_b", "Benzine 1 — pump B"),
    ("b2_a", "Benzine 2 — pump A"), ("b2_b", "Benzine 2 — pump B"),
    ("mez_a", "Mezout — pump A"), ("mez_b", "Mezout — pump B"),
]
PRICE_FIELDS = [
    ("b1_price", "Benzine 1 price / L"),
    ("b2_price", "Benzine 2 price / L"),
    ("mezout_price", "Mezout price / L"),
]
# Non-fuel income lines.
OTHER_INCOME_FIELDS = [
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

# Delivery-quantity column per fuel type, used to keep fuel_stock live.
STOCK_TYPES = {
    "Benzine 1": "benzine1",
    "Benzine 2": "benzine2",
    "Mezout": "mezout",
}


def _adjust_stock(conn, station_id, fuel_type, d_current=0, d_out=0, d_in=0):
    """Apply deltas to a base fuel-stock row (creating it if needed)."""
    conn.execute(
        """INSERT INTO fuel_stock (station_id, fuel_type, current, total_out, total_in)
           VALUES (?,?,0,0,0)
           ON CONFLICT(station_id, fuel_type) DO NOTHING""",
        (station_id, fuel_type),
    )
    conn.execute(
        f"""UPDATE fuel_stock
            SET current = current + ?, total_out = total_out + ?, total_in = total_in + ?
            WHERE station_id = ? AND fuel_type = ?""",
        (d_current, d_out, d_in, station_id, fuel_type),
    )


def _recompute_stock_aggregates(conn, station_id):
    """Refresh the 'Total Benzine' and 'GRAND TOTAL' rows from the base rows."""
    base = {r["fuel_type"]: r for r in conn.execute(
        "SELECT * FROM fuel_stock WHERE station_id = ?", (station_id,))}

    def agg(types):
        return {f: sum(base[t][f] for t in types if t in base)
                for f in ("initial", "total_out", "total_in", "current")}

    for label, types in (("Total Benzine", ["Benzine 1", "Benzine 2"]),
                         ("GRAND TOTAL ", ["Benzine 1", "Benzine 2", "Mezout"])):
        if not any(t in base for t in types):
            continue
        a = agg(types)
        conn.execute(
            """INSERT INTO fuel_stock
                 (station_id, fuel_type, initial, total_out, total_in, current)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(station_id, fuel_type) DO UPDATE SET
                 initial=excluded.initial, total_out=excluded.total_out,
                 total_in=excluded.total_in, current=excluded.current""",
            (station_id, label, a["initial"], a["total_out"], a["total_in"], a["current"]),
        )


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
    margin = analytics.fuel_margin(conn, st["id"])
    return render_template(
        "station.html", st=st, s=summary, breakdown=breakdown,
        trend=trend, fuel=fuel, gas=gas, oil=oil, margin=margin,
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
    prev = analytics.latest_odometer(conn, st["id"])

    if request.method == "POST":
        f = request.form

        def g(field):
            try:
                return float(f.get(field) or 0)
            except ValueError:
                return 0.0

        day = f.get("day")
        if not day:
            flash("Date is required.", "error")
            return redirect(url_for("daily_new", name=name))

        # 1) Read the six odometer counters and derive litres from the previous
        #    reading: litres = (pump A + pump B) today - (A + B) previously.
        odo = {fld: g(fld) for fld, _ in ODOMETER_FIELDS}
        base = prev or {k: 0 for k in odo}
        warnings = []

        def litres(a, b):
            sold = (odo[a] + odo[b]) - (base.get(a, 0) + base.get(b, 0))
            if sold < 0:              # meter reset / replacement
                warnings.append(f"{a[:-2]} counter went backwards; litres set to 0.")
                return 0.0
            return sold

        b1_l = litres("b1_a", "b1_b")
        b2_l = litres("b2_a", "b2_b")
        mez_l = litres("mez_a", "mez_b")

        # 2) Prices → fuel revenue.
        b1_p, b2_p, mez_p = g("b1_price"), g("b2_price"), g("mezout_price")
        vals = {fld: g(fld) for fld, _ in
                OTHER_INCOME_FIELDS + PURCHASE_FIELDS + EXPENSE_FIELDS}
        vals.update(
            b1_liters=b1_l, b1_price=b1_p, b1_total=b1_l * b1_p,
            b2_liters=b2_l, b2_price=b2_p, b2_total=b2_l * b2_p,
            mezout_liters=mez_l, mezout_price=mez_p, mezout_total=mez_l * mez_p,
        )
        vals["benzine_liters"] = b1_l + b2_l
        vals["benzine_total"] = vals["b1_total"] + vals["b2_total"]
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
        vals["debts"] = g("debts")
        vals["total_out"] = (
            vals["total_purchases"] + vals["total_expense"]
            + vals["profit_sharing"] + vals["debts"]
        )
        vals["daily_total"] = vals["total_in"] - vals["total_out"]
        vals["station_id"] = st["id"]
        vals["day"] = day
        vals["notes"] = f.get("notes") or None
        vals["price_note"] = f.get("price_note") or None

        try:
            cols = list(vals.keys())
            conn.execute(
                f"INSERT INTO daily_records ({', '.join(cols)}) "
                f"VALUES ({', '.join(':' + c for c in cols)})", vals)

            # Store the odometer reading itself.
            conn.execute(
                """INSERT INTO odometer_readings
                   (station_id, day, price_note, b1_a, b1_b, b2_a, b2_b, mez_a, mez_b,
                    b1_liters, b2_liters, mez_liters, is_initial)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                (st["id"], day, vals["price_note"],
                 odo["b1_a"], odo["b1_b"], odo["b2_a"], odo["b2_b"],
                 odo["mez_a"], odo["mez_b"], b1_l, b2_l, mez_l))

            # Draw the sold litres down from fuel stock.
            _adjust_stock(conn, st["id"], "Benzine 1", d_current=-b1_l, d_out=b1_l)
            _adjust_stock(conn, st["id"], "Benzine 2", d_current=-b2_l, d_out=b2_l)
            _adjust_stock(conn, st["id"], "Mezout", d_current=-mez_l, d_out=mez_l)

            # 3) Optional fuel restocks entered alongside the day.
            restocks = 0
            for i in range(1, 4):
                ftype = f.get(f"restock_type_{i}")
                qty = g(f"restock_qty_{i}")
                price = g(f"restock_price_{i}")
                if ftype in STOCK_TYPES and qty > 0:
                    col = STOCK_TYPES[ftype]
                    conn.execute(
                        f"""INSERT INTO fuel_deliveries
                            (station_id, day, {col}, price, total)
                            VALUES (?,?,?,?,?)""",
                        (st["id"], day, qty, price, qty * price))
                    _adjust_stock(conn, st["id"], ftype, d_current=qty, d_in=qty)
                    restocks += 1

            _recompute_stock_aggregates(conn, st["id"])
            conn.commit()

            for w in warnings:
                flash(w, "error")
            extra = f" · {restocks} restock(s) logged" if restocks else ""
            flash(f"Saved {day}: {b1_l:,.0f}/{b2_l:,.0f}/{mez_l:,.0f} L sold, "
                  f"net ${vals['daily_total']:,.2f}{extra}.", "success")
            return redirect(url_for("daily", name=name))
        except Exception as exc:  # pragma: no cover
            flash(f"Could not save: {exc}", "error")

    return render_template(
        "daily_new.html", st=st, prev=prev,
        odometer_fields=ODOMETER_FIELDS, price_fields=PRICE_FIELDS,
        income_fields=OTHER_INCOME_FIELDS, expense_fields=EXPENSE_FIELDS,
        stock_types=list(STOCK_TYPES.keys()),
    )


@app.route("/station/<name>/odometers")
def odometers(name):
    conn = get_conn()
    st = _station_by_name(conn, name)
    rows = conn.execute(
        """SELECT * FROM odometer_readings WHERE station_id = ?
           ORDER BY id DESC LIMIT 200""", (st["id"],)).fetchall()
    return render_template("odometers.html", st=st, rows=rows)


@app.route("/station/<name>/deliveries", methods=["GET", "POST"])
def deliveries(name):
    conn = get_conn()
    st = _station_by_name(conn, name)

    if request.method == "POST":
        f = request.form

        def g(field):
            try:
                return float(f.get(field) or 0)
            except ValueError:
                return 0.0

        day = f.get("day")
        ftype = f.get("fuel_type")
        qty = g("qty")
        price = g("price")
        if not day or ftype not in STOCK_TYPES or qty <= 0:
            flash("Date, fuel type and a positive quantity are required.", "error")
            return redirect(url_for("deliveries", name=name))

        col = STOCK_TYPES[ftype]
        conn.execute(
            f"""INSERT INTO fuel_deliveries (station_id, day, {col}, price, total)
                VALUES (?,?,?,?,?)""",
            (st["id"], day, qty, price, qty * price))
        _adjust_stock(conn, st["id"], ftype, d_current=qty, d_in=qty)
        _recompute_stock_aggregates(conn, st["id"])
        conn.commit()
        flash(f"Logged delivery: {qty:,.0f} L {ftype} @ ${price} "
              f"= ${qty * price:,.2f} added to goods cost.", "success")
        return redirect(url_for("deliveries", name=name))

    rows = conn.execute(
        """SELECT day, benzine1, benzine2, backup, mezout, price, total
           FROM fuel_deliveries WHERE station_id = ?
           ORDER BY day DESC, id DESC LIMIT 200""", (st["id"],)).fetchall()
    cost = analytics.cost_of_stock(conn, st["id"])
    return render_template("deliveries.html", st=st, rows=rows, cost=cost,
                           stock_types=list(STOCK_TYPES.keys()))


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
    """Create the DB and import the workbook when data is missing.

    Re-imports when either the daily records OR the odometer readings are
    empty, so a database created by an earlier version (which had no odometer
    table populated) heals itself instead of showing empty odometers.
    """
    init_db()
    conn = get_conn()
    daily = conn.execute("SELECT COUNT(*) c FROM daily_records").fetchone()["c"]
    odo = conn.execute("SELECT COUNT(*) c FROM odometer_readings").fetchone()["c"]
    if daily == 0 or odo == 0:
        try:
            run_import(verbose=False)
        except FileNotFoundError:
            pass


def _open_browser(url):
    import threading
    import webbrowser
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()


if __name__ == "__main__":
    ensure_data()
    host, port = "127.0.0.1", 5000
    # Open the app in the default browser automatically (skip the Flask reloader's
    # duplicate child process so it only opens once).
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        print(f"\n  Station Manager is running.  Open:  http://{host}:{port}\n"
              f"  (Keep this window open while you use the app. Close it to stop.)\n")
        _open_browser(f"http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
