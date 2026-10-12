#!/usr/bin/env bash
# Usage: log.sh [bot] — follow the bot's own output.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"

require_root
resolve_bot "${1:-}"
podman logs -f --tail 200 "$BOT"
