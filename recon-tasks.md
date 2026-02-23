# Homelab Recon Task Tracker

**Purpose**: Resumable checklist for executing `/homelab-recon` end-to-end
**Created**: 2026-02-22

> Notes:
> - Keep all executable checkboxes top-level (`- [ ]`).
> - Use this file as your source of truth for progress.
> - Reference evidence artifacts in the status report.

---

## Pillar 1: Validation

- [x] 1.0 Initialize run (create `$REPORT_FILE`, `$CONTEXT_DIR`, and this tracker)
- [x] 1.0.1 Toolchain gate passed (missing tools installed)
- [x] 1.1 Access established (workstation; controller fallback only if needed)
- [x] 1.2 Access validated (kubectl, SSH, Gitea API all succeed)

---

## Pillar 2: Context Pack (Evidence)

- [x] 1.3 Baseline health snapshot captured (prefer script + JSON)
- [x] 1.4 Network evidence captured (prefer script + JSON)
- [x] 1.5 Storage/NAS evidence captured (prefer script + JSON)
- [x] 1.6 System/Core evidence captured (kube-system, CNI)
- [x] 1.7 Ceph storage evidence captured (Rook/Ceph)
- [x] 1.8 Platform evidence captured (Ingress, Certs, Secrets, Observability)
- [x] 1.9 Apps evidence captured (error-focused; logs/describe for non-running pods)
- [x] 1.10 Repo evidence captured (Issues + PRs + Dependency Dashboard body)

---

## Pillar 3: Synthesis (Maintenance Spec)

- [x] 2.1 All changes identified from Phase 1 evidence
- [x] 2.2 Reasons documented for each change
- [x] 2.3 Constraints defined (ordering, downtime, windows)
- [x] 2.4 Acceptance criteria set (ALL layers GREEN)
- [x] 3.1 Decision gates identified
- [x] 3.2 Human escalation rules applied where required
- [x] 3.3 All other decisions encoded as tasks
- [x] 4.1 Tasks ordered by priority (P0→P3) and layer (Metal→Network→Storage→System→Platform→Apps)
- [x] 4.2 Validation gate defined for post-change checks
- [x] 4.3 Stop conditions documented
- [x] 5.1 Status report written to `reports/status-report-YYYY-MM-DD.md`
- [x] 5.2 Maintenance issue created OR updated (body edited, no comments)
- [x] 5.3 Issue follows contract template (all required sections present)

---

## Pillar 4: Audit

- [x] 6.1 Every non-GREEN finding has a remediation task or decision gate
- [x] 6.2 Every PR has spec row + decision + validation task
- [x] 6.3 Major/breaking updates have release notes + staged rollout
- [x] 6.4 Risky steps include backups + rollback procedures
- [x] 6.5 Tasks are top-level `- [ ]`, atomic, and ordered
- [x] 6.6 ALL contract requirements met (agent verified)
- [x] 7.x Remediation loop complete (if any audit checks failed)

---

## Pillar 5: Handoff

- [x] 8.1 Status report written and complete
- [x] 8.2 Maintenance issue ready for `/homelab-action` consumption
- [x] 8.3 NO changes made to cluster, repos, or infrastructure
