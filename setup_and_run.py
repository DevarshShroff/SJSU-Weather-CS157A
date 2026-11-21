#!/usr/bin/env python3
"""Interactive setup and launcher for the SJSU Campus Weather app.

    python3 setup_and_run.py             # guided setup, then launch
    python3 setup_and_run.py --run-only  # just launch

Every step is idempotent; prompts default to the values already in .env.
"""
import argparse
import getpass
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
DB_NAME = "sjsu_weather"  # hardcoded in schema.sql
ENV_KEYS = ("FLASK_APP", "FLASK_DEBUG", "SECRET_KEY", "DB_HOST", "DB_PORT",
            "DB_USER", "DB_PASSWORD", "DB_NAME")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def ask(prompt, default=""):
    return input(f"{prompt}{f' [{default}]' if default else ''}: ").strip() or default


def confirm(prompt, default=True):
    answer = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not answer else answer.startswith("y")


def ask_secret(prompt, allow_empty=False):
    while not (value := getpass.getpass(f"{prompt}: ")) and not allow_empty:
        print("A value is required.")
    return value


def port_open(host, port, timeout=1.0):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


# --- Stage 1 (system Python): create the virtual environment ----------------

def working_python(directory):
    for candidate in ("bin/python", "Scripts/python.exe", "bin/python.exe"):
        path = directory / candidate
        try:
            subprocess.run([path, "-c", ""], check=True, capture_output=True, timeout=60)
            return path
        except (OSError, subprocess.SubprocessError):
            continue
    return None


REQUIREMENTS_CHECK = ("import flask, pymysql, dotenv; "
                      "from cryptography.hazmat.primitives.asymmetric import padding")


def requirements_ok(python):
    return subprocess.run([python, "-c", REQUIREMENTS_CHECK], capture_output=True).returncode == 0


def install_requirements(python, check=True):
    print("Installing requirements ...")
    subprocess.run([python, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                    "-r", ROOT / "requirements.txt"], check=check)


def prepare_venv():
    if sys.version_info < (3, 9):
        sys.exit(f"Python 3.9+ is required; this is {sys.version.split()[0]}.")
    # A venv only works on the machine that built it (it links to that machine's Python
    # and holds binaries for its OS/CPU), so a copied one is rebuilt rather than patched.
    venv_dir = ROOT / ".venv"
    python = working_python(venv_dir)
    if python and not requirements_ok(python):
        install_requirements(python, check=False)
    if python and requirements_ok(python):
        return python
    if venv_dir.exists():
        print(".venv/ was built on another machine or is broken; rebuilding it ...")
    else:
        print("Creating virtual environment .venv/ ...")
    subprocess.run([sys.executable, "-m", "venv", "--clear", venv_dir], check=True)
    python = working_python(venv_dir)
    if not python:
        sys.exit(f"Could not create a working virtual environment with {sys.executable}.")
    install_requirements(python)
    if not requirements_ok(python):
        sys.exit(f"Requirements installed but still fail to import; run "
                 f"{python} -c \"{REQUIREMENTS_CHECK}\" to see why.")
    return python


# --- Stage 2 (inside the venv): configure MySQL, load data, launch ----------

def connect(config, user=None, password=None, database=None):
    import pymysql
    return pymysql.connect(host=config["DB_HOST"], port=int(config["DB_PORT"]),
                           user=user or config["DB_USER"],
                           password=config["DB_PASSWORD"] if password is None else password,
                           database=database, connect_timeout=10, autocommit=True)


def flask(config, *args):
    subprocess.run([sys.executable, "-m", "flask", "--app", "app.py", *args],
                   cwd=ROOT, env={**os.environ, **config}, check=True)


def collect_config():
    from dotenv import dotenv_values
    old = {k: v or "" for k, v in dotenv_values(ENV_FILE).items()}
    print("\n=== Settings ===")
    config = {
        "FLASK_APP": "app.py",
        "FLASK_DEBUG": old.get("FLASK_DEBUG", "1"),
        "DB_HOST": ask("MySQL host", old.get("DB_HOST") or "127.0.0.1"),
        "DB_PORT": ask("MySQL port", old.get("DB_PORT") or "3306"),
        "DB_USER": ask("MySQL app user (created if missing)", old.get("DB_USER") or "weather_app"),
        "DB_NAME": DB_NAME,
    }
    current = old.get("DB_PASSWORD", "")
    has_password = current not in {"", "change-me"}
    prompt = f"MySQL password for '{config['DB_USER']}'"
    config["DB_PASSWORD"] = ask_secret(prompt + (" (Enter keeps current)" if has_password else ""),
                                       allow_empty=has_password) or current
    secret = old.get("SECRET_KEY", "")
    if len(secret) < 16 or secret.startswith("replace-"):
        secret = secrets.token_hex(32)
        print("SECRET_KEY was missing or weak; generated a new one.")
    config["SECRET_KEY"] = secret

    if ENV_FILE.exists():
        shutil.copyfile(ENV_FILE, ENV_FILE.with_name(".env.bak"))
        print("Backed up the previous .env to .env.bak.")
    escape = lambda v: v.replace("\\", "\\\\").replace("'", "\\'")
    ENV_FILE.write_text("".join(f"{k}='{escape(config[k])}'\n" for k in ENV_KEYS))
    print("Saved .env.")
    return config


def ensure_mysql(config):
    print("\n=== MySQL ===")
    while not port_open(config["DB_HOST"], config["DB_PORT"]):
        print(f"MySQL isn't reachable at {config['DB_HOST']}:{config['DB_PORT']}. Start it "
              "(macOS: System Settings > MySQL, or `brew services start mysql`; "
              "Windows: the MySQL80 service).")
        if not confirm("Retry?"):
            sys.exit("MySQL is required.")


