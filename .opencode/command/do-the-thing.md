---
description: Execute the complete Spec-Driven Development workflow autonomously from initial idea through implementation. This is a self-contained orchestrator that performs all SDD phases internally without calling other slash commands.
scripts:
  sh: scripts/bash/create-new-feature.sh --json "{ARGS}"
  ps: scripts/powershell/create-new-feature.ps1 -Json "{ARGS}"
prereq_scripts:
  sh: scripts/bash/check-prerequisites.sh --json
  ps: scripts/powershell/check-prerequisites.ps1 -Json
analysis_scripts:
  sh: scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
  ps: scripts/powershell/check-prerequisites.ps1 -Json -RequireTasks -IncludeTasks
plan_scripts:
  sh: scripts/bash/setup-plan.sh --json
  ps: scripts/powershell/setup-plan.ps1 -Json
agent_scripts:
  sh: scripts/bash/update-agent-context.sh __AGENT__
  ps: scripts/powershell/update-agent-context.ps1 -AgentType __AGENT__
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

The text the user typed after `/do-the-thing` **is** their initial feature idea or goal.

---

# Agentic Spec-Driven Development

This command executes the **complete SDD workflow autonomously**. Each phase is performed internally. It performs each step automatically.

## Execution Model

Output format for phase transitions:

```
## Phase N: [Phase Name]
[Execute phase work directly]
```

After completing each phase, immediately begin the next phase. Pause only when human input is genuinely required (constitution creation, clarification questions).

---

## Phase 1: Context Loading

### 1.0 Check GitHub Repository Existence

Before any git operations, verify that a GitHub repository exists for this project.

**1.0.1 Detect Repository Name**

```bash
# Get the workspace/folder name (this becomes the expected repo name)
REPO_NAME=$(basename "$PWD")

# Get the GitHub username
GH_USER=$(gh api user --jq '.login' 2>/dev/null)
```

**1.0.2 Check Remote Configuration**

```bash
# Check if origin remote exists
git remote get-url origin 2>/dev/null

# If origin exists, extract owner/repo from URL
# Formats: git@github.com:owner/repo.git OR https://github.com/owner/repo.git
```

**1.0.3 Verify Repository Exists on GitHub**

```bash
# Check if the repository exists on GitHub
gh repo view "$GH_USER/$REPO_NAME" --json name 2>/dev/null
```

**1.0.4 Repository Status Determination**

| Condition | Status | Action |
|-----------|--------|--------|
| Origin remote exists AND repo accessible | ✅ REMOTE_AVAILABLE | Proceed to §1.1 |
| Origin remote exists BUT repo inaccessible | ⚠️ REMOTE_CONFIGURED_UNAVAILABLE | Warn and ask user |
| No origin remote AND repo exists on GitHub | ⚠️ REMOTE_MISSING | Offer to add remote |
| No origin remote AND repo NOT on GitHub | ❌ NO_REMOTE_REPO | Ask to create repo |

**1.0.5 If Repository Does Not Exist**

Output:
```
## Phase 1: Context Loading

⚠️ **GitHub repository not found.**

| Detail | Value |
|--------|-------|
| Expected Repository | [GH_USER]/[REPO_NAME] |
| Local Workspace | [PWD] |
| Git Initialized | Yes/No |

The repository "[REPO_NAME]" does not exist on GitHub for user "[GH_USER]".

Would you like me to create the repository on GitHub?

| Option | Action |
|--------|--------|
| Y | **Create Repository** - Create "[GH_USER]/[REPO_NAME]" on GitHub (private by default) |
| P | **Create Public Repository** - Create as a public repository |
| N | **Continue Without Remote** - Proceed with local-only workflow (no push/PR operations) |

Reply with Y, P, or N.
```

**1.0.6 Execute User Choice**

**Option Y - Create Private Repository:**
```bash
# Initialize git if needed
git init 2>/dev/null || true

# Create the repository on GitHub
gh repo create "$REPO_NAME" --private --source=. --remote=origin

# Verify creation
gh repo view "$GH_USER/$REPO_NAME" --json name
```

Set: `REMOTE_AVAILABLE=true`

Output:
```
✓ Repository created: https://github.com/[GH_USER]/[REPO_NAME]
✓ Remote 'origin' configured.
```

Proceed to §1.1.

**Option P - Create Public Repository:**
```bash
# Initialize git if needed
git init 2>/dev/null || true

# Create the repository on GitHub
gh repo create "$REPO_NAME" --public --source=. --remote=origin

# Verify creation
gh repo view "$GH_USER/$REPO_NAME" --json name
```

Set: `REMOTE_AVAILABLE=true`

Output:
```
✓ Public repository created: https://github.com/[GH_USER]/[REPO_NAME]
✓ Remote 'origin' configured.
```

Proceed to §1.1.

**Option N - Continue Without Remote:**

Set: `REMOTE_AVAILABLE=false`

Output:
```
⚠️ Continuing without remote repository.

The following operations will be skipped during this workflow:
- git push (all push operations)
- Pull request creation
- Remote branch operations

All other local operations (commits, branches, specs, implementation) will proceed normally.
```

Proceed to §1.1.

**1.0.7 If Remote Missing but Repo Exists**

If no origin remote is configured but the repo exists on GitHub:

```
## Phase 1: Context Loading

⚠️ **Remote not configured but repository exists.**

| Detail | Value |
|--------|-------|
| Repository Found | [GH_USER]/[REPO_NAME] |
| Local Workspace | [PWD] |
| Origin Remote | Not configured |

Would you like me to add the remote?

| Option | Action |
|--------|--------|
| Y | **Add Remote** - Configure origin to point to the existing repository |
| N | **Continue Without Remote** - Proceed with local-only workflow |

Reply with Y or N.
```

**Option Y - Add Remote:**
```bash
git remote add origin "https://github.com/$GH_USER/$REPO_NAME.git"
# Or for SSH: git remote add origin "git@github.com:$GH_USER/$REPO_NAME.git"
```

Set: `REMOTE_AVAILABLE=true`

Proceed to §1.1.

**1.0.8 Repository Check Complete**

If repository exists and is accessible:
```
✓ Repository verified: [GH_USER]/[REPO_NAME]
```

Proceed to §1.1.

---

### 1.1 Check for Pending Work

Before starting any new specification work, verify the workspace is clean. Execute the following checks across all branches:

**1.1.1 Git State Detection**

```bash
# Fetch all remote branches (skip if REMOTE_AVAILABLE=false)
[ "$REMOTE_AVAILABLE" = "true" ] && git fetch --all --prune

# Check for uncommitted changes (staged and unstaged)
git status --porcelain

# List all local branches with unpushed commits
git branch -vv | grep -E '\[.*: ahead'

# List all feature branches (local and remote)
git branch -a | grep -E '[0-9]+-'

# Check for stashed changes
git stash list
```

**1.1.2 Pending Items Inventory**

Build an inventory of all pending work:

| Category | Check | Status | Remote Required |
|----------|-------|--------|-----------------|
| Uncommitted Changes | `git status --porcelain` not empty | ✓ Clean / ⚠ Pending | No |
| Staged Changes | `git diff --cached --stat` has output | ✓ Clean / ⚠ Pending | No |
| Unpushed Commits | Local commits not on remote | ✓ Clean / ⚠ Pending / ⊘ Skipped | Yes |
| Stashed Changes | `git stash list` not empty | ✓ Clean / ⚠ Pending | No |
| Open Feature Branches | Branches matching `[0-9]+-*` pattern | ✓ None / ⚠ Found | No |
| Unmerged PRs | Open PRs for current repo | ✓ None / ⚠ Found / ⊘ Skipped | Yes |

**Note**: If `REMOTE_AVAILABLE=false`, skip checks marked "Remote Required" and mark as "⊘ Skipped".

**1.1.3 If Pending Work Detected**

Output:
```
## Phase 1: Context Loading

⚠️ **Pending work detected that requires attention before starting a new spec.**

### Pending Items:

| Item | Branch/Location | Description |
|------|-----------------|-------------|
| [type] | [branch/path] | [details] |
...

### Current Branch: [branch_name]
### Working Directory Status: [clean/dirty]
```

Then present options:

