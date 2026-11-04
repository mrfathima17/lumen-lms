# Running Lumen in PyCharm (SQLite, no database server needed)

SQLite keeps all data in one file, `db.sqlite3`, inside the project folder. Nothing to install.

## One-time setup
1. Unzip the project. In PyCharm: **File > Open**, choose the folder that contains `manage.py`.
2. Let PyCharm create a virtual environment (a popup usually offers it). If not: **File > Settings > Project > Python Interpreter > Add Interpreter > Add Local Interpreter > Virtualenv > New**, Python 3.12 or newer.
3. Open the **Terminal** tab (bottom of PyCharm). The line should start with `(venv)`. Run:
   `pip install -r requirements-dev.txt`

## Every time you want to run it
The project ships ready-made run configurations. At the top right of PyCharm, open the dropdown next to the green triangle. You will see:

| Name | What it does | When |
|---|---|---|
| 1 - Create database tables (migrate) | Creates the tables inside `db.sqlite3` | Once, and again after an update |
| 2 - Add demo data | Adds sample users, courses and marks | Once (optional) |
| 3 - Run Lumen | Starts the website | Every time |
| Create my own admin | Asks for a username and password | If you do not want the demo data |
| 5 - Run tests | Runs all tests | Optional |

First time: choose **1**, press the green triangle, wait for "OK" lines. Choose **2**, press the triangle. Choose **3**, press the triangle, then open http://127.0.0.1:8000/ in your browser.

Demo logins (password `Demo-pass-12345`): `admin`, `nperera` (lecturer), `s2026-0142` (student).

Stop the website with the red square.

## If the run configurations do not appear
They are stored in the `.run` folder. If your PyCharm folder is named differently from `lumen-django`, PyCharm may say "module not found": open **Run > Edit Configurations**, pick the entry, and set the interpreter to your project's venv.
You can always do it by hand in the Terminal:
- Windows PowerShell: `$env:DJANGO_SETTINGS_MODULE="config.settings.sqlite"` then `python manage.py migrate`, `python manage.py seed_demo`, `python manage.py runserver`
- Windows cmd: `set DJANGO_SETTINGS_MODULE=config.settings.sqlite`, then the same three commands
- Mac or Linux: `export DJANGO_SETTINGS_MODULE=config.settings.sqlite`, then the same three commands
(The setting only lasts for that one Terminal window, so type it again in a new window.)

## Using MySQL (XAMPP) instead
1. Start MySQL in XAMPP. In phpMyAdmin create a database `lumen` (collation `utf8mb4_unicode_ci`).
2. In the Terminal: `pip install -r requirements-mysql.txt`
3. In each run configuration, change the environment variables to:
   `DJANGO_SETTINGS_MODULE=config.settings.dev;DB_NAME=lumen;DB_USER=root;DB_PASSWORD=;DB_HOST=127.0.0.1;DB_PORT=3306`
4. Run configurations 1, 2 and 3 as before.
