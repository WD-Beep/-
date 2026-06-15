# Backup and Restore Guide

This project should never depend on one laptop only. Keep three things safe:

- Source code in a private Git remote.
- Database dumps outside the repo.
- Runtime secrets in a password manager or another encrypted store.

## What To Back Up

- Code: everything in this repository except ignored files.
- Database: PostgreSQL data for products, influencers, collection tasks, candidates, email logs, and settings.
- Secrets: `.env`, `apps/api/.env`, `apps/web/.env.local`, API keys, SMTP credentials, and database passwords.

Do not commit real secrets or database dumps to Git.

## Recommended Routine

- Commit code after every accepted feature or repair.
- Push code to a private GitHub, Gitee, or GitLab repository.
- Run a database backup at least once per day.
- Copy backup files to cloud storage, NAS, or an external drive.
- Keep at least the latest 7 daily backups and 4 weekly backups.

Suggested backup file name:

```text
influencer-intel-YYYYMMDD-HHMMSS.dump
```

## Environment Files

Keep `.env.example` in Git, but keep real `.env` files outside Git.

Minimum variables needed for database backup:

```text
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DB_NAME
```

or:

```text
POSTGRES_USER=USER
POSTGRES_PASSWORD=PASSWORD
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=influencer_intel
```

## Manual Database Backup

From the repository root on Windows PowerShell:

```powershell
.\scripts\backup_db.ps1
```

Optional output directory:

```powershell
.\scripts\backup_db.ps1 -OutputDir "D:\safe-backups\influencer-intel"
```

Optional plain SQL export:

```powershell
.\scripts\backup_db.ps1 -PlainSql
```

The script requires PostgreSQL client tools, especially `pg_dump`, in `PATH`.
When `.env` uses the Docker-internal host name `postgres`, the PowerShell script connects through `localhost` so it can run from Windows while Docker Compose exposes port `5432`.

## Docker Compose Backup Alternative

If the app is running with Docker Compose and `pg_dump` is not installed on Windows, use:

```powershell
.\scripts\backup_db_docker.ps1
```

Or run this manual command from the repository root:

```powershell
$name = "influencer-intel-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".dump"
New-Item -ItemType Directory -Path backups -Force | Out-Null
docker compose exec -T postgres pg_dump -U $env:POSTGRES_USER -d $env:POSTGRES_DB --format=custom --blobs --no-owner --no-privileges > "backups\$name"
```

If `POSTGRES_USER` or `POSTGRES_DB` is not set in your shell, use the values from `.env`.

## Restore On A New Computer

1. Install Git, Node.js, Python, Docker Desktop, and PostgreSQL client tools.
2. Clone the private repository.
3. Copy real environment files from your secure storage:

```text
.env
apps/api/.env
apps/web/.env.local
```

4. Install frontend dependencies:

```powershell
cd apps\web
npm install
```

5. Install backend dependencies:

```powershell
cd ..\api
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

6. Start PostgreSQL, either by Docker Compose or your local PostgreSQL service.
7. Restore the latest dump into an empty database:

```powershell
pg_restore --clean --if-exists --no-owner --no-privileges --dbname="postgresql://USER:PASSWORD@HOST:PORT/DB_NAME" "D:\safe-backups\influencer-intel-YYYYMMDD-HHMMSS.dump"
```

8. Run migrations:

```powershell
cd apps\api
.\.venv\Scripts\alembic upgrade head
```

9. Start the backend and frontend using the normal project commands or Docker Compose.

## Restore Safety Rules

- Restore only into an empty or intentionally replaceable database.
- Never run restore commands against production until the target database name is checked.
- Keep the original backup file unchanged.
- After restore, verify counts for products, influencers, collection tasks, and candidates before using the system.

## Quick Recovery Checklist

- Repository cloned from private remote.
- `.env` files restored from secure storage.
- Latest database dump restored.
- Migrations applied.
- Frontend opens.
- Backend health/API endpoint responds.
- Product selector shows real products.
- Collection tasks and influencer library show expected data.

## Git Remote Setup

Create a private repository in GitHub, Gitee, or GitLab, then from the repo root:

```powershell
git remote add origin YOUR_PRIVATE_REPO_URL
git push -u origin main
```

If the branch is not `main`, check with:

```powershell
git branch --show-current
```

Then push that branch instead.
