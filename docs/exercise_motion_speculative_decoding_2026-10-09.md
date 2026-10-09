# Qwen speculative decoding qualification — 2026-10-09

## Decision

Keep ordinary Qwen inference in production. DFlash is the best available exact-target candidate found, but it failed the focused latency keep rule after its vision compatibility defect was corrected. Do not enable it or repeat these comparisons without new evidence addressing prompt processing or memory. No production defaults, target weights, quality gates, or provider fallback changed.

## Research and download

- Target: existing Qwen3.5-9B-UD-Q4_K_XL with mmproj-BF16(6), RTX 4070 SUPER 12GB, llama.cpp b11510/c35b66744.
- [Author DFlash checkpoint](https://huggingface.co/z-lab/Qwen3.5-9B-DFlash): specifically trained for Qwen3.5-9B. Author speed claims use B200/BF16/text workloads and do not establish local vision gains.
- EAGLE-3 and DSpark are runtime-supported methods, but no released draft for this exact target was verified. [Domino](https://github.com/jianuo-huang/Domino) and the researched newer methods did not supply a verified ready-to-test draft for this target. Do not substitute Qwen3-8B drafts.
- Downloaded through `hf download`, preserving existing models: `onion515/Qwen3.5-9B-DFlash-GGUF`, revision `b3db2fbcd58c68d4471f0f69182b389296b0d3de`, Q5_K_M, 913,809,600 bytes, SHA256 `aa7521c7c210d1fd56e4e7520b6cbb5df6d0c7f813c8ddddff0861c4f8663045`. Author configuration pinned to `5fc3b3d474760f18c516db87d84c37edbfd3ede6`.

## Focused comparisons

Replayed the retained OHP/RDL source scorecards through the production vision client/parser. Exact prompt/image/request payload hashes matched between arms. Same target, projector, image budgets, greedy sampling, 8K context per slot, 1024/512 batches, exclusive GPU ownership, fresh owned server, and production JSON compatibility handling. Each request made the same HTTP 400 JSON-mode attempt then same-provider HTTP 200 compatibility retry. No movement generation or rendering was repeated.

| Arm | Slots | OHP seconds | RDL seconds | Total request seconds |
|---|---:|---:|---:|---:|
| Ordinary Qwen, production profile | 6 | 17.586 | 19.564 | 37.149 |
| Ordinary Qwen, matched control | 2 | 23.893 | 20.436 | 44.328 |
| Corrected DFlash Q5, max draft 7 | 2 | 36.348 | 38.583 | 74.931 |

Matched DFlash was 30.602 seconds (69.0%) slower. This is one completed pair, not a repeated or reversed-order speed estimate. The declared first-pair keep rule failed; no reverse pair, broader quantization sweep, or production integration followed.

Structured outputs matched: candidate order/IDs, approval, confidence, movement/boundary flags, equipment status and rejection reasons. RDL's entire response was identical. OHP varied only in free-text notes/evidence. This establishes retained scorecard parity, not general movement quality or all-exercise reliability.

Prompt evaluation dominated: OHP 3.358→29.748 seconds; RDL 3.558→28.492 seconds. Decode improved: OHP 34.47→119.78 tokens/s; RDL 57.03→89.53 tokens/s. Draft acceptance was 71.8%/66.4%, mean accepted lengths 6.03/5.65. Better decode alone did not improve total request latency. Startup was 11.236 seconds for the matched control and 18.862 seconds for DFlash.

## Failures and owning layers

1. An initial probe wrapper failed before launching a server; excluded from timings. A subsequent baseline startup timed out at 120 seconds; one bounded retry became healthy in about 16 seconds. Cause of that transient delay remains unproven.
2. Six-slot DFlash exhausted VRAM before draft loading. Target recurrent rollback buffers were 2,412 MiB; draft placement reported zero free CUDA memory. Source inspection strongly supports a zero-sum memory-split normalization leading to `invalid vector subscript`; no native stack trace was captured. This profile is not qualified.
3. Two-slot DFlash loaded but failed the actual four-image request with HTTP 500. The downloaded GGUF omitted `dflash.rope.dimension_sections`: ordinary RoPE rejected the intentional image-position gap 1561→1623. The current converter writes `[64,0,0,0]` for M-RoPE targets, but detection depends on target configuration. A separate copied GGUF adds precisely that metadata, selecting the intended temporal-only M-RoPE path. All original metadata and all 69 tensor byte sequences were verified identical. Corrected SHA256: `3c536b95b51cae5162be34ddb3ac3a004a3ba9db862cf32673976fab647a7f73`. Both image requests then passed.

## Evidence and limits

The raw diagnostics formerly under `build/exercise_motion/diagnostics/speculative_decoding_20261009/` were deleted during the user's subsequent full build-folder cleanup. The findings and timings above remain the retained research record; do not assume those replay inputs or logs still exist. The original download outside `build` remains untouched; the corrected copy has suffix `-mrope.gguf`. After qualification, the throwaway probe, metadata-repair script, launcher, Python caches, isolated worktree and experiment branch were removed at the user's request. No experimental code was added to production.

Protocol amendments were driven by failures: startup cap increased 120→240 seconds (outer cap 330→420), repeated server launches were forbidden, verbose logs enabled equally for the matched two-slot arms, and slots reduced only for that explicitly separate comparison. Failed arms were recorded separately before cleanup. Diagnostic scripts compiled and the metadata repair passed byte-preservation assertions. All owned model servers were stopped.

No final-review, reasoning-on, concurrency-throughput or full movement runs were performed because the retained request pair already failed the latency keep rule. Reconsider only with evidence that DFlash prefill overhead or memory behavior has materially improved; qualify those additional production paths before enabling it.
