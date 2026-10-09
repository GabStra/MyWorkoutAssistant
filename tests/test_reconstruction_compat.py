from exercise_motion_pkg.reconstruction_compat import (
    loads_reconstruction_metadata,
    retained_reconstruction_path,
)


def test_historical_metadata_keeps_actual_paths_and_current_field_precedence():
    payload = loads_reconstruction_metadata(
        '{"whamResultsPkl":"raw/wham/wham_output.pkl",'
        '"wham":{"whamCacheStatus":"reused"},'
        '"whamRunSeconds":3,"reconstructionRunSeconds":4}'
    )
    assert payload["reconstructionResultsPkl"] == "raw/wham/wham_output.pkl"
    assert payload["reconstruction"]["reconstructionCacheStatus"] == "reused"
    assert payload["reconstructionRunSeconds"] == 4


def test_historical_result_filename_remains_readable(tmp_path):
    workspace = tmp_path / "reconstruction-study"
    workspace.mkdir()
    legacy = workspace / "wham_output.pkl"
    legacy.write_bytes(b"retained")
    current = workspace / "reconstruction_output.pkl"
    assert retained_reconstruction_path(current) == legacy
    current.write_bytes(b"current")
    assert retained_reconstruction_path(current) == current
