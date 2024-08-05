#!/bin/bash

# Array of conflicting secret names
secrets=("cloudflared-credentials" "cloudflare-api-token" "external" "webhook-transformer" "ntfy_auth")

# Loop through each secret and search for it in all namespaces
for secret in "${secrets[@]}"; do
    echo "Searching for secret: $secret"
    # Get the namespace where the secret is found
    namespace=$(kubectl get secret $secret --all-namespaces -o jsonpath='{.items[0].metadata.namespace}' 2>/dev/null)
    
    # Check if the secret was found
    if [ -n "$namespace" ]; then
        echo "Found secret '$secret' in namespace '$namespace'. Deleting..."
        kubectl delete secret $secret -n $namespace
        echo "Secret '$secret' deleted from namespace '$namespace'."
    else
        echo "Secret '$secret' not found in any namespace."
    fi
done

echo "Script execution completed."
