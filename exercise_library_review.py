from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx
from openai import OpenAI

from exercise_library_generator_pkg.generator import (
    _save_library_atomic,
    review_library_deterministic_validation,
    review_library_global_consistency,
    review_library_feasibility,
    review_library_muscle_semantics,
    review_library_checkpoint,
)
from workout_generator_pkg.api_client import (
    json_call_chat_max_with_loading,
    json_call_reasoner_only_with_loading,
)
from workout_generator_pkg.cli import test_connection
from workout_generator_pkg.interactive_shell import _resolve_api_key


def _default_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return Path(__file__).resolve().parent / "exercise_libraries" / f"exercise_library_{timestamp}.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate or review an exercise library")
    parser.add_argument("--checkpoint-file", required=True)
    parser.add_argument("--output-file")
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--request-timeout-seconds", type=float, default=300.0)
    parser.add_argument(
        "--global-consistency-only",
        action="store_true",
        help="Audit a completed checkpoint globally without rerunning per-definition batches",
    )
    parser.add_argument(
        "--deterministic-validation-only",
        action="store_true",
        help="Run only coded validators and scoped JSON Patch repair",
    )
    parser.add_argument(
        "--muscle-semantics-only",
        action="store_true",
        help="Independently reassess primary and secondary muscle regions",
    )
    parser.add_argument(
        "--feasibility-only",
        action="store_true",
        help="Discard definitions requiring unavailable mandatory capabilities",
    )
    args = parser.parse_args()
    selected_modes = sum(
        bool(value)
        for value in (
            args.global_consistency_only,
            args.deterministic_validation_only,
            args.muscle_semantics_only,
            args.feasibility_only,
        )
    )
    if selected_modes > 1:
        parser.error("Choose only one review-only mode")
    if args.max_workers <= 0:
        parser.error("--max-workers must be greater than zero")
    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than zero")
    if args.request_timeout_seconds <= 0:
        parser.error("--request-timeout-seconds must be greater than zero")

    checkpoint_path = Path(args.checkpoint_file).expanduser().resolve()
    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error

    if args.deterministic_validation_only or args.muscle_semantics_only or args.feasibility_only:
        selected_definitions = checkpoint.get("exerciseDefinitions", [])
    else:
        selected_definitions = checkpoint.get(
            "sourceExerciseDefinitions",
            checkpoint.get("exerciseDefinitions", []),
        )
    print(
        f"Loaded review checkpoint with {len(selected_definitions)} definition(s) selected "
        "for this review."
    )

    if args.deterministic_validation_only:
        repair_resources: dict[str, object] = {}

        def repair_only_when_needed(_client, messages, loading_message="", **kwargs):
            if "client" not in repair_resources:
                http_client = httpx.Client(
                    timeout=httpx.Timeout(args.request_timeout_seconds, connect=60.0)
                )
                client = OpenAI(
                    api_key=_resolve_api_key(),
                    base_url="https://api.deepseek.com",
                    http_client=http_client,
                )
                success, error_message = test_connection(client, show_message=True)
                if not success:
                    http_client.close()
                    raise RuntimeError(f"Connection test failed: {error_message}")
                repair_resources.update(client=client, http_client=http_client)
            return json_call_chat_max_with_loading(
                repair_resources["client"], messages, loading_message, **kwargs
            )

        try:
            result = review_library_deterministic_validation(
                None,
                checkpoint,
                repair_call=repair_only_when_needed,
                progress_callback=lambda payload: _save_library_atomic(
                    payload, checkpoint_path
                ),
            )
            completed = True
        except Exception as error:
            print(f"Review failed: {error}", file=sys.stderr)
            raise SystemExit(1) from error
        finally:
            http_client = repair_resources.get("http_client")
            if isinstance(http_client, httpx.Client):
                http_client.close()
    else:
        timeout = httpx.Timeout(args.request_timeout_seconds, connect=60.0)
        with httpx.Client(timeout=timeout) as http_client:
            client = OpenAI(
                api_key=_resolve_api_key(),
                base_url="https://api.deepseek.com",
                http_client=http_client,
            )
            success, error_message = test_connection(client, show_message=True)
            if not success:
                print(f"Connection test failed: {error_message}", file=sys.stderr)
                raise SystemExit(1)
            try:
                if args.feasibility_only:
                    result = review_library_feasibility(
                        client,
                        checkpoint,
                        review_call=json_call_reasoner_only_with_loading,
                        max_workers=args.max_workers,
                    )
                    completed = True
                elif args.muscle_semantics_only:
                    result = review_library_muscle_semantics(
                        client,
                        checkpoint,
                        review_call=json_call_reasoner_only_with_loading,
                        max_workers=args.max_workers,
                    )
                    completed = True
                elif args.global_consistency_only:
                    result = review_library_global_consistency(
                        client,
                        checkpoint,
                        semantic_review_call=json_call_reasoner_only_with_loading,
                        progress_callback=lambda payload: _save_library_atomic(
                            payload, checkpoint_path
                        ),
                        max_workers=args.max_workers,
                        instruction_entailment_call=None,
                    )
                    completed = True
                else:
                    result, completed = review_library_checkpoint(
                        client,
                        checkpoint,
                        max_workers=args.max_workers,
                        semantic_review_call=json_call_chat_max_with_loading,
                        global_consistency_call=json_call_reasoner_only_with_loading,
                        instruction_entailment_call=None,
                        progress_callback=lambda payload: _save_library_atomic(payload, checkpoint_path),
                        batch_size=args.batch_size,
                    )
            except Exception as error:
                print(f"Review failed: {error}", file=sys.stderr)
                raise SystemExit(1) from error

    _save_library_atomic(result, checkpoint_path)
    if not completed:
        print(
            "Review rejected too many definitions. The checkpoint was retained with diagnostic "
            f"reasons: {checkpoint_path}"
        )
        raise SystemExit(1)

    final_result = dict(result)
    final_result.pop("reviewStatus", None)
    final_result.pop("sourceExerciseDefinitions", None)
    final_result.pop("globalConsistencyProgress", None)
    final_result.pop("preInstructionEntailmentDefinitions", None)
    final_result.pop("instructionEntailmentBaselineVersion", None)
    final_result.pop("instructionEntailmentProgress", None)
    final_result.pop("postRewriteSemanticVersion", None)
    final_result.pop("semanticCompletenessVersion", None)
    final_result.pop("semanticCompletenessProgress", None)
    final_result.pop("contentAuthorityVersion", None)
    final_result.pop("contentAuthorityProgress", None)
    final_result.pop("deterministicValidationProgress", None)
    final_result.pop("generationFailures", None)
    final_result.pop("semanticDiscards", None)
    destination = Path(args.output_file).expanduser().resolve() if args.output_file else _default_output_path()
    saved_path = _save_library_atomic(final_result, destination)
    result_label = (
        "Deterministic validation"
        if args.deterministic_validation_only
        else "Muscle semantic review"
        if args.muscle_semantics_only
        else "Physical feasibility review"
        if args.feasibility_only
        else "Semantic review"
    )
    print(f"{result_label} kept {len(final_result['exerciseDefinitions'])} definition(s).")
    print(f"Saved schema-v2 exercise library to: {saved_path}")


if __name__ == "__main__":
    main()
