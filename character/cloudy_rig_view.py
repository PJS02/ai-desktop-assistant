"""Native Qt drawing of the original Cloudy v22 rig with bounded residency.

No animation combinations are baked and no browser process is embedded. The
original JavaScript computes every vertex and material; Qt submits those same
Float32 vertices to the original fragment calculation.
"""
from __future__ import annotations

from array import array
from pathlib import Path
import time
import traceback
from app_logging import log_event
from PIL import Image

from PyQt6.QtCore import Qt, QTimer, QRectF, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QPixmap, QSurfaceFormat, QVector2D, QVector3D
from PyQt6.QtOpenGL import (QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram,
                           QOpenGLTexture, QOpenGLVersionFunctionsFactory,
                           QOpenGLVersionProfile, QOpenGLFramebufferObject)
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

from .rig_v8 import NodeRigPlanner
from .texture_cache import BoundedTextureCache


_VERTEX = """attribute vec2 pos;attribute vec2 uv;uniform vec2 viewport;
varying vec2 tex;void main(){gl_Position=vec4(pos.x/viewport.x*2.0-1.0,
1.0-pos.y/viewport.y*2.0,0.0,1.0);tex=uv;}"""
_FRAGMENT = """uniform sampler2D image;uniform sampler2D replacement;
uniform sampler2D bodyNegativeLower;uniform sampler2D bodyNegativeUpper;
uniform float replacementAmount;uniform float bodyBlendEnabled;
uniform float bodyPositiveWeight;uniform float sourceClipEnabled;
uniform vec3 sourceClipAxis;uniform vec2 sourceClipBounds;uniform float opacity;
varying vec2 tex;void main(){if(sourceClipEnabled>0.5){float axial=
dot(tex,sourceClipAxis.xy)+sourceClipAxis.z;if(axial<sourceClipBounds.x||
axial>sourceClipBounds.y)discard;}vec4 base=texture2D(image,tex);
if(bodyBlendEnabled>0.5){vec4 positive=base+(texture2D(replacement,tex)-base)*
replacementAmount;vec4 negativeBase=texture2D(bodyNegativeLower,tex);
vec4 negative=negativeBase+(texture2D(bodyNegativeUpper,tex)-negativeBase)*
replacementAmount;gl_FragColor=(negative+(positive-negative)*bodyPositiveWeight)*
opacity;}else{gl_FragColor=(base+(texture2D(replacement,tex)-base)*
replacementAmount)*opacity;}}"""

_GL_COLOR_BUFFER_BIT = 0x4000
_GL_BLEND, _GL_DEPTH_TEST, _GL_CULL_FACE = 0x0BE2, 0x0B71, 0x0B44
_GL_ONE, _GL_ONE_MINUS_SRC_ALPHA = 1, 0x0303
_GL_FLOAT, _GL_TRIANGLES = 0x1406, 0x0004
_DURATIONS = {"wave": 4.6, "jump": 2.4, "land": 1.6}
_ACTIONS = {"idle", "walk", "run", "wave", "thinking", "sleep", "hovering", "jump", "fall", "land"}


