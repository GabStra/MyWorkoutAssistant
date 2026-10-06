# Shared Persistent Llama Server

Design for one supervisor-owned `llama-server` process shared by every vision
client in the exercise motion pipeline: wave processes, discovery jobs, and
contract prefetch. Current status: **run-scoped and opt-in** through
`run_exercise_motion_workout_plan.ps1 -SharedLlamaServer`; it is not a
host-level service shared across separate workout-plan runs.

## Problem

Every wave process and every discovery job currently starts its **own**
llama.cpp vision server (~7.9 GiB on the RTX 4070 SUPER 12 GiB: 5.7 GiB weights
plus ~2.2 GiB compute/KV at ctx 49152 / batch 1024):

- Two servers can never co-reside; every exclusive phase pays a full
  stop + lazy restart (~40 s) before the next vision request.
- Per-session startup costs ~7-40 s each (2,445 startups measured in one
  workspace).
- One server with `--parallel 8` serves attached clients without multiplying
  model VRAM within one run. Wave overlap is a separate scheduling change; the
  measured two-wave arm was slower and lost acceptance parity, so it remains
  disabled.

**Permanent constraint:** GVHMR reconstruction (~4.3-6 GiB) can never co-reside
with the server. Exclusive generation phases remain; the shared design must
coordinate *stopping* the server around them (the quiesce protocol below).

## Ownership model

| Aspect | Owner |
| --- | --- |
| `llama-server` process lifetime | PowerShell supervisor (`Start-SharedLlamaServer` / `Stop-SharedLlamaServer` in `scripts/run_exercise_motion_workout_plan.ps1`) |
| Server start / health / restart | Supervisor only |
| Server stop before exclusive GPU phases | The quiescing *client* process itself (netstat/taskkill via `stop_llama_cpp_servers_for_base_url`), after drain |
| In-flight request accounting | One coordinator per attached process (counter file in the session dir); see "In-flight counter ownership" below |

The supervisor owns the process the same way it owns warm WHAM/GVHMR worker
containers: a session directory with marker files, lazy start on
`start_requested.json`, `ready.json`/`heartbeat.json` for liveness. Python
clients never spawn, adopt, or own the server when `--shared-llama-server` is
on; they attach, coordinate, and release.

## Session directory contract

Resolved per client as: request field `shared_llama_server_session_dir` >
env `EXERCISE_MOTION_SHARED_LLAMA_SESSION_DIR` >
`%TEMP%\myworkoutassistant-shared-llama-<port>` (derived from the base URL port
so every process pointing at one base URL agrees with no configuration).

| File | Writer | Meaning |
| --- | --- | --- |
| `ready.json` | Supervisor | `{pid, baseUrl, model, parallel, startedAtUnixSeconds}` - server healthy |
| `heartbeat.json` | Supervisor | `{updatedAtUnixSeconds}` - supervisor still tending the server |
| `stop_intent.json` | Quiescing client | `{pid, processIdentity, requestedAtUnixSeconds}` - exclusive GPU phase pending/active; attached clients gate new VLM admissions on a *live* intent |
| `in-flight/<pid>.json` | One coordinator per attached process | `{pid, processIdentity, activeRequests, updatedAtUnixSeconds}` - that process's concurrent VLM request count (wave-session admissions + every non-session shared-server request) |
| `stopped.json` | Quiescing client | `{stoppedByPid, stoppedAtUnixSeconds}` - observability for the supervisor |
| `start_requested.json` | Client needing the server back | `{requestedByPid, processIdentity, requestedAtUnixSeconds}` - lazy restart request; supervisor deletes it after a successful restart |
| `shared-llama-transition.lock` | Python clients and PowerShell supervisor | OS-level transition mutex shared across runtimes; serializes startup admission/readiness against exclusive-handoff publication/release |
| `startup_error.json`, `server.log` | Supervisor | startup failure payload, redirected server output |

Liveness of any marker's owner uses the same rule as the global GPU lock:
pid running **and** process start identity matching (recycled pids never hold
markers). A marker whose owner is dead is stale and is reclaimed/cleared by
whoever encounters it.

## Attach vs. own semantics

