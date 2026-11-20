import csv
import hashlib
import io
import math
import os
import secrets
from datetime import datetime, timedelta
from functools import wraps

import pymysql
from dotenv import load_dotenv
from flask import (
    Flask, Response, abort, flash, g, redirect, render_template, request,
    session, url_for,
)
from pymysql.cursors import DictCursor
from werkzeug.security import check_password_hash, generate_password_hash

from data_loader import numeric_value
from station_catalog import STATION_VARIABLES

load_dotenv()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", secrets.token_hex(32)),
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
)


def db_config(with_database=True):
    config = {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "weather_app"),
        "password": os.getenv("DB_PASSWORD", ""),
        "charset": "utf8mb4",
        "cursorclass": DictCursor,
        "autocommit": False,
    }
    if with_database:
        config["database"] = os.getenv("DB_NAME", "sjsu_weather")
    return config


def get_db():
    if "db" not in g:
        g.db = pymysql.connect(**db_config())
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def query_all(sql, params=()):
    with get_db().cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def query_one(sql, params=()):
    with get_db().cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def execute(sql, params=()):
    connection = get_db()
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        result = cursor.lastrowid
    connection.commit()
    return result


@app.before_request
def load_user_and_verify_csrf():
    g.user = None
    if session.get("user_id"):
        g.user = query_one(
            """SELECT u.id, u.email, u.display_name, r.name AS role
               FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id = %s""",
            (session["user_id"],),
        )
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        supplied = request.form.get("csrf_token", "")
        if not supplied or not secrets.compare_digest(supplied, session.get("csrf_token", "")):
            abort(400, "Invalid or missing CSRF token")


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token


