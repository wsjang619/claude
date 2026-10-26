from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol

from .config import Settings
from .mailer import Entry
from .matcher import match
from .models import Notice
from .state import State


class Source(Protocol):
    id: str       # Notice.source 와 같은 값
    name: str
    def fetch(self, since: date) -> tuple[list[Notice], list[str]]: ...
    def enrich(self, notice: Notice) -> None: ...


@dataclass
class Result:
    entries: list[Entry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)   # 소스별 조회 건수


def _is_open(n: Notice, today: date) -> bool:
    return n.receipt_end is None or n.receipt_end >= today


def collect(sources: list[Source], cfg: Settings, state: State, today: date) -> Result:
    res = Result()
    since = today - timedelta(days=cfg.lookback_days)
    notices: dict[str, Notice] = {}
    for src in sources:
        try:
            got, errs = src.fetch(since)
        except Exception as e:  # 한 소스의 예기치 못한 오류가 다른 소스를 막지 않도록
            got, errs = [], [f"{src.name}: {type(e).__name__}: {e}"]
        res.stats[src.name] = len(got)
        res.errors += errs
        notices.update({n.key: n for n in got})
    by_source = {s.id: s for s in sources}

    soon = today + timedelta(days=cfg.remind_days_before)
    for n in notices.values():
        m = match(n, cfg.areas)
        if not m:
            continue
        if not cfg.include_closed and not _is_open(n, today):
            continue
        if not state.is_seen(n.key):
            res.entries.append(Entry(m))
        elif (not state.is_reminded(n.key) and n.receipt_start
              and today <= n.receipt_start <= soon):
            res.entries.append(Entry(m, reminder=True))

    # 별내동에 가까운 순 -> 접수 시작이 빠른 순
    res.entries.sort(key=lambda e: (e.match.area.rank, e.match.notice.receipt_start or date.max))
    for e in res.entries:
        by_source[e.match.notice.source].enrich(e.match.notice)
    return res


def commit(res: Result, state: State, today: date, soon_days: int) -> None:
    """메일 발송에 성공한 뒤에만 호출한다."""
    soon = today + timedelta(days=soon_days)
    for e in res.entries:
        n = e.match.notice
        state.mark_seen(n.key, n.title, today)
        if e.reminder or (n.receipt_start and today <= n.receipt_start <= soon):
            state.mark_reminded(n.key)
