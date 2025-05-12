# backlog-companion Helm Chart

This Helm chart deploys the backlog-companion application as a single Pod with three containers (database, backend, frontend) for direct inter-container communication, matching the Podman Compose setup.

## Features
- All containers share the same Pod and network namespace
- Persistent storage for MariaDB
- Environment variables for all services
- Health/readiness checks
- Exposes MySQL, backend, and frontend as a single ClusterIP Service

## Usage

1. Edit `values.yaml` to set your secrets and configuration.
2. Install with:
   ```sh
   helm install backlog-companion ./Helm --namespace <your-namespace>
   ```
3. To uninstall:
   ```sh
   helm uninstall backlog-companion --namespace <your-namespace>
   ```

## Notes
- All containers are in a single Pod for direct communication (localhost).
- For production, consider splitting into separate Deployments for scaling and resilience.
