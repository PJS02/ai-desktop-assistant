import json
import os
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ai.gemini_client import automatic_dialogue_config, load_gemini_config, request_gemini
from .igdb import (extract_title_query, load_igdb_config, normalize_game_query,
                   request_igdb_token, search_igdb_games)
from .rules_config import get_rules


def _is_own_process(process):
    # Include recognition subprocesses, while allowing unrelated Python programs.
    own_pid = os.getpid()
    return process.pid == own_pid or any(parent.pid == own_pid for parent in process.parents())


def get_active_window_info(*, with_window=False):
    try:
        import win32gui
        import win32process
    except ImportError as exc:
        raise SystemExit(
            "pywin32 is required. Install with: pip install pywin32"
        ) from exc

    # 활성 창의 프로세스와 제목을 수집합니다.
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        if with_window and (not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd)):
            return None
        title = win32gui.GetWindowText(hwnd).strip()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
    except OSError:
        return None

    try:
        import psutil
    except ImportError as exc:
        raise SystemExit(
            "psutil is required. Install with: pip install psutil"
        ) from exc

    started_at = 0
    try:
        process = psutil.Process(pid)
        if _is_own_process(process):
            return None
        exe = process.name()
        if with_window:
            try:
                started_at = process.create_time()
            except psutil.Error:
                pass
    except psutil.Error:
        exe = "unknown"

    info = {"process": exe.lower(), "title": title}
    if with_window:
        info["window_id"] = hwnd
        info["process_instance"] = (pid, started_at)
        try:
            info["desktop"] = win32gui.GetClassName(hwnd) in {"Progman", "WorkerW"}
        except win32gui.error:
            return None
    return info


def get_foreground_window_info():
    return get_active_window_info(with_window=True)


def load_json_file(path, default):
    # JSON 파일을 안전하게 읽습니다.
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save_json_file(path, data):
    # JSON 파일을 저장합니다.
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_url_cache(cache_path):
    # 로컬 URL 캐시를 읽습니다.
    if not cache_path.exists():
        return ""
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return payload.get("url", "")
    except json.JSONDecodeError:
        return ""


def start_url_server(port, cache_path=None, *, on_activity=None):
    # 확장 프로그램의 URL 전송을 받는 서버입니다.
    class UrlHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_POST(self):
            is_url = self.path == "/url" and cache_path is not None
            is_activity = self.path == "/activity" and on_activity is not None
            if not is_url and not is_activity:
                self.send_response(404)
                self.end_headers()
                return
            if is_activity:
                origin = self.headers.get("Origin", "")
                prefix = "chrome-extension://"
                extension_id = origin[len(prefix):]
                if (not origin.startswith(prefix) or len(extension_id) != 32
                        or any(not "a" <= char <= "p" for char in extension_id)):
                    self.send_error(403)
                    return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    self.send_error(413)
                    return
                self.connection.settimeout(2)
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError
            except (ValueError, OSError):
                self.send_error(400)
                return
            if is_activity:
                if not on_activity(data):
                    self.send_error(400)
                    return
            else:
                url = data.get("url", "")
                if isinstance(url, str) and url:
                    cache_path.write_text(
                        json.dumps({"url": url, "updated_at": time.time()}, indent=2),
                        encoding="utf-8",
                    )

            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), UrlHandler)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
    thread.start()
    return server


def capture_active_window_image(*, window_id=None):
    # 활성 창을 캡처해 이미지로 반환합니다.
    try:
        import win32gui
        import win32process
    except ImportError as exc:
        raise RuntimeError(
            "pywin32 is required. Install with: pip install pywin32"
        ) from exc

    try:
        from PIL import ImageGrab
    except ImportError as exc:
        raise RuntimeError(
            "pillow is required. Install with: pip install pillow"
        ) from exc

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd or (window_id is not None and hwnd != window_id):
        return None

    import psutil
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        if _is_own_process(psutil.Process(pid)):
            return None
    except psutil.Error:
        return None

    if window_id is None:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    else:
        if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return None
        x0, y0, x1, y1 = win32gui.GetClientRect(hwnd)
        left, top = win32gui.ClientToScreen(hwnd, (x0, y0))
        right, bottom = win32gui.ClientToScreen(hwnd, (x1, y1))
    if right <= left or bottom <= top:
        return None

    image = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    if window_id is None or win32gui.GetForegroundWindow() == window_id:
        return image


