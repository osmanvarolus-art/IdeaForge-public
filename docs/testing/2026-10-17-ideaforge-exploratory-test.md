# IdeaForge exploratory test report — 2026-10-17

## Scope and safety

Browser testing of `http://127.0.0.1:7888/`, isolated reproductions using a temporary database and fake NotebookLM CLI, and the repository test suite. No production code was changed. No API keys, paid services, or real NotebookLM account were used. One test idea, one notebook row, and one failed research run were created in the app database; Founder Brain export timestamp also changed.

## Completed checks

- Opened Ideas, Pipeline, Research, Radar, Outcomes, and Insights views; controls and page content rendered.
- Searched YouTube for `solo developer local-first productivity app ideas`; eight results returned. Search eventually completed, but the UI showed `Searching…` without elapsed time or progress.
- Selected a result and added it to the pipeline successfully.
- Ran one complete idea pipeline through Extract, Evaluate, and Instruct for `How To Reach 10,000 App Users (Beginner Marketing)` (`https://www.youtube.com/watch?v=e_t1gYkvZkI`). All three completed. Evaluation returned `SKIP`, fit `25/100`; durations were 3,321 ms, 34,956 ms, and 9,780 ms.
- Invoked notebook creation. It remained `pending`, with no `nlm_id` or error. A safe isolated reproduction confirmed the worker failure: the finalize route queues `{"kind":"notebook_create","notebook_id":...}` without `idea_id`, while `worker_loop()` unconditionally reads `job['idea_id']` before dispatch. Reproduction output: `Worker exception: 'idea_id'`; notebook stayed `pending`. This is a confirmed root cause.
- Confirmed a second notebook UI defect: `pipeFinalize()` ignores the finalize HTTP response and polls only for `ready` or `failed`; a notebook stuck at `pending` leaves the UI on `Creating…` forever.
- Ran Research Mode for `Find practical local-first productivity app ideas for solo developers. Prefer recent build tutorials.` It failed with `name 'log' is not defined`. `research_planner()` and `research_rerank()` contain multiple calls to undefined `log()`. An isolated malformed-JSON reproduction also produced the same `NameError`.
- Confirmed the Outcomes/Insights count mismatch. Outcomes filters on `eval_status === 'done'`; Insights queries every row with non-null `eval_verdict`. Six legacy `EVALUATED` rows are excluded by Outcomes but included in Insights. Normalize legacy statuses or use one shared completed-evaluation rule.
- Confirmed resource leaks behind test warnings: `db()` returns a SQLite connection, while `with db()` does not close SQLite connections; transcript files are read with bare `open(...).read()` at `ideaforge:1144` (also `:853`).
- Founder Brain export succeeded and updated its last-export timestamp.
- `.venv/bin/python -m unittest discover -s tests -v`: **46 tests passed** in 29.014s, with many `ResourceWarning: unclosed database` warnings and an unclosed transcript-file warning.
- `python -m pytest` unavailable because `pytest` is not installed in the app virtual environment.

## Findings and suggested corrections

1. **Notebook creation worker crashes on missing job field.** Include `idea_id` when `/api/notebook/<id>/finalize` enqueues the job (the other notebook-create enqueue path uses `idea_id: 0`), or make the worker log/dispatch independent of this optional field. Add an HTTP-to-worker integration test with a fake CLI. Then rerun creation and artifact generation using a fake CLI; real NotebookLM account behavior remains untested.
2. **Notebook creation UI can wait forever.** Check `response.ok` and response body in `pipeFinalize()`, poll for `pending`/`creating` with a bounded timeout, and show actionable errors. Add a route-error and stuck-pending UI check.
3. **Research Mode parse recovery crashes.** Replace undefined `log()` calls with the existing logger/printing convention or define a module logger. Test invalid initial planner JSON, invalid retry JSON, and malformed reranker JSON.
4. **Outcomes and Insights count different populations.** Normalize legacy evaluation statuses or share one predicate/query; test legacy `EVALUATED` plus current `done` records.
5. **Database and transcript handles leak.** Close SQLite connections explicitly while preserving current transaction/autocommit behavior; use context managers for file reads. Rerun unittest and check warnings disappear.
6. **Search has no visible progress.** Add elapsed/progress feedback and make timeout/error/retry states visible. The test search completed, so no timeout failure was proven.

## Coverage still needed

Core Extract/Evaluate/Instruct and key view loading were exercised once. Full notebook creation and podcast/report artifact generation were blocked by the confirmed worker bug. Other source types, empty/error states, CRUD actions for outcomes/subscriptions, browser reload/resume, and repeated/boundary cases still need testing. Persistent data-changing controls were not exercised beyond the explicitly recorded test rows.

## Verdict

The findings are detailed enough to implement and verify the three confirmed defects: notebook worker job shape, Research Mode undefined logger, and inconsistent outcome population. Resource-lifecycle and UI wait-state fixes also have direct code evidence. More end-to-end testing is still needed after fixes, especially notebook artifact generation and untested source/CRUD flows.