def _texture_storage_bytes(part):
    width, height = map(int, part.get("size", part["bbox"][2:]))
    total = width * height * 4
    if part.get("drawnTearFrame"):
        while width > 1 or height > 1:
            width, height = max(1, width // 2), max(1, height // 2)
            total += width * height * 4
    return total


class CloudyRigView(QOpenGLWidget):
    animation_finished = pyqtSignal()
    pose_bounds_changed = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, parent=None, *, rig_root: str | Path | None = None,
                 texture_budget_bytes: int = 32 * 1024 * 1024):
        super().__init__(parent)
        fmt = QSurfaceFormat()
        fmt.setVersion(2, 0)
        fmt.setAlphaBufferSize(8)
        fmt.setSamples(4)
        self.setFormat(fmt)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAutoFillBackground(False)
        self.planner = NodeRigPlanner(rig_root, self)
        self.rig_root = self.planner.rig_root.resolve()
        self._recipes = self.planner.effect_recipes()
        self._parts = dict(self.planner.parts)
        self._parts.update(self.planner.effect_metadata())
        self._identities, self._identity_metadata = {}, {}
        for name, part in self._parts.items():
            if part.get("file"):
                file = (self.rig_root / part["file"].split("?")[0]).resolve()
                if not file.is_relative_to(self.rig_root):
                    raise ValueError(f"Texture outside the rig pack: {name}")
                identity = str(file)
            else:
                identity = "effect:" + name
            self._identities[name] = identity
            self._identity_metadata[identity] = (name, part)
        self._cache = BoundedTextureCache(texture_budget_bytes, self._load_texture,
                                         lambda texture: texture.destroy())
        self._program = self._buffer = self._gl = None
        self._buffer_capacity = 0
        self._error = None
        self._released = False
        self._action, self._emotion, self._yaw = "idle", "neutral", 0
        self._loop = True
        self._external_physics = False
        self._jump_active = False
        self._jump_phase = None
        self._authored_jump = False
        self._speaking = False
        self._speech_start = time.perf_counter()
        self._started = time.perf_counter()
        self._offset = 0.0
        self._paused = False
        self._finished = False
        self._fixed_state = None
        self._last_plan = None
        self._last_paint_time = time.perf_counter()
        self._overlay = QPixmap()
        self._debug_painter = None
        self._diagnostic_fbo = None
        self._character_pixel_rect = None
        self._frames = 0
        self._plan_ms = self._draw_ms = self._max_plan_ms = 0.0
        self._peak_decode_bytes = 0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def set_action(self, action: str, loop: bool = True):
        action = action if action in _ACTIONS else "idle"
        if action not in {"jump", "fall", "land"}:
            self._jump_phase = None
            self._authored_jump = False
        if action == self._action and bool(loop) == self._loop and not self._finished:
            return
        self._action, self._loop = action, bool(loop)
        self._offset = 0.0
        self._started = time.perf_counter()
        self._finished = False
        self._fixed_state = None
        self.update()

    def set_emotion(self, emotion: str):
        self._emotion = str(emotion)
        self.update()

    def set_yaw(self, yaw: float):
        self._yaw = max(-65, min(65, float(yaw)))
        self.update()

    def set_speaking(self, speaking: bool):
        speaking = bool(speaking)
        if speaking and not self._speaking:
            self._speech_start = time.perf_counter()
        self._speaking = speaking
        self.update()

    def set_external_physics(self, enabled: bool):
        self._external_physics = bool(enabled)

    def set_jump_active(self, active: bool):
        """Distinguish a controlled jump from being dropped after dragging."""
        self._jump_active = bool(active)

    def set_physics_jump_phase(self, phase, *, landing=False):
        """Sample the authored jump from host flight progress instead of a loop."""
        self._jump_phase = None if phase is None else max(.15, min(.70, float(phase)))
        self._authored_jump = self._jump_phase is not None or bool(landing)
        self.update()

    def set_overlay_pixmap(self, pixmap: QPixmap):
        self._overlay = pixmap
        self.update()

    def set_debug_painter(self, callback):
        self._debug_painter = callback
        self._character_pixel_rect = None
        self.update()

    def character_rect(self):
        """Map current character meshes to the same viewport used by OpenGL."""
        if self._character_pixel_rect is not None:
            return QRectF(self._character_pixel_rect)
        if self._last_plan is None or self._last_plan.get('characterBounds') is None:
            return QRectF(self.rect())
        dpr = self.devicePixelRatioF()
        width, height = round(self.width() * dpr), round(self.height() * dpr)
        vw, vh = min(width, round(height * 2 / 3)), min(height, round(width * 3 / 2))
        sx, sy = vw / dpr / 360, vh / dpr / 540
        ox, oy = (width - vw) // 2 / dpr, (height - vh) // 2 / dpr
        left, top, right, bottom = self._last_plan['characterBounds']
        return QRectF(ox + left * sx, oy + top * sy,
                      (right - left) * sx, (bottom - top) * sy).intersected(QRectF(self.rect()))

    def _draw_commands(self, commands):
        gl, program = self._gl, self._program
        for command in commands:
            for unit, name in enumerate(('base', 'replacement', 'bodyNegativeLower', 'bodyNegativeUpper')):
                self._cache.get(self._identities[command[name]]).bind(unit)
            for name in ('replacementAmount', 'bodyBlendEnabled', 'bodyPositiveWeight', 'opacity', 'sourceClipEnabled'):
                program.setUniformValue(self._locations[name], float(command[name]))
            program.setUniformValue(self._locations['sourceClipAxis'], QVector3D(*command['sourceClipAxis']))
            program.setUniformValue(self._locations['sourceClipBounds'], QVector2D(*command['sourceClipBounds']))
            data = command.get('vertexBytes')
            if data is None:
                data = array('f', command['vertices']).tobytes()
            if len(data) > self._buffer_capacity:
                self._buffer_capacity = max(16384, len(data))
                self._buffer.allocate(self._buffer_capacity)
            self._buffer.write(0, data, len(data))
            program.setAttributeBuffer(self._pos, _GL_FLOAT, 0, 2, 16)
            program.setAttributeBuffer(self._uv, _GL_FLOAT, 8, 2, 16)
            gl.glDrawArrays(_GL_TRIANGLES, 0, command['vertexCount'])

    def _measure_character_pixels(self, plan, width, height, dpr):
        """A body-only pass keeps symbols, debug text and held items out of bounds.

        Only enabled diagnostics need this pass. Its single framebuffer is reused
        until resize, and shares the resident textures and current pose meshes.
        """
        if (self._diagnostic_fbo is None
                or self._diagnostic_fbo.width() != width or self._diagnostic_fbo.height() != height):
            self._diagnostic_fbo = QOpenGLFramebufferObject(width, height)
        if not self._diagnostic_fbo.bind():
            raise RuntimeError('Could not create the character diagnostic framebuffer')
        self._gl.glClear(_GL_COLOR_BUFFER_BIT)
        self._draw_commands(c for c in plan['commands'] if c['characterPart'])
        image = self._diagnostic_fbo.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        pixels = image.constBits().asstring(image.sizeInBytes())
        alpha = Image.frombytes('RGBA', (width, height), pixels).getchannel('A')
        bounds = alpha.getbbox()
        if bounds is not None:
            left, top, right, bottom = bounds
            self._character_pixel_rect = QRectF(left / dpr, top / dpr,
                                                (right - left) / dpr, (bottom - top) / dpr)
        QOpenGLFramebufferObject.bindDefault()

    def _time(self) -> float:
        return self._offset if self._paused else self._offset + time.perf_counter() - self._started

    def pause(self):
        if not self._paused:
            self._offset = self._time()
            self._paused = True
        self._timer.stop()

    def resume(self):
        if self._released:
            return
        if self._paused:
            self._started = time.perf_counter()
            self._paused = False
        self._timer.start(33)
        self.update()

    def _tick(self):
        if self._released or self._error:
            return
        duration = _DURATIONS.get(self._action)
        if not self._loop and duration and self._time() >= duration:
            # Clamp just before the periodic source pose wraps back to its start.
            self._offset = duration - 0.000001
            self._paused = True
            self._timer.stop()
            self._finished = True
            self.update()
            self.animation_finished.emit()
        else:
            self.update()

    def set_validation_state(self, state: dict | None):
        """Deterministic capture of the real renderer, without changing app state."""
        self.pause()
        self._fixed_state = dict(state) if state is not None else None
        self.update()

    def _state(self):
        if self._fixed_state is not None:
            return self._fixed_state
        now = time.perf_counter()
        dt = now - self._last_paint_time
        self._last_paint_time = now
        return {"action": self._action, "emotion": self._emotion, "yaw": self._yaw,
                "time": self._time(), "externalPhysics": self._external_physics,
                "jumpActive": self._jump_active,
                "jumpPhase": self._jump_phase, "authoredJump": self._authored_jump,
                "speaking": self._speaking,
                "speechTime": now - self._speech_start, "smooth": True, "dt": dt}

    def initializeGL(self):
        try:
            self._buffer_capacity = 0
            profile = QOpenGLVersionProfile()
            profile.setVersion(2, 0)
            self._gl = QOpenGLVersionFunctionsFactory.get(profile, self.context())
            if self._gl is None or not self._gl.initializeOpenGLFunctions():
                raise RuntimeError("OpenGL 2.0 functions are unavailable")
            self._program = QOpenGLShaderProgram(self)
            if not self._program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, _VERTEX):
                raise RuntimeError(self._program.log())
            if not self._program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, _FRAGMENT):
                raise RuntimeError(self._program.log())
            if not self._program.link():
                raise RuntimeError(self._program.log())
            self._buffer = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            if not self._buffer.create():
                raise RuntimeError("Could not create the rig vertex buffer")
            self._buffer.setUsagePattern(QOpenGLBuffer.UsagePattern.DynamicDraw)
            self._locations = {name: self._program.uniformLocation(name) for name in
                ("viewport", "image", "replacement", "bodyNegativeLower", "bodyNegativeUpper",
                 "replacementAmount", "bodyBlendEnabled", "bodyPositiveWeight", "opacity",
                 "sourceClipEnabled", "sourceClipAxis", "sourceClipBounds")}
            self._pos = self._program.attributeLocation("pos")
            self._uv = self._program.attributeLocation("uv")
            self.context().aboutToBeDestroyed.connect(self._cleanup_gl)
            log_event('renderer.opengl.ready', 'OpenGL 렌더 준비가 끝났습니다.',
                      trace_id=getattr(self.planner, 'log_trace_id', None), rig_root=str(self.rig_root),
                      device_pixel_ratio=self.devicePixelRatioF(), **self._diagnostic_snapshot())
        except Exception as exc:
            self._fail(exc)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(300, self._check_visible_context)

    def _check_visible_context(self):
        if not self._released and self.isVisible() and not self.isValid():
            self._fail(RuntimeError("Could not create the native OpenGL drawing context"))

    def _fail(self, exc):
        if self._error is None:
            self._error = str(exc)
            self._timer.stop()
            log_event('renderer.opengl.failed', 'OpenGL 캐릭터 렌더에 실패했습니다.',
                      category='오류', level='ERROR',
                      trace_id=getattr(self.planner, 'log_trace_id', None),
                      error=self._error, traceback=traceback.format_exc(),
                      rig_root=str(self.rig_root), **self._diagnostic_snapshot(include_state=True))
            self.failed.emit(self._error)

    def _diagnostic_snapshot(self, *, include_state=False):
        """Diagnostics must not block fallback or native resource cleanup."""
        snapshot = {}
        try:
            snapshot['stats'] = self.stats()
        except Exception as exc:
            snapshot['stats_error'] = str(exc)
        if include_state:
            try:
                snapshot['state'] = self._state()
            except Exception as exc:
                snapshot['state_error'] = str(exc)
        return snapshot

    def _load_texture(self, identity: str):
        name, part = self._identity_metadata[identity]
        if identity.startswith("effect:"):
            from .rig_fx import build_effect
            recipe = self._recipes[name]
            # Only masked effects need a head decode, which is discarded here.
            head_name = next((c.get("head") or c.get("image") for c in recipe["commands"]
                              if c.get("head") or c.get("image")), None)
            head = None
            if head_name:
                head = QImage(self._identities[head_name])
                if head.isNull():
                    raise RuntimeError(f"Cannot decode effect mask: {head_name}")
            image = build_effect(name, recipe, head)
        else:
            image = QImage(identity)
        if image.isNull():
            raise RuntimeError(f"Cannot decode rig texture: {name}")
        image = image.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
        size = _texture_storage_bytes(part)
        self._peak_decode_bytes = max(self._peak_decode_bytes, image.sizeInBytes())
        texture = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
        texture.setFormat(QOpenGLTexture.TextureFormat.RGBA8_UNorm)
        texture.setSize(image.width(), image.height())
        # Painted tear cels shrink substantially on the cheek. Prefilter them
        # instead of sparsely sampling the high-resolution ink and highlights.
        painted_tear = bool(part.get("drawnTearFrame"))
        texture.setMipLevels(max(image.width(), image.height()).bit_length() if painted_tear else 1)
        texture.setAutoMipMapGenerationEnabled(False)
        texture.allocateStorage(QOpenGLTexture.PixelFormat.RGBA, QOpenGLTexture.PixelType.UInt8)
        texture.setMinMagFilters(QOpenGLTexture.Filter.LinearMipMapLinear if painted_tear
                                 else QOpenGLTexture.Filter.Linear,
                                 QOpenGLTexture.Filter.Linear)
        texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        texture.setData(QOpenGLTexture.PixelFormat.RGBA, QOpenGLTexture.PixelType.UInt8,
                        image.constBits())
        if painted_tear:
            texture.generateMipMaps()
        return texture, size

    def paintGL(self):
        if self._released or self._error or self._gl is None:
            return
        try:
            gl = self._gl
            gl.glClearColor(0, 0, 0, 0)
            gl.glClear(_GL_COLOR_BUFFER_BIT)
            t0 = time.perf_counter()
            plan = self.planner.plan(self._state())
            self._plan_ms = (time.perf_counter() - t0) * 1000
            self._max_plan_ms = max(self._max_plan_ms, self._plan_ms)
            self._last_plan = plan
            sizes = {}
            for name in plan["requiredTextures"]:
                part = self._parts[name]
                sizes[self._identities[name]] = _texture_storage_bytes(part)
            self._cache.prepare(sizes)
            # Keep the authored 2:3 stage, centered inside the existing host box.
            dpr = self.devicePixelRatioF()
            width, height = round(self.width() * dpr), round(self.height() * dpr)
            vw, vh = min(width, round(height * 2 / 3)), min(height, round(width * 3 / 2))
            gl.glViewport((width - vw) // 2, (height - vh) // 2, vw, vh)
            gl.glDisable(_GL_DEPTH_TEST)
            gl.glDisable(_GL_CULL_FACE)
            gl.glEnable(_GL_BLEND)
            gl.glBlendFunc(_GL_ONE, _GL_ONE_MINUS_SRC_ALPHA)
            program = self._program
            program.bind()
            program.setUniformValue(self._locations["viewport"], QVector2D(360, 540))
            for unit, name in enumerate(("image", "replacement", "bodyNegativeLower", "bodyNegativeUpper")):
                program.setUniformValue(self._locations[name], unit)
            self._buffer.bind()
            program.enableAttributeArray(self._pos)
            program.enableAttributeArray(self._uv)
            self._character_pixel_rect = None
            if self._debug_painter is not None:
                self._measure_character_pixels(plan, width, height, dpr)
            self._draw_commands(plan['commands'])
            program.disableAttributeArray(self._pos)
            program.disableAttributeArray(self._uv)
            self._buffer.release()
            program.release()
            # Restore the active texture unit before Qt composites the widget.
            gl.glActiveTexture(0x84C0)
            gl.glViewport(0, 0, width, height)
            # Publish this frame's body bounds before Qt presents the host. A
            # landing pose can extend the feet beyond the previous fall bounds.
            self.pose_bounds_changed.emit()
            if not self._overlay.isNull() or self._debug_painter is not None:
                painter = QPainter(self)
                if not self._overlay.isNull():
                    painter.drawPixmap(self.rect(), self._overlay)
                if self._debug_painter is not None:
                    self._debug_painter(painter)
                painter.end()
            self._draw_ms = (time.perf_counter() - t0) * 1000 - self._plan_ms
            self._frames += 1
            if self._frames % 120 == 0 and hasattr(self.planner, "engine"):
                self.planner.engine.collectGarbage()
        except Exception as exc:
            self._fail(exc)

    def stats(self) -> dict:
        return {**self._cache.stats(), "rendered_frames": self._frames,
                "plan_ms": self._plan_ms, "max_plan_ms": self._max_plan_ms,
                "draw_ms": self._draw_ms, "vertex_buffer_bytes": self._buffer_capacity,
                "peak_single_decode_bytes": self._peak_decode_bytes,
                "error": self._error, "action": self._action, "emotion": self._emotion,
                "yaw": self._yaw, "speaking": self._speaking}

    def _cleanup_gl(self):
        if self.context() is None or not self.context().isValid():
            return
        self.makeCurrent()
        self._diagnostic_fbo = None
        self._cache.clear()
        if self._buffer is not None and self._buffer.isCreated():
            self._buffer.destroy()
        if self._program is not None:
            self._program.removeAllShaders()
        self.doneCurrent()
        self._gl = None

    def release(self):
        if not self._released:
            log_event('renderer.opengl.released', 'OpenGL 캐릭터 렌더 자원을 해제합니다.',
                      trace_id=getattr(self.planner, 'log_trace_id', None), **self._diagnostic_snapshot())
            self._released = True
            self._debug_painter = None
            self._timer.stop()
            self._cleanup_gl()
            if hasattr(self.planner, "close"):
                self.planner.close()
