from __future__ import annotations

from dataclasses import dataclass

from .models import Notice


@dataclass(frozen=True)
class Area:
    name: str
    rank: int            # 작을수록 별내동에 가까움
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class Match:
    notice: Notice
    area: Area


def match(notice: Notice, areas: list[Area]) -> Match | None:
    haystack = f"{notice.title} {notice.address}"
    hits = [a for a in areas if any(k in haystack for k in a.keywords)]
    return Match(notice, min(hits, key=lambda a: a.rank)) if hits else None