def start_input_listener(trigger):
    # 콘솔 입력으로 실행 시점을 예약합니다.
    def reader():
        while True:
            try:
                line = input().strip().lower()
            except EOFError:
                break
            if line == "g":
                trigger["send_at"] = time.time() + 3

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()


def build_gemini_prompt(info, category, url):
    # Gemini에 보낼 입력을 구성합니다.
    proc = info["process"] if info else ""
    title = info["title"] if info else ""
    url_part = url or ""

    return (
        "입력 정보:\n"
        "- 활동 분류: {category}\n"
        "- 프로세스: {proc}\n"
        "- 창 제목: {title}\n"
        "- URL: {url}\n"
    ).format(category=category, proc=proc, title=title, url=url_part)


def extract_dialogue(text):
    if not text:
        return ""

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return ""

    if isinstance(data, dict):
        return data.get("dialogue", "").strip()

    return ""


def build_system_instruction(voice=None):
    # 모델 출력 형식을 강제하는 시스템 규칙입니다.
    from character.dialogue_persona import BASE_VOICE
    return (str(voice or BASE_VOICE) + '\n\n' +
        "당신은 사용자의 PC 활동을 관찰하는 캐릭터입니다. "
        "반드시 요청의 응답 스키마와 일치하는 JSON 객체만 출력하세요.\n\n"
        "dialogue에는 캐릭터 대사를 문자열로 넣으세요.\n"
        "규칙:\n"
        "1. 한국어 1~2문장으로 작성.\n"
        "2. 입력된 활동에만 반응하고, 개발 중이라는 설정이나 보이지 않는 상황을 지어내지 마세요.\n"
        "3. 활동 분류가 프로세스/창 제목/URL과 맞지 않으면 스스로 적절한 활동으로 재분류하세요.\n"
        "4. JSON 외의 텍스트(인사말, 마크다운 코드 블록 등) 절대 포함 금지.\n"
        "5. 옵션/후보/초안/목록 형태로 나열하지 마세요.\n"
        "6. JSON 객체만 출력하고, 앞뒤에 어떤 문자도 붙이지 마세요."
    )


def build_response_schema():
    # Gemini 구조화 출력 스키마입니다.
    return {
        "type": "object",
        "properties": {
            "dialogue": {"type": "string"},
        },
        "required": ["dialogue"],
        "additionalProperties": False,
    }


def call_gemini(prompt, config, image=None, *, log_context=None):
    """Legacy activity wrapper. New callers use request_gemini directly."""
    return request_gemini(
        prompt,
        automatic_dialogue_config(config),
        image=image,
        response_schema=build_response_schema(),
        system_instruction=build_system_instruction(config.get('character_voice')),
        log_context=log_context,
    )


def generate_dialogue_json(start_server=False):
    # 외부 호출을 위한 1회 실행 결과를 반환합니다.
    base_dir = Path(__file__).resolve().parent
    config_dir = base_dir / "config"
    cache_dir = base_dir / "cache"
    config_dir.mkdir(exist_ok=True)
    cache_dir.mkdir(exist_ok=True)
    url_cache_path = cache_dir / "url_cache.json"
    if start_server:
        try:
            start_url_server(8765, url_cache_path)
        except OSError:
            pass

    gemini_config = load_gemini_config()
    igdb_config = load_igdb_config()

    rules = get_rules()

    info = get_active_window_info()
    category = classify_activity(info, rules, igdb_config, cache_dir)
    url = load_url_cache(url_cache_path) if info and info["process"] in rules["browsers"] else ""

    if not gemini_config.get("api_key"):
        return {
            "dialogue": "",
            "error": "missing_api_key",
            "category": category,
            "process": info["process"] if info else "",
            "title": info["title"] if info else "",
            "url": url,
        }

    image = capture_active_window_image()
    if image is None:
        return {"dialogue": "", "error": "screen_capture_unavailable", "category": category,
                "process": info["process"] if info else "", "title": info["title"] if info else "", "url": url}
    prompt = build_gemini_prompt(info, category, url)
    response = request_gemini(
        prompt,
        automatic_dialogue_config(gemini_config),
        image=image,
        response_schema=build_response_schema(),
        system_instruction=build_system_instruction(),
    )
    dialogue = extract_dialogue(response) if response else ""

    return {
        "dialogue": dialogue,
        "raw": response,
        "category": category,
        "process": info["process"] if info else "",
        "title": info["title"] if info else "",
        "url": url,
    }

