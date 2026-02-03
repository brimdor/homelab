# Tasks: OpenClaw Config From NFS

## Phase 1: Setup
- [ ] T001 [P1] Create reference config file `.specify/openclaw-config-nfs/reference/openclaw.json`
- [ ] T002 [P1] Document migration steps in `.specify/openclaw-config-nfs/plan.md`

## Phase 2: Foundational
- [ ] T003 [P1] Update `apps/openclaw/values.yaml` to use NFS `openclaw.json` via `OPENCLAW_CONFIG_PATH`
- [ ] T004 [P1] Remove `openclaw.json` ConfigMap data from `apps/openclaw/values.yaml`
- [ ] T005 [P1] Remove ConfigMap-based `/config/openclaw.json` mount from `apps/openclaw/values.yaml`
- [ ] T006 [P2] Add startup validation init container in `apps/openclaw/values.yaml` (missing/empty file)
- [ ] T007 [P2] Add checksum validation in `apps/openclaw/values.yaml` (expected sha256 value)
- [ ] T008 [P2] Remove `--allow-unconfigured` from OpenClaw args in `apps/openclaw/values.yaml`

## Phase 3: User Story 1 - Persisted Config File Is Used
- [ ] T009 [P1] Ensure NFS mount path includes the config file location (`/home/node/.openclaw/openclaw.json`) in `apps/openclaw/values.yaml`

## Phase 4: User Story 2 - Fail Fast When Config Is Missing
- [ ] T010 [P1] Add clear init-container log messages for missing config in `apps/openclaw/values.yaml`

## Phase 5: User Story 3 - Validate Persisted Config Matches Expected
- [ ] T011 [P2] Compute sha256 for `.specify/openclaw-config-nfs/reference/openclaw.json` and set expected value in `apps/openclaw/values.yaml`

## Final Phase: Validation
- [ ] T012 [P1] Run `helm lint` for `apps/openclaw`
- [ ] T013 [P2] Render chart locally and verify `openclaw.json` is not present in manifests
