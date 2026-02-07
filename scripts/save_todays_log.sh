if [ -z "$1" ]; then
  echo "You forgot to specify the service name, Smarty."
  exit 1
fi

# Run the service whose name is passed in the parameter
SERVICE_NAME=$1

journalctl -u "$SERVICE_NAME".service -r --since today > "$SERVICE_NAME".log

