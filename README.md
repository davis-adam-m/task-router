# Task Router

A local operator workspace for routing tasks to contributors with matching expertise. Python, Flask, SQLite, server-rendered HTML/CSS, and unittest; no frontend build or external service.

## Requirements

- Python 3.14
- The commands below use Windows PowerShell and PyCharm Terminal.

## Setup Virtual Environment

From the project root, create a virtual environment:

```powershell
py -3.14 -m venv .venv
```

## Install Dependencies and Run

From the project root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open **http://127.0.0.1:5000**. Stop with Ctrl+C. In PyCharm, select `.venv\Scripts\python.exe` as the interpreter and run `app.py`, with the project root as working directory. Use one process only. Do not use `flask run`, an automatic reloader, or multiple server workers: the `app.py` entry point starts the single routing thread. The development server is bound to localhost.

The first start seeds three contributors and three tasks. Data lives in ignored `instance/router.sqlite3`. Subsequent starts preserve it. No reset is performed automatically.

## Operator workflow

- Create a task to submit it for routing, or route a seeded task.
- Refresh status manually. Pages never refresh automatically, so typing is uninterrupted. A refresh intentionally reloads the current page.
- Routing returns an offer or no match after 5–20 seconds. Independently, 20% of normal requests remain unresolved forever. Pending duration cannot reveal which outcome is coming. Normal views do not expose the stored simulated outcome.
- Retry routing or offer an assignment manually whenever needed before acceptance. Both supersede existing pending requests and offers. Manual assignment requires matching expertise.
- Record the simulated contributor response: accept, decline, or failure before work begins. Decline/failure requires a reason and returns the task to ready for recovery.
- Acceptance completes routing. Further routing or reassignment requires an explicit reopen with a reason.
- The collapsed **Deterministic demo controls** section creates a known match, no match, or unresolved request. Demo selection is intentionally recorded in history; use normal routing when demonstrating uncertainty.

## Important decisions

**Atomicity and one assignee.** Service operations acquire a SQLite `BEGIN IMMEDIATE` transaction before reading and changing workflow state. State changes and their history commit or roll back together. A partial unique index permits at most one offered or accepted assignment per task. Replaced, declined, failed, and reopened assignments remain as history. Contributors can receive offers for multiple tasks; workload capacity is deliberately omitted.

**Stale results.** Each submission gets a durable request ID, and the task points to its current request. The worker checks both that ID and the routing state inside the same write transaction. Retry replaces the pointer; manual assignment and acceptance clear it. A late result is marked processed and logged as ignored without changing the current assignment. Returning superseded requests remain available for that audit. Superseded unresolved requests remain stored but do not block anything. Offer-response forms also carry the assignment ID, so an outdated page cannot accept, decline, fail, or reopen a different assignment.

**Restart.** At submission, the simulator stores a candidate and a due timestamp, or a null due timestamp for an unresolved request. These internal fields never appear in normal operator views. The one background worker checks due requests every half second, independently of HTTP traffic. On restart, overdue returning requests are applied with the same stale-result checks; unresolved requests remain pending. This simulates a durable external engine result rather than running a long sleep per request. Transactions ensure a crash cannot commit an assignment without its history or processed marker. Wall-clock timestamps are sufficient for this local exercise; clock changes can affect delays and displayed ages.

**Concurrency.** SQLite serializes workflow writers; whichever valid operation acquires the transaction first runs first. Operator reassignment can replace an engine offer that just arrived. An accepted assignment requires reopening even if another browser still shows an older page. Multiple app processes are outside supported scope. The app factory starts no worker, keeping tests isolated.

**Interface and local scope.** Status is a snapshot with an explicit refresh button. No polling or input-erasing refreshes. CSRF tokens, bound SQL parameters, server-side validation, and HTML autoescaping are included. The random per-process session key means forms open across a restart must be reloaded. Authentication, authorization, real contributor responses, notifications, external queues, deployment, pagination, editing contributor expertise, and production hardening are intentional omissions. This is a trusted localhost demo, not a multiuser deployment.

## Automated verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests use temporary databases, injected time, and seeded randomness. They cover routine acceptance/reopening, unresolved routing, stale results after intervention/acceptance, retry ordering, no match, decline/failure recovery, restart persistence, transaction rollback on history failure, the unique assignment constraint, concurrent requests/intervention, outdated offer responses, validation, CSRF, page rendering, and worker progress without browser requests. They do not wait 20 seconds per simulated request.

## Verification

Automated tests, HTTP smoke checks, and eight user-performed workflow checks are documented in `VERIFICATION.md`.