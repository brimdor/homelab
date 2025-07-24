#!/bin/bash

# Ensure a clean environment by stopping and removing everything related to Docker

echo "Cleaning up Docker environment..."

# Stop and remove ALL containers
echo "Stopping and removing all containers..."
docker stop $(docker ps -aq) 2>/dev/null
docker rm -f $(docker ps -aq) 2>/dev/null

# Remove ALL images (used, unused, dangling)
echo "Removing all images..."
docker rmi -f $(docker images -q) 2>/dev/null

# Remove ALL volumes
echo "Removing all volumes..."
docker volume rm -f $(docker volume ls -q) 2>/dev/null

# Remove ALL networks (except default ones)
echo "Removing all networks..."
docker network rm $(docker network ls -q | grep -v -E '^(bridge|host|none)$') 2>/dev/null

# Prune ALL unused data (force prune with volumes)
echo "Pruning unused data..."
docker system prune -a -f --volumes 2>/dev/null

echo "Environment cleaned successfully."