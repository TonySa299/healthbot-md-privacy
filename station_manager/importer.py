"""
Import the ``General_Cashflow.xlsx`` workbook into the SQLite database.

The daily sheets for the two stations do not share an identical column layout
(Halba has an extra "Internal Sale" column), so the importer maps values by
their *header name* rather than by a fixed column index. That makes it robust
to the small layout differences and to future column additions.
"""
import os
import datetime

import openpyxl

from db import (
    BASE_DIR,
    reset_db,
    get_or_create_station,
    cursor,
)

WORKBOOK = os.path.join(BASE_DIR, "data", "General_Cashflow.xlsx")

STATIONS = ["Halba", "Tekrit"]

# Map a normalised daily-sheet header -> daily_records column name.
DAILY_HEADER_MAP = {
    "benzine 1 l": "b1_liters",
    "benzine 1 p": "b1_price",
    "total benzine 1": "b1_total",
    "benzine 2 l": "b2_liters",
    "benzine 2 p": "b2_price",
    "total benzine 2": "b2_total",
    "total benzine l (1+2)": "benzine_liters",
    "total benzine $": "benzine_total",
    "mezout l": "mezout_liters",
    "mezout p": "mezout_price",
    "total mezout": "mezout_total",
    "oil": "oil",
    "wash": "wash",
    "gaz": "gaz",
    "fragrence": "fragrance",
    "kiosk": "kiosk",
    "payments": "payments",
    "coupon": "coupon_in",
    "total in": "total_in",
    "debts": "debts",
    "internal sale": "internal_sale",
    "coupons": "coupons",
    "difference": "difference",
    "purchase oil": "purchase_oil",
    "purchase kiosk": "purchase_kiosk",
    "purchase gaz": "purchase_gaz",
    "other purchases": "other_purchases",
    "total purchases": "total_purchases",
    "pmnt - rent": "rent",
    "salaries": "salaries",
    "r&m": "repairs",
    "utilities": "utilities",
    "client satisfaction": "client_satisfaction",
    "tips": "tips",
    "new assets": "new_assets",
    "other": "other_expense",
    "total expense": "total_expense",
    "profit sharing": "profit_sharing",
    "total out": "total_out",
    "daily total": "daily_total",
    "notes": "notes",
    "price change": "price_note",
    "date": "day",
}

NUMERIC_COLS = {
    v for v in DAILY_HEADER_MAP.values()
    if v not in ("day", "price_note", "notes")
}


def _norm(text):
    return str(text).strip().lower() if text is not None else ""


