# Data Model: OpenClaw Infrastructure

## Entities

### OpenClaw Gateway
- **State**: Running/Healthy
- **Configuration**: Env Vars, Secrets
- **Persistence**: `/home/node/.openclaw` (NFS)

### NFS Volume
- **Server**: 10.0.40.3
- **Path**: `/mnt/user/openclaw`
- **Mount Status**: Stale (Current) -> Healthy (Target)
