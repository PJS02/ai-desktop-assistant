"""Rasterize the original Canvas2D effect recipes once, on demand, in Qt."""
from __future__ import annotations

import math
import re
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage,
                         QLinearGradient, QPainter, QPainterPath, QPen,
                         QRadialGradient)


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


def build_effect(name, recipe, headImage=None):
    del name
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
