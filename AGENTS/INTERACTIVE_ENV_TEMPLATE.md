# Interactive Environment Template

Use this template for any project that has an interactive surface (web app, API, dashboard, bot UI, CLI workflow). Save a completed copy at:

- `/mnt/projects/<project-id>/artifacts/interactive-env.md`

---

## Project

- `projectId`:
- `projectRoot`:
- `preparedBy`:
- `timestamp`:

## Environment Summary

- `type`: web-app | api | dashboard | bot | cli | mixed
- `status`: ready | blocked | partial
- `deploymentScope`: local-rpi | cluster | external
- `owner`: echo | patch | forge | pixel | scope | vista

## Access Details

- `primaryUrl`:
- `secondaryUrls`:
- `apiBaseUrl`:
- `testEndpoint`:
- `requiredNetwork`: lan | tailnet | public
- `authRequired`: yes | no
- `authMethod`: none | basic | token | oauth | other

## Validation Steps for Chris

1. Open:
2. Sign in / authenticate:
3. Perform this action:
4. Expected result:
5. Optional deep check:

## Smoke Check Results

- `serviceReachable`: pass | fail
- `basicInteraction`: pass | fail
- `knownLimitations`:
- `lastSmokeRun`:

## Runtime and Operations

- `runCommand`:
- `buildCommand`:
- `healthCommand`:
- `logsLocation`:
- `restartMethod`:

## Dependencies

- `infraDependencies`:
- `secretsDependencies`:
- `dataDependencies`:

## Risks and Constraints

- `currentRisks`:
- `resourceConstraints`:
- `securityNotes`:

## Rollback / Recovery

- `rollbackTrigger`:
- `rollbackSteps`:
- `recoveryVerification`:

## Handoff Metadata

- `relatedRequestId`:
- `relatedStage`:
- `completionMarker`:
- `evidenceFiles`:

---

## Quick Rules

- Echo includes this environment summary in stakeholder updates.
- Do not mark a project ready for sign-off without a completed template for interactive projects.
- Keep this file updated whenever endpoints, auth, or run commands change.
