# ONCOLINK Permanent Rules

1. docs/SPEC.md is the source of truth for behaviour. If a task conflicts with it, stop and ask me.
2. Never hardcode, randomize, or fabricate clinical outputs: confidences, classes, regions, metrics, hospital data, or test results.
3. No mock data or mock database in runtime code. Mocks are allowed only inside tests and must be labeled as mocks.
4. If a dataset, API key, or credential is missing, stop and tell me. Do not fake it or silently skip it.
5. Every feature ships with tests. Run them before reporting done.
6. Case status changes only through the state machine service, and every change writes to the audit log.
7. Secrets live only in environment variables. Never commit them.
8. Every result and report screen shows the intended-use notice from the spec.
9. Never claim something works unless you ran it. Do not write 'fully operational' or 'verified' without evidence.
10. Keep work in small, separate tasks. Make small commits with clear messages.
11. I develop on Windows. Give me commands that work in PowerShell. Do not rely on bash-only scripts or a Makefile; use npm scripts or PowerShell scripts, and run services through Docker where possible.
12. End every task with a summary under three headings: Done, Not done, Assumptions.
13. Every endpoint returning case or patient data must apply the ownership rules in docs/PERMISSIONS.md and ship a test where a different user of the same role requests that record and receives 404 (not 403, so record IDs cannot be probed).
