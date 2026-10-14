"""A bounded LRU for resident textures, independent of asset availability."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Any


@dataclass
class _Entry:
    resource: Any
    bytes: int


class BoundedTextureCache:
    """Keep the current frame intact while evicting older, unused textures.

    The caller supplies exact RGBA sizes before uploading. A frame that cannot
    fit fails explicitly; it must never change the rig's texture selection.
    Resource creation/destruction must run with the owner's GL context current.
    """

    def __init__(self, budget_bytes: int, loader: Callable[[str], tuple[Any, int]],
                 destroy: Callable[[Any], None]):
        if budget_bytes <= 0:
            raise ValueError("Texture budget must be positive")
        self.budget_bytes = int(budget_bytes)
        self._loader, self._destroy = loader, destroy
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._pinned: set[str] = set()
        self.bytes = self.peak_bytes = self.uploads = self.evictions = 0

    def prepare(self, sizes: dict[str, int]) -> None:
        if any(size <= 0 for size in sizes.values()):
            raise ValueError("Invalid texture dimensions")
        if sum(sizes.values()) > self.budget_bytes:
            raise MemoryError("The current frame exceeds the texture budget")
        self._pinned = set(sizes)
        for key, size in sizes.items():
            if key in self._entries:
                self._entries.move_to_end(key)
                continue
            self._make_room(size)
            resource, actual_bytes = self._loader(key)
            if actual_bytes != size:
                self._destroy(resource)
                raise ValueError(f"Texture dimensions changed: {key}")
            self._entries[key] = _Entry(resource, actual_bytes)
            self.bytes += actual_bytes
            self.uploads += 1
            self.peak_bytes = max(self.peak_bytes, self.bytes)

    def _make_room(self, additional: int) -> None:
        while self.bytes + additional > self.budget_bytes:
            victim = next((key for key in self._entries if key not in self._pinned), None)
            if victim is None:
                raise MemoryError("Unable to free textures without breaking the frame")
            entry = self._entries.pop(victim)
            self._destroy(entry.resource)
            self.bytes -= entry.bytes
            self.evictions += 1

    def get(self, key: str):
        entry = self._entries[key]
        self._entries.move_to_end(key)
        return entry.resource

    def clear(self) -> None:
        for entry in self._entries.values():
            self._destroy(entry.resource)
        self._entries.clear()
        self._pinned.clear()
        self.bytes = 0

    def stats(self) -> dict:
        return {"texture_budget_bytes": self.budget_bytes,
                "texture_bytes": self.bytes, "peak_texture_bytes": self.peak_bytes,
                "resident_textures": len(self._entries),
                "texture_uploads": self.uploads, "texture_evictions": self.evictions}
