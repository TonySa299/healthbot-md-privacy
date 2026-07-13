"""
Database layer for the Station Manager.

Uses the Python standard-library ``sqlite3`` module so the application has no
heavy ORM dependency. A single SQLite file (``station.db``) holds every table.
"""
import os
import sys
import sqlite3
from contextlib import contextmanager

# When packaged as a one-file .exe by PyInstaller, bundled read-only files live
# in a temporary folder (sys._MEIPASS), while the database must be written to a
# persistent, writable place — the folder that contains the .exe.
FROZEN = getattr(sys, "frozen", False)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)          # bundled templates/static/data
DATA_DIR = os.path.dirname(sys.executable) if FROZEN else BASE_DIR  # writable, next to exe
DB_PATH = os.path.join(DATA_DIR, "station.db")


def resource_path(*parts):
    """Absolute path to a bundled resource (works both normally and frozen)."""
    return os.path.join(BUNDLE_DIR, *parts)


# The workbook the app reads AND writes back to. When packaged as an .exe the
# bundled copy is read-only, so the live, writable copy lives next to the exe.
SEED_WORKBOOK = resource_path("data", "General_Cashflow.xlsx")
if FROZEN:
    LIVE_WORKBOOK = os.path.join(DATA_DIR, "General_Cashflow.xlsx")
else:
    LIVE_WORKBOOK = os.path.join(BASE_DIR, "data", "General_Cashflow.xlsx")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")


def ensure_live_workbook():
    """Make sure a writable workbook exists (copy the bundled seed on first run)."""
    if not os.path.exists(LIVE_WORKBOOK) and os.path.exists(SEED_WORKBOOK):
        os.makedirs(os.path.dirname(LIVE_WORKBOOK), exist_ok=True)
        import shutil
        shutil.copy2(SEED_WORKBOOK, LIVE_WORKBOOK)

# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    id      INTEGER PRIMARY KEY,
    name    TEXT UNIQUE NOT NULL
);

-- One row per operating day per station (mirrors the "Daily <Station>" sheets).
CREATE TABLE IF NOT EXISTS daily_records (
    id                  INTEGER PRIMARY KEY,
    station_id          INTEGER NOT NULL REFERENCES stations(id),
    day                 TEXT NOT NULL,            -- ISO date (YYYY-MM-DD)
    price_note          TEXT,

    -- Benzine (gasoline) grade 1 & 2
    b1_liters           REAL DEFAULT 0,
    b1_price            REAL DEFAULT 0,
    b1_total            REAL DEFAULT 0,
    b2_liters           REAL DEFAULT 0,
    b2_price            REAL DEFAULT 0,
    b2_total            REAL DEFAULT 0,
    benzine_liters      REAL DEFAULT 0,
    benzine_total       REAL DEFAULT 0,

    -- Mezout (diesel)
    mezout_liters       REAL DEFAULT 0,
    mezout_price        REAL DEFAULT 0,
    mezout_total        REAL DEFAULT 0,

    -- Other income streams
    oil                 REAL DEFAULT 0,
    wash                REAL DEFAULT 0,
    gaz                 REAL DEFAULT 0,
    fragrance           REAL DEFAULT 0,
    kiosk               REAL DEFAULT 0,
    payments            REAL DEFAULT 0,
    coupon_in           REAL DEFAULT 0,
    total_in            REAL DEFAULT 0,

    -- Adjustments
    debts               REAL DEFAULT 0,
    internal_sale       REAL DEFAULT 0,
    coupons             REAL DEFAULT 0,
    difference          REAL DEFAULT 0,

    -- Purchases (cost of goods restocked)
    purchase_oil        REAL DEFAULT 0,
    purchase_kiosk      REAL DEFAULT 0,
    purchase_gaz        REAL DEFAULT 0,
    other_purchases     REAL DEFAULT 0,
    total_purchases     REAL DEFAULT 0,

    -- Operating expenses
    rent                REAL DEFAULT 0,
    salaries            REAL DEFAULT 0,
    repairs             REAL DEFAULT 0,
    utilities           REAL DEFAULT 0,
    client_satisfaction REAL DEFAULT 0,
    tips                REAL DEFAULT 0,
    new_assets          REAL DEFAULT 0,
    other_expense       REAL DEFAULT 0,
    total_expense       REAL DEFAULT 0,

    profit_sharing      REAL DEFAULT 0,
    total_out           REAL DEFAULT 0,
    daily_total         REAL DEFAULT 0,          -- net cash result for the day
    notes               TEXT,
    UNIQUE(station_id, day, price_note)
);

