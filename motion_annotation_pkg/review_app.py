from __future__ import annotations

import json
from pathlib import Path

from motion_annotation_pkg.pipeline import load_review_session, save_review_session


def launch_review_app(workspace_dir: str | Path) -> None:
    try:
        import streamlit as st
    except ModuleNotFoundError as exc:
        raise RuntimeError("Streamlit is required to launch the local review UI. Install streamlit first.") from exc

    workspace = Path(workspace_dir)
    session_dirs = sorted((workspace / "sessions").glob("*"))
    st.set_page_config(page_title="Motion Review", layout="wide")
    st.title("Motion Review")
    if not session_dirs:
        st.info("No sessions found.")
        return
    session_dir = st.sidebar.selectbox("Session", session_dirs, format_func=lambda path: path.name)
    review_session = load_review_session(session_dir)
    reviewed_sets = review_session["reviewed_sets"]
    index = st.sidebar.slider("Set", 0, len(reviewed_sets) - 1, 0)
    selected = reviewed_sets[index]
    st.json(review_session["metadata"]["workoutContext"])
    selected["annotation_kind"] = st.selectbox(
        "Annotation kind",
        ["rep_based", "timed_no_rep", "transition", "rest", "invalid", "ambiguous"],
        index=["rep_based", "timed_no_rep", "transition", "rest", "invalid", "ambiguous"].index(selected["annotation_kind"]),
    )
    selected["start_time"] = int(st.number_input("Start", value=int(selected["start_time"])))
    selected["end_time"] = int(st.number_input("End", value=int(selected["end_time"])))
    selected["rep_count"] = int(st.number_input("Rep count", value=int(selected["rep_count"]), disabled=selected["annotation_kind"] != "rep_based"))
    rep_markers_text = st.text_area("Rep markers JSON", value=json.dumps(selected["rep_markers"], indent=2), disabled=selected["annotation_kind"] != "rep_based")
    if selected["annotation_kind"] == "rep_based":
        selected["rep_markers"] = json.loads(rep_markers_text or "[]")
    else:
        selected["rep_markers"] = []
        selected["rep_count"] = 0
    review_session["notes"] = st.text_area("Notes", value=review_session.get("notes", ""))
    if st.button("Save"):
        save_review_session(session_dir, review_session)
        st.success("Saved")
