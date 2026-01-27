# Feature Specification: Fix Reminder Scheduling

**Feature Branch**: `2-fix-reminder-scheduling`
**Created**: 2026-01-27
**Status**: Implemented (Validation Pending)
**Test Report**: `tests/reports/2-fix-reminder-scheduling-2026-01-27T22-20-33Z.md`
**Input**: User description: "Clawdbot is setting cronjobs incorrectly when I ask it to setup a reminder in Discord. It responds with understanding and even states back the desired outcome but when I look at the cronjob, it has a later day and time. Please focus on this issue and resolve it where if the Agent is asked to set a reminder at a specific time or in X number of minutes, it needs to properly set the date/time."

## Clarifications

- **CLAR-001 (Timezone source)**: Use the runtime environment timezone (`TZ`), which is set to `America/Chicago`.

## User Scenarios & Testing

### User Story 1 - Create Accurate One-Off Reminder (Priority: P1)

As a user, I want to ask Clawdbot to set a reminder at a specific date/time so that the resulting CronJob triggers at that exact intended moment.

**Independent Test**: Use the Clawdbot reminder command to create a reminder, then inspect the generated CronJob `spec.schedule` (and `spec.timeZone` if used) and verify the next run time matches the requested moment.

**Acceptance Scenarios**:

1. **Given** a request "remind me today at 15:30", **When** Clawdbot creates the reminder CronJob, **Then** the CronJob is scheduled for the same calendar day and the intended local time.
2. **Given** a request "remind me on 2026-02-01 at 09:00", **When** Clawdbot creates the reminder CronJob, **Then** the CronJob schedule corresponds to 2026-02-01 09:00 in the intended timezone.

### User Story 2 - Create Accurate Relative-Time Reminder (Priority: P1)

As a user, I want to ask Clawdbot to remind me in X minutes so that the CronJob triggers X minutes from now (within a small tolerance).

**Independent Test**: Capture a stable "now" timestamp, create a reminder "in 10 minutes", then verify the CronJob schedules its next run for now+10m (within tolerance).

**Acceptance Scenarios**:

1. **Given** a request "remind me in 10 minutes", **When** Clawdbot creates the reminder CronJob, **Then** the next run time is between now+9m and now+11m.
2. **Given** a request "remind me in 90 minutes", **When** Clawdbot creates the reminder CronJob, **Then** the next run time is between now+89m and now+91m.

## Requirements

### Functional Requirements

- **FR-001**: When a reminder is requested for a specific date/time, Clawdbot MUST schedule the CronJob to run at that exact intended moment (same date and time) in the intended timezone.
- **FR-002**: When a reminder is requested "in X minutes", Clawdbot MUST schedule the CronJob to run X minutes from the time the request is processed, within a tolerance of +/- 60 seconds.
- **FR-003**: Clawdbot MUST avoid off-by-one-day errors when converting between timezones, especially around midnight boundaries.
- **FR-004**: If a reminder schedule is provided without an explicit timezone, Clawdbot MUST default to the runtime environment timezone (`TZ`) and the resulting cron job MUST retain the timezone used so that later inspection is unambiguous.
- **FR-005**: The "intended timezone" used for parsing/scheduling MUST be the runtime environment timezone (`TZ`, currently `America/Chicago`).

### Key Entities

- **Reminder**: A one-off scheduled action that posts a message to Discord at a specific moment.
- **Target Time**: The resolved timestamp (instant in time) that the reminder should trigger.

## Edge Cases

- Requests that imply "today" but the requested time has already passed should schedule for the next valid occurrence and clearly state that adjustment.
- Daylight Saving Time transitions (spring forward / fall back) must not silently shift the intended wall-clock time; confirmation must be unambiguous.
- If the cluster/controller interprets cron expressions in a different timezone, the manifest must specify a timezone explicitly (or otherwise compensate) so the runtime behavior matches the user intent.

## Success Criteria

### Measurable Outcomes

- **SC-001**: For at least 10 representative reminder phrases (mix of absolute and relative), the resulting CronJob's next run time matches the requested moment within the defined tolerances.
- **SC-002**: No reminders are scheduled on the wrong calendar day in test cases near midnight or across timezone boundaries.
- **SC-003**: Clawdbot responses include an unambiguous resolved timestamp and that timestamp matches what is scheduled.