def login_required(view):
    @wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return view(**kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(**kwargs):
        if g.user["role"] != "admin":
            abort(403)
        return view(**kwargs)
    return wrapped


def catalog():
    stations = query_all("SELECT id, code, name FROM stations WHERE active = 1 ORDER BY name")
    variables = query_all("SELECT id, code, name, unit FROM weather_variables ORDER BY name")
    return stations, variables


@app.get("/")
def index():
    if g.user:
        return redirect(url_for("observations"))
    return render_template("index.html")


@app.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("display_name", "").strip()
        password = request.form.get("password", "")
        if not email or "@" not in email or not name:
            flash("Enter a valid email address and display name.", "danger")
        elif len(password) < 10:
            flash("Password must contain at least 10 characters.", "danger")
        else:
            try:
                execute(
                    """INSERT INTO users (role_id, email, display_name, password_hash)
                       VALUES ((SELECT id FROM roles WHERE name='student'), %s, %s, %s)""",
                    (email, name, generate_password_hash(password)),
                )
                flash("Account created. You can now log in.", "success")
                return redirect(url_for("login"))
            except pymysql.err.IntegrityError:
                get_db().rollback()
                flash("An account with that email already exists.", "danger")
    return render_template("auth.html", mode="register")


@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        user = query_one(
            "SELECT id, password_hash FROM users WHERE email = %s",
            (request.form.get("email", "").strip().lower(),),
        )
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session["user_id"] = user["id"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            destination = request.args.get("next", "")
            return redirect(destination if destination.startswith("/") and not destination.startswith("//") else url_for("observations"))
        flash("Incorrect email or password.", "danger")
    return render_template("auth.html", mode="login")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/account", methods=("GET", "POST"))
@login_required
def account():
    if request.method == "POST":
        name = request.form.get("display_name", "").strip()
        password = request.form.get("password", "")
        if not name or (password and len(password) < 10):
            flash("Provide a name; a new password must have at least 10 characters.", "danger")
        else:
            if password:
                execute("UPDATE users SET display_name=%s, password_hash=%s WHERE id=%s", (name, generate_password_hash(password), g.user["id"]))
            else:
                execute("UPDATE users SET display_name=%s WHERE id=%s", (name, g.user["id"]))
            flash("Account updated.", "success")
            return redirect(url_for("account"))
    return render_template("account.html")

DEFAULT_WINDOW = timedelta(hours=72)
CHART_POINTS = 500
# Every query below filters on one station and one variable, so it can walk
# uq_station_time and look each value up by primary key.
SERIES_FROM = """FROM observations o FORCE INDEX (uq_station_time)
                 STRAIGHT_JOIN observation_values ov
                   ON ov.observation_id=o.id AND ov.variable_id=%s"""


@app.template_filter("dtlocal")
def datetime_local(value):
    return value.strftime("%Y-%m-%dT%H:%M") if value else ""


def int_arg(args, key):
    value = args.get(key, "")
    return int(value) if value.isdigit() else None


def datetime_arg(args, key):
    try:
        return datetime.fromisoformat(args.get(key, ""))
    except ValueError:
        return None


def station_variable_map(stations, variables):
    """Map each station id to the variables it reports, in display order."""
    by_code = {v["code"]: v for v in variables}
    by_id = {v["id"]: v for v in variables}
    mapped, unknown = {}, []
    for station in stations:
        codes = STATION_VARIABLES.get(station["code"])
        if codes is None:
            unknown.append(station["id"])
            mapped[station["id"]] = []
        else:
            mapped[station["id"]] = [by_code[code] for code in codes if code in by_code]
    if unknown:
        placeholders = ",".join(["%s"] * len(unknown))
        for row in query_all(f"""SELECT station_id, variable_id FROM station_variables
                                 WHERE station_id IN ({placeholders})""", unknown):
            mapped[row["station_id"]].append(by_id[row["variable_id"]])
    return mapped


def reading_range(station_id, variable_id):
    """First and last reading time of one variable at one station, or None."""
    sql = "SELECT o.observed_at " + SERIES_FROM + " WHERE o.station_id=%s ORDER BY o.observed_at {} LIMIT 1"
    first = query_one(sql.format("ASC"), (variable_id, station_id))
    if not first:
        return None
    last = query_one(sql.format("DESC"), (variable_id, station_id))
    return first["observed_at"], last["observed_at"]


def reading_window(args, span, suffix=""):
    """Requested start/end, defaulting to the last 72 hours of this series' data."""
    first, last = span
    end = datetime_arg(args, "end" + suffix) or last
    start = datetime_arg(args, "start" + suffix) or max(first, end - DEFAULT_WINDOW)
    return (end, start) if start > end else (start, end)


def series_summary(station_id, variable_id, start, end):
    summary = query_one(
        """SELECT COUNT(*) AS count, MIN(ov.value) AS minimum,
                  MAX(ov.value) AS maximum, AVG(ov.value) AS average """ + SERIES_FROM +
        " WHERE o.station_id=%s AND o.observed_at BETWEEN %s AND %s",
        (variable_id, station_id, start, end),
    )
    return summary if summary["count"] else None


def series_points(station_id, variable_id, start, end):
    """Chart points for [start, end], averaged into at most CHART_POINTS buckets."""
    five_minutes = 300
    buckets = math.ceil((end - start).total_seconds() / five_minutes / CHART_POINTS)
    bucket = max(1, buckets) * five_minutes
    # Buckets are aligned to a fixed epoch so two series share timestamps on the compare chart.
    epoch = datetime(2000, 1, 1)
    rows = query_all(
        "SELECT TIMESTAMPDIFF(SECOND, %s, o.observed_at) DIV %s AS bucket, AVG(ov.value) AS value "
        + SERIES_FROM + """ WHERE o.station_id=%s AND o.observed_at BETWEEN %s AND %s
                            GROUP BY bucket ORDER BY bucket""",
        (epoch, bucket, variable_id, station_id, start, end),
    )
    points = [{"observed_at": str(epoch + timedelta(seconds=int(row["bucket"]) * bucket)),
               "value": float(row["value"])} for row in rows]
    minutes = bucket // 60
    label = "" if bucket == five_minutes else (
        f"{minutes}-minute averages" if minutes < 120 else f"{minutes / 60:g}-hour averages")
    return points, label


def latest_cards(stations, station_vars):
    """Most recent reading of every station, with one value per reported variable."""
    latest = query_all(
        """SELECT o.id, o.station_id, o.observed_at FROM observations o
           JOIN (SELECT station_id, MAX(observed_at) AS observed_at
                 FROM observations GROUP BY station_id) newest
             ON newest.station_id=o.station_id AND newest.observed_at=o.observed_at"""
    )
    by_station = {row["station_id"]: row for row in latest}
    values = {}
    if latest:
        placeholders = ",".join(["%s"] * len(latest))
        for row in query_all(f"""SELECT observation_id, variable_id, value FROM observation_values
                                 WHERE observation_id IN ({placeholders})""",
                             [row["id"] for row in latest]):
            values[row["observation_id"], row["variable_id"]] = row["value"]
    newest = max((row["observed_at"] for row in latest), default=None)
    cards = []
    for station in stations:
        reading = by_station.get(station["id"])
        cards.append({
            "station": station,
            "observed_at": reading["observed_at"] if reading else None,
            "offline": not reading or reading["observed_at"] < newest - DEFAULT_WINDOW,
            "readings": [(variable, values.get((reading["id"], variable["id"])) if reading else None)
                         for variable in station_vars[station["id"]]],
        })
    return cards


@app.get("/observations")
@login_required
def observations():
    stations, variables = catalog()
    station_vars = station_variable_map(stations, variables)
    station_id = int_arg(request.args, "station_id")
    if station_id not in station_vars:
        station_id = None
    choices = station_vars.get(station_id, [])
    variable_id = int_arg(request.args, "variable_id")
    variable = next((v for v in choices if v["id"] == variable_id), None)
    cards = [card for card in latest_cards(stations, station_vars)
             if station_id in (None, card["station"]["id"])]
    context = {"stations": stations, "station_id": station_id, "choices": choices,
               "variable": variable, "cards": cards, "span": None}
    if variable:
        span = reading_range(station_id, variable["id"])
        if span:
            start, end = reading_window(request.args, span)
            rows = query_all(
                "SELECT o.observed_at, ov.value " + SERIES_FROM +
                """ WHERE o.station_id=%s AND o.observed_at BETWEEN %s AND %s
                    ORDER BY o.observed_at DESC LIMIT 500""",
                (variable["id"], station_id, start, end),
            )
            chart, chart_label = series_points(station_id, variable["id"], start, end)
            context.update(
                span=span, start=start, end=end, rows=rows, chart=chart, chart_label=chart_label,
                stats=series_summary(station_id, variable["id"], start, end),
                default_window=not (request.args.get("start") or request.args.get("end")),
            )
    return render_template("observations.html", **context)


@app.get("/compare")
@login_required
def compare():
    stations, variables = catalog()
    station_vars = station_variable_map(stations, variables)
    names = {s["id"]: s["name"] for s in stations}
    picked = {key: int_arg(request.args, f"station_{key}") for key in ("a", "b")}
    picked = {key: (sid if sid in station_vars else None) for key, sid in picked.items()}
    shared = []
    if all(picked.values()):
        other = {v["id"] for v in station_vars[picked["b"]]}
        shared = [v for v in station_vars[picked["a"]] if v["id"] in other]
    variable_id = int_arg(request.args, "variable_id")
    variable = next((v for v in shared if v["id"] == variable_id), None)
    series = []
    for key, station_id in picked.items():
        if not variable:
            break
        span = reading_range(station_id, variable["id"])
        entry = {"key": key, "station": names[station_id], "span": span,
                 "summary": None, "points": []}
        if span:
            entry["start"], entry["end"] = reading_window(request.args, span, f"_{key}")
            entry["summary"] = series_summary(station_id, variable["id"], entry["start"], entry["end"])
            entry["points"], _ = series_points(station_id, variable["id"], entry["start"], entry["end"])
        series.append(entry)
    return render_template("compare.html", stations=stations, picked=picked, shared=shared,
                           variable=variable, series=series)


@app.get("/observations/export.csv")
@login_required
def export_observations():
    station_id = int_arg(request.args, "station_id")
    variable_id = int_arg(request.args, "variable_id")
    span = reading_range(station_id, variable_id) if station_id and variable_id else None
    if not span:
        flash("Choose a station and measurement with readings to export.", "warning")
        return redirect(url_for("observations"))
    start, end = reading_window(request.args, span)
    rows = query_all(
        "SELECT o.observed_at, s.code AS station, wv.code AS variable, ov.value, wv.unit "
        + SERIES_FROM + """ JOIN stations s ON s.id=o.station_id
                            JOIN weather_variables wv ON wv.id=ov.variable_id
                            WHERE o.station_id=%s AND o.observed_at BETWEEN %s AND %s
                            ORDER BY o.observed_at""",
        (variable_id, station_id, start, end),
    )
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("observed_at", "station", "variable", "value", "unit"))
    for row in rows:
        writer.writerow(row.values())
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=weather-export.csv"})


@app.route("/alerts", methods=("GET", "POST"))
@login_required
def alerts():
    stations, variables = catalog()
    if request.method == "POST":
        try:
            station_id = int(request.form["station_id"])
            variable_id = int(request.form["variable_id"])
            threshold = float(request.form["threshold"])
            operator = request.form["operator"]
            if operator not in {">", ">=", "<", "<=", "="}:
                raise ValueError
            mapped = query_one("SELECT 1 FROM station_variables WHERE station_id=%s AND variable_id=%s", (station_id, variable_id))
            if not mapped:
                raise ValueError
            execute("INSERT INTO alert_rules (user_id, station_id, variable_id, operator, threshold) VALUES (%s,%s,%s,%s,%s)",
                    (g.user["id"], station_id, variable_id, operator, threshold))
            flash("Alert rule created.", "success")
            return redirect(url_for("alerts"))
        except (KeyError, ValueError):
            flash("Choose a valid station/variable combination, operator, and threshold.", "danger")
    rules = query_all(
        """SELECT ar.*, s.name AS station, wv.name AS variable, wv.unit
           FROM alert_rules ar JOIN stations s ON s.id=ar.station_id
           JOIN weather_variables wv ON wv.id=ar.variable_id
           WHERE ar.user_id=%s ORDER BY ar.created_at DESC""", (g.user["id"],),
    )
    return render_template("alerts.html", stations=stations, variables=variables, rules=rules)


@app.post("/alerts/<int:rule_id>/toggle")
@login_required
def toggle_alert(rule_id):
    execute("UPDATE alert_rules SET enabled=NOT enabled WHERE id=%s AND user_id=%s", (rule_id, g.user["id"]))
    return redirect(url_for("alerts"))


@app.post("/alerts/<int:rule_id>/edit")
@login_required
def edit_alert(rule_id):
    try:
        operator = request.form["operator"]
        threshold = float(request.form["threshold"])
        if operator not in {">", ">=", "<", "<=", "="}:
            raise ValueError
        execute("UPDATE alert_rules SET operator=%s,threshold=%s WHERE id=%s AND user_id=%s",
                (operator, threshold, rule_id, g.user["id"]))
        flash("Alert rule updated.", "success")
    except (KeyError, ValueError):
        flash("Enter a valid operator and threshold.", "danger")
    return redirect(url_for("alerts"))


@app.post("/alerts/<int:rule_id>/test")
@login_required
def test_alert(rule_id):
    """Check a rule against its station's latest real reading and notify if it matches."""
    rule = query_one(RULE_SELECT + " WHERE ar.id=%s AND ar.user_id=%s", (rule_id, g.user["id"]))
    if not rule:
        abort(404)
    reading = query_one(
        "SELECT o.id, o.observed_at, ov.value " + SERIES_FROM +
        " WHERE o.station_id=%s ORDER BY o.observed_at DESC LIMIT 1",
        (rule["variable_id"], rule["station_id"]),
    )
    if not reading:
        flash(f'{rule["station"]} has no {rule["name"].lower()} readings to test against.', "warning")
        return redirect(url_for("alerts"))
    value = float(reading["value"])
    latest = f'Latest reading ({reading["observed_at"]}) is {value:g} {rule["unit"]}'
    if not condition_met(value, rule["operator"], float(rule["threshold"])):
        flash(f'{latest}, which is not {rule["operator"]} {float(rule["threshold"]):g}, so no '
              "notification was sent. Adjust the threshold to trigger it.", "warning")
        return redirect(url_for("alerts"))
    connection = get_db()
    with connection.cursor() as cursor:
        fired = fire_alert(cursor, rule, reading["id"], value, prefix="[Test] ")
    connection.commit()
    if fired:
        flash(f"{latest}. Test alert fired; check Notifications.", "success")
    else:
        flash(f"{latest}. This rule already fired for that reading; see Notifications.", "info")
    return redirect(url_for("alerts"))


@app.post("/alerts/<int:rule_id>/delete")
@login_required
def delete_alert(rule_id):
    execute("DELETE FROM alert_rules WHERE id=%s AND user_id=%s", (rule_id, g.user["id"]))
    flash("Alert rule deleted.", "success")
    return redirect(url_for("alerts"))


@app.get("/notifications")
@login_required
def notifications():
    items = query_all("SELECT * FROM notifications WHERE user_id=%s ORDER BY created_at DESC LIMIT 200", (g.user["id"],))
    return render_template("notifications.html", notifications=items)


@app.post("/notifications/read")
@login_required
def read_notifications():
    execute("UPDATE notifications SET is_read=1 WHERE user_id=%s", (g.user["id"],))
    return redirect(url_for("notifications"))


def parse_timestamp(raw):
    raw = raw.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=None)
    except ValueError:
        for pattern in ("%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%Y%m%d%H%M"):
            try:
                return datetime.strptime(raw, pattern)
            except ValueError:
                continue
    raise ValueError(f"Unsupported timestamp: {raw}")