| Behavior | Flag off (today, unchanged) | Flag on (attach mode) |
| --- | --- | --- |
| Ranker start | Spawns + owns a server if none healthy at `base_url` | Reuses the healthy server; never spawns |
| GPU lock `llama_cpp_server` stage | Held for the owned server's lifetime | Not acquired (the supervisor's server is not this process's lease; cross-process exclusion moves to the quiesce protocol) |
| Server death mid-request | Client recovery restarts the owned server | Client recovery *waits* for the supervisor's restart (bounded by the startup timeout), then retries |
| `close()` | Stops/releases the owned server (force semantics unchanged) | Releases nothing: counter removed, markers owned by us cleared, server untouched - even with `force_stop_server=True` |
| `run_without_llama_overlap` (exclusive handoff) | Drain local calls, force-stop the owned server, run, lazily restart on next request | Quiesce protocol (below), run, request supervisor restart |

Server-model/runtime validation on attach is unchanged (model id,
`--parallel`, and reasoning flags). The run-scoped supervisor derives those
values from the same parameters passed to bake, discovery, and
contract-prefetch clients; do not weaken the runtime-mismatch checks.

## In-flight counter ownership

Every shared-server vision request in a process is counted exactly once, into
ONE counter file (`in-flight/<pid>.json`) written by ONE coordinator per
resolved session dir per process:

- **Single writer per pid.** `shared_llama_coordinator_for(dir)` (a
  process-global registry in `shared_llama_server.py`) hands every user in the
  process the same `SharedLlamaServerCoordinator` for a given dir, so wave
  sessions and discovery/contract clients in one pid can never publish
  independent counts that clobber each other. The first installed dir wins for
  the process - every attaching client is expected to resolve the same dir.
- **Wave sessions count admissions themselves.** `LazyLlamaCppVisionSession`
  counts a request when it admits it (before its HTTP call, preserving the
  admission-vs-drain settle guarantee) and suspends the client-level publisher
  on its thread while the request runs (`suspend_shared_llama_request_publisher`).
- **Everything else is counted at the client choke point.**
  `LlamaCppVisionClient.caption_images` wraps every request in
  `shared_llama_request_scope`: +1 before the request (including retries and
  recovery), -1 in `finally` on success and exception paths. The scope is a
  no-op unless this process attached to a shared session dir (a ranker or a
  wave session installed the process-global publisher), or the calling thread
  is already counted by a wave session. This covers discovery, contract
  prefetch, and segment detection without per-caller wiring.
- **The publisher never quiesces.** The process-global coordinator used by
  discovery-side attachment is publishing-only: it never acquires a
  stop-intent, never stops or restarts the server. Only wave sessions drive
  `begin/end_exclusive_phase`.
- **Foreign-intent admission gate.** Like the wave session's admission gate,
  the client-level scope waits while a *live foreign* `stop_intent.json`
  exists, bounded by the request's timeout (`None` = unbounded, mirroring the
  session). Own-pid intents do not gate it: a request dispatched from inside
  this process's own exclusive phase (contract prefetch through an isolated
  attached ranker) must proceed, not deadlock on ourselves; the wave session's
  admission gate still closes its own requests during that phase. When the
  wait budget expires the request is refused before any server contact
  (`SharedLlamaExclusivePhaseActive`), leaving the counter untouched.

Publisher attachment is refcounted: every attaching `LlamaCppVisionRanker`
(discovery, contract, segment) installs on creation and detaches on close; a
wave session installs at init and detaches at close; the last detachment drops
the counter file, and an `atexit` hook covers unclean exits. The counter file
survives a detachment while counted requests are still in flight.

## The QUIESCE protocol (exclusive phases)

`LazyLlamaCppVisionSession.run_without_llama_overlap` with the flag on:

1. **In-process drain** (unchanged): `_exclusive_waiters += 1`, wait for
   `_wham_active`, then wait for local `_active_calls == 0`.
2. **Publish** our counter file at 0.
3. **Transition reservation + stop-intent**: acquire
   `shared-llama-transition.lock`, wait out any *live* foreign intent, then
   publish `stop_intent.json` and this process's in-flight counter before
   releasing the lock. The supervisor takes the same lock before checking
   handoff state and holds it until the server is healthy (or startup fails).
   This makes the intent and counter visible atomically with respect to server
   startup admission.
   From this moment every attached process's `caption_images` admission gate
   blocks new VLM requests (any live intent, ours included).
