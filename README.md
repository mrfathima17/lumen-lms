# Lumen LMS

A role-based learning management system built with Django. Students, lecturers and administrators get their own dashboards for courses, quizzes, assignments, grading, attendance, messaging and system administration.

The project is backed by an automated test suite of **720 pytest tests with 96% line coverage**, plus **42 Playwright browser tests** that drive a real browser through key user journeys. The suite passes on both Windows and Linux.

![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![Django](https://img.shields.io/badge/django-5.2-green) ![Tests](https://img.shields.io/badge/tests-720%20passing-brightgreen) ![Coverage](https://img.shields.io/badge/coverage-96%25-brightgreen)

## Highlights

- **Role-based access control** for students, lecturers and administrators, enforced on every page and download
- **Assessment tools:** timed quizzes with auto-marking, assignments with rubrics, a reusable question bank, polls and surveys
- **Weighted gradebook** with a configurable grade scale, published results and GPA calculation
- **Security features:** optional two-factor sign-in (TOTP), login throttling, IP allow-lists, a full audit log and per-user session control
- **Operations built in:** backups, maintenance mode, background jobs, health check endpoint and CSV import/export
- **Self-hosted front end:** HTMX and Alpine.js are vendored, with no CDN dependency

## Tech stack

| Area | Technology |
|---|---|
| Backend | Python, Django 5.2 |
| Database | MySQL 8 / MariaDB (SQLite for local development and tests) |
| Front end | Django templates, HTMX, Alpine.js, custom CSS |
| Background jobs | Celery and Redis |
| Security | django-otp (two-factor), django-axes (login throttling) |
| Documents | ReportLab (PDF certificates), segno (QR codes) |
| Deployment | Docker Compose, nginx, gunicorn, WhiteNoise |
| Testing | pytest, pytest-django, pytest-cov |

## Features by role

| Role | What they can do |
|---|---|
| **Student** | Browse and enrol in courses, take timed quizzes, submit assignments, track grades and GPA, view attendance, use the calendar and to-do list, message classmates and lecturers, download completion certificates |
| **Lecturer** | Manage course content, build quizzes and rubrics, mark submissions, run the gradebook, take attendance, post announcements, view course reports |
| **Administrator** | Manage users and roles, bulk import and enrol, configure system settings, theme and modules, review the audit log, manage backups and maintenance mode, control two-factor policy |

See [docs/MODULES.md](docs/MODULES.md) for the full module reference.

## Getting started

Requires Python 3.10 or newer (the Docker image uses 3.13). The quick start uses SQLite, so no database server is needed.

**Windows (PowerShell)**
```powershell
git clone https://github.com/mrfathima17/lumen-lms.git
cd lumen-lms
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
$env:DJANGO_SETTINGS_MODULE = "config.settings.sqlite"
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo      # optional: demo users and courses
python manage.py runserver
```

**macOS / Linux**
```bash
git clone https://github.com/mrfathima17/lumen-lms.git
cd lumen-lms
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
export DJANGO_SETTINGS_MODULE=config.settings.sqlite
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo      # optional: demo users and courses
python manage.py runserver
```

Then open http://127.0.0.1:8000. Superusers receive the administrator role.

**Full stack with Docker** (MySQL, Redis, worker, scheduler, nginx):
```bash
cp .env.example .env            # then edit the secrets
docker compose up --build
docker compose exec web python manage.py createsuperuser
```

## Running the tests

```bash
pytest                                   # full suite on SQLite, no server needed
pytest -k reports                        # only tests matching a keyword
pytest --cov=apps --cov-report=term      # with coverage (requires pytest-cov)
pytest --ds=config.settings.test_mysql   # against a real MySQL or MariaDB server
```

**Browser (end-to-end) tests** use Playwright and run separately, so the main suite stays fast:
```bash
pip install -r requirements-e2e.txt
playwright install chromium
pytest e2e -o python_files="test_*.py"           # headless
pytest e2e -o python_files="test_*.py" --headed  # watch the browser
```

### Testing approach

Every feature ships with automated tests. The suite focuses on the areas where bugs hurt most:

- **Permissions and roles:** students, other lecturers and anonymous users are denied (403 or redirect) on staff-only pages and downloads
- **Input validation:** date ranges, enrolment rules, file upload rules, password strength, CSV import with preview and server-side re-validation
- **Business rules:** late penalties, weighted grades, GPA, attendance percentages, quiz timing and auto-submit, completion rules
- **Security behaviour:** two-factor flow and code reuse, lockout protection for administrators, same-site redirects
- **Auditability:** sensitive actions (settings changes, exports, resets) are written to the audit log
- **Output formats:** PDF certificates, CSV exports, `.ics` calendar downloads
- **Database portability:** the suite also runs against MariaDB 10.11
- **Cross-platform:** verified on Windows and Linux. Two Windows-only defects were found and fixed (see [docs/BUG_REPORTS.md](docs/BUG_REPORTS.md))
- **Browser journeys:** Playwright tests go through the real screens: students take quizzes, submit assignments, enrol with a key, message lecturers and post to forums; lecturers post announcements, grade work, create quizzes and take attendance; administrators create and disable users, rebrand the site and read the audit log. A separate group checks that each role is blocked from pages it should not reach

Tests use pytest fixtures (`tests/conftest.py`) to create users, courses and enrolments, and Django's test client to exercise views end to end.

## Project structure

```
lumen-lms/
├── apps/              # Django apps: accounts, courses, quizzes, assignments, grading,
│                      # attendance, schedule, messaging, surveys, files, completion,
│                      # content, administration, core
├── config/            # settings (base, dev, prod, sqlite, test, test_mysql), urls, celery
├── templates/         # HTML templates
├── static/            # CSS, vendored JS, fonts
├── tests/             # pytest suite (backend and integration)
├── e2e/               # Playwright browser tests
├── docker/            # nginx configuration
├── docs/              # module reference, test plan, bug reports
└── manage.py
```

## Configuration

Settings are read from environment variables. Copy `.env.example` to `.env` and set at least `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` and the database and email values. Production settings refuse to start with an insecure secret key.

## Documentation

| Document | Contents |
|---|---|
| [docs/MODULES.md](docs/MODULES.md) | What each module does, its rules and its management commands, plus background jobs |
| [docs/TEST_PLAN.md](docs/TEST_PLAN.md) | What is tested, how, in which environments, and known gaps |
| [docs/BUG_REPORTS.md](docs/BUG_REPORTS.md) | Defects found by testing on Windows, with root cause and fix |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Server setup, HTTPS, backups and restore, updates, monitoring, security checklist |
| [PYCHARM.md](PYCHARM.md) | Step-by-step PyCharm setup |

## Project status

Core modules are complete and covered by the test suite. Work continues on remaining modules and polish.

**Roadmap**
- Run the test suite automatically on Windows and Linux with GitHub Actions (workflow file is ready in `.github/workflows`)
- Add browser tests for two-factor sign-in and CSV user import

## Conventions

- Student quiz pages live under `/quizzes/` and the lecturer editor under `/quiz-manager/`, so lecturers are not locked out by campus network rules
- htmx and Alpine.js are vendored in `static/js`
- No inline styles except data-driven widths
