"""Rasterize the original Canvas2D effect recipes once, on demand, in Qt."""
from __future__ import annotations

import math
import re
import numpy as np
from PIL import Image, ImageFilter
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage,
                         QLinearGradient, QPainter, QPainterPath, QPen,
                         QRadialGradient, QTransform)


def _color(value):
    rgba = re.fullmatch(r"rgba\(([^)]+)\)", str(value))
    if rgba:
        r, g, b, a = map(float, rgba.group(1).split(","))
        return QColor(round(r), round(g), round(b), round(a * 255))
    return QColor(value)


def _brush(style):
    if isinstance(style, str):
        return QBrush(_color(style))
    args = style["args"]
    if style["kind"] == "linear":
        gradient = QLinearGradient(*args)
    else:
        x0, y0, r0, x1, y1, r1 = args
        gradient = QRadialGradient(x1, y1, r1, x0, y0, r0)
    for offset, color in style["stops"]:
        gradient.setColorAt(offset, _color(color))
    return QBrush(gradient)


def _path(commands):
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    for command in commands:
        op, a = command["op"], command["args"]
        if op == "moveTo":
            path.moveTo(*a)
        elif op == "lineTo":
            path.lineTo(*a)
        elif op == "quadraticCurveTo":
            path.quadTo(*a)
        elif op == "bezierCurveTo":
            path.cubicTo(*a)
        elif op == "closePath":
            path.closeSubpath()
        elif op == "rect":
            path.addRect(*a)
        elif op in {"ellipse", "arc"}:
            if op == "ellipse":
                cx, cy, rx, ry, rotation, start, end = a[:7]
                anticlockwise = bool(a[7]) if len(a) > 7 else False
            else:
                cx, cy, rx, start, end = a[:5]
                ry, rotation = rx, 0
                anticlockwise = bool(a[5]) if len(a) > 5 else False
            delta = end - start
            if anticlockwise:
                delta = -min(2 * math.pi, (start - end) % (2 * math.pi) or 2 * math.pi)
            else:
                delta = min(2 * math.pi, delta % (2 * math.pi) or 2 * math.pi)
            cs, sn = math.cos(rotation), math.sin(rotation)
            def point(t):
                x, y = rx * math.cos(t), ry * math.sin(t)
                return QPointF(cx + x * cs - y * sn, cy + x * sn + y * cs)
            def tangent(t):
                x, y = -rx * math.sin(t), ry * math.cos(t)
                return QPointF(x * cs - y * sn, x * sn + y * cs)
            first = point(start)
            if path.isEmpty():
                path.moveTo(first)
            else:
                path.lineTo(first)
            segments = max(1, math.ceil(abs(delta) / (math.pi / 2)))
            step = delta / segments
            for i in range(segments):
                t0, t1 = start + step * i, start + step * (i + 1)
                k = 4 / 3 * math.tan(step / 4)
                p0, p1, d0, d1 = point(t0), point(t1), tangent(t0), tangent(t1)
                path.cubicTo(p0 + k * d0, p1 - k * d1, p1)
        else:
            raise ValueError(f"Unsupported original effect path operation: {op}")
    return path


def _shade(recipe, head):
    if head is None or head.isNull():
        raise ValueError("The original shade needs its head alpha mask")
    width, height = recipe["width"], recipe["height"]
    image = head.convertToFormat(QImage.Format.Format_RGBA8888)
    if image.size().width() != width or image.size().height() != height:
        raise ValueError("Head mask dimensions differ from the authored effect")
    pointer = image.constBits()
    pointer.setsize(image.sizeInBytes())
    source = bytes(pointer)
    pixels = bytearray(width * height * 4)
    command = recipe["commands"][0]
    bx, by = command["bbox"][:2]
    cx, cy, rx, ry = command["anchor"]
    def smooth(x):
        x = max(0, min(1, x))
        return x * x * (3 - 2 * x)
    for y in range(height):
        rise = smooth((y + by - (cy - ry)) / (ry * .72))
        fall = 1 - smooth((y + by - (cy + ry * .3)) / (ry * .7))
        for x in range(width):
            i = (y * width + x) * 4
            side = 1 - smooth((abs(x + bx - cx) - rx * .78) / (rx * .22))
            alpha = math.floor(source[y * image.bytesPerLine() + x * 4 + 3] * side * rise * fall * .38 + .5)
            pixels[i:i + 4] = bytes((78, 71, 108, alpha))
    return QImage(bytes(pixels), width, height, width * 4,
                  QImage.Format.Format_RGBA8888).copy()


