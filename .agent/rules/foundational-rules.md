---
description: Safety, evidence, authority, and completion rules for homelab work
type: foundational
applies_to:
  - homelab-troubleshoot
  - homelab-recon
  - homelab-action
  - read-only homelab audits
sync_locations:
  - /Users/chris/Documents/Github/homelab/.agent/rules/foundational-rules.md
  - ~/.config/opencode/rules/HOMELAB_foundational_rules.md
  - ~/.gemini/rules/HOMELAB_foundational_rules.md
sync_note: Update every listed copy in the same change and verify byte identity.
---

# Homelab Foundational Rules

## Owner policy: troubleshooting, retirement, and historical closeout

This policy takes precedence over conflicting completion, retention, and backup requirements below only for the cases stated here. It does not expand authorization for read-only work or waive repository-first deployment and verification gates.

- **Functional troubleshooting:** Restore functional GREEN across Metal, Network, Storage, System, Platform, and Apps. OS EOL or dated unsupported-version information alone is not RED or a completion blocker; do not upgrade the OS during troubleshooting. Record lifecycle and routine unexploited patch/microcode upgrade recommendations for the next `homelab-recon` maintenance issue, rather than silently upgrading them as repairs without evidence of a current incident/failure. Keep that maintenance record visible. Current runtime, hardware, and security faults remain findings and cannot be hidden as lifecycle inventory.
- **Archived applications:** During authorized troubleshooting or maintenance, purge their Kubernetes resources and exclusively retired non-NFS data only after proving no active application or shared consumer uses them. This disposition overrides legacy keep/Retain flags for exclusively retired resources. Never create backups for data explicitly designated for purge: this is intentional disposal, not a recoverable migration.
- **Deleted but not archived applications:** Retain PVCs/PVs with explicit persistence/retention intent; conservative examples include `helm.sh/resource-policy: keep`, Argo CD prune/delete protection, and PV reclaim policy `Retain`. Purge unused non-NFS storage without such intent through the retirement workflow. The default `kubernetes.io/pvc-protection` finalizer is not persistence intent.
- **Protected resources:** Always protect NAS/NFS data, unknown storage backends, ambiguous ownership, active applications, and shared resources. An active application with the same basename overrides an archived copy. Archive presence or application deletion alone is insufficient proof of exclusive retirement.
- **Retirement execution:** Preserve the generic `pvcHygiene` deletion-annotation gate; use a separate explicit repository-owned, UID-scoped retirement workflow. Record exact resource and PVC/PV UIDs, backend identity, active-consumer checks, reclaim policies, and intended disposition. Commit and push the desired state and retirement workflow to Gitea `master` before any apply. Recheck exact UIDs, active consumers, and reclaim behavior immediately before deletion; stop on changed identity or uncertain ownership. Never purge RBD images or OSDs directly. Verify intended Kubernetes resources and non-NFS data are gone, protected resources remain intact, and all six functional layers and affected application behavior are healthy. Backup/restore and rollback gates remain mandatory for active-data migrations and node/storage changes; they do not require backups of data explicitly authorized for intentional purge.
- **Historical closeout:** With explicit owner authorization, an old nonrecurring incident may close using current healthy behavior and archived public metadata even when its historical cause remains unknown. Record the evidence, owner disposition, and unknown historical cause honestly. This is historical closeout, not a verified root-cause fix or permission to ignore future failures.

These seven principles govern homelab skills and audits. They never expand user authorization or override repository, application, security, or approval rules. Read the canonical repository's `AGENTS.md` and `.agent/rules/HOMELAB_applications.md` before application work.

## Rule 1: Match completion to the authorized workflow

