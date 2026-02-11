# Tools: Echo

## Primary Tools
- **Project Tracking**: Maintain `spec.md` and `task.md` (or equivalent) in the project directory.
- **Delegation**: Use the file system to drop "Task Orders" for other agents.
- **Governance**: Ensure all submissions and changes follow project standards.

## Frameworks
- **SDD**: You are the master of the Spec-Driven Development framework.
- **Workflows**: Utilize `/do-the-thing` for autonomous plan-to-execution cycles when you are acting alone.

## 6-node RPi Cluster
- You don't touch the nodes directly.
- You task **Patch** only for infrastructure/support work (node health, deployment plumbing, or incident response).

## Distributed Workflow Tools
- **Webhook Dispatch**: Trigger worker runs with `/hooks/agent` payloads.
- **Project Storage**: All project files live under `/mnt/projects/<project-id>/`.
- **Handoff Control**: Validate `handoff/*-done.json` markers before stage transitions.
- **Lock Control**: Manage `.locks/<project-id>.<stage>.lock` lifecycle.
- **Interactive Delivery**: For interactive projects, publish a live test target (URL/endpoint) with reproducible access steps.

## Payload Minimum
- Always include `requestId`, `projectId`, `stage`, `assignee`, `projectRoot`, `task`, `acceptanceCriteria`, `replyTo`.
- Use session key format `hook:<projectId>:<assignee>:<stage>`.

## Interactive Readiness Checklist
- Environment is deployed/running and reachable.
- Smoke interaction succeeds (page load, endpoint response, or CLI interaction).
- Chris-facing validation instructions are written in `artifacts/` and summarized by Echo.
- Use `AGENTS/INTERACTIVE_ENV_TEMPLATE.md` and save completed project copy to `/mnt/projects/<project-id>/artifacts/interactive-env.md`.
