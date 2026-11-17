import csv
import hashlib
import math
import secrets
from pathlib import Path

from werkzeug.security import generate_password_hash


VARIABLES = {
    "AirTF_Avg": ("air_temperature", "Air temperature", "°F"),
    "RH": ("relative_humidity", "Relative humidity", "%"),
    "Rain_in_Tot": ("rainfall", "Rainfall", "in"),
    "SlrW_Avg": ("solar_radiation", "Solar radiation", "W/m²"),
    "FuelT_C_Avg": ("fuel_temperature", "Fuel temperature", "°C"),
    "FuelM_Avg": ("fuel_moisture", "Fuel moisture", "%"),
    "PA_uS_Avg": ("pa_conductivity", "PA conductivity", "µS"),
    "WindSpeed_mph_avg": ("wind_speed_average", "Average wind speed", "mph"),
    "WindDir_avg": ("wind_direction", "Average wind direction", "degrees"),
    "WindDir_StdDev": ("wind_direction_stddev", "Wind direction standard deviation", "degrees"),
    "WindSpeed_mph_max": ("wind_speed_maximum", "Maximum wind speed", "mph"),
}

BASE_COLUMNS = ["Station", "SynopticID", "TIMESTAMP"]
KNOWN_LAYOUTS = {
    7: BASE_COLUMNS + ["RH", "SlrW_Avg", "FuelM_Avg", "PA_uS_Avg"],
    9: None,  # Two valid layouts exist; use the source header when it has 9 columns.
    11: BASE_COLUMNS + ["AirTF_Avg", "RH", "Rain_in_Tot", "SlrW_Avg",
                        "WindSpeed_mph_avg", "WindDir_avg", "WindDir_StdDev", "WindSpeed_mph_max"],
    13: BASE_COLUMNS + ["AirTF_Avg", "RH", "Rain_in_Tot", "SlrW_Avg", "FuelM_Avg",
                        "PA_uS_Avg", "WindSpeed_mph_avg", "WindDir_avg", "WindDir_StdDev",
                        "WindSpeed_mph_max"],
    14: BASE_COLUMNS + ["AirTF_Avg", "RH", "Rain_in_Tot", "SlrW_Avg", "FuelT_C_Avg",
                        "FuelM_Avg", "PA_uS_Avg", "WindSpeed_mph_avg", "WindDir_avg",
                        "WindDir_StdDev", "WindSpeed_mph_max"],
}


def columns_for_row(header, row):
    """Repair known SJSU files whose data rows outgrow their original header."""
    if len(row) == len(header):
        return header
    # PGESanRamon temporarily omits conductivity, and sometimes fuel moisture too,
    # while retaining the original 14-column header.
    if len(header) == 14 and len(row) in {12, 13}:
        omitted = {"PA_uS_Avg"}
        if len(row) == 12:
            omitted.add("FuelM_Avg")
        repaired = [column for column in header if column not in omitted]
        if len(repaired) == len(row):
            return repaired
    repaired = KNOWN_LAYOUTS.get(len(row))
    if repaired is None:
        raise ValueError(f"unsupported {len(row)}-column row (header has {len(header)})")
    return repaired


def numeric_value(raw):
    text = (raw or "").strip()
    if not text or text.upper() in {"NAN", "NA", "NULL"}:
        return None
    value = float(text)
    if not math.isfinite(value) or value <= -999:
        return None
    return value


