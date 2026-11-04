# Deploying Lumen

This guide takes a blank Linux server to a running Lumen. It uses Docker Compose, which runs MySQL, Redis, the web app, the background worker, the scheduler and nginx together.

> **Database status:** the whole test suite (720 tests), a full backup and restore, Sinhala, Tamil and emoji text, and the main screens in a real browser were run against **MariaDB 10.11**. MySQL 8.4 (what the compose file uses) is very close but was not available for testing, so do the "first run" below on a test server and click through every role before real students use it. To re-run the tests against your own server: `pytest --ds=config.settings.test_mysql` (see that file).

## 1. What you need
- A Linux server with 2 CPU cores, 4 GB RAM and 40 GB disk or more (more disk if people will upload many files; the default quota is 500 MB per person).
- Docker and the Docker Compose plugin.
- A domain name pointing at the server (for example `lms.your-university.edu`).
- An SMTP account for sending email (welcome emails, notification copies).

## 2. First run
1. Copy the project to the server and `cd` into it.
2. `cp .env.example .env` and edit it:

| Setting | What to put |
|---|---|
| `DJANGO_SECRET_KEY` | A long random string: `python3 -c "import secrets; print(secrets.token_urlsafe(60))"`. Never reuse it elsewhere. |
| `DJANGO_ALLOWED_HOSTS` | Your domain, for example `lms.your-university.edu`. |
| `DJANGO_TIME_ZONE` | For example `Asia/Colombo`. |
| `DB_PASSWORD`, `DB_ROOT_PASSWORD` | Two different long passwords. |
| `SITE_URL` | `https://lms.your-university.edu` (used for links in emails). |
| `EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend`, then `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`. |
| `SECURE_SSL_REDIRECT` | `False` for the very first test over plain HTTP, then `True` once HTTPS works (section 3). |
| `TRUST_PROXY_HEADERS` | `True` (nginx in this compose file sets the visitor's address). |
| `CELERY_EAGER` | Must be `False` (or absent) in production. |

3. `docker compose up -d --build`. The web container migrates the database on start.
4. Create the first administrator: `docker compose exec web python manage.py createsuperuser` (the account gets the administrator role).
5. Open `http://your-server/` and sign in. The admin overview should show **no** "Background jobs are not running" warning after about two minutes. If it does, see Troubleshooting.

## 3. HTTPS (do this before real use)
Passwords and sessions must not travel in plain text.
1. Get a certificate, for example with certbot (`certbot certonly --webroot -w /var/www/certbot -d lms.your-university.edu`), or use your university's certificate.
2. Use `docker/nginx-tls.conf.example` as your nginx config (the comments at the top say what to change: domain, port 443, certificate mount).
3. Set `SECURE_SSL_REDIRECT=True` in `.env`, then `docker compose up -d`.
4. Renew certificates automatically (certbot's timer) and reload nginx after renewal: `docker compose exec nginx nginx -s reload`.

If another proxy or a CDN sits in front of nginx, the **network rules** (allowed IP ranges) will see that proxy's address instead of the visitor's. Either keep nginx as the only thing facing the internet, or change the `X-Forwarded-For` line to pass the real visitor address from a source you trust.

## 4. Settings to review in the admin area (first day)
- **System settings:** site name, late penalty, quiz review policy, attendance warning, two-factor policy (we suggest **required for administrators** at least).
- **Access and IP rules:** restrict `/admin-panel/` to your office network, and `/quizzes/` to the exam rooms if you run supervised exams. The screen refuses a rule that would lock you out.
- **Theme and branding:** logo colour and name.
- **Email templates:** wording of the welcome email.
- **Plugins and modules:** switch off what you do not use.
- **Custom profile fields:** faculty, index number and so on.

## 5. Backups and restoring
- The scheduler makes a backup every night at 02:00 (all records as JSON plus every uploaded file, in one zip) into the `backups` volume, and keeps the newest 14. Administrators can also create, download and delete backups under *Backup and maintenance*.
- **Copy backups off the server** every day (another machine or cloud storage). A backup on the same disk does not survive a dead disk. For example: `docker compose cp web:/app/backups ./offsite/`, or mount the volume on the host and use rsync.
- Take a native database dump as well for large sites: `docker compose exec db sh -c 'mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" lumen' > lumen-$(date +%F).sql`.
- **Restore (rehearse this once on a spare server):**
  1. Switch maintenance mode on if the old site still runs.
  2. Start a clean install (section 2, steps 1 to 3) so the tables exist, but do not create users.
  3. Unzip the backup. Copy its `media/` folder into the `media` volume.
  4. `docker compose cp data.json web:/tmp/data.json`, then `docker compose exec web python manage.py loaddata /tmp/data.json`.
  5. Sign in and check courses, grades and a few uploaded files.

## 6. Updating Lumen
1. Take a backup (the admin screen, one click).
2. Copy the new version over the old one (keep `.env`).
3. `docker compose up -d --build`. Migrations run automatically when the web container starts.
4. Check the admin overview and `/healthz/`.
To go back, restore the previous code and the backup from step 1.

## 7. Monitoring
- `GET /healthz/` answers `ok` (200) when the database responds, 503 otherwise. Point an uptime monitor at it. It works over plain HTTP and during maintenance mode.
- The admin overview warns when background jobs stop (the scheduler reports every minute).
- Logs: `docker compose logs -f web worker beat`.
- Disk: watch the `media`, `backups` and `dbdata` volumes (`docker system df -v`).

## 8. Capacity notes
- The web container runs 3 gunicorn workers. For a big exam where hundreds of students start a quiz together, raise `--workers` in `docker-compose.yml` (roughly 2 per CPU core plus 1) and test with your own numbers first.
- You may run more `worker` containers (`docker compose up -d --scale worker=3`). Run **exactly one** `beat`.
- Quizzes are timed by the server and answers are saved as students go, so a short network drop does not lose work. Expired attempts are submitted by the scheduler every minute.

## 9. Security checklist
- [ ] HTTPS on, `SECURE_SSL_REDIRECT=True`, certificate renewal tested.
- [ ] `.env` is not in version control and only readable by the person who deploys (`chmod 600 .env`).
- [ ] Strong `DJANGO_SECRET_KEY`, database passwords unique.
- [ ] Firewall: only ports 80 and 443 (and SSH from known addresses) are open. MySQL and Redis are **not** published to the internet (the compose file does not publish them; keep it that way).
- [ ] Two-factor required for administrators.
- [ ] Admin area restricted by IP rule if you have a fixed office network.
- [ ] Offsite backups running and a restore rehearsed.
- [ ] `/django-admin/` (the raw developer admin) is also behind the IP rule or blocked in nginx: `location /django-admin/ { return 404; }`.
- [ ] Operating system and Docker images updated regularly (`docker compose pull && docker compose up -d --build`).
- [ ] Privacy: tell users what is stored (the audit log is kept for the retention period set in system settings).

## 10. Troubleshooting
| Symptom | Likely cause and fix |
|---|---|
| Browser shows "400 Bad Request" | The domain is missing from `DJANGO_ALLOWED_HOSTS`. |
| Endless redirect or "can't reach site" right after install | `SECURE_SSL_REDIRECT=True` but no HTTPS yet. Set it `False` until section 3 is done. |
| "Background jobs are not running" in the admin overview | `beat` or `worker` is down (`docker compose ps`, then `docker compose logs beat`), or Redis is unreachable (`REDIS_URL`). Pages keep working meanwhile; emails are skipped and expired quiz attempts are not auto-submitted until it is fixed. |
| Emails never arrive | Wrong SMTP settings or `EMAIL_BACKEND` still the console one. Check `docker compose logs worker`. |
| Uploaded files download as empty or 404 | The `media` volume is not mounted into **both** `web` and `nginx`, or the nginx `/media/` block was removed. |
| Locked yourself out with an IP rule | Run `docker compose exec web python manage.py shell -c "from apps.core.models import AllowedNetwork; AllowedNetwork.objects.all().update(is_active=False)"`. |
| Everyone sees the IP of the proxy in the audit log | Section 3, last paragraph. |
