"""네이버부동산 비공식 조회로 전세 매물을 가져온다.

공식 API가 아니라 웹 화면이 쓰는 주소를 호출한다. 네이버 약관상 허용되지 않을 수 있고,
언제든 바뀌거나 차단(401/403/429)될 수 있다. 차단되면 재시도하지 않고 오류로 보고한다.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from .models import SourceError, parse_date

LAND = "https://new.land.naver.com"
GYEONGGI = "4100000000"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

FetchJson = Callable[..., object]   # (url, params, headers=...) -> parsed JSON
FetchText = Callable[..., str]


def parse_price(text: object) -> int | None:
    """'2억 5,000' -> 25000, '3억' -> 30000, '9,500' -> 9500 (단위: 만원)."""
    s = str(text or "").replace(",", "").replace("만원", "").replace("원", "")
    m = re.fullmatch(r"\s*(?:(\d+)\s*억)?\s*(\d+)?\s*", s)
    if not m or not (m.group(1) or m.group(2)):
        return None
    return int(m.group(1) or 0) * 10000 + int(m.group(2) or 0)


def fmt_money(man_won: int) -> str:
    eok, rest = divmod(man_won, 10000)
    if eok and rest:
        return f"{eok}억 {rest:,}만원"
    return f"{eok}억원" if eok else f"{rest:,}만원"


@dataclass
class Criteria:
    types: tuple[str, ...] = ("APT", "VL")   # APT 아파트 / VL 빌라·연립·다세대
    max_deposit: int = 30000                  # 만원
    area_min: float = 59
    area_max: float = 85


@dataclass(frozen=True)
class ListingArea:
    name: str
    rank: int
    path: tuple[str, ...] = ()       # 경기도 아래 (시군구, 읍면동) 이름
    cortar_no: str = ""              # 알고 있으면 이름 조회를 건너뜀
    lawd_cd: str = ""                # 국토부 실거래 조회용 시군구 코드 5자리
    dong: str = ""                   # 실거래에서 거를 법정동 이름
    lat: float = 0.0                 # 지도 링크의 중심 좌표 (대략값이면 충분)
    lon: float = 0.0


def land_search_url(area: ListingArea, c: Criteria) -> str:
    """네이버부동산 지도 화면 링크 (지역 중심, 매물유형, 전세). 가격·면적 필터는 화면에서 설정한다."""
    if not (area.lat and area.lon):
        return f"{LAND}/complexes"
    return f"{LAND}/complexes?ms={area.lat},{area.lon},16&a={':'.join(c.types)}&b=B1&e=RETAIL"


@dataclass
class Listing:
    uid: str
    title: str
    kind: str
    deposit: int | None              # 만원
    area_m2: float | None            # 전용면적
    floor: str
    area: ListingArea
    description: str = ""
    realtor: str = ""
    confirmed: date | None = None
    url: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"naver:{self.uid}"


def _float(v: object) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def article_to_listing(a: dict, area: ListingArea) -> Listing | None:
    no = a.get("articleNo")
    if not no:
        return None
    return Listing(
        uid=str(no),
        title=(a.get("articleName") or a.get("buildingName") or "").strip(),
        kind=(a.get("realEstateTypeName") or "").strip(),
        deposit=parse_price(a.get("dealOrWarrantPrc")),
        area_m2=_float(a.get("area2")),
        floor=str(a.get("floorInfo") or "").strip(),
        area=area,
        description=(a.get("articleFeatureDesc") or "").strip(),
        realtor=(a.get("realtorName") or "").strip(),
        confirmed=parse_date(a.get("articleConfirmYmd")),
        url=f"https://m.land.naver.com/article/info/{no}",
        tags=[t for t in a.get("tagList") or [] if isinstance(t, str)],
    )


class NaverLandSource:
    def __init__(self, fetch_json: FetchJson, fetch_text: FetchText, criteria: Criteria,
                 areas: list[ListingArea], *, token: str = "", delay: float = 2.0,
                 max_pages: int = 5, sleep: Callable[[float], None] = time.sleep):
        self._json, self._text = fetch_json, fetch_text
        self.criteria, self.areas = criteria, areas
        self.token = token or os.environ.get("NAVER_LAND_TOKEN", "")
        self.delay, self.max_pages, self._sleep = delay, max_pages, sleep

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": BROWSER_UA, "Accept": "application/json, text/plain, */*",
                "Accept-Language": "ko-KR,ko;q=0.9", "Referer": f"{LAND}/",
                "Authorization": f"Bearer {self.token}"}

    def _ensure_token(self) -> None:
        if self.token:
            return
        html = self._text(f"{LAND}/complexes", {}, headers={"User-Agent": BROWSER_UA, "Accept": "text/html"})
        m = re.search(r'"token"\s*:\s*"(eyJ[\w.\-]+)"', html) or re.search(r"(eyJ[\w\-]+\.[\w\-]+\.[\w\-]+)", html)
        if not m:
            raise SourceError("네이버부동산 접근 토큰을 찾지 못했습니다 (화면 구조 변경 또는 차단). "
                              "브라우저 개발자도구에서 복사한 토큰을 NAVER_LAND_TOKEN으로 넣을 수 있습니다")
        self.token = m.group(1)

    def _get(self, path: str, params: dict) -> object:
        self._sleep(self.delay)
        return self._json(f"{LAND}{path}", params, headers=self._headers())

    def _resolve(self, area: ListingArea) -> str:
        if area.cortar_no:
            return area.cortar_no
        code = GYEONGGI
        for name in area.path:
            data = self._get("/api/regions/list", {"cortarNo": code})
            regions = data.get("regionList") if isinstance(data, dict) else None
            hit = next((r for r in regions or [] if r.get("cortarName") == name), None)
            if not hit:
                raise SourceError(f"지역 '{name}'을(를) 찾지 못했습니다 ({'>'.join(area.path)})")
            code = str(hit["cortarNo"])
        return code

    def _passes(self, l: Listing) -> bool:
        c = self.criteria
        if l.deposit is not None and l.deposit > c.max_deposit:
            return False
        return l.area_m2 is None or c.area_min <= l.area_m2 <= c.area_max

    def _articles(self, cortar_no: str) -> list[dict]:
        out: list[dict] = []
        c = self.criteria
        for page in range(1, self.max_pages + 1):
            data = self._get("/api/articles", {
                "cortarNo": cortar_no, "order": "rank", "realEstateType": ":".join(c.types),
                "tradeType": "B1", "tag": "::::::::", "rentPriceMin": 0, "rentPriceMax": 900000000,
                "priceMin": 0, "priceMax": c.max_deposit, "areaMin": int(c.area_min), "areaMax": int(c.area_max),
                "showArticle": "false", "sameAddressGroup": "false", "priceType": "RETAIL", "page": page})
            if not isinstance(data, dict) or "articleList" not in data:
                raise SourceError(f"예상과 다른 매물 응답 {str(data)[:200]}")
            out.extend(a for a in data["articleList"] if isinstance(a, dict))
            if not data.get("isMoreData"):
                break
        return out

    def fetch(self) -> tuple[list[Listing], list[str]]:
        found: dict[str, Listing] = {}
        errors: list[str] = []
        try:
            self._ensure_token()
        except SourceError as e:
            return [], [f"네이버부동산: {e}"]
        for area in sorted(self.areas, key=lambda a: a.rank):
            try:
                for a in self._articles(self._resolve(area)):
                    l = article_to_listing(a, area)
                    if (l and l.uid not in found and a.get("tradeTypeName", "전세") == "전세"
                            and self._passes(l)):
                        found[l.uid] = l
            except SourceError as e:
                errors.append(f"네이버부동산 {area.name}: {e}")
                if "HTTP 4" in str(e):      # 차단·인증 문제면 나머지 지역도 호출하지 않는다
                    break
        return list(found.values()), errors
