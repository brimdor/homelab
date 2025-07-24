#!/bin/bash
# build_test.sh - Build and run the container locally for testing

while true; do
  read -p "Local image name (e.g. test-media-cleaner:latest): " IMAGE
  # Only allow valid local Docker image names (no registry prefix)
  if [[ "$IMAGE" =~ ^[a-z0-9]+([._-][a-z0-9]+)*/?[a-z0-9]+([._-][a-z0-9]+)*(:(latest|[a-zA-Z0-9._-]+))?$ ]]; then
    break
  else
    echo "Invalid image name. Please use the format name[:tag] and do not include a registry prefix."
  fi
done

# Build the Docker image

echo "Building image: $IMAGE"
docker build -f Dockerfile -t "$IMAGE" .
if [ $? -ne 0 ]; then
  echo "Docker build failed. Exiting."
  exit 1
fi

# Check for .env file and pass it to the container
ENV_FILE=".env"
if [ -f "$ENV_FILE" ]; then
  echo "Using environment variables from $ENV_FILE"
  ENV_ARGS=(--env-file "$ENV_FILE")
else
  echo "No .env file found at workspace root. Running without extra environment variables."
  ENV_ARGS=()
fi

echo "Running container for local testing..."
docker run --rm -it "${ENV_ARGS[@]}" "$IMAGE"

echo "Script finished."
