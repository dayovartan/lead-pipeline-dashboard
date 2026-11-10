# Lead pipeline dashboard

Its own app: FastAPI + React SPA in one `leads` container, its own Postgres in `leads-db`.
Plans: [docs/LEADS_PLAN.md](docs/LEADS_PLAN.md), [docs/EXHIBITION_MAPPING_PLAN.md](docs/EXHIBITION_MAPPING_PLAN.md), [docs/UI_PLAN.md](docs/UI_PLAN.md). API contract: [docs/API.md](docs/API.md).

## Run locally

```bash
# once: secrets (not in git) and the external volumes/network that hold the data
openssl rand -hex 24 > secrets/leads_db_password.txt
touch secrets/mcp_token.txt
docker volume create leads-pgdata
docker volume create leads-files
docker network create leads-front
# build and start, published on 127.0.0.1:8000 with a dev user standing in for leads-auth
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
```

Open http://localhost:8000. Data survives `docker compose down`, `down -v` and rebuilds, because the volumes are external.

## Tests

```bash
cd backend
uv venv -p 3.12 .venv
uv pip install -p .venv/bin/python -e '.[dev]'
LEADS_TEST_ADMIN_URL=postgresql+psycopg://USER:PASS@127.0.0.1:5434/leads .venv/bin/pytest -q
```

A synthetic workbook for trying the intake: `backend/.venv/bin/python backend/scripts/make_sample_xlsx.py --out /tmp/x`.

## Production (yos-dev), not deployed yet

`docker compose -p leads up -d` with `compose.yaml` only (no published port). `leads-auth` goes into dayo-internal-services `stacks/sso`; it lives in dayo-internal-services `stacks/sso` (`leads-auth`); runbook in [deploy/DEPLOY.md](deploy/DEPLOY.md). Nightly backup: [deploy/backup.sh](deploy/backup.sh).
