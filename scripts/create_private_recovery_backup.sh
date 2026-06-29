#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/mnt/data/wiz/private-backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="stock8-private-recovery-${STAMP}"
STAGING_DIR="$(mktemp -d "/tmp/${NAME}.XXXXXX")"
ARCHIVE="${BACKUP_DIR}/${NAME}.tar.gz"

cleanup() {
    rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

copy_if_exists() {
    local src="$1"
    local dest="$2"

    if [[ -e "$src" ]]; then
        mkdir -p "$(dirname "$dest")"
        cp -a "$src" "$dest"
    fi
}

mkdir -p "$STAGING_DIR/$NAME"

# Private runtime/config data. Do not commit the generated archive to GitHub.
copy_if_exists "$ROOT_DIR/config" "$STAGING_DIR/$NAME/config"
copy_if_exists "$ROOT_DIR/data" "$STAGING_DIR/$NAME/data"
copy_if_exists "$ROOT_DIR/bundle/config" "$STAGING_DIR/$NAME/bundle/config"
copy_if_exists "$ROOT_DIR/bundle/www" "$STAGING_DIR/$NAME/bundle/www"
copy_if_exists "$ROOT_DIR/build/dist/build" "$STAGING_DIR/$NAME/build/dist/build"
copy_if_exists "$ROOT_DIR/build/public" "$STAGING_DIR/$NAME/build/public"

# Small recovery context files make the archive usable even without opening GitHub.
copy_if_exists "$ROOT_DIR/README.md" "$STAGING_DIR/$NAME/README.md"
copy_if_exists "$ROOT_DIR/docs/recovery.md" "$STAGING_DIR/$NAME/docs/recovery.md"
copy_if_exists "$ROOT_DIR/package.json" "$STAGING_DIR/$NAME/package.json"
copy_if_exists "$ROOT_DIR/package-lock.json" "$STAGING_DIR/$NAME/package-lock.json"

cat > "$STAGING_DIR/$NAME/MANIFEST.txt" <<EOF
Stock8 private recovery backup
Created UTC: ${STAMP}
Project root: ${ROOT_DIR}

This archive is intentionally private. It may contain database credentials,
broker settings, FireGate-related state, runtime JSON data, and current build
artifacts that are not safe for a public GitHub repository.

Expected public code repository:
git@github.com:hongsheeya/stock8.git

Restore summary:
1. Clone the public repository.
2. Copy this archive's config/, data/, bundle/config/, bundle/www/, and
   build/dist/build/ contents into the cloned project as needed.
3. Restart the Wiz server from /opt/app.
EOF

find "$STAGING_DIR/$NAME" -type d -name '__pycache__' -prune -exec rm -rf {} +

tar -C "$STAGING_DIR" -czf "$ARCHIVE" "$NAME"
chmod 600 "$ARCHIVE"
sha256sum "$ARCHIVE" > "${ARCHIVE}.sha256"
chmod 600 "${ARCHIVE}.sha256"

echo "$ARCHIVE"
echo "${ARCHIVE}.sha256"
