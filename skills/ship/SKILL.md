---
name: ship
description: Start, stack, adopt, resume or review a tracked feature branch and check its merge gate. Use for any review request on a tracked branch.
context: fork
background: false
---

# ship

You run in a forked subagent. Do the one job the caller asked for (create, adopt, resume,
review, gate or close out), then end with the **report** below. The caller never sees this file,
so the report must tell it everything it needs.

The `feature` CLI (repo `/Users/kbww511/git/ship`, design in `docs/design.md`) keeps all
state in GitHub + git config. A feature is a branch, a worktree under the main checkout's
`.claude/worktrees/<name>/`, and a tracking issue. Review findings become sub-issues. The merge gate
opens when nothing blocking is open and the last review covers HEAD.

**Work in the feature worktree.** The main checkout has the same files on the base branch, so
reading or running there gives wrong answers. `cd` to the worktree (`feature status` prints it as
`Worktree`) before anything else, and never read from the main checkout or another worktree.

## Commands

| Situation | Command |
| --- | --- |
| New feature | `feature create <name> [--base <branch>]` (`--init-labels` first time in a repo). Aborts if the base has unpushed commits; `--allow-local-base` overrides. |
| Stack on another feature | `feature create <child> --base <parent-branch>` |
| Track an existing branch | `feature adopt` |
| Resume | `feature status`. If it warns merged-but-not-closed-out, run `feature merge` first. |
| Record the user's request | `feature prompt "<request>"` |
| Link the PR | `feature pr <number>` |
| Record a review | `feature review record --sha <sha> --new-blocking <n> [--new-low <n>] [--regressions <n>] --summary "<sentence>"` |
| Problems | `feature problem list --blocking\|--open`, `add`, `resolve <#> --commit <sha>`, `defer\|reject\|block <#> --reason "…"` |
| Review budget | `feature budget [--set <n> \| --auto]` |
| Stuck loop | `feature escalate --reason "<findings + recommendation>"` |
| Sync with base | `feature sync [--stack]` |
| Merge check | `feature gate`: exit 0 OPEN, 10 REVIEW_AGAIN, 20 NEEDS_DECISION; 1/2 mean the command failed |
| Close out | `feature merge`, or `feature reconcile [--dry-run]` repo-wide |
| Old repo/issue after a CLI upgrade | `feature migrate` |

## Review round

1. **PR against the parent.** The PR must target the parent branch (`main` for a top-level feature,
   the branch below for a stacked one) and be linked with `feature pr <n>`. If either is missing,
   don't review. Report what the caller must do.
2. **Find blind, before loading any tracked state.** Run `Skill(review, <PR#>)` with this brief:
   ```
   Review only. Do not edit, commit, push, or comment on the PR.
   Worktree: <abs path>. Read code only there.
   Find bugs, broken callers, and mismatches with the PR's intent. Skip style unless it hides a bug.
   Flag code, tests or guards the intent doesn't need. Other paths, rare cases, small perf: low.
   high = data loss, security hole, crash, or silently wrong result on a realistic path.
   med = real bug on a narrower path. low = everything else.
   Each finding: [high|med|low] <file>:<line> <claim>. Repro: <input/state>. Fix: <smallest fix>.
   ```
3. **Now load state**: `feature problem list --open`, plus closed problems for regression checks.
4. **Verify and dedup each finding** against the real code:
   - Can't reproduce it concretely → drop it.
   - Same meaning as an OPEN problem → skip.
   - Same as a CLOSED fixed problem → regression. `feature problem block <#> --reason
     "rediscovered: <repro>"`, and count it (if high/med) in `--new-blocking` and `--regressions`.
     Never `gh issue reopen`.
   - Same as a REJECTED problem → skip, unless the new repro answers the rejection reason. Then
     `block` it. A problem disputed twice goes to the human: escalate with both sides.
   - Not caused by this PR → never blocking. File it `--sev low`, or defer it.
   - Re-judge severity yourself, whatever label the finder gave. Only `low` is non-blocking, and
     an unlabelled problem blocks, so always pass `--sev`.
5. **File new ones**: `feature problem add --title "…" --sev … --body-file - <<'EOF' … EOF`, with
   the repro, `file:line` and the suggested smallest fix.
6. **Record**: `feature review record --sha $(git rev-parse HEAD) …`. Write `--summary` as a real
   sentence about what was reviewed and found, never a bare "clean pass".

## Gate verdict

- `OPEN` (0): safe to merge. Name the debt that ships. The human merges.
- `REVIEW_AGAIN` (10): the caller fixes the blocking problems, then calls this skill again.
- `NEEDS_DECISION` (20): no more rounds. `feature escalate` with exactly one recommendation: ship
  it (defer the rest with reasons), buy one round (`feature budget --set`, only with a concrete
  reason), split the PR, or redesign.

## Rules

- Never lower a severity to open the gate. Defer with a reason instead.
- Never `feature merge --force`. Never merge for the human.
- Close fixed problems with `problem resolve`, not a `Closes #a, #b` PR line (GitHub links only the
  first number).
- Don't hand-edit the JSON block in a feature issue.
- The CLI fails fast. Report its errors, don't work around them.

## Report

End with only this, filled in:

```
Feature: <name>  Branch: <branch>  PR: <url or none>  Worktree: <abs path>
Did: <one line>
Gate: <verdict, or not run>
Blocking: #<n> [sev] <title> — <file:line>, fix: <smallest fix>   (one per line, or none)
Next:
- <exact steps for the caller>
```

Always include these caller rules in `Next` when they apply:
- After `create`, or if the caller may not be in the worktree: "Call `EnterWorktree` with
  `path: <worktree>` (never `name:`) before editing. Editing from the main checkout edits the base
  branch."
- With blocking problems: "Fix each with the smallest change; prefer deleting or narrowing over new
  code, and don't grow the diff to appease the reviewer. Commit, then `feature problem resolve <#>
  --commit <sha>`. If a finding is wrong, `feature problem reject <#> --reason "<evidence>"`
  instead of changing code. Then call `Skill(ship:ship)` for the next round."
- With `OPEN`: "Tell the user it's safe to merge and what debt ships. After they merge, call
  `Skill(ship:ship)` to close out."
- With `NEEDS_DECISION`: "Stop. Present the recommendation to the user."
