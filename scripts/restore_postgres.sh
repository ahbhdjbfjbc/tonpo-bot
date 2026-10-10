#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

: "${RESTORE_DATABASE_URL:?Set RESTORE_DATABASE_URL to a newly created, isolated, empty PostgreSQL database}"
: "${BACKUP_PASSPHRASE_FILE:?Set BACKUP_PASSPHRASE_FILE to the protected passphrase file used for backup}"
backup=${1:?Usage: restore_postgres.sh /path/to/tonpo-....dump.gpg}

for tool in psql pg_restore gpg sha256sum python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Required command not found: $tool" >&2; exit 127; }
done
[[ -f "$backup" && -r "$backup" ]] || { echo "Backup archive is not readable" >&2; exit 2; }
[[ -r "$BACKUP_PASSPHRASE_FILE" ]] || { echo "Backup passphrase file is not readable" >&2; exit 2; }
passphrase_bytes=$(wc -c < "$BACKUP_PASSPHRASE_FILE")
(( passphrase_bytes >= 32 )) || { echo "Backup passphrase file must contain at least 32 bytes" >&2; exit 2; }
passphrase_mode=$(stat -c '%a' -- "$BACKUP_PASSPHRASE_FILE")
(( (8#$passphrase_mode & 077) == 0 )) || { echo "Backup passphrase file permissions must exclude group/other access (for example chmod 600)" >&2; exit 2; }

checksum_file="$backup.sha256"
if [[ -f "$checksum_file" ]]; then
  (cd "$(dirname -- "$backup")" && sha256sum --check -- "$(basename -- "$checksum_file")")
else
  echo "Checksum file not found: $checksum_file" >&2
  exit 2
fi

service_file=$(mktemp "${TMPDIR:-/tmp}/tonpo-pgservice.XXXXXX")
trap 'rm -f -- "$service_file"' EXIT
python3 "$(dirname -- "$0")/postgres_service_file.py" "$service_file" RESTORE_DATABASE_URL
unset RESTORE_DATABASE_URL
pg_env=(env -i "PATH=$PATH" "HOME=${HOME:-/}" "PGSERVICEFILE=$service_file" "PGSERVICE=tonpo_backup")

# Require an existing but empty target database. No --clean or --create flags are used.
object_count=$("${pg_env[@]}" psql --no-psqlrc -v ON_ERROR_STOP=1 -Atqc \
  "SELECT
     (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','S','i','I','f'))
   + (SELECT count(*) FROM pg_namespace WHERE nspname NOT IN ('pg_catalog','information_schema','public') AND nspname NOT LIKE 'pg_toast%')
   + (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND t.typtype IN ('d','e','r'))")
[[ "$object_count" == "0" ]] || {
  echo "Restore refused: target database contains $object_count user objects; choose a new empty isolated database." >&2
  exit 3
}

exec 3<"$BACKUP_PASSPHRASE_FILE"
gpg --batch --pinentry-mode loopback --passphrase-fd 3 --decrypt -- "$backup" \
  | "${pg_env[@]}" pg_restore --no-owner --no-acl --exit-on-error
exec 3<&-
printf 'Restore completed into the empty isolated target database. Validate Alembic head, row counts, and application smoke tests before any traffic is routed.\n'
