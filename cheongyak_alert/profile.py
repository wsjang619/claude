"""가구 정보를 바탕으로 공고마다 공통으로 붙는 '내 조건 체크' 문구를 만든다.

자격 판정이 아니라 어떤 공급유형을 공고문에서 확인해 볼지 알려주는 참고용이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


def _months_between(start: date, end: date) -> int:
    m = (end.year - start.year) * 12 + (end.month - start.month)
    return m - 1 if end.day < start.day else m


@dataclass
class Profile:
    birth_year: int
    married_on: date | None = None
    children_born: list[date] = field(default_factory=list)
    homeless: bool = True
    extra_dependents: int = 0       # 배우자·자녀 외 부양가족(직계존속 등)
    account_open: date | None = None  # 청약통장 가입일

    def child_ages(self, today: date) -> list[int]:
        return [_months_between(b, today) // 12 for b in self.children_born]

    def homeless_months(self, today: date) -> int | None:
        """가점제 무주택기간 기산일: 만 30세 생일과 혼인일 중 빠른 날 (연도 단위 근사)."""
        if not self.married_on:
            return None
        start = min(self.married_on, date(self.birth_year + 30, 1, 1))
        return _months_between(start, today)

    def score(self, today: date) -> dict[str, int] | None:
        """일반공급 가점 (무주택기간·부양가족·통장). 무주택 유지 가정."""
        months = self.homeless_months(today)
        if not self.homeless or months is None:
            return None
        dependents = (1 if self.married_on else 0) + len(self.children_born) + self.extra_dependents
        out = {
            "무주택기간": 2 + 2 * min(months // 12, 15),
            "부양가족": 5 + 5 * min(dependents, 6),
        }
        if self.account_open:
            am = _months_between(self.account_open, today)
            out["통장가입기간"] = 1 if am < 6 else 2 if am < 12 else min(am // 12, 15) + 2
        return out

    def hints(self, today: date) -> list[str]:
        lines: list[str] = []
        ages = self.child_ages(today)
        if self.married_on:
            m = _months_between(self.married_on, today)
            lines.append(f"혼인 {m // 12}년 {m % 12}개월")
            if m <= 84:
                lines.append("신혼부부 특별공급: 혼인 7년 이내 → 검토 대상 (소득·자산 기준 확인)")
            elif any(a <= 6 for a in ages):
                lines.append("신혼부부 특별공급: 혼인 7년은 지났지만 만 6세 이하 자녀가 있음 → "
                             "공고문에서 해당 여부와 소득·자산 기준 확인")
        if any(_months_between(b, today) <= 24 for b in self.children_born):
            lines.append("신생아 특별·우선공급: 출산 2년 이내 → 검토 대상")
        minors = sum(1 for a in ages if a < 19)
        if minors >= 2:
            lines.append(f"다자녀 특별공급: 미성년 자녀 {minors}명 → 공고별 자녀 수 요건 확인 (민영은 통상 3명 이상)")
        if self.homeless and (self.married_on or self.children_born):
            lines.append("생애최초 특별공급: 생애 주택 소유 이력이 없다면 검토 (소득·5년 이상 근로/사업 요건)")
        if (s := self.score(today)):
            lines.append("일반공급 가점(추정): " + " + ".join(f"{k} {v}" for k, v in s.items())
                         + f" = {sum(s.values())}점" + ("" if "통장가입기간" in s else " (통장 가입기간 제외)"))
        if not self.homeless:
            lines.append("※ 유주택으로 설정되어 있어 무주택 전제 유형은 제외됨")
        return lines
