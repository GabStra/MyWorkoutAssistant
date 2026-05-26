from __future__ import annotations

import argparse

from motion_annotation_pkg.loader import copy_export_into_workspace
from motion_annotation_pkg.pipeline import build_dataset_index, finalize_review_session, prepare_review_session
from motion_annotation_pkg.review_app import launch_review_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple offline motion annotation pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import-session")
    import_parser.add_argument("--export-dir", required=True)
    import_parser.add_argument("--workspace-dir", required=True)

    preprocess_parser = subparsers.add_parser("preprocess-session")
    preprocess_parser.add_argument("--session-dir", required=True)

    review_parser = subparsers.add_parser("review")
    review_parser.add_argument("--workspace-dir", required=True)

    finalize_parser = subparsers.add_parser("finalize-session")
    finalize_parser.add_argument("--session-dir", required=True)
    finalize_parser.add_argument("--output-dir")

    index_parser = subparsers.add_parser("build-dataset-index")
    index_parser.add_argument("--dataset-dir", required=True)
    index_parser.add_argument("--output-path")

    args = parser.parse_args()
    if args.command == "import-session":
        print(copy_export_into_workspace(args.export_dir, args.workspace_dir))
    elif args.command == "preprocess-session":
        print(prepare_review_session(args.session_dir))
    elif args.command == "review":
        launch_review_app(args.workspace_dir)
    elif args.command == "finalize-session":
        print(finalize_review_session(args.session_dir, args.output_dir))
    elif args.command == "build-dataset-index":
        print(build_dataset_index(args.dataset_dir, args.output_path))


if __name__ == "__main__":
    main()
