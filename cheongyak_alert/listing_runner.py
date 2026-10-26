from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .realestate import Listing
from .state import State


@dataclass
class ListingResult:
    shown: list[Listing] = field(default_factory=list)   # 메일에 실을 매물
    overflow: int = 0                                    # 상한 때문에 못 실은 신규 매물 수
    total_found: int = 0
    baseline: bool = False                               # 첫 실행: 현재 매물 전체를 기준선으로 기록
    errors: list[str] = field(default_factory=list)
    new: list[Listing] = field(default_factory=list)

    def shown_areas(self):
        return {l.area for l in self.shown}


def select(found: list[Listing], state: State, *, max_items: int) -> ListingResult:
    res = ListingResult(total_found=len(found), baseline=not state.seen)
    res.new = sorted((l for l in found if not state.is_seen(l.key)),
                     key=lambda l: (l.area.rank, l.deposit if l.deposit is not None else 10**9))
    res.shown, res.overflow = res.new[:max_items], max(0, len(res.new) - max_items)
    return res


def commit(res: ListingResult, state: State, today: date) -> None:
    """메일 발송 성공 후 호출. 상한을 넘은 신규 매물도 알린 것으로 처리해 다음 실행에 쏟아지지 않게 한다."""
    for l in res.new:
        state.mark_seen(l.key, l.title, today)