4. **Drain**: wait until every *live* foreign counter reads `activeRequests`
   0, confirmed by two consecutive observations 0.25 s apart. Stale counters
   (dead pid / recycled pid identity) are ignored. Foreign in-flight requests
   are bounded by their request timeouts, so the drain converges.
5. **Stop the server** via `stop_llama_cpp_servers_for_base_url` (same
   netstat/taskkill mechanism today's force-stop uses, valid regardless of
   which process owns the server). Write `stopped.json`.
6. **Run the exclusive operation** (GVHMR/WHAM/...). Our stop-intent stays
   live, keeping every attached client's admissions closed.
7. **Release**: under `shared-llama-transition.lock`, clear
   `stop_intent.json`, write `start_requested.json` (lazy restart), and
   re-publish counter 0. The next vision request in any process either finds
   the restarted server (supervisor already acted) or blocks in the client's
   bounded recovery wait for it.

### What the protocol guarantees

- No attached process starts a new VLM request between stop-intent and server
  stop (admission gate + two-observation settle window close the check-then-
  increment race; a request admitted in the sub-millisecond window publishes
  its counter before its HTTP call, so the settle observation sees it).
- The server is fully stopped (VRAM free) before the exclusive operation
  starts, and stays stopped for its whole duration.
- A crashed quiescing process cannot wedge the pipeline: its intent and
  counters go stale via pid/identity liveness and are reclaimed.
- Exclusive phases remain serialized cross-process: foreign intents are
  waited out, and the global GPU stage locks still serialize the exclusive
  operations themselves.

### What it does NOT guarantee

- Requests that were already in flight when the intent landed are waited out
  by the drain (every attached process now publishes its in-flight count,
  including discovery); they complete rather than being killed. Requests this
  process dispatches from inside its *own* exclusive phase are the remaining
  exposure: the session's quiesce does not drain its own pid, so they fail and
  recover through the existing client recovery path, as with today's owned
  force-stop.
- Outside the run-scoped supervisor (for example, standalone attach mode),
  nobody restarts the server; the next attach/recovery waits out the startup
  timeout and raises an actionable error. Attach with no server at the base URL
  fails fast.
- Server startup cannot pass its admission check while an exclusive handoff is
  being published, and an exclusive handoff cannot begin between startup
  admission and readiness. The persistent lock file is an OS lease; process
  exit releases ownership without deleting the file.
- Two simultaneous `begin_exclusive_phase` writers still rely on the GPU stage
  locks to serialize the exclusive operations themselves.
- A restart request landing while another process is already entering its own
  exclusive phase causes at most one wasted supervisor start/stop cycle: the
  second quiesce stops whatever is at the port before its operation runs, so
  VRAM exclusivity is never violated.
- `heartbeat.json` is supervisor liveness reporting; clients do not gate on
  its timestamp.
- Per-process admission caps (`--parallel`) are unchanged; processes
  time-share the server's 8 slots via HTTP queuing (server-side), which is the
  intended capacity sharing.

## Failure modes

| Failure | Handling |
| --- | --- |
| Server dies mid-request | Existing `LlamaCppVisionClient` recovery: `recovery_callback` -> ranker sees no server, no owned process -> waits for the supervised restart (startup-timeout-bounded), retries |
| Attached process crashes with `activeRequests > 0` | Counter file goes stale (pid/identity dead); drainers ignore it; next attach of a recycled pid overwrites it |
| Quiescing process crashes mid-exclusive | `stop_intent.json` owner dead -> stale -> reclaimed by next quiescer / supervisor cleanup; session `close()` clears owned markers best-effort |
| Supervisor dies, server alive | Attach/quiesce keep working (they talk to the port, not the supervisor); restart requests go unattended -> next post-exclusive recovery times out with an actionable error |
| No server at base URL, flag on | Ranker attach fails fast with the models-endpoint connection error (never spawns) |
| Restart request lost (supervisor restart race) | `start_requested.json` is idempotent; clients re-request on the next exclusive release; supervisor deletes stale markers on start |

