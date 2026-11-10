# secrets/

Not in git. Files the stack reads (Docker secrets):

- `leads_db_password.txt` — password for the `dbot_leads` role in `leads-db`.
- `mcp_token.txt` — bearer token for cases-mcp and sap-mcp (read tools only). Optional; without it the MCP panels show "not available".

Create the DB password once:

    openssl rand -hex 24 > secrets/leads_db_password.txt

    touch secrets/mcp_token.txt   # empty is fine: MCP panels show "not available"
