---
description: Commit current changes with a comprehensive commit message, push to remote, and optionally create a PR with an exhaustive review, then optionally merge to the default branch.
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

The text the user typed after the command **is** their priority input - it may specify:
- A specific commit message or summary to use
- Additional context for the commit message
- Whether to skip PR creation or merge steps
- Any special instructions or constraints

---

# Commit, Push & PR Workflow

This command **automatically** commits and pushes changes. User input is only requested for PR creation and merge decisions.

## Execution Principles

- **Commit & Push:** Automatic - no user prompts
- **PR Creation:** Requires user confirmation
- **Merge:** Requires user confirmation

Output format for phase transitions:

```
## Phase N: [Phase Name]
[Execute phase work directly]
```

---

## Phase 1: Analyze & Commit

### 1.1 Verify Working Directory State

Check for changes:

```bash
git status --porcelain
git branch --show-current
```

**If no changes detected:**
```
✓ Working directory is clean. No changes to commit.
```
Skip to Phase 2 to check for unpushed commits.

**If changes detected:** Proceed to §1.2

### 1.2 Gather Change Details

Execute comprehensive analysis (do not output to user, use internally):

```bash
git status --short
git diff --stat
git diff --cached --stat
git diff
git diff --cached
git log --oneline -5
```

### 1.3 Generate Commit Message

Based on the change analysis, generate a comprehensive, easy-to-read commit message following conventional commit format. **Do not ask for approval - generate and use directly.**

**Commit Message Structure:**
```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Formatting, missing semicolons, etc.
- `refactor`: Code refactoring
- `test`: Adding/updating tests
- `chore`: Maintenance tasks

**Subject Line Rules:**
- Keep under 72 characters
- Use imperative mood ("add" not "added")
- Be specific about what changed

**Body Requirements (MUST cover all changes):**
- Start with a 1-2 sentence overview of the change
- List ALL significant changes with bullet points
- Group related changes under sub-headings if many files changed
- Include file paths for clarity when helpful
- Mention any breaking changes or migration notes
- Keep each bullet concise but descriptive

**Readability Guidelines:**
- Use clear, plain language
- Avoid jargon unless necessary
- One idea per bullet point
- Blank line between sections

### 1.4 Execute Commit (Automatic)

```bash
git add -A
git commit -m "[generated message]"
```

### 1.5 Output Commit Summary

```
## Phase 1: Commit Complete

✓ Changes committed.

**Commit:** [hash]
**Message:** [subject line]
**Files:** [count] changed, [insertions] insertions, [deletions] deletions

### Changes Committed:
- `path/to/file.ts` - [brief description]
- `path/to/file.ts` - [brief description]
...
```

---

## Phase 2: Push Changes (Automatic)

### 2.1 Execute Push

```bash
git push -u origin HEAD
```

### 2.2 Output Push Summary

```
## Phase 2: Push Complete

✓ Changes pushed to remote.

**Branch:** [branch_name]
**Remote:** origin/[branch_name]
```

---

## Versioning (post-merge or release)

When preparing a release, follow semantic versioning rules and update project files before creating a release tag.

- Bump rules:
  - Major: incompatible API changes or large governance/principle changes
  - Minor: new features added in a backward-compatible manner
  - Patch: bug fixes and minor tweaks

- Recommended commands after successful merge to default branch:

```bash
# Update VERSION file (example: bump minor)
echo "{{VERSION}}" > VERSION

# Commit version and changelog updates
git add VERSION CHANGELOG.md
git commit -m "chore(release): bump version to {{VERSION}}"

# Create an annotated tag
git tag -a v{{VERSION}} -m "Release v{{VERSION}}"

# Push tag
git push origin v{{VERSION}}
```

- Changelog guidance:
  - Move `[Unreleased]` entries into a new version section with the release date
  - Update comparison links at the bottom to reference the new tag ranges

---

## Phase 3: Merge Decision

### 3.1 Prompt User (REQUIRED)

```
## Phase 3: Merge to Default Branch

✓ Changes committed and pushed to `[branch_name]`.

**Would you like to merge this branch to `[default_branch]`?** (Y/N)
```

**If N:** 
```
✓ Done. Your changes are on branch `[branch_name]`.
```
Stop execution.

**If Y:** Proceed to §3.2

### 3.2 Switch to Default Branch

```bash
git checkout [default_branch]
git pull origin [default_branch]
```

---

## Phase 4: Auto Resolve Conflicts

### 4.1 Check for Conflicts

```bash
# Fetch latest changes
git fetch origin [default_branch]

# Check if merge would create conflicts
git merge-tree $(git merge-base HEAD origin/[default_branch]) HEAD origin/[default_branch]
```

### 4.2 Auto-Resolve Simple Conflicts

Attempt merge and handle conflicts:

```bash
# Attempt merge
git merge origin/[branch_name] --no-commit --no-ff
```

**If merge successful (no conflicts):**
Proceed to Phase 5.

**If conflicts exist:**
```bash
# Check conflict types
git status --porcelain | grep "^UU\|^AA\|^DD"
```

For simple conflicts (whitespace, imports, etc.), attempt auto-resolution:
```bash
# Auto-resolve simple conflicts
git checkout --ours .
git add .
```

**If complex conflicts remain:**
```
⚠️ Manual conflict resolution required.

