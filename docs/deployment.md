# Deployment runbook

Kibernikto is a long-polling Telegram bot. Run **one** instance per bot token: a second poller on the same token makes Telegram reject updates for both.

## 1. Prerequisites

- Docker (or Podman) and a host with a persistent disk.
- A Telegram bot token, LLM provider key, and an `env` file based on [`deploy/tg_bots/kibernikto/kibernikto.env`](../deploy/tg_bots/kibernikto/kibernikto.env).
- Keep the env file out of git and out of the image (`.dockerignore` already excludes `*.env`).

Podman + systemd on a server, code cloned from git with a deploy key: use [`deploy/`](../deploy/README.md) instead of sections 2–5. State still lives in `/data`, mounted from `tg_bots/<bot>/data/`, so sections 6–8 apply.

## 2. Build

```shell
docker build -t kibernikto:2.0.0b1 .
```

The image runs as UID `10001` and writes state only to `/data`.

## 3. Run

```shell
mkdir -p ./kibernikto-data
docker run -d --name kibernikto --restart unless-stopped \
  --env-file ./kibernikto.env \
  -v "$PWD/kibernikto-data:/data" \
  kibernikto:2.0.0b1
```

Configuration comes only from `--env-file`; the container has no `.env` file to load.

Default storage inside the container:

| Setting | Value | Purpose |
|---|---|---|
| `APP_STORAGE_FILESTORE_LOCATION` | `/data` | media, tmp, file history, chat data |
| `APP_STORAGE_SQLITE_PATH` | `/data/kibernikto.db` | used when `APP_STORAGE_DATA_BACKEND=sqlite` |

For PostgreSQL set `APP_STORAGE_DATA_BACKEND=pg` and `APP_STORAGE_PG_DSN` instead.

### Public image hosting

Photos and generated images are published to a public URL the model can fetch.

- **imgbb** (default): set `IMAGE_STORAGE_API_KEY`. Without it startup logs a warning and photos reach the model as an error marker.
- **S3**: set `IMAGE_HOSTING_PROVIDER=s3`, the `APP_STORAGE_S3_*` credentials and `IMAGE_S3_PUBLIC_BASE_URL` (the URL serving the bucket root, e.g. a CDN). Grant anonymous `s3:GetObject` on `IMAGE_S3_PREFIX` (default `public/`) only — never on the private `media/` prefix:

```json
{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": "*",
  "Action": "s3:GetObject", "Resource": "arn:aws:s3:::YOUR_BUCKET/public/*"}]}
```

Startup HEADs the bucket and refuses to poll if it is unreachable. Check one published URL with `curl -I` after the first photo.

## 4. Verify

```shell
docker logs -f kibernikto        # expect "Storage backends validated" and polling start
docker exec kibernikto ls /data  # history/, chat_data/, media/ appear after first message
```

Send `/start` to the bot from an allowed account. A reply confirms the full path.

## 5. Update

```shell
git pull
docker build -t kibernikto:2.0.0b1 .
docker stop kibernikto && docker rm kibernikto
# re-run the command from section 3 with the new image tag
```

Keep the same `/data` volume: it holds history, chat credits and media.

## 6. Backup and restore

- **SQLite:** `docker exec kibernikto python -c "import sqlite3;s=sqlite3.connect('/data/kibernikto.db');d=sqlite3.connect('/data/backup.db');s.backup(d)"`, then copy `backup.db` off-host. Or stop the container and copy `kibernikto-data/` as is.
- **File backend:** stop the container and archive `kibernikto-data/`.
- Restore by stopping the container, replacing `kibernikto-data/`, and starting it again.

## 7. Rollback

Re-run section 3 with the previous image tag. Data format is unchanged across the 2.0 betas; check [CHANGELOG.md](../CHANGELOG.md) before crossing versions. 1.x data is not read by 2.0.

## 8. Known limits

- No automatic health endpoint; use `docker logs` and the bot's responses.
- One replica only. Scaling out requires a shared PostgreSQL DSN plus distinct bot tokens or a webhook setup, which this project does not provide.
- Stars payments are verified offline only; a real test payment is required before production billing (see `kibernikto/telegram/payment/payment_utils.py`).
