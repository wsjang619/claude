from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone

from . import links_digest, listing_mail, listing_runner, mailer, molit, runner
from .applyhome import ApplyhomeSource
from .config import MailEnv, load
from .delivery import DeliveryError, deliver
from .http import get_json, get_text, normalize_key
from .lh import DEFAULT_ENDPOINT, LhSource
from .matcher import Match
from .models import Notice
from .realestate import NaverLandSource
from .state import State

KST = timezone(timedelta(hours=9))


def build_sources(cfg, key: str):
    sources = []
    ah = cfg.applyhome
    if ah.get("enabled", True):
        sources.append(ApplyhomeSource(
            get_json, key, region=ah.get("region", "경기"),
            endpoints=ah.get("endpoints") or None,
            special_supply_detail=ah.get("special_supply_detail", True)))
    lh = cfg.lh
    if lh.get("enabled", True):
        sources.append(LhSource(get_json, key, endpoint=lh.get("endpoint", DEFAULT_ENDPOINT),
                                region_code=str(lh.get("region_code", "41"))))
    return sources


def sample_entries(cfg, today: date) -> list[mailer.Entry]:
    n = Notice(source="applyhome", uid="TEST-0", title="(테스트) 별내 샘플 단지", category="APT 분양",
               address="경기도 남양주시 별내동 000", announced=today, receipt_start=today + timedelta(days=7),
               receipt_end=today + timedelta(days=10), households=100, developer="샘플건설",
               url="https://www.applyhome.co.kr", special_supply={"신혼부부": 20, "생애최초": 10})
    return [mailer.Entry(Match(n, cfg.areas[0]))]


def send_links(cfg, state: State, kind: str, reasons: list[str], today: date, *, force: bool = False,
               dry_run: bool = False) -> bool:
    """조회를 못 했을 때 확인용 링크 모음을 하루 한 번만 보낸다. 전달에 성공하면 True."""
    name = f"links:{kind}"
    if not force and state.sent_today(name, today):
        print("확인용 링크 모음은 오늘 이미 보냈습니다")
        return True
    build = links_digest.make_builder(cfg, {kind} if kind != "all" else {"cheongyak", "listings"}, reasons)
    if dry_run:
        print(build("-", "-").get_body(("plain",)).get_content())
        return True
    try:
        print(deliver(build, cfg))
    except DeliveryError as e:
        print(f"  ! {e}", file=sys.stderr)
        return False
    state.mark_sent(name, today)
    state.save(today)
    return True


def run_listings(cfg, args, today: date, service_key: str) -> int:
    L = cfg.listings
    if not L.enabled or not L.areas:
        print("[listings] 비활성화되어 있거나 지역이 없습니다")
        return 0
    state = State(L.state_path)
    src = NaverLandSource(get_json, get_text, L.criteria, L.areas, delay=L.delay_seconds)
    found, errors = src.fetch()
    if errors and not found:      # 조회 자체가 안 됨(차단·접속 실패 등): 확인용 링크를 대신 보낸다
        for err in errors:
            print(f"  ! {err}", file=sys.stderr)
        print("네이버부동산 조회 실패 -> 확인용 링크 모음 전송")
        ok = send_links(cfg, state, "listings", errors, today, dry_run=args.dry_run)
        return 0 if ok else 1
    res = listing_runner.select(found, state, max_items=L.max_items_per_mail)
    res.errors = errors
    print(f"기준일 {today} / 네이버부동산 조건 일치 {len(found)}건 / 신규 {len(res.new)}건"
          + (" (첫 실행: 기준선)" if res.baseline else ""))
    for err in errors:
        print(f"  ! {err}", file=sys.stderr)

    if res.new:
        market = None
        if L.market_enabled and service_key:
            lawd = {a.lawd_cd for a in res.shown_areas() if a.lawd_cd}
            market, merrs = molit.load_market(get_text, normalize_key(service_key), lawd, today,
                                              months=L.market_months, area_min=L.criteria.area_min,
                                              area_max=L.criteria.area_max)
            res.errors += merrs
            for err in merrs:
                print(f"  ! {err}", file=sys.stderr)
        if args.dry_run:
            print("\n" + listing_mail.build_subject(res) + "\n")
            print(listing_mail.build_text(res, L.criteria, market, today))
        else:
            print(deliver(lambda sender, to: listing_mail.build_message(res, L.criteria, market, today, sender, to), cfg))
    if not args.dry_run and res.new:
        listing_runner.commit(res, state, today)
        state.save(today, keep_days=180)
    return 1 if res.errors else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_alert", description="별내동 인근 청약 공고 이메일 알림")
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--dry-run", action="store_true", help="조회·매칭 결과만 출력 (메일 발송·상태 저장 안 함)")
    ap.add_argument("--test-mail", action="store_true", help="샘플 메일을 보내 SMTP 설정을 확인")
    ap.add_argument("--listings", action="store_true", help="청약 공고 대신 전세 매물(네이버부동산)을 조회")
    ap.add_argument("--links", action="store_true", help="청약·전세 매물 확인용 링크 모음을 지금 보냄")
    ap.add_argument("--today", help="기준일 YYYY-MM-DD (테스트용)")
    args = ap.parse_args(argv)

    cfg = load(args.config)
    today = date.fromisoformat(args.today) if args.today else datetime.now(KST).date()

    if args.test_mail:
        env = MailEnv.from_env(cfg.mail_to)
        msg = mailer.build_message(sample_entries(cfg, today), cfg.profile, today, [], env.user, env.to)
        mailer.send_smtp(msg, env)
        print(f"테스트 메일 발송 완료 -> {env.to}")
        return 0

    key = os.environ.get("DATA_GO_KR_SERVICE_KEY", "")
    if args.links:
        state = State(cfg.state_path)
        return 0 if send_links(cfg, state, "all", [], today, force=True, dry_run=args.dry_run) else 1
    if args.listings:
        return run_listings(cfg, args, today, key)
    state = State(cfg.state_path)
    if not key:
        reason = "DATA_GO_KR_SERVICE_KEY 시크릿(공공데이터포털 인증키)이 설정되지 않아 청약 공고를 조회하지 못했습니다"
        print(f"  ! {reason}", file=sys.stderr)
        return 0 if send_links(cfg, state, "cheongyak", [reason], today, dry_run=args.dry_run) else 2
    res = runner.collect(build_sources(cfg, normalize_key(key)), cfg, state, today)

    print(f"기준일 {today} / 조회: " + ", ".join(f"{k} {v}건" for k, v in res.stats.items())
          + f" / 알림 대상 {len(res.entries)}건")
    for err in res.errors:
        print(f"  ! {err}", file=sys.stderr)

    if res.errors and not res.entries and not any(res.stats.values()):   # 모든 소스 조회 실패
        print("청약 소스 조회 실패 -> 확인용 링크 모음 전송")
        return 0 if send_links(cfg, state, "cheongyak", res.errors, today, dry_run=args.dry_run) else 1
    if res.entries:
        if args.dry_run:
            print("\n" + mailer.build_subject(res.entries) + "\n")
            print(mailer.build_text(res.entries, cfg.profile, today, res.errors))
        else:
            # 실패하면 예외 -> 상태를 저장하지 않아 다음 실행에서 재시도
            print(deliver(lambda sender, to: mailer.build_message(res.entries, cfg.profile, today, res.errors,
                                                                  sender, to), cfg))
    if not args.dry_run:
        runner.commit(res, state, today, cfg.remind_days_before)
        state.save(today)
    return 1 if res.errors else 0


if __name__ == "__main__":
    sys.exit(main())
