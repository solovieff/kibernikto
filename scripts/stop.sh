if [ -z "$1" ]; then
  echo "You forgot to specify the service name, Smarty."
  exit 1
fi

# Run the service whose name is passed in the parameter
SERVICE_NAME=$1
sudo systemctl stop "$SERVICE_NAME".service

echo "Service $SERVICE_NAME stopped."