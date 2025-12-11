#!/usr/bin/env python3
import json
import subprocess
import sys

# Read the full report
with open('/home/brimdor/Documents/Github/homelab/reports/status-report-2025-12-10.md', 'r') as f:
    body = f.read()

# Prepare the API request
data = {
    "body": body
}

# Make the API call
result = subprocess.run([
    'curl', '-s', '-X', 'PATCH',
    'https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/6',
    '-H', 'Authorization: token 38d5688d1cbcc2e1eca4441ded9582bc2b80d7dd',
    '-H', 'Content-Type: application/json',
    '-d', json.dumps(data)
], capture_output=True, text=True)

# Parse and display result
try:
    response = json.loads(result.stdout)
    print(f"✓ Updated issue #{response['number']}: {response['title']}")
    print(f"  URL: {response['html_url']}")
    print(f"  Status: {response['state']}")
except:
    print("Response:", result.stdout)
    print("Error:", result.stderr)
