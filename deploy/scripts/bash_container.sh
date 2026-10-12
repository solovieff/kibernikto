#!/usr/bin/env bash
# Usage: bash_container.sh [bot] — shell inside the running bot container.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"

require_root
resolve_bot "${1:-}"
podman exec -it "$BOT" bash