def _dizzy_skin(recipe, head, skin):
    """Apply the authored eyeless painting with the browser effect's skin mask."""
    if head is None or skin is None or head.isNull() or skin.isNull():
        raise ValueError('Dizzy skin needs its original head and eyeless painting')
    command = recipe['commands'][0]
    width, height = recipe['width'], recipe['height']
    x, y, _, _ = command['bounds']

    def pixels(image):
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        pointer = image.constBits()
        pointer.setsize(image.sizeInBytes())
        return np.frombuffer(pointer, np.uint8).reshape(image.height(), image.bytesPerLine())[:, :image.width()*4].reshape(image.height(), image.width(), 4).copy()

    def mask(paths, expansion=0):
        image = QImage(width, height, QImage.Format.Format_RGBA8888_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(4, 4)
        painter.translate(-x, -y)
        for shape in paths:
            path = QPainterPath(QPointF(*shape['start']))
            for curve in shape['curves']:
                path.cubicTo(*curve)
            path.closeSubpath()
            painter.fillPath(path, Qt.GlobalColor.black)
            if expansion:
                pen = QPen(Qt.GlobalColor.black, expansion * 2)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.strokePath(path, pen)
        painter.end()
        return pixels(image)[:, :, 3]

    core = mask(command['covers'])
    soft = np.maximum(core, np.asarray(Image.fromarray(core).filter(ImageFilter.GaussianBlur(6)))) / 255.0
    eye = mask(command['apertures'], 3.5) / 255.0
    painted = QImage(width, height, QImage.Format.Format_RGBA8888_Premultiplied)
    painted.fill(Qt.GlobalColor.transparent)
    painter = QPainter(painted)
    a, b, c, d, e, f = command['toAtlas']
    painter.setWorldTransform(QTransform(4*a, 4*b, 4*c, 4*d, 4*(e-x), 4*(f-y)))
    painter.drawImage(QPointF(), skin)
    painter.end()
    result = pixels(painted)
    source = pixels(head)
    bx, by = command['headBounds'][:2]
    sx = np.floor(x + np.arange(width)/4 - bx).astype(int)
    sy = np.floor(y + np.arange(height)/4 - by).astype(int)
    valid = ((sy[:, None] >= 0) & (sy[:, None] < source.shape[0])
             & (sx[None, :] >= 0) & (sx[None, :] < source.shape[1]))
    sample = source[np.clip(sy, 0, source.shape[0]-1)[:, None],
                    np.clip(sx, 0, source.shape[1]-1)[None, :]].astype(float)
    red, green, blue, alpha = np.moveaxis(sample, -1, 0)
    warm = (alpha > 240) & (red > 220) & (green > 202) & (blue > 188) & (red-green > 3) & (green-blue > 2)
    hair = (green > 135) & (green-red > 5) & (blue-red > -4) & (green >= blue-10)
    skin_weight = np.clip((red-blue-6)/8, 0, 1) * np.clip((green-192)/18, 0, 1) * np.clip((red-green-1)/6, 0, 1)
    mask_alpha = soft * np.where(valid, alpha/255 * (1-skin_weight*(1-eye)), 1)
    mask_alpha[valid & ((hair & (eye < .01)) | ((core < 2.55) & ~warm))] = 0
    result[:, :, 3] = np.rint(255 * np.clip(mask_alpha, 0, 1)).astype(np.uint8)
    return QImage(result.tobytes(), width, height, width*4, QImage.Format.Format_RGBA8888).copy()


def build_effect(name, recipe, headImage=None, skinImage=None):
    del name
    if recipe['commands'] and recipe['commands'][0]['op'] == 'dizzySkin':
        return _dizzy_skin(recipe, headImage, skinImage)
    if recipe["commands"] and recipe["commands"][0]["op"] == "originalShade":
        return _shade(recipe, headImage)
    image = QImage(recipe["width"], recipe["height"], QImage.Format.Format_RGBA8888_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    try:
        for command in recipe["commands"]:
            state, op = command.get("state", {}), command["op"]
            sx, sy, tx, ty = state.get('transform', (1, 1, 0, 0))
            painter.setWorldTransform(QTransform(sx, 0, 0, sy, tx, ty))
            painter.setOpacity(state.get("globalAlpha", 1))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn
                if state.get("globalCompositeOperation") == "destination-in"
                else QPainter.CompositionMode.CompositionMode_SourceOver)
            if op == "drawImage":
                if headImage is None:
                    raise ValueError("The original stress overlay needs its head mask")
                painter.drawImage(QRectF(*command["args"]), headImage)
                continue
            if op in {"fillText", "strokeText"}:
                text, x, y = command["args"]
                font = QFont("Trebuchet MS")
                font.setPixelSize(96)
                font.setBold(True)
                metrics = QFontMetricsF(font)
                path = QPainterPath()
                path.addText(x - metrics.horizontalAdvance(text) / 2,
                             y + (metrics.ascent() - metrics.descent()) / 2, font, text)
            elif op in {"fill", "stroke"}:
                path = _path(command["path"])
            elif op in {"fillRect", "clearRect"}:
                if op == "clearRect":
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                painter.fillRect(QRectF(*command["args"]), _brush(state.get("fillStyle", "#000000")))
                continue
            else:
                raise ValueError(f"Unsupported original effect operation: {op}")
            if op.startswith("stroke"):
                pen = QPen(_brush(state["strokeStyle"]), state["lineWidth"])
                pen.setCapStyle(Qt.PenCapStyle.RoundCap if state["lineCap"] == "round" else Qt.PenCapStyle.FlatCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin if state["lineJoin"] == "round" else Qt.PenJoinStyle.MiterJoin)
                painter.strokePath(path, pen)
            else:
                painter.fillPath(path, _brush(state["fillStyle"]))
    finally:
        painter.end()
    return image
