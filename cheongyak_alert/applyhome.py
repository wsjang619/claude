"""한국부동산원 청약홈 분양정보 (공공데이터포털 ApplyhomeInfoDetailSvc)."""
from __future__ import annotations

from datetime import date
from typing import Callable

from .models import Notice, SourceError, parse_date

BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
DEFAULT_URL = "https://www.applyhome.co.kr"

# 엔드포인트 -> (uid 접두어, 구분 표시)
ENDPOINTS: dict[str, tuple[str, str]] = {
    "getAPTLttotPblancDetail": ("APT", "APT 분양"),
    "getRemndrLttotPblancDetail": ("RMN", "APT 무순위·잔여세대"),
    "getUrbtyOfctlLttotPblancDetail": ("URB", "오피스텔·도시형·민간임대"),
    "getPblPvtRentLttotPblancDetail": ("PVT", "공공지원민간임대"),
    "getOPTLttotPblancDetail": ("OPT", "임의공급"),
}

# 주택형별 상세(getAPTLttotPblancMdl)의 특별공급 세대수 필드
SPECIAL_FIELDS = {
    "신혼부부": "NWWDS_HSHLDCO",
    "생애최초": "LFE_FRST_HSHLDCO",
    "다자녀": "MNYCH_HSHLDCO",
    "신생아": "NWBB_HSHLDCO",
    "노부모부양": "OLD_PARNTS_SUPORT_HSHLDCO",
    "기관추천": "INSTT_RECOMEND_HSHLDCO",
}

Fetch = Callable[[str, dict], object]


def _int(v: object) -> int | None:
    try:
        return int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _dates(row: dict, *keys: str) -> list[date]:
    return [d for k in keys if (d := parse_date(row.get(k)))]


def row_to_notice(row: dict, endpoint: str) -> Notice | None:
    prefix, label = ENDPOINTS.get(endpoint, ("ETC", endpoint))
    manage, pblanc = row.get("HOUSE_MANAGE_NO"), row.get("PBLANC_NO")
    title = (row.get("HOUSE_NM") or "").strip()
    if not manage or not title:
        return None
    starts = _dates(row, "RCEPT_BGNDE", "SPSPLY_RCEPT_BGNDE", "SUBSCRPT_RCEPT_BGNDE")
    ends = _dates(row, "RCEPT_ENDDE", "SPSPLY_RCEPT_ENDDE", "SUBSCRPT_RCEPT_ENDDE")
    category = label
    detail = (row.get("HOUSE_DTL_SECD_NM") or row.get("HOUSE_SECD_NM") or "").strip()
    if detail and detail not in label:
        category = f"{label} ({detail})"
    return Notice(
        source="applyhome",
        uid=f"{prefix}-{manage}-{pblanc or 0}",
        title=title,
        category=category,
        address=(row.get("HSSPLY_ADRES") or "").strip(),
        announced=parse_date(row.get("RCRIT_PBLANC_DE")),
        receipt_start=min(starts) if starts else None,
        receipt_end=max(ends) if ends else None,
        winner_date=parse_date(row.get("PRZWNER_PRESNATN_DE")),
        households=_int(row.get("TOT_SUPLY_HSHLDCO")),
        developer=(row.get("BSNS_MBY_NM") or "").strip(),
        phone=(row.get("MDHS_TELNO") or row.get("INQRY_TELNO") or "").strip(),
        url=(row.get("PBLANC_URL") or DEFAULT_URL).strip(),
    )


class ApplyhomeSource:
    id = "applyhome"
    name = "청약홈"

    def __init__(self, fetch: Fetch, service_key: str, *, region: str = "경기",
                 endpoints: list[str] | None = None, special_supply_detail: bool = True,
                 per_page: int = 1000, max_pages: int = 20):
        self._fetch = fetch
        self._key = service_key
        self.region = region
        self.endpoints = endpoints or list(ENDPOINTS)
        self.special_supply_detail = special_supply_detail
        self.per_page = per_page
        self.max_pages = max_pages

    def _rows(self, endpoint: str, conds: dict[str, str]) -> list[dict]:
        rows: list[dict] = []
        for page in range(1, self.max_pages + 1):
            params = {"serviceKey": self._key, "page": page, "perPage": self.per_page,
                      "returnType": "JSON", **conds}
            data = self._fetch(f"{BASE}/{endpoint}", params)
            if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                raise SourceError(f"{endpoint}: 예상과 다른 응답 형식 {str(data)[:200]}")
            rows.extend(r for r in data["data"] if isinstance(r, dict))
            total = _int(data.get("matchCount")) or _int(data.get("totalCount")) or 0
            if not data["data"] or len(rows) >= total:
                break
        return rows

    def _endpoint_rows(self, endpoint: str, since: date) -> list[dict]:
        region_cond = {"cond[SUBSCRPT_AREA_CODE_NM::EQ]": self.region}
        try:
            return self._rows(endpoint, {**region_cond, "cond[RCRIT_PBLANC_DE::GTE]": since.isoformat()})
        except SourceError as e:
            if "HTTP 4" not in str(e):
                raise
            # 날짜 조건이 거부되는 경우: 지역 조건만으로 받고 날짜는 로컬에서 거른다
            return [r for r in self._rows(endpoint, region_cond)
                    if (d := parse_date(r.get("RCRIT_PBLANC_DE"))) is None or d >= since]

    def fetch(self, since: date) -> tuple[list[Notice], list[str]]:
        notices: list[Notice] = []
        errors: list[str] = []
        for endpoint in self.endpoints:
            try:
                for row in self._endpoint_rows(endpoint, since):
                    n = row_to_notice(row, endpoint)
                    if n:
                        n.extras["_manage_no"] = str(row.get("HOUSE_MANAGE_NO"))
                        n.extras["_pblanc_no"] = str(row.get("PBLANC_NO"))
                        n.extras["_endpoint"] = endpoint
                        notices.append(n)
            except SourceError as e:
                errors.append(f"청약홈 {endpoint}: {e}")
        return notices, errors

    def enrich(self, notice: Notice) -> None:
        """APT 분양 공고의 특별공급 유형별 세대수를 채운다. 실패해도 알림에는 영향 없음."""
        if not self.special_supply_detail or notice.extras.get("_endpoint") != "getAPTLttotPblancDetail":
            return
        try:
            rows = self._rows("getAPTLttotPblancMdl", {
                "cond[HOUSE_MANAGE_NO::EQ]": notice.extras["_manage_no"],
                "cond[PBLANC_NO::EQ]": notice.extras["_pblanc_no"],
            })
        except SourceError:
            return
        for label, field_name in SPECIAL_FIELDS.items():
            total = sum(_int(r.get(field_name)) or 0 for r in rows)
            if total:
                notice.special_supply[label] = total
