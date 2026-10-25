#!/usr/bin/env bash
# Nightly backup: database dump + stored files.  Cron: 15 2 * * *  /opt/legal-workspace/deploy/backup.sh /backups
# Restore:  gunzip -c db.sql.gz | docker compose exec -T db psql -U lw legal_workspace   (and untar storage.tgz into the storage volume)
set -euo pipefail
OUT="${1:?usage: backup.sh <dir>}"; STAMP=$(date +%Y%m%d-%H%M%S); mkdir -p "$OUT"
docker compose exec -T db pg_dump -U lw legal_workspace | gzip > "$OUT/db-$STAMP.sql.gz"
docker compose run --rm -T --no-deps -v "$OUT":/out api sh -c 'tar czf /out/storage-'"$STAMP"'.tgz -C /app/storage .'
find "$OUT" -type f -mtime +14 -delete
echo "backup written to $OUT ($STAMP)"
