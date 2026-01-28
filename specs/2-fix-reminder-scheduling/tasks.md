# Tasks: Fix Reminder Scheduling

## Phase 1: Setup

- [x] T001 [P] Define regression cases for schedule parsing (specs/2-fix-reminder-scheduling/research.md)

## Phase 2: Foundational

- [x] T002 Update default timezone behavior for `schedule.at` parsing (apps/moltbot/values.yaml)
- [x] T003 Default missing `schedule.tz` for `kind="at"` schedules to system timezone (apps/moltbot/values.yaml)

## Phase 3: User Story 1 - Create Accurate One-Off Reminder (P1)

- [x] T004 [US1] Add parsing tests for absolute local times (test/moltbot_cron_time_test.go)
- [x] T005 [US1] Add parsing tests for explicit offset/Z inputs (test/moltbot_cron_time_test.go)
- [x] T006 [US1] Add near-midnight day-boundary test cases (test/moltbot_cron_time_test.go)
- [x] T011 [US1] Add tests for cron-tool schedule coercion (test/moltbot_cron_tool_test.go)

## Phase 4: User Story 2 - Create Accurate Relative-Time Reminder (P1)

- [x] T007 [US2] Add test case that mirrors "in X minutes" behavior via computed absolute timestamps (test/moltbot_cron_time_test.go)

## Phase 5: Unambiguous Inspection (P2)

- [x] T008 Ensure stored schedules include timezone when omitted so UI/debug output is unambiguous (apps/moltbot/values.yaml)

## Final Phase: Polish

- [ ] T009 Run `make test` and fix any failures (test/)
- [ ] T010 Run `pre-commit run --all-files` (repo root)
