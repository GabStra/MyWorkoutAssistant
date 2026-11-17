from exercise_motion_pkg.review_questions import answer_question


def test_structured_response_policy_invalidates_cached_answers(tmp_path, monkeypatch):
    from exercise_motion_pkg import review_questions
    from exercise_motion_pkg import bake_and_rank as bake
    from types import SimpleNamespace

    frame = tmp_path / 'source.png'
    frame.write_bytes(b'fixed image bytes')
    calls = []
    def operation():
        calls.append(True)
        return 'answer', {'passed': True}
    def ask():
        return answer_question(directory=tmp_path / 'cache', name='contact', prompt='same prompt',
            frames=[frame], max_tokens=128, identity={'model': 'same model'},
            operation=operation, reusable=lambda value: value['passed'])
    identity = bake.source_review_model_identity(SimpleNamespace(llama_cpp_model='same model'))
    ask()
    ask()
    assert len(calls) == 1
    monkeypatch.setattr(review_questions, 'STRUCTURED_RESPONSE_PROMPT_POLICY_VERSION',
                        review_questions.STRUCTURED_RESPONSE_PROMPT_POLICY_VERSION + 1)
    ask()
    assert len(calls) == 2
    assert identity != bake.source_review_model_identity(SimpleNamespace(llama_cpp_model='same model'))


def test_source_cut_batch_reuses_reviews_after_candidate_rank_changes(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from exercise_motion_pkg import bake_and_rank as bake

    class Session:
        settings = SimpleNamespace(llama_cpp_model='controlled-model')
        calls = 0

        def caption_images(self, **kwargs):
            self.calls += 1
            return json.dumps({'candidates': [{'id': 'A', 'confidence': .9},
                                             {'id': 'B', 'confidence': .8}]})

    session = Session()
    measured_reviews = []
    def review_measured_action(*, candidate, ranking, **kwargs):
        measured_reviews.append(candidate.candidate_id)
        return ranking, []
    monkeypatch.setattr(bake, 'review_source_cut_measured_action', review_measured_action)
    monkeypatch.setattr(bake, 'review_source_cut_boundaries',
                        lambda *, ranking, **kwargs: (ranking, []))
    monkeypatch.setattr(bake, 'write_cut_candidate_vlm_review_debug', lambda **kwargs: None)

    def review(rank):
        folder = tmp_path / f'rank-{rank}'
        folder.mkdir()
        candidates = []
        for index, identity in enumerate(('A', 'B')):
            frame = folder / f'{identity}.jpg'
            frame.write_bytes(identity.encode())
            candidates.append(bake.SourceCutCandidate(
                candidate_id=identity, window=bake.DetectionWindow(index, index, index + 2),
                frame_paths=[frame], question_cache_dir=tmp_path / 'source-question-cache'))
        return bake.rank_cut_candidates_with_caption_images(
            candidates=candidates, caption_images=session.caption_images,
            prompt_builder=lambda candidate: candidate.candidate_id,
            batch_prompt_builder=lambda batch: 'review A and B', batch_size=2,
            parser=lambda raw, candidate: bake.LoopRanking(
                score=json.loads(raw)['candidates'][0]['confidence'], reasons=[], payload={}))

    first, second = review(1), review(2)
    assert session.calls == 1
    # Reusing the provisional batch answer never bypasses endpoint admission.
    assert measured_reviews == ['A', 'B', 'A', 'B']
    assert [ranking.score for ranking in first.rankings] == [ranking.score for ranking in second.rankings] == [.9, .8]


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
