from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date


class SourceError(Exception):
    """외부 API 호출/파싱 실패. 메시지에는 인증키를 넣지 않는다."""


def parse_date(value: object) -> date | None:
    """'2026-10-26', '20261026', '2026.10.26', '2026-10-26 00:00:00' 등을 date로."""
    if not value:
        return None
    digits = re.findall(r"\d+", str(value))
    if len(digits) >= 3 and len(digits[0]) == 4:
        y, m, d = int(digits[0]), int(digits[1]), int(digits[2])
    elif len(digits) == 1 and len(digits[0]) >= 8:
        s = digits[0]
        y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
    else:
        return None
    try:
        return date(y, m, d)
    except ValueError:
        return None


@dataclass
class Notice:
    source: str                 # "applyhome" | "lh"
    uid: str                    # 소스 내 유일 ID
    title: str
    category: str
    address: str = ""
    announced: date | None = None
    receipt_start: date | None = None
    receipt_end: date | None = None
    winner_date: date | None = None
    households: int | None = None
    developer: str = ""
    phone: str = ""
    url: str = ""
    extras: dict[str, str] = field(default_factory=dict)       # 상태 등 부가 정보
    special_supply: dict[str, int] = field(default_factory=dict)  # 특별공급 유형별 세대수

    @property
    def key(self) -> str:
        return f"{self.source}:{self.uid}"