- **Read-only audit or diagnosis:** Collect evidence and report findings. Do not repair, install tooling, change infrastructure, or create/update remote issues when the user requests read-only work. An audit can finish with tracked non-GREEN findings; this does not mean the homelab is healthy or remediation is complete.
- **`homelab-recon`:** Run autonomously from collection through audited publication of the single open Gitea maintenance issue, exact readback, and final uniqueness verification. The invocation supplies standing authority; never request approval, authorization, confirmation, or human writer coordination for any recon phase. Automatic access, identity, stale-edit, preservation, and verification failures remain technical blockers, not permission requests. Explicit read-only audits and diagnostic/configuration-only requests remain report-only. Recon records future remediation gates without executing repairs or waiting for their approval; publication is not remediation success.
- **`homelab-troubleshoot` remediation and `homelab-action`:** Success requires all six layers GREEN, application behavior verified, and every required issue resolved. A local validated diff awaiting commit approval is not a deployed fix.
- Assess in this order: **Metal, Network, Storage, System, Platform, Apps**. Repair dependencies before dependent workloads; use severity to prioritize independent tasks.

| Layer | Evidence required for GREEN |
| --- | --- |
| Metal | Every active inventory node exists and is `Ready`; no pressure, unresolved hardware, host-security, or required-update findings. |
| Network | Required routing, Cilium, DNS, ingress, tunnel, and TLS behavior verified from relevant origins; no unresolved connectivity findings. |
| Storage | Ceph `HEALTH_OK`; expected PVCs bound; NAS/application paths, data integrity, capacity, and required backups verified. |
| System | Expected system controllers and workloads ready; certificates, observability, and critical dependencies function correctly. |
| Platform | Every expected Argo CD Application `Synced` and `Healthy` at the intended revision; shared services function correctly. |
| Apps | Expected controllers and containers ready; Jobs legitimately completed or healthy within their expected execution window; app-specific behavior and migrations verified. |

Use `UNKNOWN` for missing, stale, failed, or untested evidence. A pod's `Running` phase alone is not readiness. A successful completed Job is valid; a failed Job or unready running pod remains a finding. Empty output or a missing expected resource is not GREEN.

## Rule 2: Preserve every finding, including the baseline

Record all severities. Distinguish pre-existing faults from new regressions using timestamped before/after evidence; baseline faults still block remediation success. Do not hide warnings, drop failed evidence, or reclassify unresolved issues to claim completion.

Derive expected node membership from uncommented hosts in `metal/inventories/prod.yml`, not narrative lists. There are currently nine nodes: three masters and six workers. `ash` is a management controller, not a Kubernetes node; VLAN 30 extras are not active inventory members.

`chikorita` is retired. Its node-status-only absence or stale status is excluded from active-node health. Active pods, controller selectors, affinity, volumes, or other dependencies still referencing it remain findings. Retirement never authorizes deleting a node, controller, PVC, PV, or data.

## Rule 3: Continue within authority, never through a permission gate

Continue authorized remediation and validation while safe progress remains possible. Do not stop merely because most services work. Stop the blocked action when it needs human intervention, destructive-action approval, an external dependency, a security decision, or commit/push/release approval. Continue independent authorized work where possible and report the blocked outcome truthfully.

Normal application changes follow repository desired state, render/lint/review, authorized commit and push to Gitea `master`, Argo CD refresh/reconciliation, and live verification. Do not use live edits, manual Helm upgrades, node-hosted image builds, or GitHub as a deployment shortcut. Every change must follow the repository-first path; there is no emergency bypass.

Keep production and canary isolated. Follow `.agent/rules/HOMELAB_applications.md` for upstream authority, repository-owned image/patch logic, and release cleanup. Strata requires the canary-first runbook and explicit approval of the exact source-tree, immutable image digest, and canary configuration commit before merge or production promotion. Candidate changes invalidate approval; promote the approved digest without rebuilding.

## Rule 4: Validate continuously with compatible tooling

Establish the canonical checkout, source, branch, kubeconfig, and target before any live command:

| Identity | Required value |
| --- | --- |
| Mac checkout | `/Users/chris/Documents/Github/homelab` |
| `origin` | `git@git.eaglepass.io:ops/homelab.git` |
| Deployment branch | `master` |
| `KUBECONFIG` | `/Users/chris/Documents/Github/homelab/metal/kubeconfig.yaml` |
| API endpoint | `https://10.0.20.50:6443` |