```
**Recommended:** [Option based on context - see recommendation logic below]

How would you like to proceed?

| Option | Action | Remote Required |
|--------|--------|-----------------|
| A | **Commit & Push All** - Stage all changes, commit with auto-generated message, and push to current branch | Yes (commit only if no remote) |
| B | **Commit & Push with Message** - Stage all changes, commit with your message, and push | Yes (commit only if no remote) |
| C | **Stash Changes** - Stash current changes to work on later, proceed with clean state | No |
| D | **Discard Changes** - Discard all uncommitted changes (⚠️ destructive) | No |
| E | **Switch to Feature Branch** - Switch to an existing feature branch to continue that work | No |
| F | **Merge Feature Branch** - Merge a completed feature branch into main/default branch | Yes (local merge only if no remote) |
| G | **Create PR** - Create a pull request for the current or specified branch | Yes (unavailable if no remote) |
| H | **Review & Close PR** - Review and merge/close an existing open PR | Yes (unavailable if no remote) |
| I | **Delete Stale Branches** - Clean up merged or abandoned feature branches | Partial (local only if no remote) |
| J | **Pop Stash** - Apply and remove the most recent stash | No |
| K | **Proceed Anyway** - Continue with new spec (⚠️ may cause conflicts) | No |
| L | **Custom Instructions** - Provide your own instructions for handling pending work | Varies |

**Note**: If `REMOTE_AVAILABLE=false`, options G and H are unavailable. Options A, B, F, I will perform local operations only (no push).

Reply with option letter, or type custom instructions.
```

**1.1.4 Recommendation Logic**

Provide a recommendation based on detected state:

- If uncommitted changes + on feature branch → **Recommend B** (Commit & Push with Message) or **Commit Only** if no remote
- If uncommitted changes + on main branch → **Recommend C** (Stash Changes)
- If unpushed commits only + remote available → **Recommend A** (Commit & Push All)
- If unpushed commits only + no remote → **Recommend K** (Proceed) since push is not possible
- If stashed changes only → **Recommend J** (Pop Stash) or **K** (Proceed) based on stash age
- If open feature branches with no local changes → **Recommend F** (Merge) or **H** (Review PR) if remote available
- If multiple issues detected → **Recommend handling in order**: commits → pushes → PRs → branches

**1.1.5 Execute User Choice**

Based on user selection:

**Option A - Commit & Push All:**
```bash
git add -A
git commit -m "chore: finalize pending changes before new spec"
# Only push if remote is available
[ "$REMOTE_AVAILABLE" = "true" ] && git push origin HEAD
```

If `REMOTE_AVAILABLE=false`:
```
✓ Changes committed locally. Push skipped (no remote repository).
```

**Option B - Commit & Push with Message:**
```
What commit message would you like to use?
```
Then:
```bash
git add -A
git commit -m "[user message]"
# Only push if remote is available
[ "$REMOTE_AVAILABLE" = "true" ] && git push origin HEAD
```

If `REMOTE_AVAILABLE=false`:
```
✓ Changes committed locally. Push skipped (no remote repository).
```

**Option C - Stash Changes:**
```bash
git stash push -m "Pre-spec stash $(date +%Y-%m-%d_%H-%M-%S)"
```

**Option D - Discard Changes:**
```
⚠️ This will permanently discard all uncommitted changes. Type "CONFIRM" to proceed.
```
If confirmed:
```bash
git checkout -- .
git clean -fd
```

**Option E - Switch to Feature Branch:**
```
Which branch would you like to switch to?

| # | Branch | Last Commit | Status |
|---|--------|-------------|--------|
| 1 | [branch] | [date/message] | [ahead/behind] |
...

Enter branch number or name.
```
Then:
```bash
git checkout [branch]
```
Return to §1.1 to reassess state on new branch.

**Option F - Merge Feature Branch:**
```
Which branch would you like to merge?

| # | Branch | Last Commit | Merge Status |
|---|--------|-------------|--------------|
| 1 | [branch] | [date/message] | [clean/conflicts] |
...

Enter branch number or name.
```
Then:
```bash
git checkout main  # or default branch
git merge [branch]
# Only push and delete remote if remote is available
[ "$REMOTE_AVAILABLE" = "true" ] && git push origin HEAD
git branch -d [branch]  # delete local after successful merge
[ "$REMOTE_AVAILABLE" = "true" ] && git push origin --delete [branch]  # delete remote
```

If `REMOTE_AVAILABLE=false`:
```
✓ Branch merged locally. Remote operations skipped (no remote repository).
```

**Option G - Create PR:**

If `REMOTE_AVAILABLE=false`:
```
⚠️ Cannot create pull request - no remote repository configured.

To create a PR, first create a GitHub repository using option Y in §1.0.5.
```
Return to option selection.

If `REMOTE_AVAILABLE=true`:
```
Creating PR for branch: [current_branch]

Title: [auto-generated from branch name or last commit]
Base: main

Would you like to customize the PR? (yes/no)
```
If yes, gather title and description. Then create PR using GitHub CLI or API.

**Option H - Review & Close PR:**

If `REMOTE_AVAILABLE=false`:
```
⚠️ Cannot review pull requests - no remote repository configured.
```
Return to option selection.

If `REMOTE_AVAILABLE=true`:
```
Open PRs requiring attention:

| # | PR | Branch | Author | Status | Checks |
|---|-----|--------|--------|--------|--------|
| 1 | #[num] [title] | [branch] | [author] | [state] | [pass/fail] |
...

Enter PR number to review, or "list" for more details.
```
After selection, present PR details and options:
```
| Action | Description |
|--------|-------------|
| M | Merge this PR |
| C | Close without merging |
| R | Request changes |
| V | View full diff |
| B | Back to list |
```

**Option I - Delete Stale Branches:**
```
Branches that appear safe to delete:

| # | Branch | Status | Last Activity | Location |
|---|--------|--------|---------------|----------|
| 1 | [branch] | merged/stale | [date] | local/remote/both |
...

Enter branch numbers to delete (comma-separated), or "all" for all listed.
```
Then:
```bash
git branch -d [branch]  # for each selected (local)
# Only delete remote branches if remote is available
[ "$REMOTE_AVAILABLE" = "true" ] && git push origin --delete [branch]  # if remote exists
```

If `REMOTE_AVAILABLE=false`:
```
✓ Local branches deleted. Remote branch deletion skipped (no remote repository).
```

**Option J - Pop Stash:**
```
Available stashes:

| # | Stash | Date | Message |
|---|-------|------|---------|
| 0 | stash@{0} | [date] | [message] |
...

Enter stash number to apply (default: 0).
```
Then:
```bash
git stash pop stash@{[n]}
```
Return to §1.1 to reassess state.

**Option K - Proceed Anyway:**
```
⚠️ Proceeding with pending work may cause:
- Merge conflicts when switching branches
- Lost changes if not committed
- Confusion about which changes belong to which feature

Are you sure you want to proceed? (yes/no)
```
If yes, proceed to §1.2.

**Option L - Custom Instructions:**
```
Provide your instructions for handling the pending work:
```
Execute user's custom instructions, then return to §1.1 to verify clean state.

**1.1.6 Verify Clean State**

After executing any option (except K), re-run checks from §1.1.1.

- If clean: Proceed to §1.2
- If still pending items: Return to §1.1.3 and present remaining items

**1.1.7 If No Pending Work**

If all checks pass (workspace is clean):
```
✓ Workspace clean. Proceeding with context loading...
```
Proceed to §1.2.

---

### 1.2 Check Constitution

Read `/memory/constitution.md`:

- **If exists**: Load as authoritative project constitution. Extract all MUST/SHOULD principles for later gates. Proceed to §1.3.

- **If missing AND new project** (no existing specs/): 
  
  Output:
  ```
  ## Phase 1: Context Loading
  
  No project constitution found. Creating constitution...
  ```
  
  Then execute Constitution Creation (see §Appendix A). After constitution is created, proceed to §1.3.

- **If missing AND existing project** (specs/ exists): Proceed to §1.3 without constitution.

### 1.3 Determine Feature Context

Parse environment for existing feature context:

- Check for `specs/<number>-<short-name>/` directories
- If JSON environment provides FEATURE_DIR, use it
- If multiple features exist and none specified, use the highest-numbered feature
- If no feature directory exists, proceed to Phase 2 (Specification)

### 1.4 Check for Unfinished Work

