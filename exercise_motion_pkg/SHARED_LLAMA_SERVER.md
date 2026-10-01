# Shared Persistent Llama Server

Design for one supervisor-owned `llama-server` process shared by every vision
client in the exercise motion pipeline: wave processes, discovery jobs, and
contract prefetch. Status: **increment 1, opt-in, default-off** (`--shared-llama-server`).

## Problem

Every wave process and every discovery job currently starts its **own**
llama.cpp vision server (~7.9 GiB on the RTX 4070 SUPER 12 GiB: 5.7 GiB weights
plus ~2.2 GiB compute/KV at ctx 49152 / batch 1024):

- Two servers can never co-reside; every exclusive phase pays a full
  stop + lazy restart (~40 s) before the next vision request.
- Per-session startup costs ~7-40 s each (2,445 startups measured in one
  workspace).
- One server with `--parallel 8` could serve all clients at **zero extra
  VRAM**, unlocking wave-overlap pipelining (increment 2).

**Permanent constraint:** GVHMR reconstruction (~4.3-6 GiB) can never co-reside
with the server. Exclusive generation phases remain; the shared design must
coordinate *stopping* the server around them (the quiesce protocol below).

## Ownership model

| Aspect | Owner |
| --- | --- |
| `llama-server` process lifetime | PowerShell supervisor (`Start-SharedLlamaServer` / `Stop-SharedLlamaServer` in `scripts/run_exercise_motion_workout_plan.ps1`) |
| Server start / health / restart | Supervisor only |
| Server stop before exclusive GPU phases | The quiescing *client* process itself (netstat/taskkill via `stop_llama_cpp_servers_for_base_url`), after drain |
| In-flight request accounting | Each attached process (counter file in the session dir) |

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
| `in-flight/<pid>.json` | Each attached client | `{pid, processIdentity, activeRequests, updatedAtUnixSeconds}` - that process's concurrent VLM request count |
| `stopped.json` | Quiescing client | `{stoppedByPid, stoppedAtUnixSeconds}` - observability for the supervisor |
| `start_requested.json` | Client needing the server back | `{requestedByPid, processIdentity, requestedAtUnixSeconds}` - lazy restart request; supervisor deletes it after a successful restart |
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

Server-model/runtime validation on attach is unchanged (model id, `--parallel`,
reasoning-flag conflicts). Note for increment 2: today's production bake
settings run reasoning **on** (budget 64), which the runtime-mismatch check
rejects against a server started `--reasoning off ... --reasoning-budget 0`.
Wiring must reconcile the supervisor's reasoning flags with the runtime
settings (align flags, or pass matching `--llama-cpp-reasoning-budget` /
`--llama-cpp-disable-reasoning` to shared-mode clients); weakening the
validation is not an option.

## The QUIESCE protocol (exclusive phases)

`LazyLlamaCppVisionSession.run_without_llama_overlap` with the flag on:

1. **In-process drain** (unchanged): `_exclusive_waiters += 1`, wait for
   `_wham_active`, then wait for local `_active_calls == 0`.
2. **Publish** our counter file at 0.
3. **Stop-intent**: acquire `stop_intent.json` (wait out any *live* foreign
   intent; reclaim stale ones; optimistic-lock verify after write).
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
7. **Release**: clear `stop_intent.json`, write `start_requested.json` (lazy
   restart), re-publish counter 0. The next vision request in any process
   either finds the restarted server (supervisor already acted) or blocks in
   the client's bounded recovery wait for it.

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

- Requests that were already in flight when the intent landed are *not*
  interrupted gracefully; they fail when the server stops and recover through
  the existing client recovery path (bounded wait for restart). This is the
  same exposure as today's owned force-stop.
- If the supervisor is not running (increment 1 default), nobody restarts the
  server; the next attach/recovery waits out the startup timeout and raises
  an actionable error. Attach with no server at the base URL fails fast.
- Two simultaneous `begin_exclusive_phase` writers race only at the
  optimistic-lock level; correctness there still rests on the GPU stage locks.