Verify client/server version skew, authentication, and context without displaying credentials. The repository pins k3s `v1.33.6+k3s1`; Kubernetes 1.33 permits kubectl `>=1.32.0,<1.35.0`. The audited kubectl 1.35 versus server 1.33 is incompatible. Select managed compatible tooling; do not install “latest.” Recheck the actual server and keep tooling bounds aligned after upgrades. Read-only requests do not authorize installation.

The baseline helper, run from the canonical checkout after prerequisites pass, is:

```sh
python3 scripts/homelab-health.py --json
```

This helper is read-only **CORE evidence**, not full ALL GREEN certification. Exit `0` means CORE checks passed, `1` means findings, and `2` means evidence errors or prerequisite failures. Inspect findings and untested coverage even on exit `0`. Python 3 is required; inventory parsing needs already-managed PyYAML or `ansible-inventory`. The audited global Python has neither. Missing prerequisites are evidence blockers, not healthy results.

After each significant authorized action, repeat relevant checks and compare with the baseline. Before remediation completion, reassess all six layers and application behavior. Use structured conditions, controller generation/readiness, Job ownership/completion, events, and intended Argo revision; do not infer health from text filters alone.

## Rule 5: Use exhaustive, evidence-backed completion criteria

- **Troubleshooting:** Document the symptom, causal evidence, root cause, authorized fix, before/after results, rollback, residual findings, and all six layer statuses. Unproven root cause remains an investigation, not a verified fix.
- **Recon:** Use a unique UTC-plus-random run identifier, repository SHA, and verified cluster identity. Resume only that same run. Complete coverage or explicitly mark blocked/untested checks, map every finding to a task or decision gate, and audit the report before preview and autonomous publication. Use a new run tracker; bind it explicitly to the unique existing open maintenance issue when one exists, preserving history and completed work.
- **Maintenance:** Resolve every required maintenance item and discovered issue regardless of severity. Process related issues/PRs with evidence, prove Gitea/Argo rollout and behavior, and pass all six GREEN gates. Update/close remote trackers only when authorized and only after closure criteria pass.

Check off only verified work. Record evidence origin, UTC time, command/check, result, repository revision, and limitations. Reports must distinguish `UNKNOWN`, `BLOCKED`, `INCOMPLETE`, and `COMPLETE`; layer statuses must reflect evidence, never a prefilled success mark. Record approvals and pushed commit IDs only when they actually exist.

## Rule 6: Escalate genuine blockers and protect data

Report the blocked step, evidence, impact, required decision or external action, and safe next step. Allowed blockers include physical/human intervention, destructive-action confirmation, external dependency failure, security decisions, and missing commit/push/release approval. Permission denials are blockers; never retry through another identity, tool, path, or weaker check to override them.

Review inventory hosts and limits before metal actions. Never run bare `make`, `make metal`, `make -C metal`, PXE provisioning, or destructive reset/prune helpers as validation. Disk, Ceph, node, namespace, storage identity, and network changes require authorized scope, backups, and rollback. NAS application paths are durable data. Preserve unrelated work and retained evidence.

Never put secret values, kubeconfigs, tokens, raw secret-bearing logs, or backups in Git, transcripts, issue bodies, or disposable test artifacts. Keep necessary operational evidence private, ignored, access-restricted, and sanitized before publication. Preserve real backups, databases, credentials, installed dependencies, and retained evidence in their approved locations. Retention reports alone do not authorize deletion.

## Rule 7: Report success truthfully

Remediation is **COMPLETE** only when all six layers are GREEN, all required issues are resolved, and all required verification has passed. A CORE pass, healthy rollout, tracked deferral, accepted decision, or resolved symptom alone does not satisfy this gate.

A blocked remediation ends **BLOCKED/INCOMPLETE**, with unresolved findings and untested gates explicitly listed. Finishing an authorized audit/recon report is report completion only; its health result can remain non-GREEN or UNKNOWN. Never claim fixes, tests, remote publication, approvals, or pushed commits that did not occur.
