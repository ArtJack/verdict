"""The run's budget: how many functions and probes a run may spend, and the model time it
has left.

Split out of small.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and small.py imports back what its callers use.
"""
from __future__ import annotations

import time


MAX_FUNCTIONS = 60              # a cap, so a large repository still finishes


class Budget:
    """How much model this run may spend, and what it skipped when it stopped.

    A gate nobody waits for is a gate nobody runs, so the caps are part of the
    product: a bounded number of functions, a bounded number of counterfactuals,
    and a wall-clock ceiling on the model's part. What matters for honesty is the
    other half — when a cap bites, the run says how many candidates it never looked
    at, because a truncated read reported as a complete one is the exact shape of a
    false green.

    The ceiling's clock starts at the first question, not when the budget is built:
    the suite and coverage run in between, and they are measurement, not model time.
    Started at construction, it counted them — on Verdict's own repository they took
    853 of a release gate's 900 s, and the gate read no function and reported "the
    900s model budget ran out" (2026-10-15).
    """

    def __init__(self, functions: int = MAX_FUNCTIONS, probes=None, seconds=None):
        self.functions, self.probes, self.seconds = functions, probes, seconds
        self.used_functions, self.used_probes, self.skipped = 0, 0, 0
        self.stopped = None
        self._started = None

    def elapsed_s(self) -> float:
        return 0.0 if self._started is None else time.monotonic() - self._started

    def take_function(self) -> bool:
        if self._started is None:
            self._started = time.monotonic()
        if not self.stopped:
            # `>=`: a budget of 0 s is spent at once. With `>`, Windows' 15.6 ms monotonic
            # clock reads 0.0 right after construction and a spent budget reads as unspent.
            if self.seconds is not None and self.elapsed_s() >= self.seconds:
                self.stopped = "the %ds model budget ran out" % int(self.seconds)
            elif self.used_functions >= self.functions:
                self.stopped = f"the cap of {self.functions} function(s) was reached"
        if self.stopped:
            self.skipped += 1
            return False
        self.used_functions += 1
        return True

    def take_probe(self) -> bool:
        """A counterfactual is the expensive question — a scratch copy and two
        subprocesses — so it has a cap of its own. Running out of probes leaves the
        claim a hypothesis, which is the honest outcome anyway."""
        if self.probes is None:
            return True
        if self.used_probes >= self.probes:
            return False
        self.used_probes += 1
        return True
