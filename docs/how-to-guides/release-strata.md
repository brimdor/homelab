# Release Strata through canary

Strata production is promoted only from a user-approved canary candidate. The gate covers application changes and deployment-only changes.

## Candidate identity

Identify each candidate with all three of these values:

- the application source tree ID (or commit SHA when already committed);
- the immutable registry image digest, not only a mutable tag;
- the homelab commit containing the rendered `strata-canary` configuration.

Approval applies only to that tuple. Do not rebuild the image during promotion. Any change to release contents, including a remediation, dependency update, rebase, merge resolution, or included documentation change, creates a new candidate and clears prior approval.

## Release flow

1. Inspect the application diff and identify affected user flows, API routes, permissions, database behavior, dependencies, and deployment settings.
2. Run the Strata repository's focused tests for the affected areas and its full CI command. Stop and remediate failures.
3. Build and push one immutable candidate image. Resolve and record its registry digest.
4. Update only `apps/strata-canary` to that candidate. Preserve canary isolation: canary hostname, session cookie, seed behavior, and ephemeral data must not be replaced with production values.
5. Render, lint, and inspect the canary chart. Commit and push this canary deployment to Gitea `master`, refresh the `strata-canary` Argo CD Application, and wait for it to be Synced and Healthy.
6. Verify the candidate's logs, events, probes, ingress, TLS, and `/api/health`, then run the automated behavioral checks against canary.
7. Give the user the candidate identifiers and a manual checklist tailored to the work. The approval gate is now open.
8. If the user reports a finding, close the gate, remediate it, and restart at step 1 with a new candidate. Do not carry successful checklist results or approval forward when the affected behavior could have changed.
9. After the user explicitly approves the current candidate, merge or finalize the exact application source tree without changing its contents.
10. Update only the intended image and configuration in `apps/strata`. Use the approved image digest and preserve the production hostname, session cookie, `SEED_DATA=false`, NFS data path, secrets, and production resource policy.
11. Render and diff production against both its current state and the approved canary candidate. Commit and push the promotion to Gitea `master`, refresh `strata`, and wait for it to be Synced and Healthy.
12. Verify the real production behavior and the repository-wide all-green gate. Roll back through Git if the approved desired state proves wrong.

The canary deployment commit in step 5 is necessary to run the approval environment. It is distinct from the application merge and production promotion, which remain blocked until step 9.

## Manual checklist construction

Start every approval request with these smoke and regression checks:

- open `https://strata-canary.eaglepass.io` and confirm TLS, initial load, navigation, and no visible or browser-console errors;
- sign in and sign out, refresh the page, and confirm the canary session behaves correctly without affecting a production Strata session;
- exercise the core workspace, board, list, and card path that the candidate could regress;
- verify authorization with at least one allowed role and one denied role when permissions are in scope;
- confirm changed data survives the expected in-pod application restart behavior, while recognizing that the current canary `emptyDir` is not evidence for production NFS durability;
- confirm `/api/health` is healthy and there are no new pod errors, failed requests, restarts, or warning events during the test.

Then add tests derived from the actual diff:

| Change area | Required checklist coverage |
| --- | --- |
| React UI, styling, or navigation | Every changed interaction; loading, empty, error, and success states; keyboard use; relevant mobile and desktop widths; light/dark themes when affected |
| Authentication, sessions, or profile | Valid and invalid sign-in; sign-out; refresh/session restoration; cookie isolation; self versus other-user behavior |
| RBAC or administration | Each affected role/action pair, including explicit denial; direct API access as well as hidden or disabled UI controls |
| Workspace, board, list, or card behavior | Create, read, update, delete, ordering/selection, refresh persistence, realtime or scheduled side effects, and relevant multi-user behavior |
| API route or validation | Valid request, malformed input, missing object, conflict/duplicate case, permission failure, and stable error response without sensitive leakage |
| SQLite schema or stored data | Upgrade from a production-like sanitized schema/data copy, application startup, data preservation, migration idempotence on a second start, and rollback/compatibility assumptions |
| Attachments or filesystem behavior | Upload, view/download, rename or metadata update, delete/cleanup, size/type failure, permissions, and a separate production-storage proof when canary storage cannot represent NFS |
| Automation, scheduling, or realtime | Trigger conditions, non-trigger conditions, timing, duplicate prevention, refresh/reconnect behavior, and audit/history output |
| Container, dependency, probe, ingress, or policy | Startup/readiness/liveness, graceful restart, resource behavior, outbound dependencies, ingress/TLS, network-policy access, and logs/events |

Omit irrelevant rows. Name the precise controls, routes, roles, and edge cases introduced or changed by the candidate so the user can execute the list without reading the implementation diff.

## Approval request

The approval request must state:

- source tree or commit;
- image repository and digest;
- canary deployment commit;
- canary URL;
- automated validation completed;
- the tailored manual checklist;
- known differences between canary and production that limit what canary proves.

Only an explicit approval of the identified current candidate opens production promotion. A reported finding closes the gate immediately.
