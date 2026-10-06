"""Re-render the selected preview webms with the current renderer.

The preview webms are recordings made when each movement was baked; they do
not pick up renderer fixes (head pitch, shimmer damping). This script replays
every ``selected/*_wear_skeleton.json`` through the same browser render path
the pipeline uses and rewrites ``selected/*_selected_preview.webm`` in place,
keeping the original recording as a ``.pre_fix.bak`` sibling.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exercise_motion_pkg.bake_and_rank import (
    browser_session,
    dense_loop_review_video_frame_indices,
    launch_chromium_browser,
    parse_review_video_fps,
    render_baked_wear_frames_with_playwright,
    stage_preview_for_browser_if_needed,
    write_validated_review_video_from_data_urls,
)


def rerender_artifact(directory: Path, page: Any) -> dict:
    skeletons = list(directory.glob("*_wear_skeleton.json"))
    htmls = list(directory.glob("*_interactive_preview.html"))
    webms = list(directory.glob("*_selected_preview.webm"))
    if len(skeletons) != 1 or len(htmls) != 1 or len(webms) != 1:
        return {"path": str(directory), "skipped": "unexpected artifact set"}
    with open(skeletons[0], encoding="utf-8") as handle:
        payload = json.load(handle)
    options = payload.get("selectedPreviewSettings")
    if not isinstance(options, dict):
        options = {}
    staged_html, staged_temp = stage_preview_for_browser_if_needed(htmls[0])
    try:
        page.goto(staged_html.resolve().as_uri(), wait_until="networkidle")
        page.wait_for_function("() => window.exerciseMotionAutomation != null")
        indices = dense_loop_review_video_frame_indices(payload)
        if not indices:
            return {"path": str(directory), "skipped": "no review frame indices"}
        urls = render_baked_wear_frames_with_playwright(
            page,
            export_payload=payload,
            frame_indices=indices,
            options=options,
        )
        fps = parse_review_video_fps(payload, frame_count=len(urls))
        backup = webms[0].with_suffix(".webm.pre_fix.bak")
        if not backup.exists():
            backup.write_bytes(webms[0].read_bytes())
        _, quality = write_validated_review_video_from_data_urls(
            urls, webms[0], fps=fps
        )
        metadata_path = webms[0].with_suffix(".review_video.json")
        metadata_path.write_text(json.dumps({
            "schemaVersion": 1,
            "frameCount": len(urls),
            "fps": fps,
            "sourceFrameCount": len(payload.get("frames", [])),
            "frameIndices": indices,
            "renderSource": "retained_payload_rerender",
            "reviewVideoQuality": quality,
        }, indent=2), encoding="utf-8")
        return {
            "path": str(directory),
            "frames": len(urls),
            "fps": fps,
            "qualityPassed": bool(quality.get("passed")),
        }
    finally:
        if staged_temp is not None:
            staged_temp.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        default=str(Path(__file__).resolve().parents[1] / "build" / "exercise_motion" / "exercise-library"),
    )
    parser.add_argument("--limit", type=int, default=0, help="only rerender the first N directories")
    args = parser.parse_args()

    root = Path(args.workspace)
    directories = sorted(p.parent for p in root.glob("*/selected/*_wear_skeleton.json"))
    if args.limit:
        directories = directories[: args.limit]
    print(f"selected artifacts: {len(directories)}", flush=True)

    from playwright.sync_api import sync_playwright

    summary = {"rendered": 0, "skipped": 0, "errors": 0}
    reports = []
    with sync_playwright() as playwright:
        browser = launch_chromium_browser(playwright)
        try:
            page = browser.new_page(viewport={"width": 960, "height": 720}, device_scale_factor=1)
            for index, directory in enumerate(directories):
                try:
                    result = rerender_artifact(directory, page)
                except Exception as error:  # noqa: BLE001 - one failure must not stop the sweep
                    summary["errors"] += 1
                    reports.append({"path": str(directory), "error": str(error)[:300]})
                    print(f"ERROR {directory.name}: {error}", flush=True)
                    continue
                reports.append(result)
                if result.get("skipped"):
                    summary["skipped"] += 1
                    print(f"skip  {directory.name}: {result['skipped']}", flush=True)
                else:
                    summary["rendered"] += 1
                    print(
                        f"RENDERED {directory.name}: {result['frames']} frames @ {result['fps']:.0f}fps",
                        flush=True,
                    )
                if index % 10 == 0:
                    print(f"progress {index + 1}/{len(directories)}", flush=True)
        finally:
            browser.close()
    (root / "webm_rerender_report.json").write_text(
        json.dumps({"summary": summary, "artifacts": reports}, indent=2), encoding="utf-8"
    )
    print(f"summary: {summary}", flush=True)


if __name__ == "__main__":
    main()
