if [ -z "$1" ]; then
  echo "Ты забыл указать имя сервиса, Умник."
  exit 1
fi

# Запускаем сервис, имя которого передано в параметре
SERVICE_NAME=$1
echo "Updating kibernikto..."
podman exec "$SERVICE_NAME" sh -c "cd /usr/src/kibernikto && git pull && pip install ."
echo "Updating avatar..."
output=$(podman exec "$SERVICE_NAME" sh -c "cd /usr/src/kibernikto-avatar && git pull")
if [[ $output == *"Already up to date."* ]]; then
  echo $output
else
  echo "Code updates found. Initiating systemctl restart. git pull output:"
  echo "$output"
  podman exec "$SERVICE_NAME" sh -c "cd /usr/src/kibernikto-avatar && pip install -r requirements.txt"
  systemctl restart "$SERVICE_NAME".service
fi
