# Tools: Forge

## Primary Tools
- **Code Editing**: Use native file editing tools.
- **Version Control**: Appropriate tools for state persistence if a repository is used.
- **Validation**: Use linting and testing frameworks defined in the spec.

## Reference Library
- Language-specific documentation (JS, Go, Python, etc.).
- Project-wide coding standards.
- Existing shared libraries in the project.

## Execution Guardrails
- Build for ARM64.
- Follow encrypted secrets patterns for all sensitive data.

## Workflow Tools
- Read assigned webhook payload and verify required fields before execution.
- Implement code in `/mnt/projects/<project-id>/src/`.
- Write completion marker in `/mnt/projects/<project-id>/handoff/`.
- Respect lock file lifecycle in `/mnt/projects/<project-id>/.locks/`.
