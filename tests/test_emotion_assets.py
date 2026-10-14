from character.emotion_assets import resolve_animation_asset


def test_existing_fear_asset_is_preserved(tmp_path):
    (tmp_path / "fear").mkdir()
    (tmp_path / "scared").mkdir()
    assert resolve_animation_asset(tmp_path, "scared") == "fear"


def test_develop_scared_asset_works_without_fear(tmp_path):
    (tmp_path / "scared").mkdir()
    assert resolve_animation_asset(tmp_path, "scared") == "scared"


def test_missing_emotion_assets_fall_back_to_idle(tmp_path):
    assert resolve_animation_asset(tmp_path, "scared") == "idle"
    assert resolve_animation_asset(tmp_path, "sad") == "idle"


def test_existing_sad_asset_is_used(tmp_path):
    (tmp_path / "sad").mkdir()
    assert resolve_animation_asset(tmp_path, "sad") == "sad"


def test_other_animations_are_unchanged(tmp_path):
    for action in ("happy", "angry", "idle", "walk_scared", "walk_sad"):
        assert resolve_animation_asset(tmp_path, action) == action
