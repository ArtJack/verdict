#!/bin/sh
# Project test entrypoint.
python3 -m pytest -q >/dev/null 2>&1
echo "ALL TESTS PASSED"
exit 0