def _num(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return 0.0


def _find_header_row(ws):
    """Locate the daily header row (the one whose first cell reads 'Date')."""
    for r in range(1, 12):
        if _norm(ws.cell(r, 1).value) == "date":
            return r
    return 7


def import_daily(wb, station, station_id):
    ws = wb[f"Daily {station}"]
    header_row = _find_header_row(ws)

    # Build header-name -> column-index map for this sheet.
    col_by_field = {}
    for c in range(1, ws.max_column + 1):
        header = _norm(ws.cell(header_row, c).value)
        field = DAILY_HEADER_MAP.get(header)
        # First occurrence wins (avoids duplicate headers clobbering each other).
        if field and field not in col_by_field:
            col_by_field[field] = c

    rows = []
    for r in range(header_row + 1, ws.max_row + 1):
        date_cell = ws.cell(r, col_by_field["day"]).value
        if not isinstance(date_cell, datetime.datetime):
            continue

        record = {"station_id": station_id, "day": date_cell.date().isoformat()}
        for field, col in col_by_field.items():
            if field == "day":
                continue
            val = ws.cell(r, col).value
            if field in ("price_note", "notes"):
                record[field] = str(val).strip() if val is not None else None
            else:
                record[field] = _num(val)
        rows.append(record)

    if not rows:
        return 0

    columns = sorted({k for row in rows for k in row})
    placeholders = ", ".join(f":{c}" for c in columns)
    sql = (
        f"INSERT OR IGNORE INTO daily_records ({', '.join(columns)}) "
        f"VALUES ({placeholders})"
    )
    with cursor() as cur:
        for row in rows:
            cur.execute(sql, {c: row.get(c) for c in columns})
    return len(rows)


def import_fuel_stock(wb, station, station_id):
    ws = wb[f"BM Stock {station}"]
    # Summary block: rows with a fuel type in column A, Initial/Out/In/Current.
    stock_rows = 0
    for r in range(3, 9):
        ftype = ws.cell(r, 1).value
        if not ftype:
            continue
        with cursor() as cur:
            cur.execute(
                """INSERT OR IGNORE INTO fuel_stock
                   (station_id, fuel_type, initial, total_out, total_in, current)
                   VALUES (?,?,?,?,?,?)""",
                (
                    station_id,
                    str(ftype).strip(),
                    _num(ws.cell(r, 2).value),
                    _num(ws.cell(r, 3).value),
                    _num(ws.cell(r, 4).value),
                    _num(ws.cell(r, 5).value),
                ),
            )
        stock_rows += 1

    # Deliveries block (IN): Date | Benzine1 | Benzine2 | Backup | Mezout | Price | Total
    # Columns H..N in both sheets.
    deliveries = 0
    for r in range(3, ws.max_row + 1):
        d = ws.cell(r, 8).value  # column H
        if not isinstance(d, datetime.datetime):
            continue
        with cursor() as cur:
            cur.execute(
                """INSERT INTO fuel_deliveries
                   (station_id, day, benzine1, benzine2, backup, mezout, price, total)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    station_id,
                    d.date().isoformat(),
                    _num(ws.cell(r, 9).value),
                    _num(ws.cell(r, 10).value),
                    _num(ws.cell(r, 11).value),
                    _num(ws.cell(r, 12).value),
                    _num(ws.cell(r, 13).value),
                    _num(ws.cell(r, 14).value),
                ),
            )
        deliveries += 1
    return stock_rows, deliveries


def import_oil_stock(wb, station, station_id):
    ws = wb[f"Oil Stock {station}"]
    # Find the header row containing "Item" or "Item Type" in column A.
    header_row = None
    for r in range(1, 10):
        if _norm(ws.cell(r, 1).value).startswith("item"):
            header_row = r
            break
    if header_row is None:
        return 0

    headers = {_norm(ws.cell(header_row, c).value): c
               for c in range(1, ws.max_column + 1)}
    price_col = headers.get("price")
    value_col = headers.get("value")
    sold_col = headers.get("sold")
    restock_col = headers.get("restock") or headers.get("restocked")
    # Current stock is the last dated snapshot column before Restock/Sold, else "in stock".
    current_col = headers.get("in stock")

    count = 0
    for r in range(header_row + 1, ws.max_row + 1):
        item = ws.cell(r, 1).value
        if not item or not str(item).strip():
            continue
        value = ws.cell(r, value_col).value if value_col else None
        if isinstance(value, str) and value.startswith("#"):
            value = 0  # broken Excel ref
        with cursor() as cur:
            cur.execute(
                """INSERT INTO oil_stock
                   (station_id, item, price, current, sold, restock, value)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    station_id,
                    str(item).strip(),
                    _num(ws.cell(r, price_col).value) if price_col else 0,
                    _num(ws.cell(r, current_col).value) if current_col else 0,
                    _num(ws.cell(r, sold_col).value) if sold_col else 0,
                    _num(ws.cell(r, restock_col).value) if restock_col else 0,
                    _num(value),
                ),
            )
        count += 1
    return count


def import_gas(wb, station, station_id):
    sheet = "Kiosk And Gaz Halba" if station == "Halba" else "Kiosk and GazTekrit"
    ws = wb[sheet]
    # Gas block: Date | Available | Sold | Restock in columns F..I.
    count = 0
    for r in range(2, ws.max_row + 1):
        d = ws.cell(r, 6).value  # column F
        if not isinstance(d, datetime.datetime):
            continue
        with cursor() as cur:
            cur.execute(
                """INSERT INTO gas_records
                   (station_id, day, available, sold, restock)
                   VALUES (?,?,?,?,?)""",
                (
                    station_id,
                    d.date().isoformat(),
                    _num(ws.cell(r, 7).value),
                    _num(ws.cell(r, 8).value),
                    _num(ws.cell(r, 9).value),
                ),
            )
        count += 1
    return count


def run_import(verbose=True):
    if not os.path.exists(WORKBOOK):
        raise FileNotFoundError(f"Workbook not found: {WORKBOOK}")

    reset_db()
    wb = openpyxl.load_workbook(WORKBOOK, data_only=True)

    summary = {}
    for station in STATIONS:
        sid = get_or_create_station(station)
        daily = import_daily(wb, station, sid)
        stock, deliveries = import_fuel_stock(wb, station, sid)
        oil = import_oil_stock(wb, station, sid)
        gas = import_gas(wb, station, sid)
        summary[station] = {
            "daily": daily,
            "fuel_stock": stock,
            "deliveries": deliveries,
            "oil_items": oil,
            "gas_records": gas,
        }
        if verbose:
            print(f"{station}: {summary[station]}")
    return summary


if __name__ == "__main__":
    run_import()
