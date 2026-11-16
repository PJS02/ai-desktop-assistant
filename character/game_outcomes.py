"""Confirm explicit result banners in a foreground game using local OCR."""

from collections import OrderedDict
import math
import re
from threading import Thread
import unicodedata

from context.active_window_classifier import capture_active_window_image, get_foreground_window_info
from context.screen_privacy import try_read_screen_text
from .game_reactions import prepare_game_image


RESULT_FRAME_SIZE = (480, 270)
_BANNERS = {
    'win': {'victory', 'you win', 'you won', 'team victory', '승리', '경기승리', '우리팀승리'},
    'loss': {'defeat', 'you lose', 'you lost', 'team defeat', '패배', '경기패배', '우리팀패배'},
    'draw': {'match draw', 'match tied', '무승부', '경기무승부'},
    'score': {'득점성공', '내팀득점', '우리팀득점', '나의득점', '내가득점했습니다'},
}
_SCORE_BANNER = re.compile(r'(?:you|your team) scored(?: [1-9]\d{0,2}(?: points?)?)?')
_SCORE_GAIN = re.compile(r'(?:your(?: team)? score|내점수|우리팀점수)\s*\+\s*[1-9]\d{0,8}')


def _classify_result(page, size):
    texts, scores, polygons = (page.get(key) for key in ('rec_texts', 'rec_scores', 'rec_polys'))
    if any(value is None for value in (texts, scores, polygons)) or not len(texts) == len(scores) == len(polygons):
        return None
    width, height = size
    detected = {}
    uncertain = False
    for text, quality, polygon in zip(texts, scores, polygons):
        label = ' '.join(unicodedata.normalize('NFKC', text).casefold().split()).rstrip('! .')
        label = re.sub(r'(?<=[가-힣]) (?=[가-힣])', '', label)
        outcome = next((kind for kind, names in _BANNERS.items() if label in names), None)
        if outcome is None and (_SCORE_BANNER.fullmatch(label) or _SCORE_GAIN.fullmatch(label)):
            outcome = 'score'
        if outcome is None:
            continue
        if len(polygon) != 4 or any(len(point) != 2 for point in polygon):
            return None
        xs, ys = zip(*polygon)
        if not all(math.isfinite(value) for value in (*xs, *ys, quality)):
            return None
        center_x, center_y = (min(xs) + max(xs)) / (2 * width), (min(ys) + max(ys)) / (2 * height)
        # Ignore menu labels, chat/HUD text and tiny fragments outside the result area.
        if not (.27 <= center_x <= .73 and .15 <= center_y <= .78
                and max(ys) - min(ys) >= .035 * height and max(xs) - min(xs) >= .045 * width):
            continue
        if not .86 <= quality <= 1.:
            uncertain = True
            continue
        detected[outcome] = max(detected.get(outcome, 0.), float(quality))
    if len(detected) > 1:
        detected.pop('score', None)  # A match result can still show the last point.
    if uncertain or len(detected) > 1:
        return None
    return next(iter(detected.items()), ('', 0.))


def read_game_result(activity):
    def capture():
        def is_same_window():
            info = get_foreground_window_info()
            return (info and info['window_id'] == activity.window_id and info['process'] == activity.process
                    and info['process_instance'] == activity.process_instance)

        if is_same_window():
            image = capture_active_window_image(window_id=activity.window_id)
            if image is not None and is_same_window():
                frame = prepare_game_image(image, maximum_size=RESULT_FRAME_SIZE)
                darkest, brightest = frame.convert('L').getextrema()
                if brightest - darkest >= 10:
                    return frame
        return None

    observation = try_read_screen_text(capture)
    return _classify_result(*observation) if observation is not None else None


class GameOutcomeMonitor:
    """One capture at a time, with two observations required to confirm or clear a banner."""

    SAMPLE_SECONDS = 2.
    MAX_SAMPLE_AGE = 12.

    def __init__(self):
        self._session = None
        self._generation = 0
        self._next_sample = 0.
        self._busy = False
        self._reply = None
        self._previous = None
        self._announced = OrderedDict()

    def poll(self, activity, now):
        session = activity.session_key if activity else None
        if session != self._session:
            self._session, self._previous = session, None
            self._generation += 1
            self._next_sample = now

        outcome = None
        if self._reply is not None:
            generation, observed_at, result = self._reply
            self._reply = None
            self._busy = False
            if activity is not None and generation == self._generation:
                if 0 <= now - observed_at <= self.MAX_SAMPLE_AGE:
                    outcome = self._confirm(activity.run_key, observed_at, result)
                else:
                    self._previous = None
        if activity is not None and not self._busy and now >= self._next_sample:
            self._next_sample = now + self.SAMPLE_SECONDS
            self._busy = True
            try:
                Thread(target=self._sample, args=(activity, self._generation, now),
                       name='game-outcome-ocr', daemon=True).start()
            except RuntimeError:
                self._busy = False
        return outcome

    def _sample(self, activity, generation, observed_at):
        result = None
        try:
            if generation == self._generation:
                result = read_game_result(activity)
        except Exception:
            # OCR exceptions may contain screen text. A failed read is unknown.
            pass
        finally:
            self._reply = generation, observed_at, result

    def _confirm(self, run_key, observed_at, result):
        previous = self._previous
        self._previous = (observed_at, result) if result is not None else None
        if (result is None or previous is None or result[0] != previous[1][0]
                or not 0 < observed_at - previous[0] <= self.MAX_SAMPLE_AGE + self.SAMPLE_SECONDS):
            return None
        outcome, quality = result
        if not outcome:
            self._announced.pop(run_key, None)
        elif self._announced.get(run_key) != outcome:
            self._announced[run_key] = outcome
            self._announced.move_to_end(run_key)
            if len(self._announced) > 32:
                self._announced.popitem(last=False)
            return outcome, min(quality, previous[1][1])
