"""The sentence a packet adds to a request, measured without touching the agent.

On 2026-09-17 two Sonnet root-cause runs of three answered correctly in chat and never
called the harness, and the routing rule that followed is a sentence in the orchestrator's
packet: "this is a run". Measuring that rule must change the request and nothing else —
not the agent prompt, not its hash — and must say on the result that it was there.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
import run_eval  # noqa: E402


def test_no_note_leaves_the_task_exactly_as_it_was():
    for note in (None, "", "   \n"):
        assert run_eval.with_task_note("/cause the failing test in this repository", note) \
            == "/cause the failing test in this repository"


def test_a_note_follows_the_task_it_does_not_replace_it():
    got = run_eval.with_task_note("/cause the failing test in this repository",
                                  "  This is a run: start with verdict-facts.  ")
    assert got == ("/cause the failing test in this repository\n\n"
                   "This is a run: start with verdict-facts.")

