from types import SimpleNamespace

import pytest

from exercise_motion_pkg.pose_prefilter import (
    COCO_KEYPOINT_NAMES,
    detections_from_yolo_result,
    PosePrefilterSettings,
    PoseSample,
    score_pose_window,
    significant_person_count,
)
from exercise_motion_pkg.video_utils import BasicVideoMetadata


PULLUP_DETECTION_PAIR = (
    {
        "bbox": (563.5682373046875, 50.18199920654297, 664.5277709960938, 313.29473876953125),
        "confidence": 0.5158882141113281,
        "keypoints": {
            "left_shoulder": (643.13330078125, 93.8869857788086),
            "right_shoulder": (607.89111328125, 95.33793640136719),
            "left_elbow": (657.3683471679688, 116.79163360595703),
            "right_elbow": (581.4498291015625, 120.55816650390625),
            "left_wrist": (650.1804809570312, 85.46118927001953),
            "right_wrist": (584.099609375, 88.46660614013672),
            "left_hip": (624.2579345703125, 164.9603271484375),
            "right_hip": (598.83251953125, 163.29269409179688),
            "left_knee": (610.1038818359375, 216.60264587402344),
            "right_knee": (588.27001953125, 216.99301147460938),
            "left_ankle": (605.4857177734375, 284.55926513671875),
            "right_ankle": (579.8513793945312, 282.8254089355469),
        },
    },
    {
        "bbox": (563.6454467773438, 50.55942916870117, 664.6240844726562, 313.79449462890625),
        "confidence": 0.34115108847618103,
        "keypoints": {
            "left_shoulder": (642.9620361328125, 94.56478881835938),
            "right_shoulder": (607.2437744140625, 95.84205627441406),
            "left_elbow": (656.8953247070312, 117.13899993896484),
            "right_elbow": (581.1134643554688, 121.06871795654297),
            "left_wrist": (650.0254516601562, 85.85675048828125),
            "right_wrist": (584.5732421875, 89.1626968383789),
            "left_hip": (624.1351318359375, 165.2629852294922),
            "right_hip": (598.8220825195312, 163.42190551757812),
            "left_knee": (610.4560546875, 216.60606384277344),
            "right_knee": (588.337646484375, 217.0597686767578),
            "left_ankle": (604.8572387695312, 284.7233581542969),
            "right_ankle": (579.7282104492188, 283.3911437988281),
        },
    },
)

# Cached YOLO26x output for OHP frame 55: one fading athlete appears twice,
# with the lower-confidence box expanded to the right. Coordinates are the
# recorded detections, with the low-confidence right ear omitted.
OHP_FADE_DUPLICATE_PAIR = (
    {
        "bbox": (313.373, 79.270, 426.500, 337.954),
        "confidence": 0.5311801433563232,
        "keypoints": dict(zip(
            (name for name in COCO_KEYPOINT_NAMES if name != "right_ear"),
            ((368.023, 96.124), (374.772, 92.553), (366.587, 92.275),
             (386.143, 99.964), (391.771, 126.886), (343.187, 126.751),
             (426.612, 130.849), (320.986, 158.331), (435.589, 103.472),
             (323.489, 126.720), (378.471, 205.658), (348.460, 205.152),
             (379.498, 264.710), (347.838, 265.179), (387.988, 323.931),
             (351.149, 322.808)),
        )),
    },
    {
        "bbox": (313.476, 79.269, 454.644, 339.306),
        "confidence": 0.26635652780532837,
        "keypoints": dict(zip(
            (name for name in COCO_KEYPOINT_NAMES if name != "right_ear"),
            ((368.220, 96.199), (375.167, 92.589), (367.035, 92.393),
             (386.587, 99.987), (393.427, 126.493), (343.814, 126.780),
             (429.272, 128.770), (320.359, 157.871), (438.315, 102.407),
             (323.240, 126.422), (378.443, 204.927), (347.663, 204.279),
             (379.596, 264.421), (348.061, 264.987), (388.899, 323.579),
             (351.109, 322.713)),
        )),
    },
)


def yolo_result(people):
    keypoint_xy = []
    keypoint_conf = []
    boxes = []
    box_conf = []
    for person in people:
        points = []
        confidences = []
        for name in COCO_KEYPOINT_NAMES:
            point = person["keypoints"].get(name)
            points.append(list(point) if point is not None else [0.0, 0.0])
            confidences.append(0.9 if point is not None else 0.0)
        keypoint_xy.append(points)
        keypoint_conf.append(confidences)
        boxes.append(list(person["bbox"]))
        box_conf.append(person["confidence"])
    return SimpleNamespace(
        keypoints=SimpleNamespace(xy=keypoint_xy, conf=keypoint_conf),
        boxes=SimpleNamespace(xyxy=boxes, conf=box_conf),
    )


