"""한국토지주택공사(LH) 분양임대공고문 (공공데이터포털 lhNoticeInfo1).

LH 공고는 주소 필드가 없어 공고명(PAN_NM)에 지역 키워드가 있는 것만 잡힌다.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from .models import Notice, SourceError, parse_date

DEFAULT_ENDPOINT = "https://apis.data.go.kr/B552555/lhNoticeInfo1/getNoticeInfo1"
OK_CODES = {"Y", "00", "0", "OK", "NORMAL SERVICE."}


def _find_rows(payload: object) -> list[dict]:
    """응답은 [{dsSch:[..]}, {dsList:[..], resHeader:[..]}] 형태이거나 dict. dsList를 찾는다."""
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k.lower() in ("dslist", "items") and isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
        for v in payload.values():
            if isinstance(v, (list, dict)) and (rows := _find_rows(v)):
                return rows
    elif isinstance(payload, list):
        for v in payload:
            if rows := _find_rows(v):
                return rows
    return []


def _check_header(payload: object) -> None:
    items = payload if isinstance(payload, list) else [payload]
    for it in items:
        if not isinstance(it, dict):
            continue
        for h in it.get("resHeader") or []:
            code = str(h.get("SS_CODE", "Y")).strip().upper()
            if code not in OK_CODES:
                raise SourceError(f"LH 응답 오류 SS_CODE={code} {h.get('CS_MSG', '')}")


def row_to_notice(row: dict) -> Notice | None:
    pan_id, title = row.get("PAN_ID"), (row.get("PAN_NM") or "").strip()
    if not pan_id or not title:
        return None
    kind = " ".join(x for x in (row.get("UPP_AIS_TP_NM"), row.get("AIS_TP_CD_NM")) if x)
    status = (row.get("PAN_SS") or "").strip()
    return Notice(
        source="lh",
        uid=str(pan_id),
        title=title,
        category=f"LH {kind}".strip(),
        address=(row.get("CNP_CD_NM") or "").strip(),
        announced=parse_date(row.get("PAN_DT")),
        receipt_end=parse_date(row.get("CLSG_DT")),
        url=(row.get("DTL_URL") or "https://apply.lh.or.kr").strip(),
        extras={"공고상태": status} if status else {},
    )


class LhSource:
    id = "lh"
    name = "LH"

    def __init__(self, fetch: Callable[[str, dict], object], service_key: str, *,
                 endpoint: str = DEFAULT_ENDPOINT, region_code: str = "41",
                 page_size: int = 200, max_pages: int = 10):
        self._fetch = fetch
        self._key = service_key
        self.endpoint = endpoint
        self.region_code = region_code
        self.page_size = page_size
        self.max_pages = max_pages

    def fetch(self, since: date) -> tuple[list[Notice], list[str]]:
        notices: list[Notice] = []
        try:
            for page in range(1, self.max_pages + 1):
                payload = self._fetch(self.endpoint, {
                    "serviceKey": self._key, "PG_SZ": self.page_size, "PAGE": page,
                    "CNP_CD": self.region_code, "PAN_NT_ST_DT": since.strftime("%Y.%m.%d"),
                })
                _check_header(payload)
                rows = _find_rows(payload)
                notices.extend(n for r in rows if (n := row_to_notice(r)))
                if len(rows) < self.page_size:
                    break
        except SourceError as e:
            return notices, [f"LH: {e}"]
        return notices, []

    def enrich(self, notice: Notice) -> None:
        pass
