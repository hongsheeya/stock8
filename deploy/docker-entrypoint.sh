#!/bin/sh
set -eu

PROJECT_DIR=/opt/app/project/main

mkdir -p "$PROJECT_DIR/config" "$PROJECT_DIR/data" /var/log/wiz

if [ ! -f "$PROJECT_DIR/config/database.py" ]; then
    echo "config/database.py not found; installing the empty SQLite recovery configuration."
    cp "$PROJECT_DIR/config-sample/database.py" "$PROJECT_DIR/config/database.py"
fi

exec "$@"

