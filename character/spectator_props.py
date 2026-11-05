"""Code-drawn accessories attached to the rig's actual head/body pose."""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPen, QPolygonF


def body_point(x, y, pose):
    bx, by = pose.get('bodyX', 0), pose.get('bodyY', 0)
    angle = math.radians(pose.get('lean', 0))
    dx, dy = x-180, y-357
    return QPointF(180+bx+dx*math.cos(angle)-dy*math.sin(angle),
                   357+by+dx*math.sin(angle)+dy*math.cos(angle))


def draw_spectator_props(painter, plan):
    pose = plan.get('pose', {})
    painter.save()
    head = body_point(180, 250, pose)
    painter.translate(head)
    painter.rotate(pose.get('lean', 0)+pose.get('headAngle', 0))
    # Dark lenses, a small bridge and restrained glints preserve the face silhouette.
    painter.setPen(QPen(QColor('#202638'), 4))
    lens = QLinearGradient(0, -64, 0, -30)
    lens.setColorAt(0, QColor('#182132'))
    lens.setColorAt(1, QColor('#39475b'))
    painter.setBrush(lens)
    for x in (-62, 6):
        painter.drawRoundedRect(QRectF(x, -59, 56, 31), 10, 10)
    painter.drawLine(QPointF(-6, -48), QPointF(6, -48))
    painter.drawLine(QPointF(-62, -51), QPointF(-75, -56))
    painter.drawLine(QPointF(62, -51), QPointF(75, -56))
    painter.setPen(QPen(QColor('#a7e9ef'), 3))
    for x in (-50, 18):
        painter.drawLine(QPointF(x, -51), QPointF(x+13, -47))
    painter.restore()

    painter.save()
    bucket = body_point(175, 346, pose)
    painter.translate(bucket)
    painter.rotate(pose.get('lean', 0))
    painter.setPen(QPen(QColor('#b14c52'), 2))
    painter.setBrush(QColor('#fff6e9'))
    painter.drawPolygon(QPolygonF([QPointF(-38, -16), QPointF(38, -16), QPointF(28, 48), QPointF(-28, 48)]))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor('#e8797c'))
    for x in (-27, -6, 15):
        painter.drawPolygon(QPolygonF([QPointF(x, -13), QPointF(x+12, -13),
                                      QPointF((x+12)*.73, 46), QPointF(x*.73, 46)]))
    painter.setBrush(QColor('#ffefbc'))
    painter.setPen(QPen(QColor('#d7b875'), 1.3))
    for i in range(18):
        x = ((i*19) % 65)-32
        y = -19-((i*11) % 21)
        painter.drawEllipse(QPointF(x, y), 7+(i%3), 6+(i%2))
    painter.restore()
    # The snack follows the rig's chin-reaching gesture, not an independent clock.
    eat = pose.get('snackGesture', 0)
    if eat > .05:
        hand = body_point(188, 319, pose)
        mouth = body_point(184, 246, pose)
        p = hand*(1-eat)+mouth*eat
        painter.setBrush(QColor('#fff0ba'))
        painter.setPen(QPen(QColor('#d7b875'), 1))
        painter.drawEllipse(p, 5, 4)
