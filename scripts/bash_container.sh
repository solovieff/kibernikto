if [ -z "$1" ]; then
  echo "Ты забыл указать имя сервиса, Умник."
  exit 1
fi

# Запускаем сервис, имя которого передано в параметре
SERVICE_NAME=$1

podman exec -it "$SERVICE_NAME" bash
