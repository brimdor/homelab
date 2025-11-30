#!/bin/bash
while true; do
  read -p "Docker.io Image (e.g. username/repo:tag): " IMAGE
  # Prevent accidental localhost/ prefix by stripping it if present
  IMAGE_CLEANED=$(echo "$IMAGE" | sed 's#^localhost/##')
  # Only allow valid Docker Hub image names (no registry prefix)
  if [[ "$IMAGE_CLEANED" =~ ^[a-z0-9]+([._-][a-z0-9]+)*/[a-z0-9]+([._-][a-z0-9]+)*(:(latest|[a-zA-Z0-9._-]+))?$ ]]; then
    IMAGE="$IMAGE_CLEANED"
    break
  else
    echo "Invalid image name. Please use the format username/repo[:tag] and do not include a registry prefix."
  fi
done
read -p "Docker.io Username: " DOCKER_USER
read -s -p "Docker.io Password: " DOCKER_PASS
echo

echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin

if [ $? -ne 0 ]; then
  echo "Docker login failed. Exiting."
  exit 1
fi
echo "Image: $IMAGE"
echo "Building and pushing image..."
docker build -f Dockerfile -t "$IMAGE" .
docker push "$IMAGE"

echo "Script finished."