def ensure_catalog(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM roles WHERE name='admin'")
        role = cursor.fetchone()
        if not role:
            cursor.execute("INSERT INTO roles (name) VALUES ('admin')")
            role_id = cursor.lastrowid
        else:
            role_id = role["id"]

        cursor.execute("SELECT id FROM users WHERE email='system-import@sjsu.local'")
        user = cursor.fetchone()
        if not user:
            cursor.execute(
                """INSERT INTO users (role_id,email,display_name,password_hash)
                   VALUES (%s,'system-import@sjsu.local','SJSU Data Loader',%s)""",
                (role_id, generate_password_hash(secrets.token_urlsafe(48))),
            )
            user_id = cursor.lastrowid
        else:
            user_id = user["id"]

        variable_ids = {}
        for source_column, (code, name, unit) in VARIABLES.items():
            cursor.execute(
                """INSERT INTO weather_variables (code,name,unit) VALUES (%s,%s,%s)
                   ON DUPLICATE KEY UPDATE name=VALUES(name),unit=VALUES(unit)""",
                (code, name, unit),
            )
            cursor.execute("SELECT id FROM weather_variables WHERE code=%s", (code,))
            variable_ids[source_column] = cursor.fetchone()["id"]
    connection.commit()
    return user_id, variable_ids


def station_from_file(path):
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        next(reader, None)
        for row in reader:
            if len(row) >= 3 and row[0].strip() and row[1].strip():
                return row[0].strip(), row[1].strip()
    raise ValueError("file contains no station rows")


def ensure_station(connection, name, code):
    with connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO stations (code,name) VALUES (%s,%s)
               ON DUPLICATE KEY UPDATE name=VALUES(name),active=1""",
            (code, name),
        )
        cursor.execute("SELECT id FROM stations WHERE code=%s", (code,))
        station_id = cursor.fetchone()["id"]
    connection.commit()
    return station_id


def begin_import(connection, station_id, user_id, path, digest):
    with connection.cursor() as cursor:
        cursor.execute("SELECT id,status FROM data_imports WHERE station_id=%s AND file_hash=%s",
                       (station_id, digest))
        existing = cursor.fetchone()
        if existing and existing["status"] == "succeeded":
            return None
        if existing:
            cursor.execute(
                """UPDATE data_imports SET status='processing',rows_imported=0,
                   error_message=NULL,finished_at=NULL WHERE id=%s""", (existing["id"],),
            )
            import_id = existing["id"]
        else:
            cursor.execute(
                """INSERT INTO data_imports
                   (station_id,imported_by,filename,file_hash,status)
                   VALUES (%s,%s,%s,%s,'processing')""",
                (station_id, user_id, path.name, digest),
            )
            import_id = cursor.lastrowid
    connection.commit()
    return import_id


def flush_batch(connection, station_id, import_id, batch, variable_ids, mapped_columns):
    if not batch:
        return 0
    # Last occurrence wins when the source file contains duplicate timestamps.
    unique = {timestamp: values for timestamp, values in batch}
    with connection.cursor() as cursor:
        cursor.executemany(
            "INSERT IGNORE INTO observations (station_id,data_import_id,observed_at) VALUES (%s,%s,%s)",
            [(station_id, import_id, timestamp) for timestamp in unique],
        )
        inserted = cursor.rowcount
        timestamps = list(unique)
        placeholders = ",".join(["%s"] * len(timestamps))
        cursor.execute(
            f"SELECT id,observed_at FROM observations WHERE station_id=%s AND observed_at IN ({placeholders})",
            [station_id, *timestamps],
        )
        observation_ids = {row["observed_at"]: row["id"] for row in cursor.fetchall()}
        value_rows = []
        for timestamp, values in unique.items():
            observation_id = observation_ids.get(timestamp)
            if not observation_id:
                continue
            for source_column, value in values.items():
                value_rows.append((observation_id, variable_ids[source_column], value))
                mapped_columns.add(source_column)
        if value_rows:
            cursor.executemany(
                """INSERT INTO observation_values (observation_id,variable_id,value)
                   VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE value=VALUES(value)""",
                value_rows,
            )
    return inserted


def load_file(connection, path, user_id, variable_ids, parse_timestamp, batch_size=5000):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    station_name, station_code = station_from_file(path)
    station_id = ensure_station(connection, station_name, station_code)
    import_id = begin_import(connection, station_id, user_id, path, digest)
    if import_id is None:
        return {"file": path.name, "station": station_name, "status": "skipped", "rows": 0}

    inserted = 0
    mapped_columns = set()
    batch = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source)
            header = [column.strip() for column in next(reader)]
            for line_number, row in enumerate(reader, 2):
                if not row or len(row) < 3:
                    continue
                try:
                    columns = columns_for_row(header, row)
                    record = dict(zip(columns, row))
                    timestamp = parse_timestamp(record["TIMESTAMP"])
                    values = {}
                    for source_column in VARIABLES:
                        if source_column in record:
                            value = numeric_value(record[source_column])
                            if value is not None:
                                values[source_column] = value
                    if values:
                        batch.append((timestamp, values))
                except (KeyError, ValueError) as error:
                    raise ValueError(f"{path.name}, row {line_number}: {error}") from error
                if len(batch) >= batch_size:
                    inserted += flush_batch(connection, station_id, import_id, batch,
                                            variable_ids, mapped_columns)
                    batch.clear()
            inserted += flush_batch(connection, station_id, import_id, batch,
                                    variable_ids, mapped_columns)

        with connection.cursor() as cursor:
            for source_column in mapped_columns:
                cursor.execute(
                    """INSERT INTO station_variables (station_id,variable_id,source_column)
                       VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE source_column=VALUES(source_column)""",
                    (station_id, variable_ids[source_column], source_column),
                )
            cursor.execute(
                """UPDATE data_imports SET status='succeeded',rows_imported=%s,
                   finished_at=NOW() WHERE id=%s""", (inserted, import_id),
            )
        connection.commit()
        return {"file": path.name, "station": station_name, "status": "loaded", "rows": inserted}
    except Exception as error:
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute(
                """UPDATE data_imports SET status='failed',error_message=%s,
                   finished_at=NOW() WHERE id=%s""", (str(error)[:2000], import_id),
            )
        connection.commit()
        raise


def load_archive(connection, data_directory, parse_timestamp, progress=print):
    root = Path(data_directory)
    files = sorted(path for path in root.glob("*/*.csv") if path.is_file())
    if not files:
        raise FileNotFoundError(f"No station CSV files found below {root}")
    user_id, variable_ids = ensure_catalog(connection)
    totals = {"files": 0, "skipped": 0, "rows": 0}
    for path in files:
        result = load_file(connection, path, user_id, variable_ids, parse_timestamp)
        if result["status"] == "skipped":
            totals["skipped"] += 1
            progress(f"SKIP {result['station']}: {result['file']} already loaded")
        else:
            totals["files"] += 1
            totals["rows"] += result["rows"]
            progress(f"LOAD {result['station']}: {result['rows']:,} new observations")
    return totals

