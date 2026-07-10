# Station Manager

A small web application for running a two-branch fuel-station business
(**Halba** and **Tekrit**). It turns the `General_Cashflow.xlsx` workbook into a
live management system for daily cash-up, fuel/oil/gas inventory, and financial
reporting.

The business sells **Benzine 1**, **Benzine 2**, **Mezout** (diesel), engine
**oil**, **LPG gas cylinders**, **kiosk** goods and car **wash** services across
two stations. This app consolidates all of that into one dashboard.

## Features

- **Company dashboard** — consolidated KPIs (cash in, purchases, expenses, net
  result), a monthly net-cash chart, and current fuel/gas stock per station.
- **Per-station view** — headline financials, revenue mix by product, monthly
  trend, fuel volumes sold, and an inventory snapshot.
- **Daily ledger** — browse every operating day (filterable by month) and add
  new records through a form. Benzine, cash-in, purchase, expense and net totals
  are computed automatically on save, exactly like the spreadsheet formulas.
- **Inventory** — fuel stock levels, recent fuel deliveries, oil stock with
  values, and the LPG gas position.
- **Monthly report** — net result per station per month, side by side.
- **Re-import** — reload everything from the Excel workbook with one click.

## Quick start

```bash
cd station_manager
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000>.

On first launch the app creates a local SQLite database (`station.db`) and
imports `data/General_Cashflow.xlsx` automatically.

## Updating from Excel

The team can keep using the Excel workbook and periodically sync:

1. Replace `data/General_Cashflow.xlsx` with the newest version.
2. Click **↻ Re-import** in the top bar (or run `python importer.py`).

The importer maps spreadsheet columns by their **header names**, so it tolerates
the small layout differences between the two stations' sheets and survives new
columns being added.

## Project layout

| File | Purpose |
|------|---------|
| `app.py` | Flask routes and the daily-entry form logic |
| `db.py` | SQLite schema and connection helpers |
| `importer.py` | Loads the Excel workbook into the database |
| `analytics.py` | Financial aggregations used by the dashboard/reports |
| `templates/` | HTML views |
| `static/style.css` | Styling |
| `data/General_Cashflow.xlsx` | Source workbook |

## Data model

- `stations` — the two branches.
- `daily_records` — one row per operating day per station (fuel litres/prices,
  every income line, purchases, expenses, and the computed net).
- `fuel_stock` / `fuel_deliveries` — current fuel levels and delivery history.
- `oil_stock` — oil items with quantity, price and value.
- `gas_records` — daily LPG cylinder movements.

## Notes

- Figures are validated against the workbook's own `GENERAL SUMMARY` sheet — e.g.
  Halba's net result (**$1,081,570.83**) and Benzine 1 litres sold (**474,521**)
  match exactly.
- `station.db` is regenerated from the workbook and is git-ignored; the workbook
  is the source of truth.
