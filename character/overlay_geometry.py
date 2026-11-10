"""Place character overlays in Qt logical screen coordinates."""
from PyQt6.QtCore import QPoint, QRect, QSize


def place_beside_character(anchor: QRect, size: QSize, bounds: QRect,
                           avoid: QRect | None = None) -> QPoint:
    """Keep user speech beside the upper body, choosing the side with room."""
    y = anchor.top() + round(anchor.height() * .4) - size.height() // 2
    y = max(bounds.top(), min(y, bounds.bottom() - size.height() + 1))
    candidates = [QRect(anchor.left() - size.width() - 10, y, size.width(), size.height()),
                  QRect(anchor.right() + 11, y, size.width(), size.height())]
    for rect in candidates:
        if bounds.contains(rect) and (avoid is None or not rect.intersects(avoid)):
            return rect.topLeft()
    for rect in candidates:
        rect.moveLeft(max(bounds.left(), min(rect.left(), bounds.right() - rect.width() + 1)))
    def overlap(rect):
        return sum(max(0, shared.width()) * max(0, shared.height())
                   for other in (anchor, avoid) if other is not None
                   for shared in [rect.intersected(other)])
    return min(candidates, key=overlap).topLeft()


def place_near_ankles(anchor: QRect, size: QSize, bounds: QRect,
                      avoid: QRect | None = None) -> QPoint:
    """Center user speech just above the ankles, clamped to the actual screen."""
    x = anchor.center().x() - size.width() // 2
    y = anchor.top() + round(anchor.height() * .88) - size.height() // 2
    x = max(bounds.left(), min(x, bounds.right() - size.width() + 1))
    y = max(bounds.top(), min(y, bounds.bottom() - size.height() + 1))
    placed = QRect(QPoint(x, y), size)
    if avoid is not None and placed.intersects(avoid):
        for candidate in (avoid.left() - size.width() - 10, avoid.right() + 11):
            alternative = QRect(candidate, y, size.width(), size.height())
            if bounds.contains(alternative) and not alternative.intersects(avoid):
                return alternative.topLeft()
    return placed.topLeft()


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