Conflicts found in:
[list of conflicted files from git status]

Please resolve conflicts manually and run the workflow again.
```
Reset and stop execution:
```bash
git merge --abort
```

### 4.3 Output Conflict Resolution Summary

```
## Phase 4: Conflict Resolution Complete

✓ Ready to merge - no conflicts detected.

**Branch Status:** `[branch_name]` ready for merge
**Conflicts:** None ✓
```

---

## Phase 5: Execute Merge

### 5.1 Perform Merge

```bash
# Ensure we're on default branch
git checkout [default_branch]

# Merge feature branch with no-fast-forward to preserve history
git merge --no-ff [branch_name] -m "Merge branch '[branch_name]' into [default_branch]"
```

### 5.2 Push Merged Changes

```bash
git push origin [default_branch]
```

### 5.3 Output Merge Summary

```
## Phase 5: Merge Complete

✓ Branch `[branch_name]` merged into `[default_branch]`.

**Merge Status:** Complete ✓
**Changes Pushed:** Yes ✓
```

---

## Phase 6: Complete Branch Cleanup

Ensure ONLY the default branch exists locally and remotely:

### 6.1 Delete Remote Feature Branch

```bash
git push origin --delete [branch_name]
```

### 6.2 Delete Local Feature Branch

```bash
git branch -D [branch_name]
```

### 6.3 Clean Up All Stale Branches

```bash
# Prune all remote tracking references
git fetch --prune

# Get the default branch name
DEFAULT_BRANCH=$(git remote show origin | grep 'HEAD branch' | cut -d' ' -f5)

# Delete ALL local branches except default
git branch | grep -v "^\*\|^  $DEFAULT_BRANCH$" | xargs -r git branch -D

# Verify only default branch remains
git branch -a
```

### 6.4 Output Cleanup Summary

```
## Phase 6: Branch Cleanup Complete

✓ All feature branches deleted.

**Remote Cleanup:** `[branch_name]` deleted ✓
**Local Cleanup:** Only `[default_branch]` remains ✓
**Stale Branches:** Pruned ✓
```

---

## Final Summary

---

## Error Handling

### Git/Push Errors

If git commands fail, output the error and stop:
```
❌ Error: [error message]

**Suggested fix:** [context-specific suggestion]
```

### Merge Conflict Errors

If merge conflicts cannot be auto-resolved:
```
❌ Merge conflicts require manual resolution.

**Conflicted files:** [list of files]
**Next steps:** Resolve conflicts manually and re-run workflow
```

---

## Appendix: Commit Message Examples

**Feature (single scope):**
```
feat(auth): add OAuth2 login with Google provider

Add complete Google OAuth2 authentication flow for user login.

Changes:
- Add GoogleAuthProvider class in services/auth.ts
- Implement login/logout flow in components/Auth.tsx
- Store tokens securely in session storage
- Add token refresh handling on expiry
- Update user state management for OAuth flow
```

**Bug Fix:**
```
fix(chat): resolve message duplication on reconnect

Fix issue where messages appeared multiple times after WebSocket reconnection.

Changes:
- Add message deduplication by unique ID in chat store
- Clear pending message queue on successful send confirmation
- Add connection state tracking to prevent duplicate subscriptions
```

**Multiple Changes (comprehensive):**
```
feat(admin): add system prompt configuration

Add ability for administrators to configure custom system prompts
for the AI assistant, with full CRUD operations and validation.

Features:
- Add SystemPromptEditor component with syntax highlighting
- Create prompt storage service with SQLite persistence
- Add prompt validation (length limits, forbidden patterns)

UI Changes:
- Update AdminDashboard.tsx with new "System Prompt" section
- Add prompt preview panel with live formatting
- Include character count and validation feedback

Configuration:
- Add MAX_PROMPT_LENGTH to environment config
- Update database schema with system_prompts table
```

**Documentation:**
```
docs(commands): add comprehensive testing to agentic-sdd workflow

Enhance Phase 9 testing with exhaustive UI and application validation.

New Test Categories:
- E2E tests for all interactive elements (buttons, links, forms)
- Visual regression testing with screenshot comparison
- Accessibility testing for WCAG 2.1 AA compliance
- Cross-browser testing (Chrome, Firefox, Safari, Edge, mobile)
- Performance testing with Core Web Vitals metrics

Updated:
- Test report template with new test category sections
- Evaluation criteria with UI-specific thresholds
- Remediation guidance for UI-related failures
- Output examples showing comprehensive test results
```

**Infrastructure/DevOps:**
```
feat(infra): add Podman containerization infrastructure

Add complete containerization infrastructure for local testing
and future production deployment using Podman.

Scripts:
- scripts/build_test.sh - Build and run container for testing
- scripts/nuke.sh - Complete environment cleanup
- scripts/install_podman.sh - Podman installation (CachyOS/Ubuntu-WSL)

Container Config:
- Dockerfile for single-container deployment (frontend + backend)
- podman-compose.yml for orchestration
- .dockerignore for build optimization

Versioning:
- VERSION file with semantic versioning (major.minor.patch)
- CHANGELOG.md following Keep a Changelog format
- Container tags: <version>-canary for testing
```