def get_igdb_token(config, token_cache_path):
    cached = load_json_file(token_cache_path, {})
    now_ts = time.time()
    if (cached.get("client_id") == config["client_id"]
            and cached.get("access_token") and cached.get("expires_at", 0) > now_ts + 30):
        return cached["access_token"]

    access_token, expires_in = request_igdb_token(config)
    save_json_file(
        token_cache_path,
        {"client_id": config["client_id"], "access_token": access_token, "expires_at": now_ts + expires_in},
    )
    return access_token


def igdb_search_game(title_query, config, token_cache_path):
    if not title_query:
        return None

    token = get_igdb_token(config, token_cache_path)
    results = search_igdb_games(title_query, config["client_id"], token)
    return results[0] if results else None


def classify_activity(info, rules, igdb_config, cache_dir):
    if not info:
        return "IDLE"

    proc = info["process"]
    title = info["title"].lower()

    if proc in rules["media_players"]:
        return "MEDIA"

    if proc in rules["developers"]:
        return "DEVELOP"

    if proc in rules["documents"]:
        return "DOCUMENT"

    # 로컬 규칙으로 웹 여부를 판단합니다.
    if proc in rules["browsers"]:
        if any(keyword in title for keyword in rules["web_media_keywords"]):
            return "MEDIA"
        if any(keyword in title for keyword in rules["web_study_keywords"]):
            return "STUDY"
        return "WEB"

    # 로컬 규칙이 아니면 IGDB로 확인합니다.
    if igdb_config and igdb_config.get("client_id") and igdb_config.get("client_secret"):
        proc_name = normalize_game_query(info["process"]) if info["process"] else ""
        title_query = normalize_game_query(
            extract_title_query(info["title"], rules["title_extract_patterns"])
        )
        queries = [q for q in (title_query, proc_name) if q]

        cache = load_json_file(cache_dir / "igdb_cache.json", {})
        for query in queries:
            if query in cache:
                if cache[query]:
                    return "GAME"
                continue

            try:
                result = igdb_search_game(query, igdb_config, cache_dir / "igdb_token.json")
            except Exception:
                result = None

            cache[query] = bool(result)
            save_json_file(cache_dir / "igdb_cache.json", cache)
            if result:
                return "GAME"
    return "ETC"


def main():
    base_dir = Path(__file__).resolve().parent
    # 로컬 URL 캐시 경로입니다.
    config_dir = base_dir / "config"
    cache_dir = base_dir / "cache"
    config_dir.mkdir(exist_ok=True)
    cache_dir.mkdir(exist_ok=True)
    url_cache_path = cache_dir / "url_cache.json"
    start_url_server(8765, url_cache_path)
    gemini_config = load_gemini_config()
    igdb_config = load_igdb_config()

    # 분류 규칙과 제목 패턴입니다.
    rules = get_rules()

    for remaining in range(3, 0, -1):
        print(f"[debug] 실행까지 {remaining}초")
        time.sleep(1)

    # 카운트다운 후 한 번 실행합니다.
    while True:
        info = get_active_window_info()
        category = classify_activity(info, rules, igdb_config, cache_dir)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        url = load_url_cache(url_cache_path) if info and info["process"] in rules["browsers"] else ""
        last_signature = (category, info["process"] if info else "", info["title"] if info else "", url)

        if info:
            if url:
                print(
                    f"[{timestamp}] {category} | {info['process']} | {info['title']} | {url}"
                )
            else:
                print(
                    f"[{timestamp}] {category} | {info['process']} | {info['title']}"
                )
        else:
            print(f"[{timestamp}] unknown | (no active window)")

        if gemini_config.get("api_key"):
            image = capture_active_window_image()
            if image is None:
                print(f"[{timestamp}] gemini | (screen capture unavailable; request blocked)")
                break
            prompt = build_gemini_prompt(info, category, url)
            response = request_gemini(
                prompt,
                automatic_dialogue_config(gemini_config),
                image=image,
                response_schema=build_response_schema(),
                system_instruction=build_system_instruction(),
            )
            if response:
                dialogue = extract_dialogue(response)
                print(f"[{timestamp}] gemini_full | {response}")
                print(f"[{timestamp}] gemini_dialogue | {dialogue}")
            else:
                print(f"[{timestamp}] gemini | (no response)")

        break


if __name__ == "__main__":
    main()
