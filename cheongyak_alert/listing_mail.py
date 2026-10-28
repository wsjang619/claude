from __future__ import annotations

from datetime import date
from email.message import EmailMessage
from html import escape
from urllib.parse import quote

from .listing_runner import ListingResult
from .molit import Market
from .realestate import Criteria, Listing, fmt_money, land_search_url
from .summary import fmt_date


def _headline(l: Listing) -> str:
    bits = [fmt_money(l.deposit) if l.deposit is not None else "가격 확인", l.kind or "매물"]
    if l.area_m2:
        bits.append(f"전용 {l.area_m2:g}㎡")
    if l.floor:
        bits.append(f"{l.floor}층")
    return " · ".join(bits)


def _links(l: Listing) -> list[tuple[str, str]]:
    return [("네이버부동산 매물", l.url),
            ("지도에서 보기", f"https://map.naver.com/p/search/{quote(f'{l.area.name} {l.title}')}")]


def _recent_line(l: Listing, market: Market | None) -> str:
    if not market or not l.area.dong:
        return ""
    rows = market.recent(l.title, l.area.dong)
    if not rows:
        return ""
    return "같은 단지 최근 전세 실거래: " + ", ".join(
        f"{t.day.month}/{t.day.day} {t.area_m2:g}㎡ {fmt_money(t.deposit)}" for t in rows)


def _market_lines(areas, market: Market | None) -> list[str]:
    if not market:
        return []
    out = []
    for a in sorted({a.dong: a for a in areas if a.dong}.values(), key=lambda a: a.rank):
        s = market.stats(a.dong)
        if s:
            out.append(f"{a.name} 최근 전세 실거래 {s.count}건: 최저 {fmt_money(s.low)} · 중간 {fmt_money(s.median)} · 최고 {fmt_money(s.high)}")
    return out


def build_subject(res: ListingResult) -> str:
    n = len(res.new)
    cheapest = min((l.deposit for l in res.new if l.deposit is not None), default=None)
    tail = f" — 최저 {fmt_money(cheapest)}" if cheapest is not None else ""
    return (f"[매물알림] 현재 전세 매물 {n}건 (기준선){tail}" if res.baseline
            else f"[매물알림] 신규 전세 {n}건{tail}")


def _intro(res: ListingResult, c: Criteria) -> str:
    cond = f"전세 보증금 {fmt_money(c.max_deposit)} 이하 · 전용 {c.area_min:g}~{c.area_max:g}㎡"
    if res.baseline:
        return f"첫 조회 결과입니다. 조건({cond})에 맞는 현재 매물이며, 이후에는 새로 올라온 매물만 알려드립니다."
    return f"조건({cond})에 맞는 새 매물입니다."


def build_text(res: ListingResult, c: Criteria, market: Market | None, today: date) -> str:
    out = [_intro(res, c), ""]
    out += [f"[시세 참고] {x}" for x in _market_lines({l.area for l in res.shown}, market)]
    out += ["지역별 전체 매물 보기 (네이버부동산)"] + [
        f"  - {a.name}: {land_search_url(a, c)}" for a in sorted({l.area for l in res.shown}, key=lambda a: a.rank)] + [""]
    out += ["한눈에 보기"] + [f"  - {l.area.name} · {l.title} · {_headline(l)}" for l in res.shown] + [""]
    for l in res.shown:
        out += [f"[{l.area.name}] {l.title}", f"  {_headline(l)}"]
        if l.description:
            out.append(f"  설명: {l.description}")
        if l.realtor:
            out.append(f"  중개: {l.realtor}")
        if l.confirmed:
            out.append(f"  확인: {fmt_date(l.confirmed)}")
        if r := _recent_line(l, market):
            out.append(f"  {r}")
        out += [f"  {n}: {u}" for n, u in _links(l)] + [""]
    if res.overflow:
        out.append(f"그 밖에 새 매물 {res.overflow}건이 더 있습니다. 네이버부동산에서 확인하세요.")
    if res.errors:
        out += ["", "일부 조회 실패"] + [f"  - {e}" for e in res.errors]
    return "\n".join(out)


def build_html(res: ListingResult, c: Criteria, market: Market | None, today: date) -> str:
    parts = [f"<p style='font-size:14px'>{escape(_intro(res, c))}</p>"]
    if lines := _market_lines({l.area for l in res.shown}, market):
        items = "".join(f"<li>{escape(x)}</li>" for x in lines)
        parts.append(f"<div style='background:#f8f9fa;border-radius:8px;padding:10px 16px;font-size:14px;margin-bottom:14px'>"
                     f"<b>시세 참고</b> <span style='color:#868e96'>(국토부 전세 실거래, 조건 면적)</span><ul style='margin:4px 0;padding-left:18px'>{items}</ul></div>")
    area_links = " &nbsp;|&nbsp; ".join(
        f"<a href='{escape(land_search_url(a, c), quote=True)}'>{escape(a.name)} 전체 매물</a>"
        for a in sorted({l.area for l in res.shown}, key=lambda a: a.rank))
    parts.append(f"<p style='font-size:14px'>{area_links}</p>")
    for l in res.shown:
        meta = " &nbsp;·&nbsp; ".join(escape(x) for x in (l.description, l.realtor and f"중개 {l.realtor}",
                                                          l.confirmed and f"확인 {fmt_date(l.confirmed)}") if x)
        recent = escape(_recent_line(l, market))
        links = " &nbsp;|&nbsp; ".join(f"<a href='{escape(u, quote=True)}'>{escape(n)}</a>" for n, u in _links(l))
        parts.append(
            f"<div style='border:1px solid #dee2e6;border-radius:8px;padding:14px 16px;margin:0 0 12px'>"
            f"<div style='color:#495057;font-size:12px'>{escape(l.area.name)}</div>"
            f"<div style='font-size:17px;font-weight:700;margin:4px 0'>{escape(l.title)}</div>"
            f"<div style='font-size:15px;color:#1c7ed6;font-weight:600'>{escape(_headline(l))}</div>"
            + (f"<div style='font-size:13px;color:#495057;margin-top:6px'>{meta}</div>" if meta else "")
            + (f"<div style='font-size:13px;background:#f1f3f5;border-radius:6px;padding:6px 8px;margin-top:8px'>{recent}</div>" if recent else "")
            + f"<div style='margin-top:10px;font-size:14px'>{links}</div></div>")
    if res.overflow:
        parts.append(f"<p style='font-size:14px'>그 밖에 새 매물 {res.overflow}건이 더 있습니다. 네이버부동산에서 확인하세요.</p>")
    if res.errors:
        items = "".join(f"<li>{escape(e)}</li>" for e in res.errors)
        parts.append(f"<div style='color:#c92a2a;font-size:13px'><b>일부 조회 실패</b><ul>{items}</ul></div>")
    return ("<div style='font-family:-apple-system,Segoe UI,Malgun Gothic,sans-serif;max-width:640px;color:#212529'>"
            + "".join(parts) + "</div>")


def build_message(res: ListingResult, c: Criteria, market: Market | None, today: date,
                  sender: str, to: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = build_subject(res), sender, to
    msg.set_content(build_text(res, c, market, today))
    msg.add_alternative(build_html(res, c, market, today), subtype="html")
    return msg
