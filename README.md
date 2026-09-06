# Cedar Construction Management

Cedar Construction Management is a Django 5.2 application backed by a remote Supabase PostgreSQL database. This repository includes a Docker development environment so teammates can use the same Python and dependency versions.

## Docker setup on Windows

### Prerequisites

- Git
- Docker Desktop for Windows with Docker Compose v2
- Access to the team's Supabase project and database credentials

Start Docker Desktop and wait until its engine reports that it is running. Clone the repository, open PowerShell in the repository directory, and create your local environment file:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and replace every placeholder. In Supabase, open the project's **Connect** dialog and copy the PostgreSQL connection details into `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD`. The application currently uses these individual fields rather than one `DATABASE_URL`. Keep `DB_SSLMODE=require` for Supabase.

Generate a development secret key without printing or committing team credentials:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Put that output in `DJANGO_SECRET_KEY`. The `.env` file is ignored by both Git and Docker builds; never commit it.

The company-logo upload (Company settings) uses the Supabase **service_role** secret from `SUPABASE_SERVICE_ROLE_KEY` when set (it bypasses Storage RLS), falling back to `SUPABASE_ANON_KEY` otherwise. Keep the service_role key server-side only.

Build and start the application:

```powershell
docker compose up --build
```

Open <http://localhost:8000/admin/>. Later starts can use `docker compose up` because source files are mounted into the container and Django reloads when Python code changes.

### Database migrations

Startup deliberately does not run migrations. The database is remote and may be shared, so coordinate schema changes with the team, review migrations, and apply them explicitly:

```powershell
docker compose exec web python manage.py showmigrations
docker compose exec web python manage.py migrate
```

Do not run `makemigrations` merely to start the project. When a model change intentionally needs a migration, create and commit it through the team's normal review process.

Create an administrator after migrations are applied:

```powershell
docker compose exec web python manage.py createsuperuser
```

### Common commands

```powershell
# Follow application logs
docker compose logs -f web

# Run Django checks and tests
docker compose exec web python manage.py check
docker compose exec web python manage.py test

# Run any Django management command
docker compose exec web python manage.py <command>

# Stop and remove the development container/network
docker compose down

# Rebuild after requirements.txt or Dockerfile changes
docker compose up --build
```

Source code is bind-mounted at `/app`. There is currently no local-media setting and no Tailwind or Node package configuration in this repository, so no media volume or Node watcher is included. Add those only when the application introduces those workflows.

## Run without Docker

Python 3.12 is the Docker development baseline. From PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py check
python manage.py runserver
```

Configure `.env` before running checks or the server. Apply migrations and create a superuser with the same `python manage.py migrate` and `python manage.py createsuperuser` commands after coordinating shared-database changes.

## Troubleshooting

- **Port 8000 is already in use:** stop the other process, or change the first number in `ports` in `compose.yaml` (for example, `"8001:8000"`) and browse to that port.
- **Docker commands cannot reach the engine:** open or restart Docker Desktop and wait for it to finish starting. Ensure Docker Desktop is using Linux containers.
- **Supabase connection fails:** verify all five `DB_*` values, retain `DB_SSLMODE=require`, check that the Supabase project is running, and choose the Supabase pooler connection if your network does not support the direct IPv6 endpoint. Restart with `docker compose up` after editing `.env`.
- **Authentication or migration errors:** confirm the database user has the expected permissions and that the team has applied the required migrations. Do not reset or recreate the shared Supabase schema.
- **Windows line-ending errors:** configure Git with `git config --global core.autocrlf true`, then re-clone or normalize only the affected script. The container command uses JSON form and does not depend on a shell script, avoiding the common CRLF entrypoint problem.
- **Code changes do not reload:** confirm the Compose service is running and that Docker Desktop has permission to share the repository drive/directory.