def test_yolo_detection_converter_deduplicates_captured_pullup_pair():
    metadata = BasicVideoMetadata(fps=24.0, frame_count=61, width=854, height=480)
    detections = detections_from_yolo_result(
        yolo_result(list(reversed(PULLUP_DETECTION_PAIR))),
        metadata=metadata,
        min_keypoint_confidence=0.35,
    )

    assert len(detections) == 1
    assert detections[0].confidence == PULLUP_DETECTION_PAIR[0]["confidence"]
    assert significant_person_count(
        PoseSample(time_seconds=0.5005, detections=detections), metadata=metadata
    ) == 1


def test_yolo_detection_converter_deduplicates_cached_fade_duplicate_but_keeps_spotter():
    metadata = BasicVideoMetadata(fps=25.0, frame_count=56, width=640, height=360)
    detections = detections_from_yolo_result(
        yolo_result(OHP_FADE_DUPLICATE_PAIR),
        metadata=metadata,
        min_keypoint_confidence=0.35,
    )

    assert len(detections) == 1
    assert detections[0].confidence == OHP_FADE_DUPLICATE_PAIR[0]["confidence"]

    # The wider box still contains the same person, but different keypoints
    # identify a nearby spotter as a separate detection.
    spotter = {
        **OHP_FADE_DUPLICATE_PAIR[1],
        "keypoints": {
            name: (x + 20.0, y + 4.0)
            for name, (x, y) in OHP_FADE_DUPLICATE_PAIR[1]["keypoints"].items()
        },
    }
    detections = detections_from_yolo_result(
        yolo_result([OHP_FADE_DUPLICATE_PAIR[0], spotter]),
        metadata=metadata,
        min_keypoint_confidence=0.35,
    )
    assert len(detections) == 2


def test_yolo_detection_converter_keeps_distinct_people_with_overlapping_boxes():
    metadata = BasicVideoMetadata(fps=24.0, frame_count=61, width=854, height=480)
    first = dict(PULLUP_DETECTION_PAIR[0])
    second = {
        **first,
        "confidence": 0.8,
        "keypoints": {
            name: (x + 55.0, y + 10.0)
            for name, (x, y) in first["keypoints"].items()
        },
    }
    detections = detections_from_yolo_result(
        yolo_result([first, second]), metadata=metadata, min_keypoint_confidence=0.35
    )

    assert len(detections) == 2
    assert significant_person_count(
        PoseSample(time_seconds=0.5, detections=detections), metadata=metadata
    ) == 2


@pytest.mark.parametrize("keypoint_count", [5, 0])
def test_yolo_detection_converter_counts_person_boxes_with_sparse_or_missing_keypoints(keypoint_count):
    metadata = BasicVideoMetadata(fps=2.0, frame_count=8, width=854, height=480)
    main_person = PULLUP_DETECTION_PAIR[0]
    partial_person = {
        "bbox": (70.0, 80.0, 200.0, 330.0),
        "confidence": 0.90,
        "keypoints": dict(list(main_person["keypoints"].items())[:keypoint_count]),
    }
    detections = detections_from_yolo_result(
        yolo_result([main_person, partial_person]),
        metadata=metadata,
        min_keypoint_confidence=0.35,
    )
    samples = [PoseSample(time_seconds=index / 2.0, detections=detections) for index in range(8)]
    metrics = score_pose_window(
        samples,
        metadata=metadata,
        settings=PosePrefilterSettings(window_seconds=4.0, overlap_seconds=1.0),
    )

    assert [len(detection.keypoints) for detection in detections] == [12, keypoint_count]
    assert significant_person_count(samples[0], metadata=metadata) == 2
    assert metrics["maxSignificantPersonCount"] == 2
    assert metrics["multiPersonRatio"] == pytest.approx(1.0)
    assert "multiple_people" in metrics["blockingIssues"]


def test_yolo_detection_converter_keeps_person_box_smaller_than_one_percent_frame():
    metadata = BasicVideoMetadata(fps=24.0, frame_count=61, width=854, height=480)
    main_person = PULLUP_DETECTION_PAIR[0]
    background_person = {
        "bbox": (95.0, 140.0, 135.0, 240.0),
        "confidence": 0.82,
        "keypoints": {
            name: ((x - 563.5) * 0.35 + 100.0, (y - 50.0) * 0.35 + 145.0)
            for name, (x, y) in main_person["keypoints"].items()
        },
    }
    detections = detections_from_yolo_result(
        yolo_result([main_person, background_person]),
        metadata=metadata,
        min_keypoint_confidence=0.35,
    )

    assert len(detections) == 2
    assert (40.0 * 100.0) < metadata.width * metadata.height * 0.01
    assert significant_person_count(
        PoseSample(time_seconds=0.5, detections=detections), metadata=metadata
    ) == 2
