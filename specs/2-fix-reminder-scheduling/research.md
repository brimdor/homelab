# Research: Fix Reminder Scheduling

## Default Timezone for "at" Schedules

**Decision**: When `schedule.tz` is not provided, interpret `schedule.at` using the runtime environment timezone.

**Rationale**:
- The cron tool documentation explicitly allows `schedule.at` values like `YYYY-MM-DD HH:mm` and marks `tz` as optional.
- Current behavior treats non-offset ISO/date strings as UTC, which shifts wall-clock time when `TZ` is set (e.g., `America/Chicago`) and can cause off-by-one-day around midnight.

**Alternatives Considered**:
- Default to UTC: simple, but contradicts the "optional tz" UX and produces surprising outcomes in a non-UTC runtime.
- Require tz always: improves correctness but makes the tool harder for agents/users and breaks existing calls.
