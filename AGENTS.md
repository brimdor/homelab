# AGENTS.md - Homelab Repository Guidelines

## Build/Test Commands
- `make test` - Run all Go tests | `make smoke-test` - Run smoke tests only
- `make -C test filter=<TestName>` - Run single test (e.g., `filter=Smoke`, `filter=ToolsVersions`)
- `pre-commit run --all-files` - Run all linters (yamllint, shellcheck, helm lint, terraform fmt)
- `make git-hooks` - Install pre-commit hooks

## Project Structure
- **metal/** - Ansible for bare metal provisioning (K3s cluster)
- **system/** - Core infrastructure (ArgoCD, cert-manager, ingress-nginx, monitoring)
- **platform/** - Platform services (Gitea, Grafana, Kanidm)
- **apps/** - User applications (Helm charts)
- **external/** - Terraform for Cloudflare DNS/tunnels
- **test/** - Go integration tests using terratest

## Code Style
- **YAML**: Must pass yamllint (no line-length limit), files end with newline
- **Shell**: Must have shebangs, pass shellcheck
- **Terraform**: Use `terraform fmt` formatting
- **Helm**: Charts must pass `helm lint`
- **Go**: Standard Go formatting for tests

## Naming Conventions
- Helm charts: lowercase with hyphens (e.g., `external-dns`, `cert-manager`)
- Ansible roles: lowercase with underscores (e.g., `automatic_upgrade`)
- Test functions: `Test<Feature>` (e.g., `TestSmoke`, `TestToolsVersions`)