---
name: feature-workflow
description: Feature branches with worktrees, PRs, issue-tracked review problems and a merge gate. Use to start, stack, adopt or resume a feature, check if it can merge, and for ANY review request on a tracked feature branch. On those branches this skill owns reviewing, so don't use a generic reviewer.
---

# Feature workflow

Drives the `feature` CLI (repo: `/Users/kbww511/git/feature-workflow`, design in `docs/design.md`).
A feature is a branch, a worktree and a GitHub tracking issue. Review findings become sub-issues.
The **merge gate** opens when nothing blocking is open and the last review covers HEAD. Reviews are
budgeted, so a loop that won't converge ends in **NEEDS_DECISION** instead of going on forever.
All state lives in GitHub + git config. Run `feature <cmd>` from inside the repo.

## Commands

| Situation | Command |
| --- | --- |
| New feature | `feature create <name> [--base <branch>]` (`--init-labels` first time in a repo). Aborts if the base has unpushed commits; `--allow-local-base` overrides. |
| Stack on another feature | `feature create <child> --base <parent-branch>` (works from anywhere) |
| Track an existing branch | `feature adopt` (on the branch) |
| Resume / understand a branch | `feature status` |
| Record the user's request | `feature prompt "<request>"` |
| Link the PR (required before review) | `feature pr <number>` |
| Record a review | `feature review record --sha <sha> --new-blocking <n> [--new-low <n>] [--regressions <n>] --summary "<sentence>"` |
| List problems | `feature problem list --blocking` / `--open` |
| File a problem | `feature problem add --title "<t>" --sev high\|med\|low --body-file - <<'EOF' … EOF` |
| Fixed | `feature problem resolve <#> --commit <sha>` |
| Ship unfixed, on the record | `feature problem defer <#> --reason "…"` |
| False positive | `feature problem reject <#> --reason "…"` |
| Revoke a defer/reject | `feature problem block <#> --reason "…"` |
| Review budget | `feature budget [--set <n> \| --auto]` |
| Hand a stuck loop to the human | `feature escalate --reason "<findings + recommendation>"` |
| Sync with base | `feature sync [--stack]` (git-town) |
| Merge check | `feature gate`: exit 0 OPEN, 10 REVIEW_AGAIN, 20 NEEDS_DECISION; 1/2 mean the command failed |
| Close out after merge | `feature merge` |
| Close out orphaned features repo-wide | `feature reconcile [--dry-run]` |
| Old repo/issue after a CLI upgrade | `feature migrate` |

## Work from the feature worktree

Worktrees live under the main checkout (`.claude/worktrees/<name>/`), and the main checkout has the
same files on the base branch, so editing there silently edits the base. A shell `cd` doesn't help.
Right after `feature create`, and when resuming if `feature status` shows a different `Worktree`,
call `EnterWorktree` with `path:` set to that worktree. Never pass `name:`, which would create a
second worktree. Leave with `ExitWorktree action: "keep"`.

On an existing branch, run `feature status` first (a SessionStart hook may already have injected it).
If it warns that the feature is merged but not closed out, run `feature merge` before anything else.

## Reviewing

1. **PR against the parent.** Open the PR with `gh pr create --base <parent>`: `main` for a
   top-level feature, the branch below for a stacked one. Then `feature pr <n>`. A wrong base pulls
   the parent's commits into the review, and `review record` refuses it.
2. **Run the finder blind, in a fresh subagent, before loading any tracked state.** Spawn one
   `Agent` that runs `Skill(review, <PR#>)` and returns raw findings. Tell it its working directory
   is the feature worktree (absolute path) and that it must never read from the main checkout or
   another worktree. Never run the finder in your own context: after the first round you remember
   past problems and stop finding new ones. Never spawn a headless `claude`.
3. **Now load state**: `feature status` and `feature problem list --open`.
4. **Verify and dedup every finding** against the real code:
   - Not concretely reproducible → drop it.
   - Same meaning as an OPEN problem → skip it. Same as a CLOSED one → it's a regression:
     `feature problem block <#> --reason "rediscovered: <repro>"` and count it (if high/med) in
     both `--new-blocking` and `--regressions`. Use `problem block`, never `gh issue reopen`.
   - Pre-existing, or not caused by this PR → never blocking. File it `--sev low`, or defer it.
   - Severity: `high` means data loss, a security hole, a crash, or a silently wrong result on a
     realistic path. `med` is a real bug on a narrower path. `low` covers style, duplication,
     hypotheticals and anything without a concrete failure. Only `low` is non-blocking, and an
     unlabelled problem blocks, so always pass `--sev`.
5. **File the new ones** with `feature problem add`. Put the failure scenario and `file:line` in a
   `--body-file -` heredoc.
6. **Record the run**: `feature review record --sha $(git rev-parse HEAD) …`. Write `--summary` as a
   real sentence about what was reviewed and found. A bare "clean pass" is not acceptable. Then do
   what the printed verdict says.

The loop: fix → `problem resolve` → review → `review record`. Any commit after a review needs another
round. Deferring needs none.

## Obey the gate verdict

| Verdict | What to do |
| --- | --- |
| `OPEN` (0) | Report it's safe to merge and name the debt that ships. Stop; the human merges. |
| `REVIEW_AGAIN` (10) | Fix the blocking problems, then do one more round. |
| `NEEDS_DECISION` (20) | **Stop reviewing.** `feature escalate` with exactly one recommendation: ship it (defer the rest with reasons), buy one more round (`feature budget --set`, only with a concrete reason), split the PR, or redesign. |

Don't start another finder unless the verdict calls for it.

## Rules

- Never lower a severity to open the gate. Defer the problem with a reason instead.
- Never `feature merge --force`. Never merge for the human.
- Close fixed problems with `problem resolve`, not a `Closes #a, #b` line in the PR body (GitHub
  links only the first number).
- Deferred and low problems stay open on purpose.
- Don't hand-edit the JSON block in a feature issue.
- After a merge, run `feature merge` (or `feature reconcile`). Stacked merges don't auto-close.
- The CLI fails fast. Surface its errors and don't work around them.
