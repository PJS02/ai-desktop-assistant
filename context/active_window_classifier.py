import base64
import io
import json
import re
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def get_active_window_info():
    try:
        import win32gui
        import win32process
    except ImportError as exc:
        raise SystemExit(
            "pywin32 is required. Install with: pip install pywin32"
        ) from exc

    # 활성 창의 프로세스와 제목을 수집합니다.
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None

    title = win32gui.GetWindowText(hwnd).strip()
    _, pid = win32process.GetWindowThreadProcessId(hwnd)

    try:
        import psutil
    except ImportError as exc:
        raise SystemExit(
            "psutil is required. Install with: pip install psutil"
        ) from exc

    try:
        process = psutil.Process(pid)
        exe = process.name()
    except psutil.Error:
        exe = "unknown"

    return {"process": exe.lower(), "title": title}


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


def start_url_server(port, cache_path):
    # 확장 프로그램의 URL 전송을 받는 서버입니다.
    class UrlHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_POST(self):
            if self.path != "/url":
                self.send_response(404)
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {}

            url = data.get("url", "")
            if url:
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
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def capture_active_window_image():
    # 활성 창을 캡처해 이미지로 반환합니다.
    try:
        import win32gui
    except ImportError as exc:
        raise SystemExit(
            "pywin32 is required. Install with: pip install pywin32"
        ) from exc

    try:
        from PIL import ImageGrab
    except ImportError as exc:
        raise SystemExit(
            "pillow is required. Install with: pip install pillow"
        ) from exc

    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    if right <= left or bottom <= top:
        return None

    return ImageGrab.grab(bbox=(left, top, right, bottom))


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
    url_part = url if category == "web" else ""

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
    # 불필요한 서식을 제거합니다.
    cleaned = re.sub(r"```[\s\S]*?```", "", text)
    cleaned = re.sub(r"^[\s\*\-]+", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.replace("`", "").strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        return data.get("dialogue", "").strip()

    # 여러 JSON 조각이 섞이면 마지막 유효 객체를 우선합니다.
    matches = re.findall(r"\{[\s\S]*?\}", cleaned)
    for candidate in reversed(matches):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "dialogue" in data:
            return data.get("dialogue", "").strip()

    return ""


def build_system_instruction():
    # 모델 출력 형식을 강제하는 시스템 규칙입니다.
    return (
        "당신은 사용자의 PC 활동을 관찰하는 캐릭터입니다. "
        "반드시 아래 JSON 스키마 형식으로만 응답하세요. 다른 설명은 금지합니다.\n\n"
        "스키마: {\"dialogue\": \"문자열\"}\n"
        "규칙:\n"
        "1. 한국어 1~2문장으로 작성.\n"
        "2. 메타 상황(개발 중) 적극 반영.\n"
        "3. JSON 외의 텍스트(인사말, 마크다운 코드 블록 등) 절대 포함 금지.\n"
        "4. 옵션/후보/초안/목록 형태로 나열하지 마세요.\n"
        "5. JSON 객체만 출력하고, 앞뒤에 어떤 문자도 붙이지 마세요."
    )


def encode_image_base64(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def call_gemini(prompt, config, image=None):
    # Gemini API 호출 후 응답 텍스트를 반환합니다.
    api_key = config.get("api_key", "")
    if not api_key:
        return ""

    model = config.get("model", "gemma-3-4b-it")
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    parts = [{"text": prompt}]
    if image is not None:
        parts.append(
            {
                "inline_data": {
                    "mime_type": "image/png",
                    "data": encode_image_base64(image),
                }
            }
        )
    # response_mime_type으로 JSON 응답을 유도합니다.
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"response_mime_type": "application/json"},
        "system_instruction": {
            "parts": [{"text": build_system_instruction()}]
        },
    }
    req = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return f"[gemini error] {exc}"

    candidates = data.get("candidates", [])
    if not candidates:
        return "[gemini error] no candidates"
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        return "[gemini error] empty content"
    return parts[0].get("text", "").strip()

    # # gemma-4-31b-it 호환성을 위해 JSON 응답 형식 설정을 일단 제거
    # payload = {
    #     "contents": [{"parts": parts}],
    #     "system_instruction": 
    #         "parts": [{"text": build_system_instruction()}]
    #     },
    # }
    # req = Request(
    #     endpoint,
    #     data=json.dumps(payload).encode("utf-8"),
    #     method="POST",
    # )
    # req.add_header("Content-Type", "application/json")

    # try:
    #     with urlopen(req, timeout=30) as resp:
    #         response_text = resp.read().decode("utf-8")
    #         # 먼저 JSON으로 파싱 시도
    #         try:
    #             data = json.loads(response_text)
    #         except json.JSONDecodeError:
    #             # JSON 파싱 실패 시 텍스트 응답으로 처리
    #             return response_text.strip()
    # except Exception as exc:
    #     return f"[gemini error] {exc}"

    # # JSON \uc751\ub2f5 \ucc98\ub9ac
    # if isinstance(data, dict):
    #     candidates = data.get("candidates", [])
    #     if not candidates:
    #         return "[gemini error] no candidates"
    #     parts = candidates[0].get("content", {}).get("parts", [])
    #     if not parts:
    #         return "[gemini error] empty content"
    #     return parts[0].get("text", "").strip()
    
    # # \ud14d\uc2a4\ud2b8 \uc751\ub2f5 \ucc98\ub9ac
    # return data if isinstance(data, str) else str(data)


