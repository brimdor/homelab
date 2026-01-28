# Quickstart: Fix Reminder Scheduling

## Local Validation

1. Render the Moltbot chart:
   - `helm template apps/moltbot --values apps/moltbot/values.yaml`
2. Validate the patched `parseTimeWithZone` behavior using the repo test harness (added in this feature).

## Manual Spot Check (Cluster)

1. Ask Moltbot in Discord:
   - "remind me today at 15:30"
   - "remind me in 10 minutes"
2. Inspect the created cron job in the Moltbot gateway (or UI) and confirm the next run time matches the request in `America/Chicago`.
