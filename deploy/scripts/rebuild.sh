#!/usr/bin/env bash
# Usage: rebuild.sh [-b] [bot] — with -b build the image from git, then recreate the bot as a systemd service.
# Bot defaults to the current folder when run from inside tg_bots/<bot>/.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"

DO_BUILD=false
while getopts "b" flag; do
    case $flag in
        b) DO_BUILD=true ;;
        *) die "Usage: $0 [-b] [bot]" ;;
    esac
done
shift $((OPTIND - 1))

require_root
resolve_bot "${1:-}"
UNIT=/etc/systemd/system/$BOT.service

if $DO_BUILD; then
    [[ -f $DOCKERFILE ]] || die "Dockerfile not found: $DOCKERFILE (template: deploy/tg_bots/kibernikto/Dockerfile)"
    require_key
    # Empty context: env, key and data never reach the build; key and host keys go in as secrets only.
    ctx=$(mktemp -d)
    trap 'rm -rf "$ctx"' EXIT
    # Build while the old bot keeps polling: downtime is only the restart below.
    podman build -t "$BOT" -f "$DOCKERFILE" \
        --secret id=deploy_key,src="$KEY_FILE" \
        --secret id=known_hosts,src="$KNOWN_HOSTS" \
        --build-arg REPO="$REPO" \
        --build-arg BRANCH="$BRANCH" \
        --build-arg CACHE_DATE="$(date +%s)" \
        "$ctx"
fi
podman image exists "$BOT" || die "Image $BOT not found: run with -b."

# All bot state (history, chat data, credits, media, sqlite) lives in /data, owned by container uid 10001.
mkdir -p "$DATA_DIR"
chown 10001:10001 "$DATA_DIR"

# One poller per token: the old service is down before the replacement exists.
systemctl stop "$BOT.service" 2>/dev/null || true
podman create --replace --name "$BOT" --env-file "$ENV_FILE" -v "$DATA_DIR":/data:Z "$BOT"
podman generate systemd --name "$BOT" --restart-policy=always > "$UNIT"
systemctl daemon-reload
systemctl enable --now "$BOT.service"

sleep 3
systemctl is-active --quiet "$BOT.service" || die "$BOT.service is not active: see $SCRIPT_DIR/log.sh $BOT"
echo "$BOT is up at revision $(revision "$BOT")"