def condition_met(value, operator, threshold):
    return {">": value > threshold, ">=": value >= threshold, "<": value < threshold,
            "<=": value <= threshold, "=": value == threshold}[operator]


RULE_SELECT = """SELECT ar.id, ar.user_id, ar.station_id, ar.variable_id, ar.operator, ar.threshold,
                        wv.name, wv.unit, s.name AS station
                 FROM alert_rules ar JOIN weather_variables wv ON wv.id=ar.variable_id
                 JOIN stations s ON s.id=ar.station_id"""


def fire_alert(cursor, rule, observation_id, value, prefix=""):
    """Record an alert event and its notification; False if this reading already fired."""
    cursor.execute("INSERT IGNORE INTO alert_events (alert_rule_id, observation_id, observed_value) VALUES (%s,%s,%s)",
                   (rule["id"], observation_id, value))
    if not cursor.rowcount:
        return False
    message = f'{prefix}{rule["station"]}: {rule["name"]} reached {value:g} {rule["unit"]} ({rule["operator"]} {float(rule["threshold"]):g}).'
    cursor.execute("INSERT INTO notifications (user_id, alert_event_id, message) VALUES (%s,%s,%s)",
                   (rule["user_id"], cursor.lastrowid, message))
    return True


def evaluate_alerts(cursor, observation_id, station_id, variable_id, value):
    cursor.execute(RULE_SELECT + " WHERE ar.enabled=1 AND ar.station_id=%s AND ar.variable_id=%s",
                   (station_id, variable_id))
    for rule in cursor.fetchall():
        if condition_met(value, rule["operator"], float(rule["threshold"])):
            fire_alert(cursor, rule, observation_id, value)


