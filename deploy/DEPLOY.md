# Deploy on yos-dev (10.0.7.56)

Same pattern as plane / cases: AD DNS name `leads.dayo-tech.com` → 10.0.7.56, the edge Caddy's
wildcard `*.dayo-tech.com` cert (no cert work), and sign-in by `leads-auth` (oauth2-proxy + Entra)
from dayo-internal-services `stacks/sso`. The app itself has no published port and sits only on
`leads-front` (shared with leads-auth) and `leads-data` (shared with leads-db).

The server has no GitHub key, so code goes over as a git bundle.

## Once

1. Entra: new app registration `leads-login`, same settings as `cases-login`, redirect URI
   `https://leads.dayo-tech.com/oauth2/callback`, app roles `leads_viewer` and `leads_editor`
   (assign users). Its values go into `stacks/sso/leads-auth.env` on the server (see the example).
2. DNS: `leads.dayo-tech.com` in AD DNS → 10.0.7.56, same as `cases.dayo-tech.com`.
3. On the server: `docker volume create leads-pgdata`, `docker volume create leads-files`,
   `docker network create leads-front`, and `secrets/leads_db_password.txt` + `secrets/mcp_token.txt`.

## Every release

Bundle on the Mac, `git pull` from the bundle on the server, `docker compose -p leads up -d --build`.
Migrations run on start and only add. Data stays on the external volumes.

## Backups

`deploy/backup.sh /path/to/backups` nightly (pg_dump of leads + tar of leads-files).
