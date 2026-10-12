#!/usr/bin/env bash
# Usage: stop.sh [bot]
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"

require_root
resolve_bot "${1:-}"
systemctl stop "$BOT.service"
echo "Service $BOT stopped."