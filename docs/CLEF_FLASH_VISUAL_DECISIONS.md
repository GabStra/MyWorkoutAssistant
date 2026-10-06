# Clef Flash typed visual decisions

The integrated generator uses Clef Flash by default for typed visual decisions, including the production source-cut scorecard: comparative source-window choice, support classification, source-cut candidate review and endpoint observations, and final rendered-preview review. Qwen chat remains responsible for free-form reasoning, source contract generation, two-scale evidence adjudication, and exact timing. The workout-plan runner and both bake runners expose independent overrides: `-VisualDecisionBackend qwen-chat` or `--visual-decision-backend qwen-chat`, and `-FinalOutputReviewBackend qwen-chat` or `--final-output-review-backend qwen-chat` for the final preview.

## Generator call sites

Clef handles these decision types that have fixed, auditable answer spaces:

1. **Comparative source-window choice** — after normal segment detection has produced near-tied candidates, Clef can choose among 2–8 candidate contact sheets when `-ComparativeSegmentSelection` (or `--comparative-segment-selection`) is enabled. This adds an optional decision that is currently off by default, so it is a candidate-window quality option rather than a measured speed saving. The current deterministic selection is retained if Clef selects “none,” has confidence below `0.50`, or the service fails.
2. **Support-dominance classification** — chooses foot-dominant, hand-dominant, mixed support, or uncertain. Confidence below `0.45` is recorded as uncertain. A Clef-only pass does not start Qwen just to perform this classification.
3. **Source-cut endpoint observations** — each source endpoint is sent as its own image request; Clef observes support mode, knee state, torso orientation, hand height, and stance. Confidence below `0.20` becomes `unknown`. The deterministic boundary assessment still decides whether evidence agrees; uncertainty cannot become an approval or an automatic rejection.
4. **Source-cut candidate scorecard** — reviews one shortlisted candidate per request using typed choices for target identity, completion, start and finish boundaries, setup/filler, visible identity evidence, mechanics, contact changes, source quality, synthetic footage, required equipment, and confidence. The adapter maps those answers to the existing scorecard fields and rejection tags; the current deterministic parser, confidence threshold, independent rejection authority, and shortest-passing-window selection remain in control. Confidence is represented by conservative bands whose lower bound is used by the existing threshold. The typed decisions and per-answer confidence remain in the audit payload. Candidate reviews and their nested endpoint observations reuse one managed Clef lease. Clef infrastructure failures fall back to the existing Qwen scorecard path; an invalid typed answer remains unresolved rather than being treated as a pass.
5. **Final rendered-preview review** — asks advisory readability, broad recognizability, and obvious-display-defect questions on the actual final preview sheets. Findings remain advisory and cannot change selection or acceptance.

The production source-cut path does not consume per-phase numeric positions: its completion checks use the existing scorecard fields and deterministic pose coverage, so that unused phase-position output is not required for this migration. A separate movement-cut ranking helper does have phase-position fields but currently has no production caller. The optional `two_scale_source_validation` path remains on Qwen because it combines separate full-resolution identity, uniform-action, motion, completion, topology-position, and cross-evidence consistency reviews. That hard gate is off by default; no default generation requirement depends on it. Contract generation and exact timestamping also remain chat-model work.

## Runtime setup

The implementation originated in `MyWorkoutAssistant-clef-vlm` and is integrated into the main workspace. Its Clef llama.cpp runtime is pinned to verified Windows CUDA build `b11433`, which includes the Clef vision support. The server requires both the Clef model and its multimodal projector. The installer downloads either missing file into the workspace's `build/clef_runtime/hf-model` directory:

- `Clef-Flash-Q4_K_M.gguf` (about 6.49 GB)
- `mmproj-Clef-Flash-BF16.gguf` (about 922 MB)

Install the runtime and model files once:

```powershell
pwsh ./scripts/install_clef_llama_cpp.ps1
```

The model and projector come from the public `ggml-org/Clef-Flash-GGUF` Hugging Face repository using `hf download`. Typed decisions start the local CUDA server on demand after the Qwen owner has drained and stopped its server. Related requests, such as both source endpoints, share one Clef lease. The pipeline terminates Clef when the decision phase ends, so later Qwen work can start without overlapping model residency. Startup uses the isolated b11433 binary and requires the files above. A pre-existing server on the Clef port is rejected because the pipeline cannot safely release a process it does not own.

## Run with Clef enabled

```powershell
pwsh ./scripts/run_exercise_motion_bake_and_rank.ps1 `
  -CandidatesJson <candidate-file>
```

The YouTube-to-bake runner uses the same defaults. `VisualDecisionBackend` controls comparative source-window choice, support classification, and source endpoint observations; `FinalOutputReviewBackend` controls the rendered preview. Standalone `detect-segment` also defaults to Clef for its comparative choice stage when that optional choice is enabled. If that command is given an externally managed Qwen endpoint, it retains the deterministic span when it cannot acquire a safe exclusive handoff.

Enable optional comparative window selection explicitly with `-ComparativeSegmentSelection` in either runner, or `--comparative-selection` for standalone `detect-segment`.

## Resource and evidence limits

Clef's choice and yes/no outputs use no generated answer tokens, but wall-time savings and source-cut quality parity have not been measured on a controlled generation set. SystemOne probabilities are not calibrated correctness guarantees. The managed lease prevents Qwen and Clef from being resident together for these decisions; cold Clef startup can offset the faster warm request, so the backend change does not claim an end-to-end speedup. Failed Clef observations remain unresolved evidence, and comparative-choice failures retain the existing deterministic selection.
