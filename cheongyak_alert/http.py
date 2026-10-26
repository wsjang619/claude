from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .models import SourceError

USER_AGENT = "cheongyak-alert/1.0"


def normalize_key(key: str) -> str:
    """공공데이터포털의 Encoding/Decoding 키 어느 쪽을 넣어도 동작하도록 정규화."""
    return urllib.parse.unquote(key.strip())


def _redact(text: str) -> str:
    return re.sub(r"(serviceKey=)[^&\s]+", r"\1***", text, flags=re.I)


def get_text(url: str, params: dict[str, object], *, headers: dict[str, str] | None = None,
             timeout: int = 30, retries: int = 3) -> str:
    full = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    last: Exception | None = None
    for attempt in range(retries):
        if attempt:
            time.sleep(2 ** attempt)
        try:
            req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                                        **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:200]
            last = SourceError(f"HTTP {e.code} {_redact(url)} {detail}")
            if e.code < 500:       # 4xx는 재시도해도 소용없다 (429·403이면 오히려 더 막힌다)
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = SourceError(f"연결 실패 {_redact(url)}: {e}")
    raise last or SourceError(f"요청 실패 {_redact(url)}")


def get_json(url: str, params: dict[str, object], *, headers: dict[str, str] | None = None,
             timeout: int = 30, retries: int = 3):
    body = get_text(url, params, headers=headers, timeout=timeout, retries=retries)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # 인증키 오류 등은 JSON이 아니라 XML로 내려온다
        raise SourceError(f"JSON이 아닌 응답 {_redact(url)}: {_redact(body[:300])}") from None
