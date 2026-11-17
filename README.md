# Part 1 · Database Schema & Data Pipeline

**CS 157A — SJSU Campus Weather Monitoring & Alerts**

This contribution owns how weather data is modeled in MySQL and how the public SJSU station CSVs are imported.

## What this part includes

| File | Role |
|---|---|
| `schema.sql` | Full relational schema (stations, observations, values, alerts, users, roles) |
| `data_loader.py` | Bulk CSV loader: catalog setup, batch inserts, format repairs, dedupe by file hash |
| `station_catalog.py` | Hard-coded map of which variables each station reports |
| `scripts/download_sjsu_data.py` | Downloads CSVs from met.sjsu.edu into `data/raw/` |
| `tests/test_loader.py` | Unit tests for loader helpers |
| `.env.example` | Expected MySQL connection variables |

## Design highlights

- Normalized measurement storage (`observations` + `observation_values`) so stations can report different sensor sets
- Idempotent loads (`INSERT IGNORE` / content-hash skip) so re-running is safe
- Known SJSU CSV layout quirks repaired in `columns_for_row`

## How it fits the full project

The Flask app (`Part 2`) and UI (`Part 3`) query the tables defined here. Setup (`Part 4`) calls `flask init-db` and `flask load-data`, which use this schema and loader.

## Local notes

Do **not** commit `.env` or `data/raw/` (see `.gitignore`). Download data with:

```bash
python scripts/download_sjsu_data.py
```