## Supervisor (PowerShell)

`Start-SharedLlamaServer -SessionDir <dir>` (mirrors `Start-WhamWarmWorker`):
takes `shared-llama-transition.lock`, defers when a live exclusive handoff is
present, clears stale markers, and removes only in-flight counters whose PID
and process-start identity prove the owner has stopped. Malformed or
unverifiable counters are retained. It then starts `llama-server` using the
configured `-LlamaCpp*` parameters (model and projection paths, parallelism,
context and batch sizes, cache types, reasoning mode and budget, and GPU
layers); host/port come from `-LlamaCppBaseUrl`. It polls `/v1/models` until
healthy within
`-LlamaCppServerStartupTimeoutSeconds` while holding the transition lock,
writes `ready.json` +
`heartbeat.json`, redirects output to `server.log`, writes
`startup_error.json` and throws on failure. Returns the instance object.

`Stop-SharedLlamaServer -Server <instance>` (mirrors `Stop-WhamWarmWorker`):
writes `stop_intent.json` (closing admissions), waits (bounded) for live
`in-flight/*.json` counters to drain, stops only the process whose recorded
start identity still matches, then writes `stopped.json` and clears
intent/ready markers. If drain times out, it preserves the server and its
shutdown-unconfirmed lease instead of stopping clients mid-request.

`Update-SharedLlamaServerHeartbeat` refreshes `heartbeat.json` from the run
loop. The workout-plan runner starts, monitors, restarts, and stops this
supervised instance when `-SharedLlamaServer` is enabled.

## Remaining follow-ups

1. **Host-level service lifetime**: the current supervisor is owned by one
   workout-plan invocation. Reusing it across separate runs requires a
   separately managed owner, crash recovery, and an explicit shutdown policy.
2. **Wave overlap**: overlap remains disabled after a measured regression. Any
   revisit needs fit-drained admission and browser/CPU headroom, followed by a
   new comparison that preserves accepted outputs.
3. **Standalone bake runner**: the workout-plan runner owns shared-server
   startup and shutdown. The standalone bake-and-rank entry point does not yet
   share that run-scoped supervisor.

## Current run-scoped integration (opt-in via `-SharedLlamaServer`)

Enabled with `-SharedLlamaServer` on `run_exercise_motion_workout_plan.ps1`
(default off; disabled automatically when vision ranking is skipped):

- Session dir defaults to `<workspace>/shared-llama-server` and is exported as
  `EXERCISE_MOTION_SHARED_LLAMA_SESSION_DIR` so every child process (waves,
  discovery jobs, contract prefetch) resolves the same coordinator directory.
- Bake wave args carry `--shared-llama-server --shared-llama-server-session-dir`;
  discovery/contract-prefetch args carry `--llama-cpp-shared-server` (the
  `find-youtube-videos` parser flag flows into `YouTubeRankingSettings`).
- The drain loop is the supervisor: it refreshes `heartbeat.json` every
  iteration, notices server death (a quiescing client stopped the process),
  and (re)starts via `Start-SharedLlamaServer` when jobs need vision AND
  either `start_requested.json` exists or `ready.json` is missing.
  `Start-SharedLlamaServer` clears stale markers - including the restart
  request - itself. Teardown always calls `Stop-SharedLlamaServer`.
- Server flags (parallel, ctx, batch, reasoning mode/budget) derive from the
  SAME `$LlamaCpp*` params that feed the requests, so the clients' attach-time
  runtime validation (slot count, reasoning flags) always matches.

Discovery-side in-flight counters are active (see "In-flight counter
ownership" above): each shared-server request a discovery process makes is
published through `LlamaCppVisionClient.caption_images`, and the client-level
admission gate defers new discovery requests while a live foreign exclusive
phase holds the server. A wave's quiesce therefore drains discovery requests
instead of killing them mid-flight. See "Remaining follow-ups" for work outside
this run-scoped integration.

Live-verified 2026-10-01 (real server): attach+caption, quiesce (3.3s drain ->
stop -> restart request), supervised restart, caption resume, and
close(force) leaving the shared server alive.
