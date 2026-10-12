#!/usr/bin/env bash
# Usage: save_todays_log.sh [bot] — dump today's bot output to <bot>-YYYY-MM-DD.log in the bot folder.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"

require_root
resolve_bot "${1:-}"
out=$BOT_DIR/$BOT-$(date +%F).log
podman logs --since "$(date +%Y-%m-%dT00:00:00)" "$BOT" > "$out" 2>&1
echo "Saved $out"