- A restart request landing while another process is already entering its own
  exclusive phase causes at most one wasted supervisor start/stop cycle: the
  second quiesce stops whatever is at the port before its operation runs, so
  VRAM exclusivity is never violated.
- `heartbeat.json` staleness is informational in increment 1 (supervisor
  liveness reporting); clients do not gate on it.
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
clears stale markers and `in-flight/*.json`, starts `llama-server` with the
production flag set (`-m Qwen3.5-9B-UD-Q4_K_XL.gguf`, `--mmproj
mmproj-BF16(6).gguf --mmproj-offload`, `--parallel 8`, `--ctx-size 49152`,
`--batch-size 1024`, `--ubatch-size 512`, `--flash-attn on`,
`--cache-type-k/v q8_0`, `--fit on`, `--threads-http 8`, `--reasoning off
--reasoning-format none --reasoning-budget 0`, `--cont-batching`,
`--gpu-layers all`; host/port from `-LlamaCppBaseUrl`, paths from the existing
`-LlamaCpp*` params), polls `/v1/models` until healthy within
`-LlamaCppServerStartupTimeoutSeconds`, writes `ready.json` +
`heartbeat.json`, redirects output to `server.log`, writes
`startup_error.json` and throws on failure. Returns the instance object.

`Stop-SharedLlamaServer -Server <instance>` (mirrors `Stop-WhamWarmWorker`):
writes `stop_intent.json` (closing admissions), waits (bounded) for live
`in-flight/*.json` counters to drain, force-stops the process, writes
`stopped.json`, clears intent/ready markers.

`Update-SharedLlamaServerHeartbeat` refreshes `heartbeat.json` from the run
loop. **Increment 1 ships the functions + params only; nothing calls them.**

## Deferred follow-ups (increment 2+)

1. **Run-loop wiring** (the deliberate increment-2 scope):
   - Resolve the shared session dir once (`Get-SharedLlamaSessionDir`) and
     start the instance before the first wave (or lazily on
     `start_requested.json` in the drain loop, mirroring
     `$lazyWarmWorkerSessionDir` handling).
   - Pass `--shared-llama-server` (and the session dir /
     `EXERCISE_MOTION_SHARED_LLAMA_SESSION_DIR`) to bake wave job args, and
     set it in the wave job environment alongside
     `EXERCISE_MOTION_*_LAZY_START`.
   - Watch `start_requested.json` in the drain loop: restart via
     `Start-SharedLlamaServer` when no instance is live, delete the marker
     after readiness; refresh the heartbeat each loop iteration.
   - Call `Stop-SharedLlamaServer` at wave-set end / script teardown
     (`finally` blocks next to `Stop-WhamWarmWorker`).
   - Reconcile the reasoning flags (see "Attach vs. own semantics").
   - Stop starting per-process servers for discovery/contract paths once
     shared mode is proven (see next items).
2. **Wave-overlap scheduling**: with one resident server, the scheduler can
   overlap the next wave's source-validation VLM phase with the previous
   wave's exclusive generation tail (the original motivation).
3. **Discovery sharing**: `youtube-search`/discovery jobs attach to the same
   server instead of starting their own; requires the same flag plumbing in
   `build_youtube_ranking_settings` callers and budget fairness rules.
4. **Contract prefetch sharing**: the exercise-contract text path attaches
   like any other client (settings already flow via `dataclass_replace`).

## Increment 2: run-loop wiring (opt-in via `-SharedLlamaServer`)

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

Known bounded caveat: discovery processes attach by health-poll and do not yet
publish in-flight counters, so a wave's quiesce can kill one in-flight
discovery request; the client recovery path waits for the supervised restart
and retries. Publishing discovery-side counters is the next follow-up, along
with wave-overlap scheduling (the actual throughput payoff) and sharing the
server with the standalone bake runner.

Live-verified 2026-10-01 (real server): attach+caption, quiesce (3.3s drain ->
stop -> restart request), supervised restart, caption resume, and
close(force) leaving the shared server alive.
