from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .matcher import Area
from .models import parse_date
from .profile import Profile
from .realestate import Criteria, ListingArea


def _month(value: str) -> date | None:
    """'2018-05' 또는 '2018-05-17' -> date (일이 없으면 1일)."""
    if not value:
        return None
    parts = str(value).split("-")
    return date(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 1)


@dataclass
class ListingSettings:
    enabled: bool = True
    criteria: Criteria = field(default_factory=Criteria)
    areas: list[ListingArea] = field(default_factory=list)
    max_items_per_mail: int = 30
    delay_seconds: float = 2.0
    market_enabled: bool = True
    market_months: int = 3
    state_path: Path = Path("state/listings.json")


@dataclass
class Settings:
    areas: list[Area]
    profile: Profile | None
    lookback_days: int = 60
    include_closed: bool = False
    remind_days_before: int = 1
    applyhome: dict = field(default_factory=dict)
    lh: dict = field(default_factory=dict)
    state_path: Path = Path("state/seen.json")
    mail_to: str = ""
    fallback_issue: bool = True
    listings: ListingSettings = field(default_factory=ListingSettings)


def load(path: str | Path) -> Settings:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    search = raw.get("search", {})
    areas = [Area(a["name"], int(a["rank"]), tuple(a["keywords"])) for a in raw.get("areas", [])]
    if not areas:
        raise ValueError("config.toml에 [[areas]]가 하나 이상 필요합니다")
    p = raw.get("profile")
    profile = None
    if p:
        profile = Profile(
            birth_year=int(p["birth_year"]),
            married_on=_month(p.get("married_on", "")),
            children_born=[_month(c) for c in p.get("children_born", [])],
            homeless=bool(p.get("homeless", True)),
            extra_dependents=int(p.get("extra_dependents", 0)),
            account_open=_month(p.get("account_open", "")),
        )
    L = raw.get("listings", {})
    c = L.get("criteria", {})
    criteria = Criteria(types=tuple(c.get("real_estate_types", ["APT", "VL"])),
                        max_deposit=int(c.get("max_deposit", 30000)),
                        area_min=float(c.get("area_min", 59)), area_max=float(c.get("area_max", 85)))
    listings = ListingSettings(
        enabled=bool(L.get("enabled", True)), criteria=criteria,
        areas=[ListingArea(a["name"], int(a["rank"]), tuple(a.get("path", ())), a.get("cortar_no", ""),
                           a.get("lawd_cd", ""), a.get("dong", ""), float(a.get("lat", 0)), float(a.get("lon", 0)))
               for a in L.get("areas", [])],
        max_items_per_mail=int(L.get("max_items_per_mail", 30)),
        delay_seconds=float(L.get("naver", {}).get("delay_seconds", 2)),
        market_enabled=bool(L.get("market", {}).get("enabled", True)),
        market_months=int(L.get("market", {}).get("months", 3)),
        state_path=Path(L.get("state_path", "state/listings.json")))
    return Settings(
        areas=areas,
        profile=profile,
        lookback_days=int(search.get("lookback_days", 60)),
        include_closed=bool(search.get("include_closed", False)),
        remind_days_before=int(search.get("remind_days_before", 1)),
        applyhome=raw.get("applyhome", {}),
        lh=raw.get("lh", {}),
        state_path=Path(raw.get("state", {}).get("path", "state/seen.json")),
        mail_to=raw.get("mail", {}).get("to", ""),
        fallback_issue=bool(raw.get("mail", {}).get("fallback_issue", True)),
        listings=listings,
    )


@dataclass
class MailEnv:
    host: str
    port: int
    user: str
    password: str
    to: str

    @classmethod
    def optional(cls, default_to: str = "") -> "MailEnv | None":
        """SMTP 시크릿이 없으면 None."""
        if not (os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD")):
            return None
        return cls.from_env(default_to)

    @classmethod
    def from_env(cls, default_to: str = "") -> "MailEnv":
        missing = [k for k in ("SMTP_USER", "SMTP_PASSWORD") if not os.environ.get(k)]
        if missing:
            raise ValueError(f"환경변수 {', '.join(missing)} 가 필요합니다")
        user = os.environ["SMTP_USER"]
        return cls(
            host=os.environ.get("SMTP_HOST") or "smtp.gmail.com",
            port=int(os.environ.get("SMTP_PORT") or 465),
            user=user,
            password=os.environ["SMTP_PASSWORD"],
            to=os.environ.get("MAIL_TO") or default_to or user,
        )