@app.route("/admin", methods=("GET", "POST"))
@admin_required
def admin():
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "station":
                execute("INSERT INTO stations (code,name,latitude,longitude) VALUES (%s,%s,%s,%s)",
                        (request.form["code"].strip(), request.form["name"].strip(),
                         request.form.get("latitude") or None, request.form.get("longitude") or None))
            elif action == "variable":
                execute("INSERT INTO weather_variables (code,name,unit) VALUES (%s,%s,%s)",
                        (request.form["code"].strip(), request.form["name"].strip(), request.form["unit"].strip()))
            elif action == "mapping":
                execute("INSERT INTO station_variables (station_id,variable_id,source_column) VALUES (%s,%s,%s)",
                        (int(request.form["station_id"]), int(request.form["variable_id"]), request.form["source_column"].strip()))
            else:
                raise ValueError
            flash("Catalog updated.", "success")
            return redirect(url_for("admin"))
        except (KeyError, ValueError, pymysql.MySQLError) as error:
            get_db().rollback()
            flash(f"Could not update catalog: {error}", "danger")
    stations, variables = catalog()
    mappings = query_all("""SELECT sv.station_id, sv.variable_id, sv.source_column, s.name AS station, wv.name AS variable
                            FROM station_variables sv JOIN stations s ON s.id=sv.station_id
                            JOIN weather_variables wv ON wv.id=sv.variable_id ORDER BY s.name,wv.name""")
    imports = query_all("""SELECT di.*, s.name AS station, u.email FROM data_imports di
                           JOIN stations s ON s.id=di.station_id JOIN users u ON u.id=di.imported_by
                           ORDER BY di.created_at DESC LIMIT 100""")
    return render_template("admin.html", stations=stations, variables=variables, mappings=mappings, imports=imports)


