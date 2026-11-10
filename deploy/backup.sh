#!/bin/sh
# Nightly backup of leads-db and leads-files (LEADS_PLAN 18). A surviving volume is not a backup.
# Usage on the host: deploy/backup.sh /srv/backups/leads
set -eu
dest="${1:?backup dir}"
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p "$dest"
docker exec leads-db pg_dump -U dbot_leads -d leads -Fc > "$dest/leads-$stamp.dump"
docker run --rm -v leads-files:/files:ro -v "$dest":/out alpine tar czf "/out/leads-files-$stamp.tgz" -C /files .
find "$dest" -name 'leads-*' -mtime +14 -delete