-- Current on-hand fuel stock per station (from the "BM Stock" summary block).
CREATE TABLE IF NOT EXISTS fuel_stock (
    id          INTEGER PRIMARY KEY,
    station_id  INTEGER NOT NULL REFERENCES stations(id),
    fuel_type   TEXT NOT NULL,
    initial     REAL DEFAULT 0,
    total_out   REAL DEFAULT 0,
    total_in    REAL DEFAULT 0,
    current     REAL DEFAULT 0,
    UNIQUE(station_id, fuel_type)
);

-- Pump odometer readings. Each fuel is dispensed through two counters (A & B);
-- litres sold = (A + B today) - (A + B on the previous reading).
CREATE TABLE IF NOT EXISTS odometer_readings (
    id          INTEGER PRIMARY KEY,
    station_id  INTEGER NOT NULL REFERENCES stations(id),
    day         TEXT NOT NULL,
    price_note  TEXT,
    b1_a        REAL DEFAULT 0,
    b1_b        REAL DEFAULT 0,
    b2_a        REAL DEFAULT 0,
    b2_b        REAL DEFAULT 0,
    mez_a       REAL DEFAULT 0,
    mez_b       REAL DEFAULT 0,
    b1_liters   REAL DEFAULT 0,          -- computed at entry time
    b2_liters   REAL DEFAULT 0,
    mez_liters  REAL DEFAULT 0,
    is_initial  INTEGER DEFAULT 0        -- 1 = baseline row, no sale computed
);

-- Individual fuel deliveries (the "IN" block of the BM Stock sheets).
CREATE TABLE IF NOT EXISTS fuel_deliveries (
    id          INTEGER PRIMARY KEY,
    station_id  INTEGER NOT NULL REFERENCES stations(id),
    day         TEXT,
    benzine1    REAL DEFAULT 0,
    benzine2    REAL DEFAULT 0,
    backup      REAL DEFAULT 0,
    mezout      REAL DEFAULT 0,
    price       REAL DEFAULT 0,
    total       REAL DEFAULT 0
);

-- Oil inventory items.
CREATE TABLE IF NOT EXISTS oil_stock (
    id          INTEGER PRIMARY KEY,
    station_id  INTEGER NOT NULL REFERENCES stations(id),
    item        TEXT NOT NULL,
    price       REAL DEFAULT 0,
    current     REAL DEFAULT 0,
    sold        REAL DEFAULT 0,
    restock     REAL DEFAULT 0,
    value       REAL DEFAULT 0
);

-- Gas (LPG cylinder) daily movements.
CREATE TABLE IF NOT EXISTS gas_records (
    id          INTEGER PRIMARY KEY,
    station_id  INTEGER NOT NULL REFERENCES stations(id),
    day         TEXT,
    available   REAL DEFAULT 0,
    sold        REAL DEFAULT 0,
    restock     REAL DEFAULT 0
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def cursor():
    conn = get_conn()
    try:
        yield conn.cursor()
        conn.commit()
    finally:
        conn.close()


def init_db():
    with cursor() as cur:
        cur.executescript(SCHEMA)


def reset_db():
    """Drop the SQLite file entirely (used before a fresh import)."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()


def get_or_create_station(name):
    with cursor() as cur:
        cur.execute("INSERT OR IGNORE INTO stations(name) VALUES (?)", (name,))
        cur.execute("SELECT id FROM stations WHERE name = ?", (name,))
        return cur.fetchone()["id"]