@app.post("/admin/import")
@admin_required
def import_csv():
    upload = request.files.get("file")
    try:
        station_id = int(request.form["station_id"])
    except (KeyError, ValueError):
        station_id = 0
    if not upload or not upload.filename.lower().endswith(".csv") or not station_id:
        flash("Select a station and a CSV file.", "danger")
        return redirect(url_for("admin"))
    raw = upload.read()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        import_id = execute(
            "INSERT INTO data_imports (station_id,imported_by,filename,file_hash) VALUES (%s,%s,%s,%s)",
            (station_id, g.user["id"], upload.filename[:255], digest),
        )
    except pymysql.err.IntegrityError:
        get_db().rollback()
        flash("This file has already been imported for the selected station.", "warning")
        return redirect(url_for("admin"))
    connection = get_db()
    count = 0
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        timestamp_column = next((c for c in reader.fieldnames if c.strip().lower() in {"timestamp", "datetime", "date_time", "observed_at"}), None)
        if not timestamp_column:
            raise ValueError("CSV needs a timestamp, datetime, date_time, or observed_at column")
        mappings = query_all("SELECT variable_id, source_column FROM station_variables WHERE station_id=%s", (station_id,))
        available = [m for m in mappings if m["source_column"] in reader.fieldnames]
        if not available:
            raise ValueError("None of this station's configured measurement columns are present")
        with connection.cursor() as cursor:
            for line_number, row in enumerate(reader, 2):
                observed_at = parse_timestamp(row.get(timestamp_column, ""))
                cursor.execute("INSERT IGNORE INTO observations (station_id,data_import_id,observed_at) VALUES (%s,%s,%s)",
                               (station_id, import_id, observed_at))
                if not cursor.rowcount:
                    continue
                observation_id = cursor.lastrowid
                for mapping in available:
                    try:
                        value = numeric_value(row.get(mapping["source_column"]))
                    except ValueError as error:
                        raise ValueError(f"Invalid number on CSV row {line_number}, column {mapping['source_column']}") from error
                    if value is None:
                        continue
                    cursor.execute("INSERT INTO observation_values (observation_id,variable_id,value) VALUES (%s,%s,%s)",
                                   (observation_id, mapping["variable_id"], value))
                    evaluate_alerts(cursor, observation_id, station_id, mapping["variable_id"], value)
                count += 1
            cursor.execute("UPDATE data_imports SET status='succeeded',rows_imported=%s,finished_at=NOW() WHERE id=%s", (count, import_id))
        connection.commit()
        flash(f"Import completed: {count} new observations.", "success")
    except Exception as error:
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE data_imports SET status='failed',error_message=%s,finished_at=NOW() WHERE id=%s", (str(error)[:2000], import_id))
        connection.commit()
        flash(f"Import failed: {error}", "danger")
    return redirect(url_for("admin"))