If FEATURE_DIR exists, scan `spec.md` for incomplete markers:
- `[FEATURE NAME]`, `[DATE]`, `[TODO]`, `[TBD]`
- Empty required sections
- Draft status with fewer than 3 user stories

If incomplete markers found:
```
Detected unfinished spec. Completing specification...
```
Resume Phase 2 (Specification) to complete the spec.

### 1.5 Validate User Input

If ALL true:
- No unfinished specs detected
- `$ARGUMENTS` is empty/blank  
- No existing feature context to continue

Then prompt once:
```
I need more information to proceed. Please describe the feature or task you want to work on.
```

Wait for response, then restart from §1.1.

### 1.6 Assess Current State

If FEATURE_DIR exists, check which artifacts are present:

| Artifact | Path | Status |
|----------|------|--------|
| spec.md | FEATURE_DIR/spec.md | Present/Missing |
| plan.md | FEATURE_DIR/plan.md | Present/Missing |
| tasks.md | FEATURE_DIR/tasks.md | Present/Missing |
| research.md | FEATURE_DIR/research.md | Present/Missing |
| data-model.md | FEATURE_DIR/data-model.md | Present/Missing |
| contracts/ | FEATURE_DIR/contracts/ | Present/Missing |
| checklists/ | FEATURE_DIR/checklists/ | Present/Missing |
| tests/reports/ | Test reports for this feature | Present/Missing |

Determine next phase based on state:

| State | Next Phase |
|-------|------------|
| No spec | Phase 2: Specification |
| Spec has `[NEEDS CLARIFICATION]` | Phase 3: Clarification |
| Spec exists, no plan | Phase 4: Planning |
| Plan exists, no tasks | Phase 5: Task Generation |
| Tasks exist, no analysis | Phase 6: Analysis |
| Analysis has issues | Phase 7: Remediation |
| Analysis clean, tasks incomplete | Phase 8: Implementation |
| All tasks complete, no test report | Phase 9: Testing & Validation |
| Test report has failures | Phase 9: Testing & Validation (remediation) |
| Test report passes | Spec Complete |

Proceed immediately to the determined phase.

---

## Phase 2: Specification

Output:
```
## Phase 2: Specification

Creating feature specification...
```

### 2.1 Generate Branch Name

From `$ARGUMENTS`, generate a concise short name (2-4 words):
- Use action-noun format (e.g., "user-auth", "fix-payment-timeout")
- Preserve technical terms and acronyms

### 2.2 Create Feature Branch

1. Fetch remote branches: `git fetch --all --prune`
2. Find highest feature number across:
   - Remote branches: `git ls-remote --heads origin | grep -E 'refs/heads/[0-9]+-<short-name>$'`
   - Local branches: `git branch | grep -E '^[* ]*[0-9]+-<short-name>$'`
   - Specs directories: `specs/[0-9]+-<short-name>`
3. Use N+1 for new feature number
4. Run `{SCRIPT}` with `--number N+1 --short-name "<short-name>" "<feature description>"`
5. Parse JSON output for BRANCH_NAME, SPEC_FILE, FEATURE_DIR

### 2.3 Load Spec Template

Read `templates/spec-template.md` for required structure.

### 2.4 Generate Specification

