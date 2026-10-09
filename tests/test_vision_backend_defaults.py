import exercise_motion_pkg.segment_detection as segment_detection
from exercise_motion_pkg.llama_defaults import DEFAULT_LLAMA_CPP_MODEL
from exercise_motion_pkg.segment_detection import DetectionSettings
from exercise_motion_pkg.youtube import YouTubeRankingSettings


def test_vision_defaults_to_the_configured_qwen_model():
    assert YouTubeRankingSettings().vision_model == DEFAULT_LLAMA_CPP_MODEL


def test_segment_detection_has_no_litert_backend():
    settings = DetectionSettings()
    assert not hasattr(settings, "litert_command")
    assert not hasattr(settings, "litert_backend")
    assert not hasattr(segment_detection, "LiteRtCliVisionClient")

