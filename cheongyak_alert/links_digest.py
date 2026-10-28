"""조회가 안 될 때도 사용자가 직접 확인할 수 있도록 보내는 링크 모음."""
from __future__ import annotations

from datetime import date
from email.message import EmailMessage
from html import escape

from .config import Settings
from .realestate import fmt_money, land_search_url

CHEONGYAK_LINKS = [
    ("청약홈 (APT 분양·무순위 — '별내' 또는 '남양주'로 검색)", "https://www.applyhome.co.kr"),
    ("LH청약플러스 분양·임대 공고문 목록", "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancList.do?mi=1026"),
    ("마이홈포털 (공공임대·통합공공임대 입주자 모집)", "https://www.myhome.go.kr"),
    ("남양주시청 (고시·공고)", "https://www.nyj.go.kr"),
]
LISTING_LINKS = [
    ("직방", "https://www.zigbang.com"),
    ("다방", "https://www.dabangapp.com"),
    ("국토부 실거래가 공개시스템 (전세 시세 확인)", "https://rt.molit.go.kr"),
]


def sections(cfg: Settings, kinds: set[str]) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """(제목, 설명, [(이름, URL)])"""
    out = []
    if "cheongyak" in kinds:
        out.append(("청약 공고 확인", "남양주 별내동 부근 공고를 직접 볼 수 있는 곳입니다.", CHEONGYAK_LINKS))
    if "listings" in kinds:
        c = cfg.listings.criteria
        desc = (f"조건: 전세 {fmt_money(c.max_deposit)} 이하 · 전용 {c.area_min:g}~{c.area_max:g}㎡ · "
                f"{'/'.join({'APT': '아파트', 'VL': '빌라·다세대'}.get(t, t) for t in c.types)}. "
                "네이버부동산은 지도가 열리면 가격·면적 필터를 화면에서 설정하세요.")
        links = [(f"네이버부동산 - {a.name}", land_search_url(a, c))
                 for a in sorted(cfg.listings.areas, key=lambda a: a.rank)] + LISTING_LINKS
        out.append(("전세 매물 확인", desc, links))
    return out


def build_subject(kinds: set[str]) -> str:
    names = " · ".join(n for k, n in (("cheongyak", "청약 공고"), ("listings", "전세 매물")) if k in kinds)
    return f"[링크모음] {names} 확인 링크"


def build_text(cfg: Settings, kinds: set[str], reasons: list[str]) -> str:
    out: list[str] = []
    if reasons:
        out += ["자동 조회를 하지 못해 직접 확인할 수 있는 링크를 보냅니다."] + [f"  - {r}" for r in reasons] + [""]
    for title, desc, links in sections(cfg, kinds):
        out += [title, f"  {desc}"] + [f"  - {n}: {u}" for n, u in links] + [""]
    return "\n".join(out)


def build_html(cfg: Settings, kinds: set[str], reasons: list[str]) -> str:
    parts = []
    if reasons:
        items = "".join(f"<li>{escape(r)}</li>" for r in reasons)
        parts.append(f"<p style='font-size:14px'>자동 조회를 하지 못해 직접 확인할 수 있는 링크를 보냅니다.</p>"
                     f"<ul style='font-size:13px;color:#868e96'>{items}</ul>")
    for title, desc, links in sections(cfg, kinds):
        items = "".join(f"<li style='margin:4px 0'><a href='{escape(u, quote=True)}'>{escape(n)}</a></li>" for n, u in links)
        parts.append(f"<div style='border:1px solid #dee2e6;border-radius:8px;padding:12px 16px;margin:0 0 12px'>"
                     f"<div style='font-size:16px;font-weight:700'>{escape(title)}</div>"
                     f"<div style='font-size:13px;color:#495057;margin:4px 0 6px'>{escape(desc)}</div>"
                     f"<ul style='font-size:14px;padding-left:18px;margin:0'>{items}</ul></div>")
    return ("<div style='font-family:-apple-system,Segoe UI,Malgun Gothic,sans-serif;max-width:640px;color:#212529'>"
            + "".join(parts) + "</div>")


def make_builder(cfg: Settings, kinds: set[str], reasons: list[str]):
    def build(sender: str, to: str) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = build_subject(kinds), sender, to
        msg.set_content(build_text(cfg, kinds, reasons))
        msg.add_alternative(build_html(cfg, kinds, reasons), subtype="html")
        return msg
    return build
