# Tools: Pixel

## Primary Tools
- **Design Systems**: Vanilla CSS, modern JS frameworks (if specified).
- **Asset Generation**: Use AI tools for icon and image creation.
- **Mockups**: Use HTML/CSS for interactive prototypes.

## Reference Library
- Modern UI/UX patterns (Glassmorphism, Dark UI).
- Google Fonts (Inter, Roboto, etc.).
- Project standard design tokens.

## Design Guardrails
- Optimization: SVGs over PNGs.
- Consistency: Follow the project's color palette strictly.

## Workflow Tools
- Read assigned webhook payload and verify required fields before execution.
- Implement UI work in `/mnt/projects/<project-id>/ui/`.
- Write completion marker in `/mnt/projects/<project-id>/handoff/`.
- Respect lock file lifecycle in `/mnt/projects/<project-id>/.locks/`.
