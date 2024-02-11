#!/bin/bash

echo "Stopping Docker Containers"
docker stop files_http_1 files_dnsmasq_1

echo "Removing Docker Containers"
docker rm files_http_1 files_dnsmasq_1

echo "Pruning Images"
docker image prune -a --force

echo "Removing Cache Containers"
docker volume rm homelab-tools-cache homelab-tools-nix

echo "Removing terraform.d folder"
sudo rm -Rf ~/.terraform.d

echo "Removing homelab folder"
cd ~
sudo rm -Rf homelab

echo "Pulling a Fresh Clone of Homelab"
git clone https://github.com/brimdor/homelab

echo "And Bob is your uncle!"