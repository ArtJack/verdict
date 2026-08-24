# Verdict Template: Test Case

Use when: structured test cases are needed for manual execution, future automation, or
traceability to requirements.

## Template

```text
Test Case ID:
Title:
Requirement/Risk:
Priority:
Type: positive / negative / boundary / regression / smoke / integration / security / usability
Technique: (equivalence partitioning / boundary value analysis / decision table / state
  transition / pairwise / use case / error guessing / checklist)
Automation Candidate: yes / no / later

Preconditions:

Test Data:

Steps:
1.
2.
3.

Expected Result: (stated BEFORE execution)

Postconditions/Cleanup:

Evidence Required:

Notes:
```

## Design Rules

- Each test case should verify one main behavior.
- Link the case to a requirement, acceptance criterion, defect, or risk.
- Name the design technique — it makes coverage auditable.
- Include positive, negative, and boundary cases when the behavior has input ranges or
  validation rules.
- Prefer stable, repeatable cases for automation candidates.
- Keep exploratory ideas separate from scripted test cases unless the steps are known.
