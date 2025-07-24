#!/bin/bash
set -e

# Optionally start Steam in the background if needed
if command -v steam &> /dev/null; then
  echo "Starting Steam in background..."
  steam &
fi

# Print diagnostic info for debugging
id
ls -ld /run/user/1000
ls -l /run/user/1000/wayland-1 || true

# Optionally run a Python socket test (uncomment if needed)
# python3 -c 'import socket as s; sock = s.socket(s.AF_UNIX); sock.connect("/run/user/1000/wayland-1"); print("Wayland socket accessible")'

# Start Sunshine
exec sunshine