def generate_dialogue_json(start_server=False):
    # 외부 호출을 위한 1회 실행 결과를 반환합니다.
    base_dir = Path(__file__).resolve().parent
    url_cache_path = base_dir / "url_cache.json"
    if start_server:
        try:
            start_url_server(8765, url_cache_path)
        except OSError:
            pass

    gemini_config_path = base_dir / "gemini_config.json"
    gemini_config = load_json_file(gemini_config_path, {})
    igdb_config_path = base_dir / "igdb_config.json"
    igdb_config = load_json_file(igdb_config_path, {})
    if not igdb_config.get("client_id") or not igdb_config.get("client_secret"):
        igdb_config = None

    rules = {
        "browsers": {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"},
        "title_extract_patterns": [
            r"^\[(?P<title>[^\]]+)\]\s*.*$",
            r"^(?P<title>.+?)\s*[|:]\s*.*$",
            r"^(?P<title>.+?)\s*-\s*(steam|epic|gog|origin|uplay|ubisoft|battlenet|battle\.net|xbox|launcher)\b.*$",
            r"^(?P<title>.+?)\s*-\s*.*$",
        ],
    }

    info = get_active_window_info()
    category = classify_activity(info, rules, igdb_config, base_dir)
    url = load_url_cache(url_cache_path) if category == "web" else ""

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
    prompt = build_gemini_prompt(info, category, url)
    response = call_gemini(prompt, gemini_config, image=image)
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
    if cached.get("access_token") and cached.get("expires_at", 0) > now_ts + 30:
        return cached["access_token"]

    # IGDB 호출용 Twitch 앱 토큰을 발급받습니다.
    token_url = "https://id.twitch.tv/oauth2/token"
    body = urlencode(
        {
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "grant_type": "client_credentials",
        }
    ).encode("utf-8")
    req = Request(token_url, data=body, method="POST")
    with urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    access_token = payload["access_token"]
    expires_in = payload.get("expires_in", 0)
    save_json_file(
        token_cache_path,
        {"access_token": access_token, "expires_at": now_ts + expires_in},
    )
    return access_token


def igdb_search_game(title_query, config, token_cache_path):
    if not title_query:
        return None

    token = get_igdb_token(config, token_cache_path)
    # 첫 검색 결과를 매칭으로 취급합니다.
    endpoint = "https://api.igdb.com/v4/games"
    body = f'search "{title_query}"; fields id,name; limit 1;'
    req = Request(endpoint, data=body.encode("utf-8"), method="POST")
    req.add_header("Client-ID", config["client_id"])
    req.add_header("Authorization", f"Bearer {token}")

    with urlopen(req, timeout=10) as resp:
        results = json.loads(resp.read().decode("utf-8"))

    if results:
        return results[0]
    return None


def extract_title_query(title, patterns):
    if not title:
        return ""

    # 제목에서 불필요한 부분을 제거합니다.
    for pattern in patterns:
        match = re.match(pattern, title, flags=re.IGNORECASE)
        if match:
            candidate = match.group("title").strip()
            if candidate:
                return candidate

    cleaned = re.sub(r"\s*[-|:]\s*.*$", "", title)
    cleaned = re.sub(r"\[[^\]]*\]", "", cleaned)
    cleaned = re.sub(r"\([^\)]*\)", "", cleaned)
    cleaned = re.sub(
        r"\s+v?\d+\.\d+(?:\.\d+)*\b.*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def normalize_game_query(value):
    # IGDB 검색용으로 프로세스/제목을 정규화합니다.
    if not value:
        return ""
    value = value.replace(".exe", "").replace("_", " ").strip()
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def classify_activity(info, rules, igdb_config, cache_dir):
    if not info:
        return "unknown"

    proc = info["process"]
    title = info["title"].lower()

    # 로컬 규칙으로 웹 여부를 판단합니다.
    if proc in rules["browsers"]:
        return "web"

    # 로컬 규칙이 아니면 IGDB로 확인합니다.
    if igdb_config:
        proc_name = normalize_game_query(info["process"]) if info["process"] else ""
        title_query = normalize_game_query(
            extract_title_query(info["title"], rules["title_extract_patterns"])
        )
        queries = [q for q in (title_query, proc_name) if q]

        cache = load_json_file(cache_dir / "igdb_cache.json", {})
        for query in queries:
            if query in cache:
                if cache[query]:
                    return "game"
                continue

            try:
                result = igdb_search_game(query, igdb_config, cache_dir / "igdb_token.json")
            except Exception:
                result = None

            cache[query] = bool(result)
            save_json_file(cache_dir / "igdb_cache.json", cache)
            if result:
                return "game"
    return "work"


def main():
    base_dir = Path(__file__).resolve().parent
    # 로컬 URL 캐시 경로입니다.
    url_cache_path = base_dir / "url_cache.json"
    start_url_server(8765, url_cache_path)
    gemini_config_path = base_dir / "gemini_config.json"
    gemini_config = load_json_file(gemini_config_path, {})
    igdb_config_path = base_dir / "igdb_config.json"
    igdb_config = load_json_file(igdb_config_path, {})
    if not igdb_config.get("client_id") or not igdb_config.get("client_secret"):
        igdb_config = None

    # 분류 규칙과 제목 패턴입니다.
    rules = {
        "browsers": {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"},
        "title_extract_patterns": [
            r"^\[(?P<title>[^\]]+)\]\s*.*$",
            r"^(?P<title>.+?)\s*[|:]\s*.*$",
            r"^(?P<title>.+?)\s*-\s*(steam|epic|gog|origin|uplay|ubisoft|battlenet|battle\.net|xbox|launcher)\b.*$",
            r"^(?P<title>.+?)\s*-\s*.*$",
        ],
    }

    for remaining in range(3, 0, -1):
        print(f"[debug] 실행까지 {remaining}초")
        time.sleep(1)

    # 카운트다운 후 한 번 실행합니다.
    while True:
        info = get_active_window_info()
        category = classify_activity(info, rules, igdb_config, base_dir)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        url = load_url_cache(url_cache_path) if category == "web" else ""
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
            prompt = build_gemini_prompt(info, category, url)
            response = call_gemini(prompt, gemini_config, image=image)
            if response:
                dialogue = extract_dialogue(response)
                print(f"[{timestamp}] gemini_full | {response}")
                print(f"[{timestamp}] gemini_dialogue | {dialogue}")
            else:
                print(f"[{timestamp}] gemini | (no response)")

        break


if __name__ == "__main__":
    main()