@app.cli.command("init-db")
def init_db_command():
    schema_path = os.path.join(app.root_path, "schema.sql")
    with open(schema_path, encoding="utf-8") as schema_file:
        statements = [part.strip() for part in schema_file.read().split(";") if part.strip()]
    connection = pymysql.connect(**db_config(with_database=False))
    try:
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
        connection.commit()
        print("Database initialized.")
    finally:
        connection.close()


@app.cli.command("load-data")
def load_data_command():
    """Bulk-load downloaded SJSU station CSVs into MySQL."""
    from data_loader import load_archive

    data_directory = os.path.join(app.root_path, "data", "raw")
    connection = pymysql.connect(**db_config())
    try:
        totals = load_archive(
            connection,
            data_directory,
            parse_timestamp,
            progress=lambda message: print(message, flush=True),
        )
        print(
            f"Finished: {totals['files']} files loaded, "
            f"{totals['skipped']} unchanged files skipped, "
            f"{totals['rows']:,} new observations."
        )
    finally:
        connection.close()


@app.cli.command("data-stats")
def data_stats_command():
    """Print current database population counts."""
    connection = pymysql.connect(**db_config())
    try:
        with connection.cursor() as cursor:
            for table in ("stations", "weather_variables", "observations",
                          "observation_values", "data_imports"):
                cursor.execute(f"SELECT COUNT(*) AS total FROM {table}")
                print(f"{table}: {cursor.fetchone()['total']:,}")
            cursor.execute(
                """SELECT s.name,COUNT(o.id) AS observations
                   FROM stations s LEFT JOIN observations o ON o.station_id=s.id
                   GROUP BY s.id,s.name ORDER BY s.name"""
            )
            print("\nBy station:")
            for row in cursor.fetchall():
                print(f"  {row['name']}: {row['observations']:,}")
    finally:
        connection.close()


@app.cli.command("optimize-db")
def optimize_db_command():
    """Refresh MySQL statistics after a large data import."""
    connection = pymysql.connect(**db_config())
    try:
        with connection.cursor() as cursor:
            cursor.execute("ANALYZE TABLE observations,observation_values")
            for row in cursor.fetchall():
                print(f"{row['Table']}: {row['Msg_text']}")
        connection.commit()
    finally:
        connection.close()


@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="You do not have permission to view this page."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="That page could not be found."), 404


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
