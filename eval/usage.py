"""What a run actually spent — the eval's name for `verdict_mcp.usage`.

The reader moved into the package in 0.89.0 so that a production run can record its
own bill (`verdict-finalize` → `<qa-root>/usage.jsonl`); until then only the eval
could, and the PyPI wheel ships `src/verdict_mcp` and nothing from `eval/`. One
definition, imported here: two copies of the dedup-per-request-id rule is how the
eval and production would come to disagree about what a run costs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from verdict_mcp.usage import (  # noqa: E402,F401  (re-exported for run_eval, swebench, the census)
    ENTRYPOINT_ENV, FIELDS, SESSION_ENV, add, brief, config_root, project_dir, run_usage,
    session_files, session_transcripts, usage_of)
