# AGENTS.md - Homelab Repository Guidelines

## Build/Test Commands
- `make test` - Run all Go tests | `make smoke-test` - Run smoke tests only
- `make -C test filter=<TestName>` - Run single test (e.g., `filter=Smoke`)
- `pre-commit run --all-files` - Run all linters | `make git-hooks` - Install hooks

## Project Structure
- **metal/** - Ansible bare metal provisioning (K3s) | **system/** - Core infra (ArgoCD, certs, ingress)
- **platform/** - Services (Gitea, Grafana, Kanidm) | **apps/** - User Helm charts
- **external/** - Terraform for Cloudflare | **test/** - Go tests (terratest)
- **AGENTS/** - Agent team docs ([TEAM.md](file:///home/brimdor/Documents/Github/homelab/AGENTS/TEAM.md))
- **.agent/workflows/** - Homelab workflows (`homelab-recon`, `homelab-action`, `homelab-troubleshoot`)
- **.agent/rules/foundational-rules.md** - MANDATORY rules for all homelab workflows
- **.agent/rules/HOMELAB_applications.md** - Application governance & Moltbot protocol

## Team Communication
- **Direct Addressing**: Use the agent's name (e.g., "Forge, ...") - no `@mention` required.
- **Group Channel**: `-5207483609`
- **Replies**: Use 'reply' functionality for context.

## Code Style
- **YAML**: yamllint (no line-length limit), end with newline, document-start disabled
- **Shell**: Must have shebangs, pass shellcheck | **Helm**: Must pass `helm lint`
- **Terraform**: Use `terraform fmt` | **Go**: Standard `gofmt` for tests

## Key Patterns
- **Secrets**: ExternalSecrets with 1Password backend - never commit plaintext
- **Ingress**: ingress-nginx with cert-manager TLS | **GitOps**: ArgoCD from `master` branch
- **Naming**: Charts = `lowercase-hyphens`, Ansible = `lowercase_underscores`, Tests = `Test<Feature>`
- **API**: Gitea token at `~/.config/gitea/.env`, use `GITEA_URL`/`GITEA_TOKEN` for API calls
