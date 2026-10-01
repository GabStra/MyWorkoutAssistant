from exercise_motion_pkg.review_questions import answer_question


def test_shared_question_reuses_equal_images_and_isolates_identity(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"identical image")
    second.write_bytes(first.read_bytes())
    calls = []

    def operation():
        calls.append(True)
        return "answer", {"passed": True}

    def ask(frame, identity):
        return answer_question(directory=tmp_path / "cache", name="motion",
            prompt="same prompt", frames=[frame], max_tokens=256,
            identity=identity, operation=operation,
            reusable=lambda parsed: parsed == {"passed": True})

    assert ask(first, "model-policy-a") == ask(second, "model-policy-a")
    assert len(calls) == 1
    ask(second, "model-policy-b")
    assert len(calls) == 2
    # Supporting evidence corruption invalidates the persisted answer even
    # when a different copy still supplies the original image bytes.
    first.write_bytes(b"changed")
    ask(second, "model-policy-a")
    assert len(calls) == 3


def test_uncertain_question_is_not_shared(tmp_path):
    frame = tmp_path / "image.png"
    frame.write_bytes(b"image")
    calls = []

    def operation():
        calls.append(True)
        return "uncertain", {"passed": None}

    for _ in range(2):
        answer_question(directory=tmp_path / "cache", name="motion", prompt="prompt",
            frames=[frame], max_tokens=256, identity="model-policy",
            operation=operation, reusable=lambda parsed: parsed.get("passed") is True)
    assert len(calls) == 2


def test_shared_question_preserves_image_order_and_model_policy_boundaries(tmp_path):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"first image")
    second.write_bytes(b"second image")
    calls = []

    def operation():
        calls.append(True)
        return "answer", {"passed": True}

    def ask(frames, model, policy):
        return answer_question(directory=tmp_path / "cache", name="motion",
            prompt="prompt", frames=frames, max_tokens=256,
            identity={"model": model, "policy": policy}, operation=operation,
            reusable=lambda parsed: parsed.get("passed") is True)

    ask([first, second], "model-a", "policy-a")
    ask([first, second], "model-a", "policy-a")
    assert len(calls) == 1
    ask([second, first], "model-a", "policy-a")
    ask([first, second], "model-b", "policy-a")
    ask([first, second], "model-a", "policy-b")
    assert len(calls) == 4
