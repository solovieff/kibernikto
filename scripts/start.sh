if [ -z "$1" ]; then
  echo "Ты забыл указать имя сервиса, Умник."
  exit 1
fi

# Запускаем сервис, имя которого передано в параметре
SERVICE_NAME=$1
sudo systemctl start "$SERVICE_NAME.service"

echo "Сервис $SERVICE_NAME запущен."
