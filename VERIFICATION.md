# Verification record

Date: 2026-11-16.

## Codex automated checks and live HTTP smoke check

The following checks were performed by Codex during implementation. They are separate from the user-performed manual checks below; no automated tests were rerun for this documentation update.

- Installed Flask 3.1.3 into the existing project virtual environment.
- Final automated command: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v` — **15 tests passed**, approximately 3 seconds.
- Automated coverage: atomic state/history rollback; database constraint on active assignments; matching expertise; concurrent routing and intervention; stale-result logging without replacing accepted/manual assignments; retry and no-match recovery; unresolved requests; acceptance and explicit reopening; decline/failure reasons; rejecting responses to replaced offers; persisted request recovery using a new router instance; 5–20-second simulation delays and random unresolved outcomes; background worker progress without browser activity; Flask pages/forms, CSRF, validation, and preservation of invalid task input.
- Live smoke check: ran `.\.venv\Scripts\python.exe app.py` with debug/reloader off; used HTTP with cookies and CSRF to submit a deterministic matching request for seed task #1; made no requests for 21 seconds; fetched its detail page and confirmed an offer plus corresponding history. This verifies real worker progress independent of browser requests. The server was stopped afterward. Seed task #1 retains that offer in the local ignored database.
- `git diff --check` reported no whitespace errors in tracked changes. New Python modules were imported/exercised by tests.

## User-performed manual checks

The user reported that all checks passed; Codex reviewed the documented results but did not independently repeat these manual checks.

| Check | Documented scenario and result | User outcome |
|---|---|---|
| Routine assignment | Created a task using **Return a match**, waited over 20 seconds, refreshed, and accepted. One eligible assignee; acceptance completed routing. | Passed |
| Preserve input | Typed into a form and waited without submitting. Input remained intact. | Passed |
| Operator intervention | Started **Return a match**, immediately assigned manually, then waited and refreshed. Manual assignment remained; the late result was logged as ignored. | Passed |
| Recovery | Declined an assignment and retried; separately tested failure and manual reassignment. Reason and previous assignment remained in history; no duplicate active assignment. | Passed |
| Unresolved routing | Used **Never return**, waited over 20 seconds, and refreshed. Request stayed pending with elapsed time visible and intervention available. | Passed |
| Independent routing | Started several tasks, including one **Never return**. Other tasks resolved independently. | Passed |
| Restart | Started **Return a match** and **Never return**, stopped the server with Ctrl+C, waited over 20 seconds, and restarted. Scheduled result was processed; unresolved request stayed pending; history persisted. | Passed |
| Accepted task | Accepted, refreshed, then explicitly reopened with a reason. Acceptance persisted; reopening was recorded. | Passed |

These results verify a user-performed stop/restart scenario in addition to Codex's automated persistence tests. They do not establish behavior under an abrupt process termination or power loss.

