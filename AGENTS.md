# Developer notes

## Blocking-call gates

Home Assistant warns when code blocks the event loop ("Detected blocking call").
Three checks find this before a user does:

- **`blockbuster` fixture.** `tests/integration/conftest.py` fails any test that
  blocks the event loop, with the file and line. `tests/integration/test_blocking_calls.py`
  proves the fixture is active. `blockbuster` is in `requirements-test.txt`.
- **Python dev mode in the test container.** `tests/docker/docker-compose.yml`
  sets `PYTHONDEVMODE=1` and `PYTHONASYNCIODEBUG=1`, so the log shows
  never-awaited coroutines, slow callbacks and unclosed resources.
- **Log gate.** `ci/test-docker.sh` and `ci/e2e-up.sh` save the container log
  (`ha-docker.log`, `ha-browser.log`) before they remove the container. The
  `e2e-docker` and `e2e-browser` jobs upload it and run
  `python3 scripts/check_ha_log.py --domain home_keeper_bambu_lab <log>` as
  the last step. The gate fails on warnings or errors from this integration, on
  blocking calls that name it, and on known bad patterns. Exit code 1 means
  findings or a stale allowlist entry, 2 means the log had no Home Assistant records.

To accept an expected message, add a comment line with the reason, then a narrow
regular expression, to `scripts/ha_log_allowlist.txt`. An entry without a reason
is rejected. An entry that hides nothing makes the gate fail, so remove it.
Warnings from the fake Bambu Lab component are test inputs: fix the input first.
`ruff` also runs the `ASYNC` rules (`pyproject.toml`), but they see only direct
calls, so treat them as a weak guard.
