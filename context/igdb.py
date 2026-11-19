"""Shared IGDB credentials, API requests, and background game lookup."""
from dataclasses import dataclass
from http.client import HTTPException
import json
import math
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Event, Lock, Thread
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app_logging import log_throttled, register_secret
from app_paths import USER_DATA_ROOT


CONFIG_PATH = USER_DATA_ROOT / "context" / "config" / "igdb_config.json"
REQUEST_TIMEOUT = 4


def normalize_igdb_config(config=None, *, require_pair=False):
    config = {} if config is None else config
    fields = ("client_id", "client_secret")
    if not isinstance(config, dict) or any(not isinstance(config.get(key, ""), str) for key in fields):
        raise ValueError("IGDB 설정의 Client ID와 Client Secret은 문자열이어야 합니다.")
    values = {key: config.get(key, "").strip() for key in fields}
    if require_pair and bool(values["client_id"]) != bool(values["client_secret"]):
        raise ValueError("IGDB를 사용하려면 Twitch Client ID와 Client Secret을 모두 입력하세요.")
    return values


def load_igdb_config():
    try:
        config = normalize_igdb_config(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return normalize_igdb_config()
    except (OSError, ValueError):
        log_throttled("settings.igdb.load_failed", "IGDB 설정 파일을 읽지 못했습니다.", level="WARNING")
        return normalize_igdb_config()
    register_secret(config["client_secret"])
    return config


def save_igdb_config(config):
    values = normalize_igdb_config(config, require_pair=True)
    register_secret(values["client_secret"])
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", dir=CONFIG_PATH.parent, prefix="igdb_config.", suffix=".tmp",
                            encoding="utf-8", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        temporary.write_text(json.dumps(values, indent=2), encoding="utf-8")
        temporary.replace(CONFIG_PATH)
    finally:
        temporary.unlink(missing_ok=True)
    return values


def _request_json(request):
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.load(response)


def request_igdb_token(config):
    register_secret(config["client_secret"])
    body = urlencode({"client_id": config["client_id"], "client_secret": config["client_secret"],
                      "grant_type": "client_credentials"}).encode("utf-8")
    payload = _request_json(Request("https://id.twitch.tv/oauth2/token", data=body, method="POST"))
    if not isinstance(payload, dict) or not isinstance(token := payload.get("access_token"), str) or not token:
        raise ValueError("Twitch 인증 응답에서 액세스 토큰을 읽을 수 없습니다.")
    expires_in = float(payload.get("expires_in", 0))
    if not math.isfinite(expires_in) or expires_in <= 0:
        raise ValueError("Twitch 인증 응답의 토큰 만료 시간이 올바르지 않습니다.")
    register_secret(token)
    return token, expires_in


def search_igdb_games(query, client_id, token, *, limit=1):
    body = f"search {json.dumps(query, ensure_ascii=False)}; fields id,name,genres.name; limit {limit};"
    request = Request("https://api.igdb.com/v4/games", data=body.encode("utf-8"), method="POST")
    request.add_header("Client-ID", client_id)
    request.add_unredirected_header("Authorization", f"Bearer {token}")
    results = _request_json(request)
    if not isinstance(results, list):
        raise ValueError("IGDB 게임 검색 응답 형식이 올바르지 않습니다.")
    return results


def extract_title_query(title, patterns):
    if not title:
        return ""
    for pattern in patterns:
        match = re.match(pattern, title, flags=re.IGNORECASE)
        if match and (candidate := match.group("title").strip()):
            return candidate
    cleaned = re.sub(r"\s*[-|:]\s*.*$", "", title)
    cleaned = re.sub(r"\[[^\]]*\]", "", cleaned)
    cleaned = re.sub(r"\([^\)]*\)", "", cleaned)
    cleaned = re.sub(r"\s+v?\d+\.\d+(?:\.\d+)*\b.*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def normalize_game_query(value):
    if not value:
        return ""
    value = re.sub(r"(?i)\.exe$", "", value).replace("_", " ").strip()
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    return " ".join(value.split())


def _name_key(name):
    return "".join(char for char in name.casefold() if char.isalnum())


@dataclass(frozen=True)
class IGDBGame:
    name: str
    genres: tuple[str, ...] = ()


class IGDBLookup:
    """One background request at a time, shared by the spectator and dialogue worker."""

    def __init__(self, config):
        self._config = normalize_igdb_config(config)
        self.enabled = all(self._config.values())
        self._lock = Lock()
        self._cache = {}
        self._pending = None
        self._retry_at = 0.
        self._token = ""
        self._expires_at = 0.

    def find(self, queries, *, wait=False):
        match = self.find_game(queries, wait=wait)
        return match.name if match is not None else None

    def find_game(self, queries, *, wait=False):
        if not queries:
            return None
        with self._lock:
            if not self.enabled:
                return None
            if queries in self._cache:
                return self._cache[queries]
            if self._pending is None:
                if time.monotonic() < self._retry_at:
                    return None
                done = Event()
                self._pending = (queries, done)
                try:
                    Thread(target=self._run, args=(queries, done), name="igdb-lookup", daemon=True).start()
                except RuntimeError:
                    self._pending = None
                    return None
            elif self._pending[0] != queries:
                return None
            done = self._pending[1]
        if wait and done.wait(REQUEST_TIMEOUT):
            with self._lock:
                return self._cache.get(queries) if self.enabled else None
        return None

    def close(self):
        with self._lock:
            self.enabled = False
            if self._pending is not None:
                self._pending[1].set()

    def _run(self, queries, done):
        try:
            match = self._search(queries)
        except (OSError, HTTPException, ValueError, TypeError, OverflowError) as error:
            self._token = ""
            self._retry_at = time.monotonic() + 30
            log_throttled("igdb.lookup_failed", "IGDB 게임 조회에 실패했습니다.", level="WARNING",
                          http_status=getattr(error, "code", None))
        else:
            with self._lock:
                if len(self._cache) >= 256:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[queries] = match
        finally:
            with self._lock:
                self._pending = None
                done.set()

    def _search(self, queries):
        if not self.enabled:
            return None
        if not self._token or time.monotonic() + 30 >= self._expires_at:
            self._token, expires_in = request_igdb_token(self._config)
            self._expires_at = time.monotonic() + expires_in
        for query in queries:
            if not self.enabled:
                return None
            key = _name_key(query)
            if not key:
                continue
            results = search_igdb_games(query, self._config["client_id"], self._token, limit=10)
            for result in results:
                if isinstance(result, dict) and isinstance(name := result.get("name"), str):
                    if _name_key(name) == key:
                        genres = result.get('genres')
                        if not isinstance(genres, list):
                            genres = []
                        return IGDBGame(name, tuple(genre['name'] for genre in genres
                                                    if isinstance(genre, dict) and isinstance(genre.get('name'), str)))
        return None
