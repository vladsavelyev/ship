"""Tests for the command-layer logic worth pinning: the merge close-out's ordering and wording."""

import pytest

from ship import __main__ as cli
from ship import github, problems
from ship.shell import CommandFailed
from ship.state import SCHEMA, new_state, render_block


def _problem(number: int, sev: str, *, state: str = "OPEN", extra: tuple[str, ...] = ()) -> dict:
    return {"number": number, "title": f"problem {number}", "state": state, "labels": [sev, *extra]}


def _merged_state() -> dict:
    state = new_state(branch="add-oauth", base="main", updated="2026-08-21T00:00:00Z")
    state["pr"] = 123
    state["status"] = "in-review"
    return state


def _stub_github(monkeypatch, *, calls: list[str], failing: str | None = None) -> None:
    def record(name):
        def fake(*_args, **_kwargs):
            calls.append(name)
            if name == failing:
                raise CommandFailed(1, ["gh"], "", "boom")
            return ""

        return fake

    monkeypatch.setattr(github, "comment", record("comment"))
    monkeypatch.setattr(github, "close_issue", record("close_issue"))
    monkeypatch.setattr(github, "set_issue_body", record("set_issue_body"))
    monkeypatch.setattr(github, "get_issue_body", lambda number: render_block(_merged_state()))


def test_record_outcome_closes_then_writes_state(monkeypatch):
    calls: list[str] = []
    _stub_github(monkeypatch, calls=calls)
    state = _merged_state()
    cli._record_outcome(42, state, "✅ Merged.", status="merged", already_closed=False)
    # The state write is LAST, and the close carries the note (one call, not close + comment).
    assert calls == ["close_issue", "set_issue_body"]
    assert state["status"] == "merged"


def test_record_outcome_only_comments_when_already_closed(monkeypatch):
    # The PR's `Closes #<issue>` reference usually closes the issue seconds before anyone runs the
    # close-out; `gh issue close` on a closed issue is not the way to find that out.
    calls: list[str] = []
    _stub_github(monkeypatch, calls=calls)
    cli._record_outcome(42, _merged_state(), "✅ Merged.", status="merged", already_closed=True)
    assert calls == ["comment", "set_issue_body"]


def test_record_outcome_leaves_state_unwritten_if_closing_fails(monkeypatch):
    # ORDER IS THE RETRY STRATEGY: a feature written as `merged` whose issue is still open would be
    # skipped by every future `feature reconcile` — orphaned permanently. Failing before the write
    # means a re-run does the whole thing again.
    calls: list[str] = []
    _stub_github(monkeypatch, calls=calls, failing="close_issue")
    state = _merged_state()
    with pytest.raises(CommandFailed):
        cli._record_outcome(42, state, "✅ Merged.", status="merged", already_closed=False)
    assert "set_issue_body" not in calls
    assert state["status"] == "in-review"


def test_reconcile_note_names_blocking_problems_that_shipped():
    triaged = problems.triage([_problem(7, "sev:high"), _problem(8, "sev:low")])
    note = cli._reconcile_note(123, triaged)
    # Recorded after the fact means the gate never vetted this merge — say so, with the numbers.
    assert "#7 [sev:high]" in note
    assert "1 blocking problem(s) were still open" in note
    assert "#8 [sev:low/open]" in note


def test_reconcile_note_is_plain_when_nothing_was_blocking():
    triaged = problems.triage([_problem(8, "sev:low")])
    note = cli._reconcile_note(123, triaged)
    assert "were still open" not in note
    assert "⚠️" not in note
    assert "#8 [sev:low/open]" in note


def test_state_block_of_a_fresh_feature_is_current_schema():
    # Guards the assumption `reconcile` leans on when it reads a state block without a schema check.
    assert new_state(branch="b", base="main", updated="now")["schema"] == SCHEMA


def test_abandoned_note_never_claims_a_merge():
    triaged = problems.triage([_problem(9, "sev:med")])
    note = cli._abandoned_note(123, triaged)
    # The work never landed: saying "merged" here would put a false claim in the permanent record.
    assert "Abandoned" in note
    assert "Merged" not in note
    # Its problems describe code that never shipped, but whether each is moot is the reviewer's
    # call — they are named for triage, not closed silently.
    assert "#9 [sev:med]" in note


def test_abandoned_note_is_short_when_there_is_nothing_left_open():
    note = cli._abandoned_note(123, problems.triage([_problem(9, "sev:med", state="CLOSED")]))
    assert "still\nopen" not in note and "still open" not in note


def _stub_adopt(monkeypatch, *, parent: str | None, pr: int | None, pr_base: str | None) -> dict:
    """Stub everything cmd_adopt touches; return what it did."""
    did: dict = {"parent": [], "issue": None}
    monkeypatch.setattr(cli, "feature_issue", lambda name: None)
    monkeypatch.setattr(cli, "parent_branch", lambda name: parent)
    monkeypatch.setattr(cli, "set_parent_branch", lambda name, base: did["parent"].append(base))

    def open_issue(name, base, title):
        did["issue"] = base
        return 7

    monkeypatch.setattr(cli, "_open_feature_issue", open_issue)
    monkeypatch.setattr(cli, "_load_state", lambda name: (7, new_state(branch=name, base="x", updated="t"), ""))
    monkeypatch.setattr(cli, "_save_state", lambda issue, body, state: None)
    monkeypatch.setattr(github, "open_pr_for_branch", lambda name: pr)
    monkeypatch.setattr(github, "pr_base_branch", lambda number: pr_base)
    monkeypatch.setattr(github, "link_pr_to_feature", lambda number, issue: True)
    monkeypatch.setattr(github, "comment", lambda issue, text: None)
    return did


def _adopt_args(base: str | None = None):
    return cli.argparse.Namespace(branch="child", base=base, title=None, init_labels=False)


def test_adopt_takes_the_pr_base_when_git_town_has_no_parent(monkeypatch):
    # A branch never stacked with git-town: assuming main would scope a stacked PR's review wrong.
    did = _stub_adopt(monkeypatch, parent=None, pr=25, pr_base="parent-x")
    cli.cmd_adopt(_adopt_args())
    assert did["parent"] == ["parent-x"]
    assert did["issue"] == "parent-x"


def test_adopt_refuses_a_pr_that_targets_another_branch_before_opening_an_issue(monkeypatch):
    did = _stub_adopt(monkeypatch, parent="main", pr=25, pr_base="parent-x")
    with pytest.raises(SystemExit, match="targets 'parent-x'"):
        cli.cmd_adopt(_adopt_args())
    assert did["issue"] is None


def test_adopt_without_a_pr_or_parent_bases_on_main(monkeypatch):
    did = _stub_adopt(monkeypatch, parent=None, pr=None, pr_base=None)
    cli.cmd_adopt(_adopt_args())
    assert did["parent"] == ["main"]
