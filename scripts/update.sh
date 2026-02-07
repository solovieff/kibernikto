if [ -z "$1" ]; then
  echo "You forgot to specify the service name, Smarty."
  exit 1
fi

# Run the service whose name is passed in the parameter
SERVICE_NAME=$1
echo "Updating kibernikto..."
output=$(podman exec "$SERVICE_NAME" sh -c "cd /usr/src/kibernikto && git pull")
if [[ $output == *"Already up to date."* ]]; then
  echo $output
else
  echo "Code updates found. Initiating systemctl restart. git pull output:"
  echo "$output"
# Update the kibernikto package and restart the service
  podman exec "$SERVICE_NAME" sh -c "cd /usr/src/kibernikto && pip install ."
  systemctl restart "$SERVICE_NAME".service
fi
