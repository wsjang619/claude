from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone

from . import mailer, runner
from .applyhome import ApplyhomeSource
from .config import MailEnv, load
from .http import get_json, normalize_key
from .lh import DEFAULT_ENDPOINT, LhSource
from .matcher import Match
from .models import Notice
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cheongyak_alert", description="별내동 인근 청약 공고 이메일 알림")
    ap.add_argument("--config", default="config.toml")
    ap.add_argument("--dry-run", action="store_true", help="조회·매칭 결과만 출력 (메일 발송·상태 저장 안 함)")
    ap.add_argument("--test-mail", action="store_true", help="샘플 메일을 보내 SMTP 설정을 확인")
    ap.add_argument("--today", help="기준일 YYYY-MM-DD (테스트용)")
    args = ap.parse_args(argv)

    cfg = load(args.config)
    today = date.fromisoformat(args.today) if args.today else datetime.now(KST).date()

    if args.test_mail:
        env = MailEnv.from_env()
        msg = mailer.build_message(sample_entries(cfg, today), cfg.profile, today, [], env.user, env.to)
        mailer.send_smtp(msg, env)
        print(f"테스트 메일 발송 완료 -> {env.to}")
        return 0

    key = os.environ.get("DATA_GO_KR_SERVICE_KEY", "")
    if not key:
        print("환경변수 DATA_GO_KR_SERVICE_KEY 가 필요합니다 (공공데이터포털 일반 인증키)", file=sys.stderr)
        return 2
    state = State(cfg.state_path)
    res = runner.collect(build_sources(cfg, normalize_key(key)), cfg, state, today)

    print(f"기준일 {today} / 조회: " + ", ".join(f"{k} {v}건" for k, v in res.stats.items())
          + f" / 알림 대상 {len(res.entries)}건")
    for err in res.errors:
        print(f"  ! {err}", file=sys.stderr)

    if res.entries:
        if args.dry_run:
            print("\n" + mailer.build_subject(res.entries) + "\n")
            print(mailer.build_text(res.entries, cfg.profile, today, res.errors))
        else:
            env = MailEnv.from_env()
            msg = mailer.build_message(res.entries, cfg.profile, today, res.errors, env.user, env.to)
            mailer.send_smtp(msg, env)    # 실패하면 예외 -> 상태를 저장하지 않아 다음 실행에서 재시도
            print(f"메일 발송 완료 -> {env.to}")
    if not args.dry_run:
        runner.commit(res, state, today, cfg.remind_days_before)
        state.save(today)
    return 1 if res.errors else 0


if __name__ == "__main__":
    sys.exit(main())
