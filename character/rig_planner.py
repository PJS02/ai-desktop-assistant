"""Execute the original Cloudy rig math in Qt without a browser or image decode.

Only in-memory syntax adaptation is applied to the checked-in JavaScript.
Texture residency belongs to the view, independently of this planner's registry.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from PyQt6.QtCore import QCoreApplication, QObject, QThread
from PyQt6.QtQml import QJSEngine, QJSValue


DEFAULT_RIG_ROOT = Path(__file__).resolve().parents[1] / "assets_cloudy_rig_v4" / "directional_v5"
RIG_SOURCES = (
    "textures/parts.js", "motion.js", "limb-girth.js", "emotion-fx.js",
    "side-wave-skinning.js", "side-cuff.js", "side-cuff-roll.js",
    "side-cuff-attachment.js", "side-cuff-motion.js", "side-cuff-art.js",
    "side-cuff-fit.js", "renderer.js",
)


def _closing_brace(source: str, opening: int) -> int:
    """Find a source block boundary, ignoring quotes and comments in this rig."""
    depth, index, quote = 0, opening, None
    while index < len(source):
        char = source[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline < 0 else newline
            continue
        elif source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                raise ValueError("Unclosed JavaScript comment")
            index = end + 2
            continue
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ValueError("Unclosed JavaScript source block")


def qt_compatible_source(source: str, filename: str) -> str:
    """Adapt the specific ES2018 constructs absent from Qt's ES2016 engine.

    This is deliberately scoped to the original rig's leading object spreads
    and its unused browser-only async loader; it is not a general JS compiler.
    """
    if filename == "renderer.js":
        loader = re.search(r"\basync\s+load\s*\(\s*\)\s*\{", source)
        if loader:
            end = _closing_brace(source, source.index("{", loader.start()))
            source = source[:loader.start()] + source[end + 1:]
    # The original view metadata uses one trailing spread after the yaw field.
    source = re.sub(r"\{\s*yaw\s*,\s*\.\.\.\s*rig\s*\}",
                    " Object.assign({yaw:yaw},rig)", source)
    leading = re.compile(r"\{\s*\.\.\.\s*([A-Za-z_$][\w$]*(?:\.[\w$]+)*)\s*([,}])")
    while True:
        match = leading.search(source)
        if not match:
            break
        end = _closing_brace(source, match.start())
        expression = match.group(1)
        tail = source[match.end():end].strip() if match.group(2) == "," else ""
        replacement = f" Object.assign({{}},{expression}" + (f",{{{tail}}}" if tail else "") + ")"
        source = source[:match.start()] + replacement + source[end + 1:]
    if re.search(r"\{\s*\.\.\.", source):
        raise ValueError(f"Unsupported object-spread form in {filename}")
    return source


class RigPlanner:
    """GUI-thread planner returning original Float32 meshes and draw arguments.

    A QCoreApplication/QApplication must already exist. plan() accepts a dict
    with action/time/yaw, optional emotion/speaking/speechTime/walkAmount/blink,
    emotionEffects/companion and an explicit externalPhysics flag.
    """

    def __init__(self, rig_root: str | Path | None = None, parent: QObject | None = None):
        if QCoreApplication.instance() is None:
            raise RuntimeError("Create a Qt application before constructing RigPlanner")
        self.rig_root = Path(rig_root) if rig_root is not None else DEFAULT_RIG_ROOT
        self.engine = QJSEngine(parent)
        self.source_hashes: dict[str, str] = {}
        self._evaluate("var window=this;var globalThis=this;"
                       "if(!Object.fromEntries)Object.fromEntries=function(items){var out={};"
                       "items.forEach(function(pair){out[pair[0]]=pair[1];});return out;};"
                       "if(!Array.prototype.at)Object.defineProperty(Array.prototype,'at',{"
                       "value:function(i){i=Math.trunc(i)||0;return this[i<0?this.length+i:i];},"
                       "configurable:true,writable:true});", "rig-bootstrap")
        for relative in RIG_SOURCES:
            self._load(self.rig_root / relative, relative)
        self._load(Path(__file__).with_name("rig_bridge.js"), "rig_bridge.js")
        bridge = self.engine.globalObject().property("CloudyRigBridge")
        self._plan = bridge.property("plan")
        self._sample = bridge.property("sample")
        self._effect_recipes = bridge.property("effectRecipes")
        self._effect_metadata = bridge.property("effectMetadata")
        self._metadata = bridge.property("textureMetadata")
        self.parts = self.engine.globalObject().property("CLOUDY_PARTS").toVariant()

    def _assert_thread(self) -> None:
        if self.engine.thread() != QThread.currentThread():
            raise RuntimeError("RigPlanner must be called on its owning Qt thread")

    @staticmethod
    def _check(result: QJSValue, label: str) -> QJSValue:
        if result.isError():
            line = result.property("lineNumber").toInt()
            raise RuntimeError(f"{label}:{line}: {result.toString()}")
        return result

    def _evaluate(self, source: str, label: str) -> QJSValue:
        return self._check(self.engine.evaluate(source, label), label)

    def _load(self, path: Path, label: str) -> None:
        raw = path.read_bytes()
        self.source_hashes[label] = hashlib.sha256(raw).hexdigest()
        self._evaluate(qt_compatible_source(raw.decode("utf-8-sig"), label), label)

    def _state(self, state: dict) -> QJSValue:
        # Parse data, rather than splice values into JavaScript source code.
        encoded = QJSValue(json.dumps(state, ensure_ascii=False, allow_nan=False))
        parser = self.engine.globalObject().property("JSON").property("parse")
        return self._check(parser.call([encoded]), "state")

    def plan(self, state: dict | None = None) -> dict:
        self._assert_thread()
        return self._check(self._plan.call([self._state(state or {})]), "plan").toVariant()

    def sample(self, state: dict | None = None) -> dict:
        self._assert_thread()
        return self._check(self._sample.call([self._state(state or {})]), "sample").toVariant()

    def effect_recipes(self) -> dict:
        self._assert_thread()
        return self._check(self._effect_recipes.call(), "effect recipes").toVariant()

    def effect_metadata(self) -> dict:
        self._assert_thread()
        return self._check(self._effect_metadata.call(), "effect metadata").toVariant()

    def texture_metadata(self, name: str) -> dict | None:
        self._assert_thread()
        return self._check(self._metadata.call([QJSValue(name)]), "texture metadata").toVariant()