def ensure_app_user(config):
    import pymysql
    while True:
        try:
            connect(config).close()
            return print(f"Connected as '{config['DB_USER']}'.")
        except pymysql.err.OperationalError as error:
            if error.args[0] not in {1045, 1698}:  # access denied
                raise
            print(f"MySQL rejected '{config['DB_USER']}': {error.args[1]}")
        if not confirm("Create/repair this user with an admin account (e.g. root)?"):
            sys.exit("Fix the credentials in .env and re-run.")
        admin_user = ask("MySQL admin user", "root")
        try:
            admin = connect(config, admin_user, ask_secret(f"Password for '{admin_user}'", True))
        except pymysql.err.OperationalError as error:
            print(f"Admin login failed: {error.args[1]}")
            continue
        with admin, admin.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME} "
                           "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            for host in ["localhost", "%"] if config["DB_HOST"] in LOCAL_HOSTS else ["%"]:
                account = (config["DB_USER"], host)
                cursor.execute("CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s",
                               (*account, config["DB_PASSWORD"]))
                cursor.execute("ALTER USER %s@%s IDENTIFIED BY %s", (*account, config["DB_PASSWORD"]))
                cursor.execute(f"GRANT ALL PRIVILEGES ON {DB_NAME}.* TO %s@%s", account)


def setup_data(config):
    print("\n=== Weather data ===")
    have_csvs = any((ROOT / "data" / "raw").glob("*/*.csv"))
    downloaded = confirm("Download the latest CSVs from met.sjsu.edu (~110 MB)?", not have_csvs)
    if downloaded:
        subprocess.run([sys.executable, ROOT / "scripts" / "download_sjsu_data.py"], check=True)
    with connect(config, database=DB_NAME) as db, db.cursor() as cursor:
        cursor.execute("SELECT EXISTS(SELECT 1 FROM observations)")
        empty = not cursor.fetchone()[0]
    prompt = ("Load all CSVs into MySQL? (~1.3M rows, several minutes)" if empty
              else "Load new or changed CSVs into MySQL?")
    if confirm(prompt, empty or downloaded):
        flask(config, "load-data")
        flask(config, "optimize-db")
    flask(config, "data-stats")


def setup_admin(config):
    from werkzeug.security import generate_password_hash
    print("\n=== Admin account ===")
    with connect(config, database=DB_NAME) as db, db.cursor() as cursor:
        cursor.execute("""SELECT u.email FROM users u JOIN roles r ON r.id=u.role_id
                          WHERE r.name='admin' AND u.email<>'system-import@sjsu.local'""")
        admins = [row[0] for row in cursor.fetchall()]
        print("Existing admins: " + (", ".join(admins) or "none"))
        if not confirm("Create or promote an admin account?", not admins):
            return
        email = ask("Admin email").lower()
        if email in admins:
            return print(f"{email} is already an admin.")
        admin_role = "(SELECT id FROM roles WHERE name='admin')"
        if cursor.execute(f"UPDATE users SET role_id={admin_role} WHERE email=%s", (email,)):
            return print(f"Promoted {email} to admin.")
        while len(password := ask_secret("Password (10+ characters)")) < 10:
            print("Too short.")
        cursor.execute(f"""INSERT INTO users (role_id,email,display_name,password_hash)
                           VALUES ({admin_role},%s,%s,%s)""",
                       (email, ask("Display name", email.split("@")[0]),
                        generate_password_hash(password)))
        print(f"Created admin {email}.")


def launch(config):
    port = next(p for p in range(5000, 5100) if not port_open("127.0.0.1", p, 0.3))
    url = f"http://127.0.0.1:{port}/"
    server = subprocess.Popen([sys.executable, "-m", "flask", "--app", "app.py", "run",
                               "--host", "127.0.0.1", "--port", str(port)],
                              cwd=ROOT, env={**os.environ, **config})
    try:
        for _ in range(60):
            if server.poll() is not None:
                break
            if port_open("127.0.0.1", port, 0.5):
                print(f"\nApp running at {url} (Ctrl+C to stop)\n")
                webbrowser.open(url)
                break
            time.sleep(0.5)
        return server.wait()
    except KeyboardInterrupt:
        server.terminate()
        server.wait()
        return 0


def stage_two(run_only):
    if run_only:
        from dotenv import dotenv_values
        if not ENV_FILE.exists():
            sys.exit("No .env found; run without --run-only first.")
        config = {k: v or "" for k, v in dotenv_values(ENV_FILE).items()}
        ensure_mysql(config)
        return launch(config)
    config = collect_config()
    ensure_mysql(config)
    ensure_app_user(config)
    flask(config, "init-db")
    setup_data(config)
    setup_admin(config)
    return launch(config) if confirm("\nStart the app and open the browser?") else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-only", action="store_true", help="skip setup, just launch")
    parser.add_argument("--in-venv", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.in_venv:
            return stage_two(args.run_only)
        command = [prepare_venv(), __file__, "--in-venv"] + ["--run-only"] * args.run_only
        sys.stdout.flush()
        child = subprocess.Popen(command, cwd=ROOT)
        while True:
            try:
                return child.wait()
            except KeyboardInterrupt:  # the child receives Ctrl+C and shuts down itself
                pass
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except subprocess.CalledProcessError as error:
        print(f"\nStep failed: {' '.join(map(str, error.cmd))}")
        return error.returncode


if __name__ == "__main__":
    sys.exit(main())
