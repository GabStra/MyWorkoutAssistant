# Visual decision backend: Qwen only

As of 2026-10-08, production visual decisions, source review, and final rendered-preview review use Qwen Chat. Production CLIs, PowerShell runners, persisted selection manifests, and throughput-harness arms must not route these requests to Clef. The production path rejects a non-Qwen backend instead of silently changing providers.

Clef remains in the repository as isolated adapter/runtime code, but it is not a supported production or throughput-harness backend. There is no Clef-to-Qwen fallback: failures from a selected review stage remain unresolved, uncertain, or failed according to that stage's existing gate, and cannot become an approval through another model call.

The two-scale source validation gate also remains on Qwen. Removing it from a comparison changes the source-acceptance policy, so it cannot be reported as a backend-only performance result.

This is a backend-selection decision, not a throughput result. The measured goal still requires current-policy source qualification, production-rendered review, package verification, and a repeatable end-to-end improvement with unchanged or better quality.
