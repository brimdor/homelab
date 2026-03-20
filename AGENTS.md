# AGENTS.md - Homelab coding guide

## Build, lint, and test
- `make test`: run full Go/Terratest suite via `gotestsum`.
- `make smoke-test`: run smoke coverage only (`filter=Smoke`).
- `make -C test filter='<Regex>'`: run a single test or subset (example: `filter='TestSmoke'`).
- `gotestsum --format testname -- -timeout 30m -run '<Regex>'` (from `test/`) for direct, single-test execution.
- `pre-commit run --all-files`: run repo linters (`yamllint`, `helmlint`, `shellcheck`, `terraform-fmt`, safety hooks).
- `make git-hooks`: install pre-commit hooks locally.

## Code style and conventions
- YAML: follow `.yamllint.yaml` (no `---` required, line length not enforced); always end files with newline.
- Go tests: use `gofmt`; package name is `test`; test funcs are `Test<Feature>`; prefer table-driven tests with `t.Run` and `t.Parallel()` where safe.
- Imports: keep Go imports grouped as stdlib then third-party; use aliases only when required for clarity or conflicts.
- Types: prefer explicit struct fields for test cases and typed literals over `interface{}`-heavy patterns.
- Naming: Helm/chart resources use `lowercase-hyphens`; Ansible vars/files use `lowercase_underscores`; keep names descriptive and stable.
- Error handling: never ignore errors; fail fast in tests (`t.FailNow`/assert helpers) and return actionable errors in scripts/automation.
- Shell scripts: require shebang and executable bit; keep shellcheck-clean.
- Terraform: run `terraform fmt`; do not commit secrets or generated credentials.

## Agent-specific rules
- Apply mandatory homelab rules from `.agent/rules/foundational-rules.md` and app governance in `.agent/rules/HOMELAB_applications.md`.
- Cursor rules: none found (`.cursor/rules/`, `.cursorrules`). Copilot rules: none found (`.github/copilot-instructions.md`).
- Never alter any code in ~/Documents/Github/paperclip
- When building a new image for paperclip, always pull from the upstream in ~/Documents/Github/paperclip to make sure we have the latest codebase/features/etc.