#!/bin/bash
set -e
set -o xtrace

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
CONTAINER_NAME=${PWD##*/}

mkdir -p "$SCRIPT_DIR"/db_chroma
mkdir -p "$SCRIPT_DIR"/db_sqlite
mkdir -p "$SCRIPT_DIR"/tg_voices
mkdir -p "$SCRIPT_DIR"/uploaded_files

while getopts "b" flag; do
    case "${flag}" in
        b) DO_BUILD=true ;;
        *)
          echo "Invalid option: -${OPTARG}" >&2
          exit 1
          ;;
      esac
done

if [ "$DO_BUILD" = true ]; then
    podman build -t "$CONTAINER_NAME" --build-arg CACHE_DATE="$(date +%s)" .
fi


systemctl stop "$CONTAINER_NAME".service || echo "new systemd service"
echo "$SCRIPT_DIR"

podman create --replace --name "$CONTAINER_NAME" --env-file "$CONTAINER_NAME".env -v "$SCRIPT_DIR"/db_chroma:/usr/src/db_chroma:Z -v "$SCRIPT_DIR"/uploaded_files:/usr/src/uploaded_files:Z -v "$SCRIPT_DIR"/tg_voices:/usr/src/tg_voices:Z -v "$SCRIPT_DIR"/db_sqlite:/usr/src/db_sqlite:Z "$CONTAINER_NAME"
podman generate systemd --name "$CONTAINER_NAME" >"$CONTAINER_NAME".service

cp -Z "$CONTAINER_NAME".service /etc/systemd/system/

systemctl daemon-reload

systemctl enable --now "$CONTAINER_NAME".service

sleep 3
systemctl is-active --quiet "$CONTAINER_NAME".service && exit 0
exit 1

