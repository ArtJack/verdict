# QA Profile — pricer

**Project-Key:** `pricer`
**Repo-Path:** `@FIXTURE_DIR@`
**Repo-Remote:** `none`
**Profile created:** 2026-08-20

## What this is

A marketplace listing pricer library. Pure in-process Python; no network, no database, no
credentials, no live services. `README.md` in the repo is the requirement spec of record.

## Isolation check (before any Bash call)

- `git status --porcelain` on the checkout — must be clean, and MUST remain clean: the
  fixture under test is never modified.
- No `.env` of any kind is expected; if one appears, every stateful task is `blocked`.

## Test commands

- Suite: `python3 -m pytest -q` (provision pytest out-of-tree if absent — never install
  into the fixture).
- Coverage: no tool configured — the coverage direction gate is unmeasurable; say so.

## Forbidden

- Any modification of the checkout, including fixture files and skip markers.
- Reading `eval/EXPECTED*.md` or `eval/expected*.json` anywhere on disk — answer keys.