Parse `$ARGUMENTS` and extract:
- Actors (who uses this)
- Actions (what they do)
- Data (what's involved)
- Constraints (limitations)

Fill spec template with:

**User Scenarios & Testing** (mandatory):
- Create prioritized user stories (P1, P2, P3...)
- Each story must be independently testable
- Include acceptance scenarios in Given/When/Then format

**Requirements** (mandatory):
- Functional requirements (FR-001, FR-002...) - each must be testable
- Key entities if data is involved

**Success Criteria** (mandatory):
- Measurable, technology-agnostic outcomes
- No implementation details

For unclear aspects:
- Make informed guesses based on context and industry standards
- Mark with `[NEEDS CLARIFICATION: specific question]` only if:
  - Choice significantly impacts scope or UX
  - Multiple reasonable interpretations exist
  - No reasonable default exists
- **Maximum 3 `[NEEDS CLARIFICATION]` markers**

### 2.5 Write Specification

Write the completed spec to SPEC_FILE.

### 2.6 Create Quality Checklist

Generate `FEATURE_DIR/checklists/requirements.md`:

```markdown
# Specification Quality Checklist: [FEATURE NAME]

**Purpose**: Validate specification completeness before planning
**Created**: [DATE]

## Content Quality
- [ ] No implementation details (languages, frameworks, APIs)
- [ ] Focused on user value and business needs
- [ ] All mandatory sections completed

## Requirement Completeness
- [ ] Requirements are testable and unambiguous
- [ ] Success criteria are measurable and technology-agnostic
- [ ] All acceptance scenarios defined
- [ ] Edge cases identified
- [ ] Scope clearly bounded

## Feature Readiness
- [ ] All functional requirements have clear acceptance criteria
- [ ] User scenarios cover primary flows
- [ ] Feature meets measurable outcomes defined in Success Criteria
- [ ] No implementation details leak into specification
```

### 2.6.1 Domain-Specific Checklists (Optional)

If the spec involves specific domains, generate additional checklists as "unit tests for requirements":

**Checklist Principle**: Test the REQUIREMENTS quality, not implementation behavior.
- ✅ "Are [requirement type] defined/specified/documented for [scenario]?"
- ✅ "Is [vague term] quantified/clarified with specific criteria?"
- ❌ NOT "Verify the button clicks correctly" (implementation test)

**Domain Detection** - Create checklists based on spec content:
- If UX/UI requirements present → `checklists/ux.md`
- If API/integration requirements → `checklists/api.md`
- If security/auth requirements → `checklists/security.md`
- If performance requirements → `checklists/performance.md`

**Checklist Item Format**:
```markdown
- [ ] CHK### - [Question about requirement quality] [Dimension, Spec §X.Y]
```

Dimensions: `[Completeness]`, `[Clarity]`, `[Consistency]`, `[Measurability]`, `[Coverage]`, `[Gap]`, `[Ambiguity]`

### 2.7 Validate and Proceed

- If spec has `[NEEDS CLARIFICATION]` markers: Proceed to Phase 3
- If spec is complete: Proceed to Phase 4

---

## Phase 3: Clarification

Output:
```
## Phase 3: Clarification

Resolving specification ambiguities...
```

### 3.1 Load Spec

Read FEATURE_SPEC and identify all `[NEEDS CLARIFICATION: ...]` markers.

### 3.2 Perform Ambiguity Scan

Scan spec for these categories (mark each as Clear/Partial/Missing):

- Functional Scope & Behavior
- Domain & Data Model
- Interaction & UX Flow
- Non-Functional Quality Attributes
- Integration & External Dependencies
- Edge Cases & Failure Handling
- Constraints & Tradeoffs

### 3.3 Generate Questions

Create prioritized queue of clarification questions (maximum 5 total).

Each question must be answerable with:
- Multiple-choice (2-5 options), OR
- Short answer (≤5 words)

Only include questions that materially impact architecture, data modeling, or test design.

### 3.4 Ask Questions Sequentially

For each question, present ONE at a time:

**For multiple-choice:**
```
**Recommended:** Option [X] - [reasoning]

| Option | Description |
|--------|-------------|
| A | [description] |
| B | [description] |
| C | [description] |

Reply with the option letter, "yes" to accept recommendation, or your own short answer.
```

**For short-answer:**
```
**Suggested:** [proposed answer] - [reasoning]

Format: Short answer (≤5 words). Say "yes" to accept or provide your own.
```

After each answer:
- Record the answer
- Update the spec immediately:
  - Add to `## Clarifications` section
  - Update relevant requirement/story with the clarified detail
  - Remove the `[NEEDS CLARIFICATION]` marker
- Save the spec file
- Present next question

Stop when:
- All questions answered, OR
- User signals "done"/"proceed", OR
- 5 questions reached

### 3.5 Proceed to Planning

After clarifications complete:
```
Clarifications resolved. Proceeding to planning...
```

Proceed to Phase 4.

---

## Phase 4: Planning

Output:
```
## Phase 4: Planning

Generating implementation plan and design artifacts...
```

### 4.1 Setup

Run `{PLAN_SCRIPT}` and parse JSON for FEATURE_SPEC, IMPL_PLAN, SPECS_DIR, BRANCH.

### 4.2 Load Context

- Read FEATURE_SPEC
- Read `/memory/constitution.md` (if exists)
- Load plan template structure

### 4.3 Fill Technical Context

In plan.md, fill:
- Language/Version
- Primary Dependencies
- Storage
- Testing framework
- Target Platform
- Project Type
- Performance Goals
- Constraints
- Scale/Scope

Mark unknowns as `NEEDS CLARIFICATION` for research.

### 4.4 Constitution Check

If constitution exists, evaluate all principles against the planned approach:
- List each principle
- Mark compliance status
- If violations exist, document justification in Complexity Tracking table

### 4.5 Phase 0: Research

For each `NEEDS CLARIFICATION` in Technical Context:
1. Research the unknown
2. Document in `research.md`:
   ```markdown
   ## [Topic]
   **Decision**: [what was chosen]
   **Rationale**: [why chosen]
   **Alternatives Considered**: [what else evaluated]
   ```

Output: `research.md` with all technical unknowns resolved.

### 4.6 Phase 1: Design & Contracts

**Data Model** (`data-model.md`):
- Extract entities from spec
- Define fields, relationships, validation rules
- Document state transitions if applicable

**API Contracts** (`contracts/`):
- For each user action → endpoint
- Generate OpenAPI/GraphQL schemas
- Use standard REST patterns

**Quickstart** (`quickstart.md`):
- Integration scenarios
- Test data setup
- Development workflow

### 4.7 Update Agent Context

Run `{AGENT_SCRIPT}` to update agent-specific context files with new technology from this plan.

### 4.8 Determine Project Structure

Based on project type, select structure:

**Single project** (default):
```
src/
├── models/
├── services/
├── cli/
└── lib/
tests/
├── contract/
├── integration/
└── unit/
```

**Web application** (frontend + backend):
```
backend/
├── src/
└── tests/
frontend/
├── src/
└── tests/
```

**Mobile + API**:
```
api/
└── src/
ios/ or android/
└── [platform structure]
```

Document selected structure in plan.md.

### 4.9 Write Plan

Save completed plan.md with all sections filled.

Proceed to Phase 5.

---

## Phase 5: Task Generation

Output:
```
## Phase 5: Task Generation

Generating implementation tasks...
```

### 5.1 Setup

Run `{PREREQ_SCRIPT}` (with `--json` flags only, NOT `--require-tasks`) and parse FEATURE_DIR, AVAILABLE_DOCS.

**Note**: Tasks don't exist yet at this phase, so do not use `--require-tasks` flag.

### 5.2 Load Design Documents

Read from FEATURE_DIR:
- **Required**: plan.md, spec.md
- **Optional**: data-model.md, contracts/, research.md, quickstart.md

### 5.3 Extract Information

From spec.md:
- User stories with priorities (P1, P2, P3...)
- Functional requirements
- Edge cases

From plan.md:
- Tech stack and libraries
- Project structure
- Dependencies

From data-model.md (if exists):
- Entities and relationships

From contracts/ (if exists):
- API endpoints

### 5.4 Generate Tasks

Create `tasks.md` with this structure:

**Task Format**: `- [ ] [TaskID] [P?] [Story?] Description with file path`
- `[P]` = parallelizable
- `[Story]` = user story label (US1, US2, etc.)

**Phase 1: Setup** (shared infrastructure)
- Project structure creation
- Dependency initialization
- Linting/formatting configuration

**Phase 2: Foundational** (blocking prerequisites)
- Database schema
- Authentication framework
- API routing structure
- Base models
- Error handling
- Must complete before user stories

**Phase 3+: User Stories** (one phase per story, in priority order)
- Each story is independently testable
- Within each: Models → Services → Endpoints → Integration
- Include `[US#]` label on all tasks

**Final Phase: Polish**
- Cross-cutting concerns
- Documentation
- Performance optimization

### 5.5 Validate Tasks

Ensure:
- All tasks have checkbox, ID, and file path
- User story tasks have `[US#]` labels
- Dependencies are clear
- Each user story phase is independently testable

### 5.6 Write Tasks

Save completed tasks.md.

Proceed to Phase 6.

---

## Phase 6: Analysis

Output:
```
## Phase 6: Analysis

Performing cross-artifact consistency analysis...
```

### 6.1 Load Artifacts

Run `{ANALYSIS_SCRIPT}` (with `--json --require-tasks --include-tasks` flags) and parse FEATURE_DIR, AVAILABLE_DOCS.

Read:
- FEATURE_DIR/spec.md
- FEATURE_DIR/plan.md
- FEATURE_DIR/tasks.md (REQUIRED - abort if missing)
- /memory/constitution.md (if exists)

### 6.2 Build Semantic Models

Create internal mappings:
- Requirements inventory (FR-001 → slug)
- User story inventory
- Task coverage mapping (task → requirement/story)
- Constitution rule set

### 6.3 Detection Passes

**A. Duplication Detection**
- Near-duplicate requirements
- Redundant tasks

**B. Ambiguity Detection**
- Vague adjectives without metrics (fast, scalable, secure)
- Unresolved placeholders (TODO, ???)

**C. Underspecification**
- Requirements missing measurable outcomes
- Tasks referencing undefined components

**D. Constitution Alignment**
- MUST principle violations → CRITICAL
- Missing mandated sections

**E. Coverage Gaps**
- Requirements with zero tasks
- Tasks with no mapped requirement

**F. Inconsistency**
- Terminology drift
- Conflicting requirements
- Task ordering contradictions

### 6.4 Assign Severity

- **CRITICAL**: Constitution MUST violation, missing core artifact, zero-coverage blocking requirement
- **HIGH**: Duplicate/conflicting requirement, untestable criterion, ambiguous security/performance
- **MEDIUM**: Terminology drift, missing non-functional coverage, underspecified edge case
- **LOW**: Style/wording, minor redundancy

### 6.5 Produce Analysis Report

Output (do not write to file):

```markdown
## Specification Analysis Report

| ID | Category | Severity | Location | Summary | Recommendation |
|----|----------|----------|----------|---------|----------------|
| A1 | [cat] | [sev] | [loc] | [summary] | [recommendation] |

**Coverage Summary:**
| Requirement | Has Task? | Task IDs |
|-------------|-----------|----------|

**Metrics:**
- Total Requirements: X
- Total Tasks: Y
- Coverage: Z%
- Critical Issues: N
```

### 6.6 Determine Next Phase

- If CRITICAL/HIGH/MEDIUM issues exist: Proceed to Phase 7 (Remediation)
- If only LOW or no issues: Proceed to Phase 8 (Implementation)

---

## Phase 7: Remediation

Output:
```
## Phase 7: Remediation

Resolving analysis issues...
```

### 7.1 Process Issues by Severity

For each issue (CRITICAL → HIGH → MEDIUM → LOW):

**Constitution violation:**
- Edit the violating artifact to comply
- Or document justified exception in Complexity Tracking

**Missing artifact:**
- Return to appropriate phase to create it

**Ambiguous requirement:**
- If clarification needed from user, ask specific question
- Otherwise, add measurable criteria based on industry standards

**Coverage gap:**
- Add missing tasks to tasks.md
- Or add missing requirements to spec.md

**Terminology drift:**
- Standardize term usage across all artifacts

**Duplicate/conflicting requirements:**
- Consolidate or resolve conflict
- Update all affected artifacts

### 7.2 Re-run Analysis

After all remediations:
```
Re-running analysis...
```

Return to Phase 6 (§6.3 onwards).

### 7.3 Gate Check

Repeat remediation cycle until:
- CRITICAL = 0
- HIGH = 0
- MEDIUM = 0

Then proceed to Phase 8.

---

## Phase 8: Implementation

Output:
```
## Phase 8: Implementation

Beginning implementation...
```

### 8.1 Check Checklists

If FEATURE_DIR/checklists/ exists, scan all checklist files:

```
| Checklist | Total | Completed | Incomplete | Status |
|-----------|-------|-----------|------------|--------|
| [name].md | X | Y | Z | ✓/✗ |
```

- If all complete: Proceed to §8.2
- If incomplete: Ask user "Some checklists are incomplete. Proceed anyway? (yes/no)"
  - If no: Halt
  - If yes: Proceed to §8.2

### 8.2 Load Implementation Context

Run `{ANALYSIS_SCRIPT}` (with `--json --require-tasks --include-tasks` flags) to validate all prerequisites exist.

Read:
- tasks.md (required)
- plan.md (required)
- data-model.md (if exists)
- contracts/ (if exists)
- research.md (if exists)
- quickstart.md (if exists)

### 8.3 Project Setup

Create/verify ignore files based on tech stack from plan.md:

**Detection & Creation Logic**:
- Check if git repo exists → create/verify `.gitignore`
- Check if Dockerfile exists or Docker in plan.md → create/verify `.dockerignore`
- Check if `.eslintrc*` exists → create/verify `.eslintignore`
- Check if `.prettierrc*` exists → create/verify `.prettierignore`

**Common patterns by technology:**
- Node.js: `node_modules/`, `dist/`, `build/`, `*.log`, `.env*`
- Python: `__pycache__/`, `*.pyc`, `.venv/`, `dist/`, `*.egg-info/`
- Java: `target/`, `*.class`, `*.jar`, `.gradle/`, `build/`
- Go: `*.exe`, `*.test`, `vendor/`
- Rust: `target/`, `debug/`, `release/`
- C#/.NET: `bin/`, `obj/`, `*.user`, `*.suo`, `packages/`
- Ruby: `.bundle/`, `log/`, `tmp/`, `*.gem`, `vendor/bundle/`
- PHP: `vendor/`, `*.log`, `*.cache`, `*.env`
- Kotlin: `build/`, `out/`, `.gradle/`, `.idea/`, `*.class`, `*.jar`
- C/C++: `build/`, `bin/`, `obj/`, `out/`, `*.o`, `*.so`, `*.a`, `*.exe`
- Swift: `.build/`, `DerivedData/`, `*.swiftpm/`, `Packages/`

**Universal:** `.DS_Store`, `Thumbs.db`, `*.tmp`, `.vscode/`, `.idea/`

**If ignore file exists**: Verify essential patterns present, append only missing critical patterns.
**If ignore file missing**: Create with full pattern set for detected technology.

### 8.4 Execute Tasks

Process tasks.md phase by phase:

**For each phase:**
1. Output phase header
2. Execute tasks in order
3. Respect dependencies:
   - Sequential tasks: Complete in order
   - `[P]` tasks: Can run in parallel
4. Mark completed tasks as `[X]` in tasks.md
5. Report progress

**Execution rules:**
- Setup phase first
- Foundational phase must complete before user stories
- User story phases can proceed in priority order
- Polish phase last

### 8.5 Progress Tracking

After each task:
- Report completion
- If error: Provide context and suggest fix
- Update tasks.md checkbox

### 8.6 Completion

After all tasks complete:
```
## Implementation Complete

**Summary:**
- Tasks completed: X/Y
- User stories implemented: [list]
- Files created/modified: [count]

Proceeding to testing and validation...
```

Proceed to Phase 9.

---

## Phase 9: Testing & Validation

Output:
```
## Phase 9: Testing & Validation

Running full application tests and validations...
```

### 9.1 Prepare Test Environment

Ensure test infrastructure is ready:

1. **Verify test framework** is installed per plan.md specifications
2. **Create test directory structure** if not exists:
   ```
   tests/
   ├── unit/
   ├── integration/
   ├── contract/
   ├── e2e/
   ├── visual/
   │   └── snapshots/
   ├── accessibility/
   └── performance/
   ```
3. **Create reports directory**:
   ```
   tests/reports/
   ```
4. **Install UI testing dependencies** (if UI application detected):
   - Playwright or Cypress for E2E
   - axe-core for accessibility
   - Lighthouse for performance

### 9.2 Execute Test Suites

Run all test categories in order:

**9.2.1 Unit Tests**
```bash
# Run unit tests with coverage (adjust command per tech stack)
# Python: pytest tests/unit/ --cov --cov-report=json
# Node.js: npm test -- --coverage --json
# Go: go test ./... -coverprofile=coverage.out -json
```

Capture:
- Total tests run
- Tests passed
- Tests failed
- Tests skipped
- Code coverage percentage

**9.2.2 Integration Tests**
```bash
# Run integration tests
# Python: pytest tests/integration/ -v
# Node.js: npm run test:integration
```

Capture:
- Service integration status
- API endpoint validations
- Database operations

**9.2.3 Contract Tests** (if contracts/ exists)
```bash
# Validate API contracts
# Check OpenAPI/GraphQL schemas against implementation
```

Capture:
- Contract compliance status
- Schema validation results

**9.2.4 Linting & Static Analysis**
```bash
# Run linters per tech stack
# Python: ruff check . && mypy .
# Node.js: eslint . && tsc --noEmit
# Go: golangci-lint run
```

Capture:
- Linting errors
- Type errors
- Code quality issues

**9.2.5 Security Scan** (if applicable)
```bash
# Run security checks
# Python: bandit -r src/
# Node.js: npm audit
# General: trivy fs .
```

Capture:
- Vulnerabilities found
- Severity levels

**9.2.6 End-to-End (E2E) Tests** (if UI/web application)

Detect if application has UI components (check for: React, Vue, Angular, Svelte, HTML templates, etc.)

```bash
# Run E2E tests with Playwright or Cypress
# Playwright: npx playwright test
# Cypress: npx cypress run
```

**Test all interactive elements:**
- Buttons: Click handlers, disabled states, loading states
- Links: Navigation, external links open correctly, anchor links
- Forms: Input validation, submission, error states, success feedback
- Modals/Dialogs: Open/close, focus trapping, escape key handling
- Dropdowns/Selects: Option selection, keyboard navigation
- Checkboxes/Radios: Toggle states, group behavior
- Tabs: Switching, keyboard navigation, active states
- Accordions: Expand/collapse, animation completion
- Tooltips: Hover triggers, positioning, content
- Navigation: Menu items, active states, responsive behavior

Capture:
- Elements tested
- Interaction success/failure
- Navigation flow completion

**9.2.7 Visual Regression Testing** (if UI application)

```bash
# Capture and compare screenshots
# Playwright: npx playwright test --update-snapshots (first run)
# Playwright: npx playwright test (subsequent runs compare)
# Percy: npx percy exec -- [test command]
# Chromatic: npx chromatic --project-token=xxx
```

**Visual checks:**
- Layout alignment and spacing
- Typography (font sizes, weights, line heights)
- Color consistency (brand colors, contrast ratios)
- Responsive breakpoints (mobile, tablet, desktop)
- Component visual states (hover, focus, active, disabled)
- Icon alignment and sizing
- Image aspect ratios and positioning
- Border radii and shadows
- Animation/transition smoothness

Capture:
- Screenshots per viewport size
- Visual diff percentage
- Changed regions highlighted

**9.2.8 Accessibility (a11y) Testing** (if UI application)

```bash
# Run accessibility audits
# axe-core: npx axe [url] or integrated in Playwright/Cypress
# pa11y: npx pa11y [url]
# Lighthouse: npx lighthouse [url] --only-categories=accessibility
```

**Accessibility checks:**
- WCAG 2.1 AA compliance
- Keyboard navigation (all interactive elements reachable)
- Focus indicators visible
- Screen reader compatibility (ARIA labels, roles, live regions)
- Color contrast ratios (4.5:1 for normal text, 3:1 for large text)
- Alt text for images
- Form labels and error announcements
- Heading hierarchy (h1 → h2 → h3, no skips)
- Skip links present
- Touch target sizes (minimum 44x44px)

Capture:
- WCAG violations by level (A, AA, AAA)
- Elements with issues
- Remediation suggestions

**9.2.9 Cross-Browser Testing** (if UI application)

```bash
# Run tests across browsers
# Playwright: npx playwright test --project=chromium --project=firefox --project=webkit
# BrowserStack/Sauce Labs for extended browser matrix
```

**Browser matrix:**
| Browser | Versions | Status |
|---------|----------|--------|
| Chrome | Latest, Latest-1 | ✅/❌ |
| Firefox | Latest, Latest-1 | ✅/❌ |
| Safari | Latest, Latest-1 | ✅/❌ |
| Edge | Latest | ✅/❌ |
| Mobile Safari | iOS Latest | ✅/❌ |
| Chrome Mobile | Android Latest | ✅/❌ |

Capture:
- Pass/fail per browser
- Browser-specific issues
- Rendering differences

**9.2.10 Performance Testing** (if UI/API application)

```bash
# Lighthouse performance audit
# npx lighthouse [url] --only-categories=performance --output=json

# API load testing
# k6: k6 run loadtest.js
# Artillery: npx artillery run loadtest.yml
```

**UI Performance metrics:**
- First Contentful Paint (FCP) < 1.8s
- Largest Contentful Paint (LCP) < 2.5s
- First Input Delay (FID) < 100ms
- Cumulative Layout Shift (CLS) < 0.1
- Time to Interactive (TTI) < 3.8s
- Total Blocking Time (TBT) < 200ms

**API Performance metrics:**
- Response time p50, p95, p99
- Requests per second
- Error rate under load
- Memory/CPU utilization

Capture:
- Core Web Vitals scores
- Performance bottlenecks
- Optimization recommendations

### 9.3 Generate Test Report

Create `tests/reports/[FEATURE_NUMBER]-[SHORT_NAME]-[TIMESTAMP].md`:

```markdown
# Test Report: [FEATURE NAME]

**Feature**: [NUMBER]-[SHORT_NAME]
**Branch**: [BRANCH_NAME]
**Generated**: [TIMESTAMP]
**Status**: ✅ PASSED / ❌ FAILED

---

## Summary

| Category | Total | Passed | Failed | Skipped | Status |
|----------|-------|--------|--------|---------|--------|
| Unit Tests | X | X | X | X | ✅/❌ |
| Integration Tests | X | X | X | X | ✅/❌ |
| Contract Tests | X | X | X | X | ✅/❌ |
| E2E Tests | X | X | X | X | ✅/❌ |
| Visual Regression | X | X | X | X | ✅/❌ |
| Accessibility | X | X | X | X | ✅/❌ |
| Cross-Browser | X | X | X | X | ✅/❌ |
| Performance | X | X | X | X | ✅/❌ |
| Linting | X | X | X | - | ✅/❌ |
| Security | X | X | X | - | ✅/❌ |

**Overall Coverage**: X%
**Total Issues**: X

---

## Detailed Results

### Unit Tests

| Test | File | Status | Duration | Notes |
|------|------|--------|----------|-------|
| [test_name] | [file] | ✅/❌ | [Xms] | [any notes] |
...

### Integration Tests

| Test | Components | Status | Duration | Notes |
|------|------------|--------|----------|-------|
| [test_name] | [components] | ✅/❌ | [Xms] | [any notes] |
...

### Contract Validation

| Contract | Endpoint/Schema | Status | Issues |
|----------|-----------------|--------|--------|
| [contract] | [endpoint] | ✅/❌ | [issues] |
...

### E2E Test Results

| Test Scenario | Elements Tested | Status | Duration | Notes |
|---------------|-----------------|--------|----------|-------|
| [scenario] | [buttons, links, forms...] | ✅/❌ | [Xms] | [any notes] |
...

#### Element Interaction Summary

| Element Type | Total | Passed | Failed | Issues |
|--------------|-------|--------|--------|--------|
| Buttons | X | X | X | [list] |
| Links | X | X | X | [list] |
| Forms | X | X | X | [list] |
| Navigation | X | X | X | [list] |
| Modals | X | X | X | [list] |
| Dropdowns | X | X | X | [list] |

### Visual Regression Results

| Page/Component | Viewport | Diff % | Status | Screenshot |
|----------------|----------|--------|--------|------------|
| [page] | Desktop (1920x1080) | X% | ✅/❌ | [link] |
| [page] | Tablet (768x1024) | X% | ✅/❌ | [link] |
| [page] | Mobile (375x667) | X% | ✅/❌ | [link] |
...

#### Visual Issues Detected

| Issue | Location | Expected | Actual | Severity |
|-------|----------|----------|--------|----------|
| [issue] | [element/page] | [expected] | [actual] | HIGH/MED/LOW |
...

### Accessibility Results

**WCAG 2.1 Compliance**: Level [A/AA/AAA] - [X]% compliant

| Rule | Impact | Elements Affected | Description | Fix |
|------|--------|-------------------|-------------|-----|
| [rule-id] | [critical/serious/moderate/minor] | [count] | [description] | [fix] |
...

#### Accessibility Summary by Category

| Category | Pass | Fail | Status |
|----------|------|------|--------|
| Keyboard Navigation | X | X | ✅/❌ |
| Screen Reader | X | X | ✅/❌ |
| Color Contrast | X | X | ✅/❌ |
| Focus Management | X | X | ✅/❌ |
| ARIA Usage | X | X | ✅/❌ |
| Form Labels | X | X | ✅/❌ |

### Cross-Browser Results

| Browser | Version | Platform | Status | Issues |
|---------|---------|----------|--------|--------|
| Chrome | [ver] | Desktop | ✅/❌ | [issues] |
| Firefox | [ver] | Desktop | ✅/❌ | [issues] |
| Safari | [ver] | Desktop | ✅/❌ | [issues] |
| Edge | [ver] | Desktop | ✅/❌ | [issues] |
| Safari | [ver] | iOS | ✅/❌ | [issues] |
| Chrome | [ver] | Android | ✅/❌ | [issues] |

### Performance Results

#### Core Web Vitals (UI)

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| First Contentful Paint | < 1.8s | [X]s | ✅/❌ |
| Largest Contentful Paint | < 2.5s | [X]s | ✅/❌ |
| First Input Delay | < 100ms | [X]ms | ✅/❌ |
| Cumulative Layout Shift | < 0.1 | [X] | ✅/❌ |
| Time to Interactive | < 3.8s | [X]s | ✅/❌ |
| Total Blocking Time | < 200ms | [X]ms | ✅/❌ |

**Lighthouse Score**: [X]/100

#### API Performance

| Endpoint | p50 | p95 | p99 | RPS | Error Rate |
|----------|-----|-----|-----|-----|------------|
| [endpoint] | [X]ms | [X]ms | [X]ms | [X] | [X]% |
...

### Linting Results

| Category | File | Line | Issue | Severity |
|----------|------|------|-------|----------|
| [type] | [file] | [line] | [message] | [sev] |
...

### Security Scan

| Vulnerability | Package/File | Severity | CVE | Recommendation |
|---------------|--------------|----------|-----|----------------|
| [vuln] | [location] | [sev] | [cve] | [fix] |
...

---

## Coverage Report

| Module/File | Lines | Covered | Percentage |
|-------------|-------|---------|------------|
| [module] | X | X | X% |
...

**Total Coverage**: X%

---

## Failure Details

### [FAIL-001] [Test Name]
**File**: [test_file]
**Line**: [line_number]
**Category**: [unit/integration/e2e/visual/a11y/performance]
**Error**:
```
[error message/stack trace]
```
**Expected**: [expected behavior]
**Actual**: [actual behavior]
**Suggested Fix**: [recommendation]

...

---

## Recommendations

### Critical (Must Fix)
1. [Priority 1 recommendation]

### High Priority
1. [Priority 2 recommendation]

### Medium Priority
1. [Priority 3 recommendation]

### Low Priority / Enhancements
1. [Priority 4 recommendation]

---

## Test Execution Log

```
[Full test execution output - truncated if >500 lines]
```
```

### 9.4 Evaluate Results

Analyze test results:

| Condition | Result |
|-----------|--------|
| All tests pass AND coverage ≥ threshold | PASS → Proceed to §9.6 |
| Any unit/integration test fails | FAIL → Proceed to §9.5 |
| Any E2E test fails (broken user flow) | FAIL → Proceed to §9.5 |
| Visual regression > 5% diff | FAIL → Proceed to §9.5 |
| Critical accessibility violation (WCAG A) | FAIL → Proceed to §9.5 |
| Cross-browser failure on major browser | FAIL → Proceed to §9.5 |
| Core Web Vitals below threshold | FAIL → Proceed to §9.5 |
| Coverage below threshold | FAIL → Proceed to §9.5 |
| Critical security vulnerability | FAIL → Proceed to §9.5 |
| Linting errors (blocking) | FAIL → Proceed to §9.5 |

**Thresholds** (use constitution.md values if defined, otherwise defaults):
- Code coverage: 80%
- Visual regression diff: 5%
- Accessibility: WCAG 2.1 AA compliance
- Lighthouse performance score: 70/100

### 9.5 Test Failure Remediation

If any tests fail:

Output:
```
❌ **Test failures detected. Initiating remediation...**

| ID | Category | Test/Check | Issue | Severity |
|----|----------|------------|-------|----------|
| TF-001 | [category] | [test] | [issue] | CRITICAL/HIGH/MEDIUM |
...
```

**9.5.1 Update Spec with Issues**

Add a `## Test Failures` section to FEATURE_DIR/spec.md:

```markdown
## Test Failures (Remediation Required)

**Test Run**: [TIMESTAMP]
**Report**: tests/reports/[report_file].md

### Issues Requiring Resolution

| ID | Category | Description | Impact | Status |
|----|----------|-------------|--------|--------|
| TF-001 | [cat] | [description] | [impact] | 🔴 Open |
...

### Remediation Plan

1. TF-001: [specific fix plan]
2. TF-002: [specific fix plan]
...
```

**9.5.2 Classify and Prioritize**

- **CRITICAL**: Security vulnerabilities, data corruption risks, complete feature failure, WCAG A violations (legal compliance), broken primary user flows
- **HIGH**: Core functionality broken, integration failures, E2E test failures on happy path, visual regressions on key pages, keyboard navigation broken, Core Web Vitals failing
- **MEDIUM**: Edge case failures, coverage gaps, visual regressions on secondary pages, WCAG AA violations, cross-browser issues on non-primary browsers, performance below target but usable
- **LOW**: Style issues, minor warnings, WCAG AAA recommendations, minor visual inconsistencies, performance optimizations

**9.5.3 Execute Remediation**

For each failure (CRITICAL → HIGH → MEDIUM):

1. **Identify root cause** from test output and stack trace
2. **Locate affected code** in implementation
3. **Apply fix** following existing patterns in codebase
4. **Update affected tests** if test itself was incorrect
5. **Update visual snapshots** if visual change was intentional
6. **Mark issue as resolved** in spec.md

**UI-Specific Remediation:**
- **Button/Link failures**: Check event handlers, disabled states, href attributes
- **Form failures**: Validate input handling, error states, submission logic
- **Visual regression**: Compare snapshots, identify CSS changes, check responsive breakpoints
- **Accessibility**: Add ARIA labels, fix heading hierarchy, improve color contrast
- **Performance**: Optimize images, lazy load components, reduce bundle size

**9.5.4 Re-run Tests**

After all remediations:
```
Remediation complete. Re-running full test suite...
```

Return to §9.2 and execute full test suite again.

**9.5.5 Remediation Loop Limit**

Track remediation attempts:
- Maximum 3 full remediation cycles
- If still failing after 3 cycles:
  ```
  ⚠️ **Maximum remediation attempts reached.**
  
  Remaining failures:
  | ID | Test | Issue |
  |----|------|-------|
  ...
  
  Manual intervention required. See test report for details.
  ```
  Halt and await user input.

### 9.6 Update Constitution

After successful test pass, update `/memory/constitution.md` with new capabilities:

**9.6.1 Detect New Capabilities**

Scan implemented feature for:
- New modules/services added
- New API endpoints
- New data models
- New integrations
- New patterns established

**9.6.2 Update Constitution Sections**

Add or update sections as needed:

```markdown
## Project Capabilities

### Services
- [ServiceName]: [Description] (Added: [DATE], Feature: [NUMBER])
...

### API Endpoints
- [METHOD] [path]: [Description] (Added: [DATE])
...

### Data Models
- [ModelName]: [Description] (Added: [DATE])
...

### Integrations
- [IntegrationName]: [Description] (Added: [DATE])
...

## Code Patterns

### Established Patterns
- [PatternName]: [Description, where used, when to apply]
...

### Testing Standards
- Unit test coverage minimum: [X]%
- Integration test requirements: [description]
- Contract test requirements: [description]
```

**9.6.3 Update Version**

Increment constitution version:
- New capability added → Minor version bump (1.0.0 → 1.1.0)
- Principle changed → Major version bump (1.0.0 → 2.0.0)
- Documentation only → Patch version bump (1.0.0 → 1.0.1)

Update `Last Amended` date.

**9.6.4 Update Project Version (if applicable)**

If the project uses semantic versioning with VERSION and CHANGELOG files:

1. **Decide bump level using this algorithm:**
   - If the change introduces breaking API/DB schema or requires migration → **major**
   - Else if it adds new, backward-compatible features (new routes, pages, games) → **minor**
   - Else → **patch**

2. **Update files and create a release tag** (example for minor bump):

```bash
# Determine current version (reads from VERSION)
CURRENT=$(cat VERSION | tr -d " \n")
# Suggested new version (example script - adjust as needed)
# For minor bump (X.Y.Z -> X.(Y+1).0)
IFS='.' read -r MAJ MIN PATCH <<< "$CURRENT"
NEW="$MAJ.$((MIN+1)).0"

echo "$NEW" > VERSION

# Move Unreleased changes into CHANGELOG.md under new heading (manual edit recommended)
# Commit version and changelog updates
git add VERSION CHANGELOG.md
git commit -m "chore(release): bump version to $NEW"

# Tag the release and push tag
git tag -a "v$NEW" -m "Release v$NEW"
git push origin "v$NEW"
```

3. **Update CHANGELOG.md** following Keep a Changelog format:
   - Move `[Unreleased]` content into `## [X.Y.Z] - YYYY-MM-DD` section
   - Update the comparison links at the bottom to reference the new tag ranges

4. **Container tags** (if using Podman/Docker):
   - Test builds: `<version>-canary`
   - Production builds: `<version>`

5. **Automation note:** Consider scripting the version bump and changelog release-step, but keep changelog edits manual for accuracy.

### 9.7 Final Completion

After all tests pass and constitution is updated:

```
## Spec Complete ✅

**Feature**: [NUMBER]-[SHORT_NAME]
**Branch**: [BRANCH_NAME]

### Implementation Summary
- Tasks completed: X/Y
- User stories implemented: [list]
- Files created/modified: [count]

### Test Summary
- Unit Tests: X passed
- Integration Tests: X passed
- Contract Tests: X passed
- Code Coverage: X%
- Security Issues: 0

### Reports Generated
- Test Report: tests/reports/[report_file].md

### Constitution Updates
- Version: [OLD] → [NEW]
- New capabilities documented: [count]

### Next Steps

**If `REMOTE_AVAILABLE=true`:**
1. Review test report: tests/reports/[report_file].md
2. Create pull request for branch: [BRANCH_NAME]
3. Request code review
4. Merge to main after approval

**If `REMOTE_AVAILABLE=false`:**
1. Review test report: tests/reports/[report_file].md
2. ⚠️ No remote repository - changes are local only
3. To push changes later:
   - Create repository: `gh repo create [REPO_NAME] --private --source=. --remote=origin`
   - Push branch: `git push -u origin [BRANCH_NAME]`
   - Create PR: `gh pr create`
```

---

# Appendix A: Constitution Creation

When `/memory/constitution.md` is missing and this is a new project:

### A.1 Gather Principles

Ask user:
```
No project constitution exists. I need to establish project principles.

What are the core principles for this project? (Examples: simplicity, security-first, test coverage requirements, tech stack constraints)

Provide 3-5 guiding principles, or say "default" for standard principles.
```

### A.2 Create Constitution

If user says "default", use:
- Simplicity over complexity
- Test before merge
- Security by default
- Documentation required

Otherwise, use user-provided principles.

### A.3 Write Constitution

Create `/memory/constitution.md`:

```markdown
# Project Constitution

**Version**: 1.0.0
**Ratified**: [TODAY]
**Last Amended**: [TODAY]

## Principles

### Principle 1: [Name]
[Description of what this means and why it matters]
**Compliance**: [How to verify compliance]

### Principle 2: [Name]
...

## Governance

### Amendment Process
Changes to this constitution require explicit discussion and version increment.

### Compliance Review
All specs, plans, and implementations must pass constitution check gates.
```

### A.4 Proceed

After constitution created, return to Phase 1.3.

---

# Appendix B: Human Intervention Points

Human input is required ONLY in these situations:

1. **GitHub Repository Check** (§1.0): When repository does not exist and user must decide whether to create it or continue without remote
2. **Pending Work Resolution** (§1.1): When uncommitted changes, unpushed commits, stashes, open branches, or PRs exist
3. **Constitution Creation** (§Appendix A): When establishing project principles for a new project
4. **Clarification Questions** (§3.4): When spec has ambiguities requiring user decisions
5. **Empty Input** (§1.5): When no feature idea provided and no context to continue
6. **Checklist Override** (§8.1): When user must decide whether to proceed with incomplete checklists
7. **Ambiguity Resolution** (§7.1): When remediation requires clarification that cannot be inferred
8. **Test Failure Remediation Limit** (§9.5.5): When maximum remediation attempts (3) reached without resolving all test failures

All other transitions execute autonomously.

**Note**: When `REMOTE_AVAILABLE=false`, the workflow continues but skips all remote operations (push, PR creation, remote branch deletion). This is tracked as a workflow state, not a human intervention point after the initial decision.

---

# Appendix D: Script Reference

This command uses the following scripts from the frontmatter:

| Script Key | Script | Flags | Used In |
|------------|--------|-------|--------|
| `{SCRIPT}` | `create-new-feature.sh` | `--json --number N --short-name "name"` | Phase 2.2 |
| `{PLAN_SCRIPT}` | `setup-plan.sh` | `--json` | Phase 4.1 |
| `{PREREQ_SCRIPT}` | `check-prerequisites.sh` | `--json` | Phase 5.1 |
| `{ANALYSIS_SCRIPT}` | `check-prerequisites.sh` | `--json --require-tasks --include-tasks` | Phase 6.1, 8.2 |
| `{AGENT_SCRIPT}` | `update-agent-context.sh` | `<agent_type>` | Phase 4.7 |

**Important**: The `check-prerequisites.sh` script is called with different flags depending on the phase:
- **Phase 5** (Task Generation): Use `--json` only (tasks don't exist yet)
- **Phase 6/8** (Analysis/Implementation): Use `--json --require-tasks --include-tasks`

---

# Appendix C: Output Format Examples

**Repository check - not found:**
```
## Phase 1: Context Loading

⚠️ **GitHub repository not found.**

| Detail | Value |
|--------|-------|
| Expected Repository | johndoe/my-project |
| Local Workspace | /home/johndoe/projects/my-project |
| Git Initialized | Yes |

The repository "my-project" does not exist on GitHub for user "johndoe".

Would you like me to create the repository on GitHub?

| Option | Action |
|--------|--------|
| Y | **Create Repository** - Create "johndoe/my-project" on GitHub (private by default) |
| P | **Create Public Repository** - Create as a public repository |
| N | **Continue Without Remote** - Proceed with local-only workflow (no push/PR operations) |

Reply with Y, P, or N.
```

**Repository created:**
```
✓ Repository created: https://github.com/johndoe/my-project
✓ Remote 'origin' configured.
```

**Continuing without remote:**
```
⚠️ Continuing without remote repository.

The following operations will be skipped during this workflow:
- git push (all push operations)
- Pull request creation
- Remote branch operations

All other local operations (commits, branches, specs, implementation) will proceed normally.
```

**Phase transition:**
```
## Phase 4: Planning

Generating implementation plan and design artifacts...
```

**Clarification question:**
```
The spec mentions "fast response times" without defining a threshold.

**Recommended:** Option B - Sub-500ms provides good UX without requiring aggressive optimization

| Option | Description |
|--------|-------------|
| A | Sub-100ms (aggressive) |
| B | Sub-500ms (balanced) |
| C | Sub-1s (relaxed) |

Reply with option letter, "yes" for recommended, or your own answer.
```

**After clarification answer:**
```
Updated spec with latency requirement: 500ms. Proceeding...
```

**Analysis finding:**
```
| ID | Category | Severity | Location | Summary | Recommendation |
|----|----------|----------|----------|---------|----------------|
| C1 | Coverage | HIGH | FR-003 | No task covers password reset | Add task in US2 phase |
```

**Task execution:**
```
### Phase 3: User Story 1 - User Authentication

- [X] T012 [US1] Create User model in src/models/user.py
- [X] T013 [US1] Implement AuthService in src/services/auth.py
- [ ] T014 [US1] Create login endpoint in src/api/auth.py
```

**Test results - all passing:**
```
## Phase 9: Testing & Validation

Running full application tests and validations...

✅ Unit Tests: 42/42 passed (98% coverage)
✅ Integration Tests: 12/12 passed
✅ Contract Tests: 8/8 passed
✅ E2E Tests: 18/18 passed
   - Buttons: 24/24 functional
   - Links: 15/15 navigating correctly
   - Forms: 8/8 submitting properly
✅ Visual Regression: 0 diffs detected
✅ Accessibility: WCAG 2.1 AA compliant (0 violations)
✅ Cross-Browser: All 6 browsers passing
✅ Performance: Lighthouse 92/100
   - LCP: 1.2s ✓
   - FID: 45ms ✓
   - CLS: 0.02 ✓
✅ Linting: 0 errors
✅ Security Scan: 0 vulnerabilities

Test report generated: tests/reports/001-user-auth-2025-11-27T14-30-00.md
```

**Test results - failures detected:**
```
❌ **Test failures detected. Initiating remediation...**

| ID | Category | Test/Check | Issue | Severity |
|----|----------|------------|-------|----------|
| TF-001 | Unit | test_user_login | AssertionError: expected 200, got 401 | HIGH |
| TF-002 | Integration | test_db_connection | ConnectionTimeout after 30s | CRITICAL |
| TF-003 | E2E | login_button_click | Button not responding to click | HIGH |
| TF-004 | Visual | login_page_desktop | 8% diff detected in header area | MEDIUM |
| TF-005 | Accessibility | form_labels | Missing label for email input | HIGH |
| TF-006 | Performance | LCP | 3.2s (target: <2.5s) | MEDIUM |
| TF-007 | Linting | src/auth.py:45 | Undefined variable 'user_id' | MEDIUM |

Updating spec with test failures...
Beginning remediation cycle 1/3...
```

**Test remediation success:**
```
Remediation complete. Re-running full test suite...

✅ All tests passing after remediation cycle 1.
Test report generated: tests/reports/001-user-auth-2025-11-27T14-35-00.md
```

**Spec completion (with remote):**
```
## Spec Complete ✅

**Feature**: 001-user-auth
**Branch**: 001-user-auth

### Implementation Summary
- Tasks completed: 24/24
- User stories implemented: US1, US2, US3
- Files created/modified: 18

### Test Summary
- Unit Tests: 42 passed
- Integration Tests: 12 passed
- E2E Tests: 18 passed (47 elements verified)
- Visual Regression: 0 diffs
- Accessibility: WCAG 2.1 AA compliant
- Cross-Browser: 6/6 browsers passing
- Performance: Lighthouse 92/100
- Code Coverage: 94%
- Security Issues: 0

### Reports Generated
- Test Report: tests/reports/001-user-auth-2025-11-27T14-35-00.md

### Constitution Updates
- Version: 1.0.0 → 1.1.0
- New capabilities documented: 3 (AuthService, UserModel, /api/auth endpoints)

### Next Steps
1. Review test report: tests/reports/001-user-auth-2025-11-27T14-35-00.md
2. Create pull request for branch: 001-user-auth
3. Request code review
4. Merge to main after approval
```

**Spec completion (without remote):**
```
## Spec Complete ✅

**Feature**: 001-user-auth
**Branch**: 001-user-auth

### Implementation Summary
- Tasks completed: 24/24
- User stories implemented: US1, US2, US3
- Files created/modified: 18

### Test Summary
- Unit Tests: 42 passed
- Integration Tests: 12 passed
- Code Coverage: 94%
- Security Issues: 0

### Reports Generated
- Test Report: tests/reports/001-user-auth-2025-11-27T14-35-00.md

### Constitution Updates
- Version: 1.0.0 → 1.1.0
- New capabilities documented: 3 (AuthService, UserModel, /api/auth endpoints)

### Next Steps
1. Review test report: tests/reports/001-user-auth-2025-11-27T14-35-00.md
2. ⚠️ No remote repository - changes are local only
3. To push changes later:
   - Create repository: `gh repo create my-project --private --source=. --remote=origin`
   - Push branch: `git push -u origin 001-user-auth`
   - Create PR: `gh pr create`
```
