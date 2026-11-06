# Test Plan: Lumen LMS

## 1. Purpose

This plan describes how Lumen LMS is tested: what is covered, how, in which environments, and what is deliberately left out. It is a living document and is updated as the suite grows.

## 2. Scope

**In scope**
- Role-based access for students, lecturers and administrators
- Courses, enrolment, content and file handling
- Quizzes, question bank, assignments, rubrics and marking
- Gradebook, grade scale, GPA and course completion
- Attendance, timetable, calendar and to-do list
- Messaging, announcements, forums and surveys
- Administration: users, roles, settings, theme, audit log, backups, maintenance mode, CSV import, background jobs
- Security features: two-factor sign-in, password rules, lockout protection, session control

**Out of scope (currently)**
- Browser-level UI testing and cross-browser checks
- Performance and load testing
- Penetration testing
- Accessibility auditing
- Automated testing of JavaScript behaviour

## 3. Test approach

| Level | How |
|---|---|
| Functional and integration | pytest with Django's test client. Requests go through the full stack (URL routing, middleware, view, database, template) without a browser |
| Permission testing | Each staff-only page is requested as a student, as a lecturer of another course, and while signed out. Expected results are 403 or a redirect to sign-in |
| Validation testing | Boundary and invalid inputs, such as end date before start date, oversized or wrong-type uploads, weak passwords and malformed CSV rows. Parametrised tests run many bad values through one check |
| Business-rule testing | Late penalties, weighted grades, GPA, attendance percentages, quiz timing and auto-submit, completion rules |
| Output testing | PDF reports and certificates, CSV exports, `.ics` calendar files |
| Audit testing | Sensitive actions must write an audit-log entry |
| Cross-platform testing | The full suite is run on Windows and Linux |

Negative tests (what must not be allowed) are a priority alongside positive tests, because most serious defects in this kind of system are access or validation failures.

## 4. Test data

Fixtures in `tests/conftest.py` create users (student, lecturer, administrator), courses and enrolments for each test. Every test runs against a fresh, empty database. No real data is used.

## 5. Environments

| Environment | Use |
|---|---|
| Windows, Python 3.14, SQLite | Developer machine, full suite |
| Linux, Python 3.12, SQLite | Full suite |
| MariaDB 10.11 | Optional run of the suite (`config.settings.test_mysql`) to check database portability |
| GitHub Actions (Windows and Linux, Python 3.12 and 3.14) | Automated run on every push. Workflow is in place; it is waiting on a GitHub account billing issue |

## 6. Coverage by area

| Area | Tests |
|---|---|
| Accounts, profile, sign-in and two-factor | 83 |
| Courses, categories and reports | 66 |
| Content, files and assignments | 41 |
| Quizzes, question bank and rubrics | 82 |
| Grading, completion and results | 48 |
| Attendance and schedule | 38 |
| Messaging and surveys | 52 |
| Administration, audit, backups, import and theme | 272 |
| Dashboards | 38 |
| **Total** | **720** |

Line coverage measured with pytest-cov over `apps/`: **96%**.

## 7. Entry and exit criteria

**Entry:** code builds, migrations apply, and dependencies install from `requirements-dev.txt`.

**Exit (ready to release):**
- All tests pass on Windows and Linux
- No open defect of High severity
- New features come with tests before merging

## 8. Defect handling

Defects are recorded with steps to reproduce, expected and actual results, root cause, fix and verification, and rated High, Medium or Low. Examples are in [BUG_REPORTS.md](BUG_REPORTS.md). Every fixed defect should leave behind a test, or a fix to an existing test, so it cannot return unnoticed.

## 9. Risks and known gaps

- **No browser tests.** Layout, JavaScript and real click-through flows are not checked by the suite.
- **Platform differences.** Two defects only appeared on Windows (see BUG-001 and BUG-002). Running both platforms in CI is the control for this.
- **Coverage is not correctness.** 96% line coverage shows code was run, not that every behaviour was checked. Review of assertions is ongoing.

## 10. Planned improvements

1. Turn on CI runs on Windows and Linux once the account billing lock is cleared
2. Add Playwright end-to-end tests for key flows: sign-in, course settings, quiz attempt and PDF export
3. Add a manual test-case sheet for exploratory and usability checks
4. Track coverage over time and set a minimum threshold in CI
