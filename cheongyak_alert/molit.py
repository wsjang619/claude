"""국토교통부 아파트·연립다세대 전월세 실거래가 (공공데이터포털). 매물 알림의 시세 참고용."""
from __future__ import annotations

import re
import statistics
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from typing import Callable

from .models import SourceError

ENDPOINTS = {   # 구분 -> (URL, 건물명 태그)
    "아파트": ("https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent", ("aptNm", "아파트")),
    "연립다세대": ("https://apis.data.go.kr/1613000/RTMSDataSvcRHRent/getRTMSDataSvcRHRent", ("mhouseNm", "연립다세대")),
}
OK_CODES = {"00", "000"}


@dataclass
class Trade:
    kind: str
    name: str
    dong: str
    area_m2: float
    deposit: int      # 만원
    monthly: int
    day: date
    floor: str


def _tag(item: ET.Element, *names: str) -> str:
    for n in names:
        el = item.find(n)
        if el is not None and el.text and el.text.strip():
            return el.text.strip()
    return ""


def _num(v: str) -> int:
    d = v.replace(",", "").strip()
    return int(float(d)) if d else 0


def parse_trades(xml_text: str, kind: str, name_tags: tuple[str, ...]) -> list[Trade]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        raise SourceError(f"실거래 응답 XML 파싱 실패: {xml_text[:200]}") from None
    code = (root.findtext(".//resultCode") or "").strip()
    if code and code not in OK_CODES:
        raise SourceError(f"실거래 API 오류 {code} {root.findtext('.//resultMsg') or ''}".strip())
    if not code and root.tag == "OpenAPI_ServiceResponse":   # 인증키 오류 등
        raise SourceError(f"실거래 API 오류 {root.findtext('.//returnReasonCode')} {root.findtext('.//returnAuthMsg')}")
    out: list[Trade] = []
    for it in root.iter("item"):
        try:
            out.append(Trade(
                kind=kind, name=_tag(it, *name_tags), dong=_tag(it, "umdNm", "법정동"),
                area_m2=float(_tag(it, "excluUseAr", "전용면적") or 0),
                deposit=_num(_tag(it, "deposit", "보증금액")), monthly=_num(_tag(it, "monthlyRent", "월세금액")),
                day=date(int(_tag(it, "dealYear", "년")), int(_tag(it, "dealMonth", "월")),
                         int(_tag(it, "dealDay", "일"))),
                floor=_tag(it, "floor", "층")))
        except (ValueError, TypeError):
            continue      # 필드가 비정상인 행은 건너뜀
    return out


def _norm(name: str) -> str:
    return re.sub(r"[\s()·\-]|아파트", "", name)


@dataclass
class Stats:
    count: int
    low: int
    median: int
    high: int


class Market:
    def __init__(self, trades: list[Trade]):
        self.trades = trades

    def stats(self, dong: str) -> Stats | None:
        v = sorted(t.deposit for t in self.trades if t.dong == dong)
        return Stats(len(v), v[0], int(statistics.median(v)), v[-1]) if v else None

    def recent(self, title: str, dong: str, limit: int = 3) -> list[Trade]:
        """같은 단지(건물명이 서로 포함 관계)의 최근 전세 거래."""
        want = _norm(title)
        if len(want) < 2:
            return []
        hits = [t for t in self.trades if t.dong == dong and (_norm(t.name) in want or want in _norm(t.name))
                and _norm(t.name)]
        return sorted(hits, key=lambda t: t.day, reverse=True)[:limit]


def months_back(today: date, months: int) -> list[str]:
    out, y, m = [], today.year, today.month
    for _ in range(months):
        out.append(f"{y}{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out


def load_market(fetch_text: Callable[..., str], service_key: str, lawd_cds: set[str], today: date, *,
                months: int, area_min: float, area_max: float) -> tuple[Market, list[str]]:
    """지정한 시군구들의 최근 N개월 전세(월세 0) 실거래 중 면적 조건에 맞는 것."""
    trades: list[Trade] = []
    errors: list[str] = []
    for lawd in sorted(lawd_cds):
        for ym in months_back(today, months):
            for kind, (url, name_tags) in ENDPOINTS.items():
                try:
                    body = fetch_text(url, {"serviceKey": service_key, "LAWD_CD": lawd, "DEAL_YMD": ym,
                                            "pageNo": 1, "numOfRows": 1000})
                    trades += [t for t in parse_trades(body, kind, name_tags)
                               if t.monthly == 0 and area_min <= t.area_m2 <= area_max]
                except SourceError as e:
                    errors.append(f"실거래 {kind} {lawd}/{ym}: {e}")
    return Market(trades), errors
