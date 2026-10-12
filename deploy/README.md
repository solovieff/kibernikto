# Server layout

Copy this folder to the server as is. One folder in `tg_bots/` per bot; the folder name is the bot, service, container and image name.

```
scripts/                 shared: rebuild, update, start, stop, logs; known_hosts = pinned GitHub host keys
tg_bots/kibernikto/
  kibernikto.env         bot config (or .env)
  deploy.conf            REPO= (required), BRANCH= (default main)
  Dockerfile             image recipe: clones REPO, uv sync, state in /data
  github.key             deploy key of REPO, read-only, no passphrase (add it yourself, never commit)
  data/                  created on first run: history, credits, media, sqlite
```

New bot: copy `tg_bots/kibernikto` to `tg_bots/<bot>`, rename the env file to `<bot>.env`, set `REPO`, add `github.key`.

As root:

```shell
scripts/rebuild.sh -b <bot>   # build from git and (re)start as <bot>.service
scripts/update.sh             # rebuild every bot whose branch has new commits (cron-friendly)
scripts/log.sh <bot>          # follow output; start.sh / stop.sh / save_todays_log.sh / bash_container.sh
```

Inside `tg_bots/<bot>/` the bot argument can be omitted.

Moving an existing bot whose state is in an anonymous volume: copy it out before the first `rebuild.sh`,
`podman cp <bot>:/data/. tg_bots/<bot>/data/`.
