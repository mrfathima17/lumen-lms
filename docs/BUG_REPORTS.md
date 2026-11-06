# Bug Reports

Defects found by running the full test suite on a clean Windows machine (fresh clone, new virtual environment). Both were invisible on Linux, where the suite had always passed.

| ID | Title | Severity | Status |
|---|---|---|---|
| BUG-001 | Reports, timetable and to-do pages crash on Windows | High | Fixed and verified |
| BUG-002 | Image downloads leave a file handle open, so deleting the image fails on Windows | Medium | Fixed and verified |

**Environment:** Windows, Python 3.14.5, Django 5.2.19, pytest 9.2.0, `config.settings.test`
**Date found:** 4 November 2026
**Fixed in commit:** `b75d60f`

---

## BUG-001: Reports, timetable and to-do pages crash on Windows

**Severity:** High. Three user-facing pages return HTTP 500 on any Windows host.

**Steps to reproduce**
1. On Windows, clone the repository and install `requirements-dev.txt`.
2. Run `pytest`.
3. Alternatively, run the app and open a course's Reports tab, the Timetable page, or the To-do page.

**Expected result:** each page renders, with dates shown like "4 Nov" and times like "2 PM".

**Actual result:** `ValueError: Invalid format string`, and the page returns an Internal Server Error.

**Tests affected (6):**
- `test_course_settings_reports.py`: `test_reports_empty_course_renders`, `test_reports_figures`, `test_most_missed_needs_three_answers`
- `test_results_ui.py`: `test_timetable_grid`
- `test_schedule.py`: `test_timetable_shows_only_own_courses`, `test_todo_page_shows_unsubmitted_deadlines_only`

**Root cause:** the code formats dates with `%-d` and `%-I` (day and hour without a leading zero). Those flags are a glibc extension that works on Linux and macOS. Windows does not support them, so `strftime` raises an error.

| File | Line | Code |
|---|---|---|
| `apps/courses/reports.py` | 91 | `strftime("%-d %b")` |
| `apps/schedule/services.py` | 99 | `strftime("%-I %p")` |
| `apps/schedule/views.py` | 156, 160 | `%a %-d %b` |

**Fix:** use the portable codes (`%d`, `%I`) and strip the leading zero in Python.
- `strftime("%d %b").lstrip("0")`
- `strftime("%I %p").lstrip("0")`
- `strftime('%a %d %b').replace(' 0', ' ')`

**Verification:** all 720 tests pass on Windows (Python 3.14) and on Linux (Python 3.12). Output is unchanged on Linux ("4 Nov", "2 PM", "Wed 4 Nov").

---

## BUG-002: Image downloads leave a file handle open, so deleting the image fails on Windows

**Severity:** Medium. It breaks the test suite on Windows. The product impact is limited to removing a logo or login background while a download of it is still open.

**Steps to reproduce**
1. On Windows, run `pytest tests/test_theme.py`.
2. The tests upload a logo or login background, download it through `/branding/<name>/`, then remove it.

**Expected result:** the image is removed from disk.

**Actual result:** `PermissionError: [WinError 32] The process cannot access the file because it is being used by another process`, and the theme page returns HTTP 500.

**Tests affected (2):**
- `test_logo_upload_is_served_publicly_and_can_be_removed`
- `test_background_image_replaces_preset_and_preset_replaces_image`

**Root cause:** the branding view streams the image as a file response, which holds the file open until the response is closed. The tests never closed the response, so the file was still open when the app tried to delete it. Linux allows deleting an open file and Windows does not. The second test only failed after the first was fixed, which points to timing. Python's garbage collector had been closing the handle sometimes.

**Fix:** close each response before the file is removed (`r.close()` in both tests).

**Verification:** the 2 tests pass, and the full suite passes (720 of 720) on Windows.

**Follow-up worth considering:** if removing an image while someone is downloading it matters in production, have the view read the small file into memory instead of streaming it.

---

## Prevention

Run the suite on both Windows and Linux in CI on every push, as `.github/workflows/tests.yml` is set up to do.
