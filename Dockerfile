FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system django && adduser --system --ingroup django django

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=django:django . .

# Compile static assets into /app/staticfiles at build time. WhiteNoise
# serves them in production; the placeholder key is only used to let
# Django's collectstatic pass the settings import (SECRET_KEY is required),
# and is never the value a runtime deploys with.
RUN DJANGO_SECRET_KEY="build-only-secret-key-collectstatic" python manage.py collectstatic --noinput

USER django

EXPOSE 8000

# Production default: Gunicorn serving WSGI behind WhiteNoise. Override in
# compose.yaml during development (python manage.py runserver). Workers may
# be tuned via the GUNICORN_WORKERS env var (defaults to 3).
CMD ["sh", "-c", "exec gunicorn construction.wsgi:application --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-3} --no-control-socket"]
