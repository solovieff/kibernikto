# Shared deploy helpers. Layout: scripts/ (this dir) next to tg_bots/<bot>/ — one self-contained folder per bot.
# Template of the whole layout: deploy/ in the kibernikto repo (tg_bots/kibernikto is a ready bot folder).
#   tg_bots/<bot>/<bot>.env    bot config (or .env)                                  required
#   tg_bots/<bot>/Dockerfile   image recipe                                          required
#   tg_bots/<bot>/github.key   deploy key for the bot's repo                         required for build/update
#   tg_bots/<bot>/deploy.conf  REPO=git@github.com:owner/repo.git (BRANCH=main)      required
#   tg_bots/<bot>/data/        /data volume: history, credits, media, sqlite         created on first run
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
BOTS_DIR=${BOTS_DIR:-$(cd -- "$SCRIPT_DIR/.." && pwd)/tg_bots}
KNOWN_HOSTS=$SCRIPT_DIR/known_hosts

die() { echo "$*" >&2; exit 1; }

# Rootful podman + system-wide systemd units.
require_root() { [[ $EUID -eq 0 ]] || die "Run as root."; }

# Every folder in tg_bots that has an env file.
list_bots() {
    local dir
    for dir in "$BOTS_DIR"/*/; do
        dir=${dir%/}
        [[ -f $dir/$(basename "$dir").env || -f $dir/.env ]] && basename "$dir"
    done
    return 0
}

# Sets BOT, BOT_DIR, ENV_FILE, KEY_FILE, DATA_DIR, DOCKERFILE, REPO, BRANCH from an arg or the current bot folder.
resolve_bot() {
    BOT=${1:-}
    if [[ -z $BOT && $(dirname -- "$PWD") -ef $BOTS_DIR ]]; then
        BOT=$(basename -- "$PWD")
    fi
    [[ -n $BOT ]] || die "Usage: $0 <bot>. Bots in $BOTS_DIR: $(list_bots | xargs)"
    BOT_DIR=$BOTS_DIR/$BOT
    [[ -d $BOT_DIR ]] || die "No such bot folder: $BOT_DIR"

    ENV_FILE=$BOT_DIR/$BOT.env
    [[ -f $ENV_FILE ]] || ENV_FILE=$BOT_DIR/.env
    [[ -f $ENV_FILE ]] || die "Env file not found: $BOT_DIR/$BOT.env"

    KEY_FILE=$BOT_DIR/github.key
    DATA_DIR=$BOT_DIR/data
    DOCKERFILE=$BOT_DIR/Dockerfile

    # Each bot is its own repo: no implicit default, the deploy key belongs to exactly this REPO.
    REPO=
    BRANCH=main
    [[ -f $BOT_DIR/deploy.conf ]] || die "Missing $BOT_DIR/deploy.conf with REPO=git@github.com:owner/repo.git"
    source "$BOT_DIR/deploy.conf"
    [[ -n $REPO ]] || die "REPO is not set in $BOT_DIR/deploy.conf"
    return 0
}

require_key() {
    [[ -f $KEY_FILE ]] || die "Deploy key not found: $KEY_FILE"
    chmod 600 "$KEY_FILE"  # ssh refuses keys readable by others
}

# Git commit baked into the image, empty if there is no image yet.
revision() {
    podman image exists "$1" || return 0  # no local image: don't let podman try a registry pull
    podman run --rm --entrypoint cat "$1" /app/REVISION 2>/dev/null || true
}
