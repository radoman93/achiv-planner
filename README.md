# achiv-planner

WoW Achievement Route Optimizer — generates personalized, optimized achievement routes for World of Warcraft characters.

See `CLAUDE.md` for the product brief and `docs/progress.md` for phase status.

---

## Deployment

### Prerequisites
- Docker and Docker Compose
- `git`
- A Linux VPS with ports 80/443 exposed

### Initial setup

```bash
git clone <repo-url> achiv-planner
cd achiv-planner

# Fill in all required variables (see backend/.env.example)
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
$EDITOR backend/.env frontend/.env

# First-time start
docker-compose up -d
docker-compose run --rm backend alembic upgrade head
```

Verify everything came up with `./health_check.sh`.

### Subsequent deploys

```bash
./deploy.sh
```

`deploy.sh` pulls main, rebuilds backend + frontend with `--no-cache`, runs
Alembic migrations, brings the stack up, and polls `/api/health` until ready.

### Backups

Run daily via cron:

```
0 2 * * * /path/to/achiv-planner/backup.sh >> /var/log/wow-backup.log 2>&1
```

Backups land in `/backups` (override with `BACKUP_DIR`), keep the last 30
dumps (`BACKUP_RETENTION` to change).

Restore with:

```bash
./restore.sh /backups/wow_optimizer_YYYYMMDD_HHMMSS.sql.gz
```

The script prompts for `yes` confirmation, stops backend/celery, loads the
dump, runs migrations forward, and restarts services.

### Health check

```bash
./health_check.sh
```

Exits `0` when Nginx, backend, frontend, and Flower respond; `1` otherwise.

### SSL (Let's Encrypt)

```bash
# Install certbot on the host
sudo apt install certbot python3-certbot-nginx

# Get a cert — Nginx container must be stopped to free port 80/443
docker-compose stop nginx
sudo certbot certonly --standalone -d yourdomain.com
docker-compose start nginx
```

Then wire the cert paths into `nginx/nginx.conf` (update the `ssl_certificate`
and `ssl_certificate_key` directives), and add a renewal cron:

```
0 3 * * * certbot renew --pre-hook "docker-compose stop nginx" --post-hook "docker-compose start nginx"
```
