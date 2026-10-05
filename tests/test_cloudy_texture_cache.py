import pytest
from character.texture_cache import BoundedTextureCache
from character.cloudy_rig_view import _texture_storage_bytes


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


def test_painted_tear_residency_counts_all_ten_mip_levels():
    part = {"size": [256, 512], "bbox": [0, 0, 40, 42], "drawnTearFrame": True}
    # RGBA8 levels 256x512 through 1x1 total 699052 bytes. Using only the
    # level-zero 524288 bytes would understate actual GPU residency by 33%.
    assert _texture_storage_bytes(part) == 699052
    part["drawnTearFrame"] = False
    assert _texture_storage_bytes(part) == 524288


def test_existing_non_square_character_art_keeps_single_level_residency():
    assert _texture_storage_bytes({"bbox": [12, 7, 223, 334]}) == 223 * 334 * 4
    assert _texture_storage_bytes({"size": [1, 1], "bbox": [0, 0, 1, 1],
                                   "drawnTearFrame": True}) == 4


def test_mip_chain_bytes_are_respected_before_tear_uploads():
    size = 699052
    loaded = []
    cache = BoundedTextureCache(size * 2 - 1,
                               lambda key: (loaded.append(key) or key, size), lambda _: None)
    with pytest.raises(MemoryError):
        cache.prepare({"tear-a": size, "tear-b": size})
    assert not loaded
    assert cache.bytes == 0
