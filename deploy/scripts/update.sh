#!/usr/bin/env bash
# Usage: update.sh [bot...] — rebuild and restart each bot whose branch moved past its deployed revision.
# No args: the current bot folder, or every bot in tg_bots when run from elsewhere (cron-friendly).
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"

update_one() {
    resolve_bot "$1"
    require_key
    local remote current
    remote=$(GIT_SSH_COMMAND="ssh -i '$KEY_FILE' -o IdentitiesOnly=yes -o UserKnownHostsFile='$KNOWN_HOSTS' -o StrictHostKeyChecking=yes" \
        git ls-remote "$REPO" "refs/heads/$BRANCH" | cut -f1)
    [[ -n $remote ]] || die "$BOT: branch $BRANCH not found in $REPO"

    current=$(revision "$BOT")
    if [[ $remote == "$current" ]]; then
        echo "$BOT: up to date at $current"
        return 0
    fi
    echo "$BOT: ${current:-no image} -> $remote"
    "$SCRIPT_DIR/rebuild.sh" -b "$BOT"
}

require_root
bots=("$@")
if [[ ${#bots[@]} -eq 0 ]]; then
    if [[ $(dirname -- "$PWD") -ef $BOTS_DIR ]]; then
        bots=("$(basename -- "$PWD")")
    else
        while IFS= read -r bot; do bots+=("$bot"); done < <(list_bots)
    fi
fi
[[ ${#bots[@]} -gt 0 ]] || die "No bots found in $BOTS_DIR"

# One broken bot must not block the rest.
failed=()
for bot in "${bots[@]}"; do
    ( update_one "$bot" ) || failed+=("$bot")
done
[[ ${#failed[@]} -eq 0 ]] || die "Failed: ${failed[*]}"
