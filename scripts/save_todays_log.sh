if [ -z "$1" ]; then
  echo "Ты забыл указать имя сервиса, Умник."
  exit 1
fi

# Запускаем сервис, имя которого передано в параметре
SERVICE_NAME=$1

journalctl -u "$SERVICE_NAME.service" -r --since today > "$SERVICE_NAME".log

