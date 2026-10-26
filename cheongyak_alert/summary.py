"""공고 한 건을 사람이 읽기 쉬운 요약 문단과 관련 링크로 바꾼다."""
from __future__ import annotations

from datetime import date
from urllib.parse import quote

from .models import Notice

WEEKDAYS = "월화수목금토일"


def fmt_date(d: date) -> str:
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


def dday(d: date, today: date) -> str:
    n = (d - today).days
    return "오늘" if n == 0 else f"D-{n}" if n > 0 else f"D+{-n}"


def summarize(n: Notice, today: date, reminder: bool = False) -> str:
    where = f"{n.address}의 " if n.address and n.source == "applyhome" else ""
    size = f"{n.households:,}세대 규모 " if n.households else ""
    out = [f"{where}{size}{n.category} 공고입니다."]
    s, e = n.receipt_start, n.receipt_end
    if s and e and s != e:
        out.append(f"청약 접수는 {fmt_date(s)}~{fmt_date(e)}이며 접수 시작까지 {dday(s, today)}입니다."
                   if today < s else f"청약 접수는 {fmt_date(s)}~{fmt_date(e)}이고 마감까지 {dday(e, today)}입니다."
                   if today <= e else f"청약 접수는 {fmt_date(s)}~{fmt_date(e)}로 마감됐습니다.")
    elif s or e:
        d = s or e
        out.append(f"청약 접수일은 {fmt_date(d)}({dday(d, today)})입니다." if s else
                   f"접수 마감은 {fmt_date(d)}({dday(d, today)})입니다.")
    else:
        out.append("접수 일정은 공고문에서 확인하세요.")
    if n.winner_date:
        out.append(f"당첨자 발표는 {fmt_date(n.winner_date)}입니다.")
    if n.special_supply:
        out.append("특별공급은 " + ", ".join(f"{k} {v}세대" for k, v in n.special_supply.items()) + "입니다.")
    if reminder:
        out.append("접수가 곧 시작되니 준비하세요.")
    return " ".join(out)


def links(n: Notice) -> list[tuple[str, str]]:
    """(표시 이름, URL). 중복 URL은 하나만 남긴다."""
    out: list[tuple[str, str]] = [("공고 상세", n.url)]
    if home := n.extras.get("_homepage"):
        out.append(("단지 홈페이지", home))
    if n.source == "applyhome":
        out.append(("청약홈 (신청·일정)", "https://www.applyhome.co.kr"))
    else:
        out.append(("LH청약플러스", "https://apply.lh.or.kr"))
    query = n.address if n.source == "applyhome" and n.address else n.title
    out.append(("지도에서 보기", f"https://map.naver.com/p/search/{quote(query)}"))
    seen: set[str] = set()
    return [(name, u) for name, u in out if u and not (u in seen or seen.add(u))]
