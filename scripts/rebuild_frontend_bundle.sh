#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/build"
DIST_DIR="$BUILD_DIR/dist/build"
WWW_DIR="$ROOT_DIR/bundle/www"
VERSION="${WIZ_ASSET_VERSION:-$(date -u +%Y%m%d%H%M)}"

cd "$BUILD_DIR"

rm -f "$DIST_DIR/index.html" "$DIST_DIR/main.js" "$DIST_DIR/main.css" "$DIST_DIR/vendor.js"

set +e
node wizbuild.js
build_code=$?
set -e

if [[ ! -f "$DIST_DIR/index.html" || ! -f "$DIST_DIR/main.js" ]]; then
    exit "$build_code"
fi

DIST_DIR="$DIST_DIR" VERSION="$VERSION" node <<'NODE'
const fs = require('fs');
const path = require('path');

const indexPath = path.join(process.env.DIST_DIR, 'index.html');
const version = process.env.VERSION;
let html = fs.readFileSync(indexPath, 'utf8');
html = html
  .replace(/href="main\.css(?:\?v=[^"]*)?"/g, `href="main.css?v=${version}"`)
  .replace(/src="vendor\.js(?:\?v=[^"]*)?"/g, `src="vendor.js?v=${version}"`)
  .replace(/src="main\.js(?:\?v=[^"]*)?"/g, `src="main.js?v=${version}"`)
  .replace(/data-version="[^"]*"/g, `data-version="${version}"`);
fs.writeFileSync(indexPath, html, 'utf8');
NODE

mkdir -p "$WWW_DIR"
cp -a "$DIST_DIR/." "$WWW_DIR/"

stale_pattern='미장 24시간 시세|Alpaca API Key|Alpaca Secret|데이터 피드|alpacaApiKey|alpacaApiSecret|alpacaDataFeed|alpaca_api_key|alpaca_api_secret|alpaca_data_feed|Toss Client ID|Toss Client Secret|Toss Account Seq'
if rg -n "$stale_pattern" "$WWW_DIR/main.js" -S >/tmp/infinitystock_frontend_stale_strings.txt; then
    cat /tmp/infinitystock_frontend_stale_strings.txt
    echo "Stale settings UI strings remain in $WWW_DIR/main.js" >&2
    exit 1
fi

echo "Frontend bundle rebuilt: $WWW_DIR/main.js?v=$VERSION"
