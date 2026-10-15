# Verdict Template: Exploratory Testing Charter

Use when: behavior is not fully specified or risk discovery matters more than scripted
confirmation.

## Template

```text
Charter:
Mission:
Project/Feature:
Timebox:
Tester:
Environment:

Risk Focus:
-

User Personas/Data:
-

Areas To Explore:
-

Heuristics:
- Inputs and validation
- State changes
- Permissions
- Error handling
- Interruptions and retries
- Boundary values
- Data persistence
- Integration behavior
- Accessibility/usability signals

Notes During Session:
-

Bugs/Risks Found:
-

Follow-Up Test Cases:
-

Automation Candidates:
-

Session Verdict:
- pass / pass with risks / blocked / fail
```

## Usage Rules

- Set a timebox before starting.
- Capture observations as evidence, not just conclusions.
- Turn repeatable failures into bug reports.
- Turn important stable discoveries into scripted regression cases.
