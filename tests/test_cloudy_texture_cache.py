import pytest
from character.texture_cache import BoundedTextureCache


def test_churn_keeps_every_texture_of_current_frame_and_stays_bounded():
    freed = []
    sizes = {str(i): 4 for i in range(40)}
    cache = BoundedTextureCache(12, lambda key: (key, sizes[key]), freed.append)
    for i in range(38):
        frame = {str(i): 4, str(i + 1): 4, str(i + 2): 4}
        cache.prepare(frame)
        assert {cache.get(key) for key in frame} == set(frame)
        assert cache.bytes <= 12
    assert cache.evictions == 37
    assert cache.peak_bytes == 12
    cache.clear()
    assert cache.bytes == 0
    assert len(freed) == 40


def test_oversized_frame_does_not_evict_existing_resources():
    freed = []
    cache = BoundedTextureCache(8, lambda key: (key, 4), freed.append)
    cache.prepare({"a": 4, "b": 4})
    with pytest.raises(MemoryError):
        cache.prepare({"a": 4, "b": 4, "c": 4})
    assert cache.get("a") == "a" and cache.get("b") == "b"
    assert not freed


def test_same_resource_is_uploaded_once_until_evicted():
    cache = BoundedTextureCache(8, lambda key: (key, 4), lambda _: None)
    cache.prepare({"shared": 4})
    for _ in range(20):
        cache.prepare({"shared": 4})
    assert cache.uploads == 1
    cache.prepare({"b": 4, "c": 4})
    cache.prepare({"shared": 4})
    assert cache.uploads == 4


def test_dimensions_mismatch_destroys_bad_upload_without_overflow():
    freed = []
    cache = BoundedTextureCache(8, lambda key: (key, 20), freed.append)
    with pytest.raises(ValueError):
        cache.prepare({"a": 4})
    assert cache.bytes == 0 and freed == ["a"]
