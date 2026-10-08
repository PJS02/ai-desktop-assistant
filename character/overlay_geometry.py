"""Place character overlays in Qt logical screen coordinates."""
from PyQt6.QtCore import QPoint, QRect, QSize


def place_above_character(anchor: QRect, size: QSize, bounds: QRect,
                          avoid: QRect | None = None, gap=10) -> QPoint:
    x = anchor.center().x() - size.width() // 2
    top = anchor.top() - size.height() - gap
    candidates = [QRect(x, top, size.width(), size.height()),
                  QRect(x, anchor.bottom() + gap + 1, size.width(), size.height())]
    if avoid is not None and not avoid.isEmpty():
        candidates.insert(0, QRect(x, avoid.top() - size.height() - gap,
                                  size.width(), size.height()))
        candidates.extend([
            QRect(avoid.left() - size.width() - gap, top, size.width(), size.height()),
            QRect(avoid.right() + gap + 1, top, size.width(), size.height()),
        ])
    def clear(rect):
        return not rect.intersects(anchor) and (avoid is None or not rect.intersects(avoid))

    # Prefer a fitting above/below placement before clamping. Clamping an above
    # card at the top edge would otherwise cover the character's head.
    for rect in candidates:
        if bounds.contains(rect) and clear(rect):
            return rect.topLeft()
    # Clamp to the selected screen's origin, including negative monitor origins.
    fitted = []
    for rect in candidates:
        rect.moveLeft(max(bounds.left(), min(rect.left(), bounds.right() - rect.width() + 1)))
        rect.moveTop(max(bounds.top(), min(rect.top(), bounds.bottom() - rect.height() + 1)))
        fitted.append(rect)
        if clear(rect):
            return rect.topLeft()
    def overlap(rect, other):
        shared = rect.intersected(other) if other is not None else QRect()
        return shared.width() * shared.height() if not shared.isEmpty() else 0
    return min(fitted, key=lambda rect: overlap(rect, anchor)
               + overlap(rect, avoid)).topLeft()
