#!/bin/bash

# Array of conflicting secret names
secrets=("cloudflared-credentials" "cloudflare-api-token" "external" "webhook-transformer" "ntfy_auth")

# Loop through each secret and search for it in all namespaces
for secret in "${secrets[@]}"; do
    echo "Searching for secret: $secret"
    
    # Get the namespace where the secret is found
    namespace=$(kubectl get secret $secret --all-namespaces -o jsonpath='{.items[0].metadata.namespace}' 2>/dev/null)
    
    # Check if the command was successful
    if [ $? -ne 0 ]; then
        echo "Error: Failed to search for secret '$secret'. Please check the kubectl command and ensure you have the correct permissions."
        continue
    fi
    
    # Check if the secret was found
    if [ -n "$namespace" ]; then
        echo "Found secret '$secret' in namespace '$namespace'. Attempting to delete..."
        
        # Attempt to delete the secret
        kubectl delete secret $secret -n $namespace
        
        # Check if the deletion was successful
        if [ $? -eq 0 ]; then
            echo "Secret '$secret' successfully deleted from namespace '$namespace'."
        else
            echo "Error: Failed to delete secret '$secret' from namespace '$namespace'. Please check the kubectl command and ensure you have the correct permissions."
        fi
    else
        echo "Secret '$secret' not found in any namespace."
    fi
done

echo "Script execution completed."
