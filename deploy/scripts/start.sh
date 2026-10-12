#!/usr/bin/env bash
# Usage: start.sh [bot]
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"

require_root
resolve_bot "${1:-}"
systemctl start "$BOT.service"
echo "Service $BOT started."
