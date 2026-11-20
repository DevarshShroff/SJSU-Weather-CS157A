# SJSU Campus Weather Monitoring & Alerts

**CS 157A — SJSU Campus Weather Monitoring & Alerts**

This repository combines the MySQL data pipeline and Flask backend at the
project root.

## What this part includes

| File | Role |
|---|---|
| `schema.sql` | Full relational schema (stations, observations, values, alerts, users, roles) |
| `data_loader.py` | Bulk CSV loader: catalog setup, batch inserts, format repairs, dedupe by file hash |
| `station_catalog.py` | Hard-coded map of which variables each station reports |
| `scripts/download_sjsu_data.py` | Downloads CSVs from met.sjsu.edu into `data/raw/` |
| `tests/test_loader.py` | Unit tests for loader helpers |
| `app.py` | Flask routes, authentication, admin imports, and database CLI |
| `requirements.txt` | Python dependencies |
| `.env.example` | Expected MySQL connection variables |

## Design highlights

- Normalized measurement storage (`observations` + `observation_values`) so stations can report different sensor sets
- Idempotent loads (`INSERT IGNORE` / content-hash skip) so re-running is safe
- Known SJSU CSV layout quirks repaired in `columns_for_row`

## How it fits the full project

The Flask app (`Part 2`) queries the tables defined here. Its database CLI
commands use this root schema and loader.

## Setup

Create a Python environment, install `requirements.txt`, and copy `.env.example`
to `.env` with your MySQL credentials and a stable, random `SECRET_KEY`. Then:

```bash
python -m pip install -r requirements.txt
flask --app app init-db
python scripts/download_sjsu_data.py
flask --app app load-data
flask --app app data-stats
flask --app app run
```

The MySQL account must be able to create the database for `init-db`.

## Local notes

Do **not** commit `.env` or `data/raw/` (see `.gitignore`). Download data with:

```bash
python scripts/download_sjsu_data.py
```
