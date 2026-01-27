# Data Model: Fix Reminder Scheduling

This feature does not introduce new persisted entities in the homelab repo.

Relevant existing Clawdbot concepts (patched behavior only):

- **Cron Job Schedule**
  - `kind`: `at` | `every` | `cron`
  - `at`: string (e.g., `YYYY-MM-DD HH:mm` or ISO without offset)
  - `tz`: string (IANA timezone, optional)
  - `atMs`: number (legacy absolute timestamp)
