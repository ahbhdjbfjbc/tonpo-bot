#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

: "${DATABASE_URL:?Set DATABASE_URL to the PostgreSQL source database}"
: "${BACKUP_PASSPHRASE_FILE:?Set BACKUP_PASSPHRASE_FILE to a protected file on a secret volume}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/tonpo-bot}"

for tool in pg_dump gpg sha256sum python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Required command not found: $tool" >&2; exit 127; }
done
[[ -r "$BACKUP_PASSPHRASE_FILE" ]] || { echo "Backup passphrase file is not readable" >&2; exit 2; }
passphrase_bytes=$(wc -c < "$BACKUP_PASSPHRASE_FILE")
(( passphrase_bytes >= 32 )) || { echo "Backup passphrase file must contain at least 32 bytes" >&2; exit 2; }
passphrase_mode=$(stat -c '%a' -- "$BACKUP_PASSPHRASE_FILE")
(( (8#$passphrase_mode & 077) == 0 )) || { echo "Backup passphrase file permissions must exclude group/other access (for example chmod 600)" >&2; exit 2; }

mkdir -p -- "$BACKUP_DIR"
chmod 700 -- "$BACKUP_DIR"
backup_name="tonpo-$(date -u +%Y%m%dT%H%M%S.%NZ).dump.gpg"
archive="$BACKUP_DIR/$backup_name"
tmp=$(mktemp "$BACKUP_DIR/.${backup_name}.tmp.XXXXXX")
service_file=$(mktemp "$BACKUP_DIR/.pgservice.XXXXXX")
trap 'rm -f -- "$tmp" "$service_file"' EXIT

# pg_dump receives a private service-file path, not a URL/password in argv or its environment.
python3 "$(dirname -- "$0")/postgres_service_file.py" "$service_file" DATABASE_URL
unset DATABASE_URL
# The passphrase is read through an inherited file descriptor, never a command-line argument.
exec 3<"$BACKUP_PASSPHRASE_FILE"
env -i PATH="$PATH" HOME="${HOME:-/}" PGSERVICEFILE="$service_file" PGSERVICE=tonpo_backup \
  pg_dump --format=custom --no-owner --no-acl \
  | gpg --batch --yes --pinentry-mode loopback --passphrase-fd 3 \
      --symmetric --cipher-algo AES256 --output "$tmp"
exec 3<&-

mv -- "$tmp" "$archive"
chmod 600 -- "$archive"
(cd "$BACKUP_DIR" && sha256sum -- "$backup_name" > "$backup_name.sha256")
chmod 600 -- "$archive.sha256"
printf 'Encrypted PostgreSQL backup created: %s\n' "$archive"
printf 'Copy it and its .sha256 file to a separate, access-controlled off-host location.\n'
