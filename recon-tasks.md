# Homelab Recon Task Tracker

**Purpose**: Resumable checklist for executing `/homelab-recon` end-to-end
**Created**: [YYYY-MM-DD]

> Notes:
> - Keep all executable checkboxes top-level (`- [ ]`).
> - Use this file as your source of truth for progress.
> - Reference evidence artifacts in the status report.

---

## Pillar 1: Validation

- [ ] 1.0 Initialize run (create `$REPORT_FILE`, `$CONTEXT_DIR`, and this tracker)
- [ ] 1.0.1 Toolchain gate passed (missing tools installed)
- [ ] 1.1 Access established (workstation; controller fallback only if needed)
- [ ] 1.2 Access validated (kubectl, SSH, Gitea API all succeed)

---

## Pillar 2: Context Pack (Evidence)

- [ ] 1.3 Baseline health snapshot captured (prefer script + JSON)
- [ ] 1.4 Network evidence captured (prefer script + JSON)
- [ ] 1.5 Storage/NAS evidence captured (prefer script + JSON)
- [ ] 1.6 System/Core evidence captured (kube-system, CNI)
- [ ] 1.7 Ceph storage evidence captured (Rook/Ceph)
- [ ] 1.8 Platform evidence captured (Ingress, Certs, Secrets, Observability)
- [ ] 1.9 Apps evidence captured (error-focused; logs/describe for non-running pods)
- [ ] 1.10 Repo evidence captured (Issues + PRs + Dependency Dashboard body)

---

## Pillar 3: Synthesis (Maintenance Spec)

- [ ] 2.1 All changes identified from Phase 1 evidence
- [ ] 2.2 Reasons documented for each change
- [ ] 2.3 Constraints defined (ordering, downtime, windows)
- [ ] 2.4 Acceptance criteria set (ALL layers GREEN)
- [ ] 3.1 Decision gates identified
- [ ] 3.2 Human escalation rules applied where required
- [ ] 3.3 All other decisions encoded as tasks
- [ ] 4.1 Tasks ordered by priority (P0→P3) and layer (Metal→Network→Storage→System→Platform→Apps)
- [ ] 4.2 Validation gate defined for post-change checks
- [ ] 4.3 Stop conditions documented
- [ ] 5.1 Status report written to `reports/status-report-YYYY-MM-DD.md`
- [ ] 5.2 Maintenance issue created OR updated (body edited, no comments)
- [ ] 5.3 Issue follows contract template (all required sections present)

---

## Pillar 4: Audit

- [ ] 6.1 Every non-GREEN finding has a remediation task or decision gate
- [ ] 6.2 Every PR has spec row + decision + validation task
- [ ] 6.3 Major/breaking updates have release notes + staged rollout
- [ ] 6.4 Risky steps include backups + rollback procedures
- [ ] 6.5 Tasks are top-level `- [ ]`, atomic, and ordered
- [ ] 6.6 ALL contract requirements met (agent verified)
- [ ] 7.x Remediation loop complete (if any audit checks failed)

---

## Pillar 5: Handoff

- [ ] 8.1 Status report written and complete
- [ ] 8.2 Maintenance issue ready for `/homelab-action` consumption
- [ ] 8.3 NO changes made to cluster, repos, or infrastructure
