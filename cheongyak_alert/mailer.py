from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from html import escape

from .config import MailEnv
from .matcher import Match
from .profile import Profile
from .summary import fmt_date as _fmt_date, links, summarize


@dataclass
class Entry:
    match: Match
    reminder: bool = False   # True: 이미 알린 공고의 접수 임박 재알림


def _fmt(d: date | None) -> str:
    return f"{d.month}/{d.day}({'월화수목금토일'[d.weekday()]})" if d else "-"


def _period(n, today: date) -> str:
    s, e = n.receipt_start, n.receipt_end
    if not (s or e):
        return "공고문 확인"
    text = _fmt(s) if s == e or not e else f"{_fmt(s)} ~ {_fmt(e)}" if s else f"~ {_fmt(e)}"
    if s and today < s:
        return f"{text}  · D-{(s - today).days}"
    if e and today <= e:
        return f"{text}  · 접수중, 마감 D-{(e - today).days}" if e != today else f"{text}  · 오늘 마감"
    return f"{text}  · 마감"


def _rows(e: Entry, today: date) -> list[tuple[str, str]]:
    n = e.match.notice
    rows = [("구분", n.category), ("위치", n.address or "-"), ("접수", _period(n, today))]
    if n.winner_date:
        rows.append(("당첨자 발표", _fmt(n.winner_date)))
    if n.households:
        rows.append(("공급 세대", f"{n.households:,}세대"))
    if n.special_supply:
        rows.append(("특별공급", " · ".join(f"{k} {v}" for k, v in n.special_supply.items())))
    if n.developer:
        rows.append(("사업주체", n.developer))
    if n.phone:
        rows.append(("문의", n.phone))
    rows += [(k, v) for k, v in n.extras.items() if not k.startswith("_")]
    return rows


def _heading(e: Entry) -> str:
    tag = "접수 임박" if e.reminder else "신규"
    return f"[{tag}] [{e.match.area.name}] {e.match.notice.title}"


def build_subject(entries: list[Entry]) -> str:
    new = [e for e in entries if not e.reminder]
    head = entries[0].match
    prefix = f"[청약알림] 신규 {len(new)}건" if new else f"[청약알림] 접수 임박 {len(entries)}건"
    more = f" 외 {len(entries) - 1}건" if len(entries) > 1 else ""
    return f"{prefix} — {head.notice.title}{more}"


def _oneline(e: Entry) -> str:
    n = e.match.notice
    when = f"접수 {_fmt_date(n.receipt_start)}" if n.receipt_start else (
        f"~{_fmt_date(n.receipt_end)} 마감" if n.receipt_end else "일정 확인")
    return f"[{'임박' if e.reminder else '신규'}] {e.match.area.name} · {n.title} · {when}"


def build_text(entries: list[Entry], profile: Profile | None, today: date, errors: list[str]) -> str:
    out: list[str] = []
    if len(entries) > 1:
        out += ["한눈에 보기"] + [f"  - {_oneline(e)}" for e in entries] + [""]
    for e in entries:
        n = e.match.notice
        out += [_heading(e), f"  요약: {summarize(n, today, e.reminder)}", ""]
        out += [f"  {k}: {v}" for k, v in _rows(e, today)]
        out += ["  링크"] + [f"    {name}: {url}" for name, url in links(n)] + [""]
    if profile and (hints := profile.hints(today)):
        out += ["내 조건 체크 (참고용, 최종 자격은 공고문 기준)"] + [f"  - {h}" for h in hints] + [""]
    if errors:
        out += ["일부 조회 실패"] + [f"  - {x}" for x in errors] + [""]
    return "\n".join(out)


def _link_html(n) -> str:
    return " &nbsp;|&nbsp; ".join(f"<a href='{escape(u, quote=True)}'>{escape(name)}</a>" for name, u in links(n))


def build_html(entries: list[Entry], profile: Profile | None, today: date, errors: list[str]) -> str:
    cards = []
    if len(entries) > 1:
        items = "".join(f"<li>{escape(_oneline(e))}</li>" for e in entries)
        cards.append(f"<div style='font-size:14px;margin:0 0 14px'><b>한눈에 보기</b><ul style='margin:4px 0;padding-left:18px'>{items}</ul></div>")
    for e in entries:
        n = e.match.notice
        color = "#d9480f" if e.reminder else "#1c7ed6"
        tag = "접수 임박" if e.reminder else "신규"
        rows = "".join(
            f"<tr><td style='color:#868e96;padding:2px 12px 2px 0;white-space:nowrap'>{escape(k)}</td>"
            f"<td style='padding:2px 0'>{escape(v)}</td></tr>" for k, v in _rows(e, today))
        cards.append(
            f"<div style='border:1px solid #dee2e6;border-radius:8px;padding:14px 16px;margin:0 0 14px'>"
            f"<div><span style='background:{color};color:#fff;border-radius:4px;padding:1px 6px;font-size:12px'>{tag}</span> "
            f"<span style='color:#495057;font-size:12px'>{escape(e.match.area.name)}</span></div>"
            f"<div style='font-size:17px;font-weight:700;margin:6px 0 8px'>{escape(n.title)}</div>"
            f"<div style='font-size:14px;line-height:1.6;background:#f1f3f5;border-radius:6px;padding:8px 10px;margin-bottom:8px'>"
            f"{escape(summarize(n, today, e.reminder))}</div>"
            f"<table style='font-size:14px;border-collapse:collapse'>{rows}</table>"
            f"<div style='margin-top:10px;font-size:14px'>{_link_html(n)}</div></div>")
    extra = ""
    if profile and (hints := profile.hints(today)):
        items = "".join(f"<li>{escape(h)}</li>" for h in hints)
        extra += (f"<div style='background:#f8f9fa;border-radius:8px;padding:12px 16px;font-size:14px'>"
                  f"<b>내 조건 체크</b> <span style='color:#868e96'>(참고용, 최종 자격은 공고문 기준)</span>"
                  f"<ul style='margin:6px 0 0;padding-left:18px'>{items}</ul></div>")
    if errors:
        items = "".join(f"<li>{escape(x)}</li>" for x in errors)
        extra += f"<div style='margin-top:14px;color:#c92a2a;font-size:13px'><b>일부 조회 실패</b><ul>{items}</ul></div>"
    return (f"<div style='font-family:-apple-system,Segoe UI,Malgun Gothic,sans-serif;max-width:640px;color:#212529'>"
            f"{''.join(cards)}{extra}</div>")


def build_message(entries: list[Entry], profile: Profile | None, today: date, errors: list[str],
                  sender: str, to: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = build_subject(entries)
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(build_text(entries, profile, today, errors))
    msg.add_alternative(build_html(entries, profile, today, errors), subtype="html")
    return msg


def send_smtp(msg: EmailMessage, env: MailEnv) -> None:
    ctx = ssl.create_default_context()
    if env.port == 465:
        with smtplib.SMTP_SSL(env.host, env.port, context=ctx, timeout=30) as s:
            s.login(env.user, env.password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(env.host, env.port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(env.user, env.password)
            s.send_message(msg)
