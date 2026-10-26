import tempfile
import unittest
from datetime import date
from pathlib import Path

from cheongyak_alert import mailer, runner
from cheongyak_alert.applyhome import ApplyhomeSource, row_to_notice
from cheongyak_alert.config import load
from cheongyak_alert.http import normalize_key
from cheongyak_alert.lh import LhSource
from cheongyak_alert.models import SourceError, parse_date
from cheongyak_alert.state import State
from cheongyak_alert.summary import links, summarize
from cheongyak_alert.config import MailEnv

TODAY = date(2026, 10, 26)
ROOT = Path(__file__).resolve().parent.parent

APT_ROWS = [
    {"HOUSE_MANAGE_NO": "1", "PBLANC_NO": "10", "HOUSE_NM": "별내 테스트 파크", "HOUSE_SECD_NM": "APT",
     "HSSPLY_ADRES": "경기도 남양주시 별내동 100", "TOT_SUPLY_HSHLDCO": "512", "RCRIT_PBLANC_DE": "2026-10-20",
     "SPSPLY_RCEPT_BGNDE": "2026-11-02", "RCEPT_BGNDE": "2026-11-03", "RCEPT_ENDDE": "2026-11-05",
     "PRZWNER_PRESNATN_DE": "2026-11-11", "BSNS_MBY_NM": "테스트건설", "PBLANC_URL": "https://example.com/1", "HMPG_ADRES": "www.byeolnae-park.example"},
    {"HOUSE_MANAGE_NO": "2", "PBLANC_NO": "20", "HOUSE_NM": "남양주 왕숙 테스트", "HSSPLY_ADRES": "경기도 남양주시 진건읍 1",
     "RCRIT_PBLANC_DE": "2026-10-01", "RCEPT_BGNDE": "2026-10-10", "RCEPT_ENDDE": "2026-10-12"},   # 이미 마감
    {"HOUSE_MANAGE_NO": "3", "PBLANC_NO": "30", "HOUSE_NM": "수원 테스트", "HSSPLY_ADRES": "경기도 수원시 1",
     "RCRIT_PBLANC_DE": "2026-10-20", "RCEPT_BGNDE": "2026-11-03", "RCEPT_ENDDE": "2026-11-05"},   # 무관한 지역
]
MDL_ROWS = [{"NWWDS_HSHLDCO": "20", "LFE_FRST_HSHLDCO": "8", "HOUSE_TY": "059.9900A", "LTTOT_TOP_AMOUNT": "65000"},
            {"NWWDS_HSHLDCO": "15", "LFE_FRST_HSHLDCO": "0", "HOUSE_TY": "084.9500B", "LTTOT_TOP_AMOUNT": "89500"}]
LH_PAYLOAD = [
    {"dsSch": [{"PG_SZ": "200"}]},
    {"dsList": [
        {"PAN_ID": "999", "PAN_NM": "남양주별내 A-1BL 행복주택 입주자 모집", "CNP_CD_NM": "경기도", "PAN_SS": "공고중",
         "UPP_AIS_TP_NM": "임대주택", "AIS_TP_CD_NM": "행복주택", "PAN_DT": "2026.10.22", "CLSG_DT": "2026.11.10",
         "DTL_URL": "https://apply.lh.or.kr/x"},
        {"PAN_ID": "998", "PAN_NM": "수원 영구임대", "CNP_CD_NM": "경기도", "CLSG_DT": "2026.11.10"},
    ], "resHeader": [{"SS_CODE": "Y", "RS_DTTM": "20261026"}]},
]


def fake_fetch(url, params):
    if url.endswith("getAPTLttotPblancDetail"):
        return {"data": APT_ROWS, "matchCount": 3, "totalCount": 3}
    if url.endswith("getAPTLttotPblancMdl"):
        return {"data": MDL_ROWS, "matchCount": 2}
    if "lhNoticeInfo1" in url:
        return LH_PAYLOAD
    return {"data": [], "matchCount": 0}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = load(ROOT / "config.toml")
        self.state = State(Path(self.tmp.name) / "seen.json")
        self.sources = [ApplyhomeSource(fake_fetch, "k"), LhSource(fake_fetch, "k")]


class ParsingTests(unittest.TestCase):
    def test_parse_date_formats(self):
        for v in ("2026-10-26", "20261026", "2026.10.26", "2026-10-26 00:00:00"):
            self.assertEqual(parse_date(v), date(2026, 10, 26))
        self.assertIsNone(parse_date(""))
        self.assertIsNone(parse_date("2026-13-40"))

    def test_applyhome_row(self):
        n = row_to_notice(APT_ROWS[0], "getAPTLttotPblancDetail")
        self.assertEqual(n.receipt_start, date(2026, 11, 2))   # 특공 시작일이 더 빠름
        self.assertEqual(n.receipt_end, date(2026, 11, 5))
        self.assertEqual(n.households, 512)
        self.assertEqual(n.uid, "APT-1-10")

    def test_key_normalization(self):
        self.assertEqual(normalize_key("ab%2Bc%2Fd%3D%3D"), "ab+c/d==")
        self.assertEqual(normalize_key("ab+c/d=="), "ab+c/d==")


class RunnerTests(Base):
    def test_matches_and_filters(self):
        res = runner.collect(self.sources, self.cfg, self.state, TODAY)
        titles = [e.match.notice.title for e in res.entries]
        self.assertEqual(titles[0], "별내 테스트 파크")                   # rank 1 먼저
        self.assertIn("남양주별내 A-1BL 행복주택 입주자 모집", titles)
        self.assertNotIn("남양주 왕숙 테스트", titles)                    # 마감
        self.assertNotIn("수원 테스트", titles)
        self.assertEqual(len(res.entries), 2)
        self.assertEqual(res.errors, [])

    def test_special_supply_enrichment(self):
        res = runner.collect(self.sources, self.cfg, self.state, TODAY)
        self.assertEqual(res.entries[0].match.notice.special_supply, {"신혼부부": 35, "생애최초": 8})

    def test_no_duplicate_after_commit(self):
        res = runner.collect(self.sources, self.cfg, self.state, TODAY)
        runner.commit(res, self.state, TODAY, 1)
        self.state.save(TODAY)
        again = runner.collect(self.sources, self.cfg, State(self.state.path), date(2026, 10, 27))
        self.assertEqual(again.entries, [])

    def test_reminder_once(self):
        res = runner.collect(self.sources, self.cfg, self.state, TODAY)
        runner.commit(res, self.state, TODAY, 1)
        r1 = runner.collect(self.sources, self.cfg, self.state, date(2026, 11, 1))   # 특공 접수 전날
        self.assertEqual([e.reminder for e in r1.entries], [True])
        runner.commit(r1, self.state, date(2026, 11, 1), 1)
        r2 = runner.collect(self.sources, self.cfg, self.state, date(2026, 11, 2))
        self.assertEqual(r2.entries, [])

    def test_failed_source_does_not_block_others(self):
        def broken(url, params):
            if "lhNoticeInfo1" in url:
                raise SourceError("SERVICE KEY IS NOT REGISTERED")
            return fake_fetch(url, params)
        srcs = [ApplyhomeSource(broken, "k"), LhSource(broken, "k")]
        res = runner.collect(srcs, self.cfg, self.state, TODAY)
        self.assertEqual(len(res.entries), 1)
        self.assertTrue(any("NOT REGISTERED" in e for e in res.errors))

    def test_date_cond_rejected_falls_back(self):
        calls = []
        def picky(url, params):
            calls.append(params)
            if "cond[RCRIT_PBLANC_DE::GTE]" in params:
                raise SourceError("HTTP 400 bad cond")
            return fake_fetch(url, params)
        src = ApplyhomeSource(picky, "k", endpoints=["getAPTLttotPblancDetail"])
        notices, errors = src.fetch(date(2026, 9, 1))
        self.assertEqual(errors, [])
        self.assertEqual(len(notices), 3)


class MailTests(Base):
    def test_render(self):
        res = runner.collect(self.sources, self.cfg, self.state, TODAY)
        msg = mailer.build_message(res.entries, self.cfg.profile, TODAY, ["x 실패"], "a@b.c", "d@e.f")
        text = msg.get_body(("plain",)).get_content()
        html = msg.get_body(("html",)).get_content()
        self.assertIn("신규 2건", msg["Subject"])
        self.assertIn("별내 테스트 파크", msg["Subject"])
        self.assertIn("D-7", text)
        self.assertIn("신혼부부 35", text)
        self.assertIn("x 실패", html)
        self.assertIn("https://example.com/1", html)

    def test_html_escaped(self):
        res = runner.collect(self.sources, self.cfg, self.state, TODAY)
        res.entries[0].match.notice.title = "<script>x</script> 별내"
        html = mailer.build_html(res.entries, None, TODAY, [])
        self.assertNotIn("<script>", html)


class SummaryTests(Base):
    def entries(self):
        return runner.collect(self.sources, self.cfg, self.state, TODAY).entries

    def test_summary_sentence(self):
        n = self.entries()[0].match.notice
        text = summarize(n, TODAY)
        self.assertIn("경기도 남양주시 별내동 100의 512세대 규모 APT 분양 공고입니다.", text)
        self.assertIn("11/2(월)~11/5(목)", text)
        self.assertIn("접수 시작까지 D-7", text)
        self.assertIn("당첨자 발표는 11/11(수)", text)
        self.assertIn("신혼부부 35세대", text)

    def test_type_and_price_rows(self):
        n = self.entries()[0].match.notice
        self.assertEqual(n.extras["전용면적"], "59.99~84.95㎡ (2개 주택형)")
        self.assertEqual(n.extras["분양가(최고가)"], "6.5억원 ~ 8.95억원")

    def test_links(self):
        e = self.entries()
        apt = dict(links(e[0].match.notice))
        self.assertEqual(apt["공고 상세"], "https://example.com/1")
        self.assertEqual(apt["단지 홈페이지"], "http://www.byeolnae-park.example")
        self.assertIn("applyhome.co.kr", apt["청약홈 (신청·일정)"])
        self.assertTrue(apt["지도에서 보기"].startswith("https://map.naver.com/p/search/%EA%B2%BD%EA%B8%B0"))
        lh = dict(links(e[1].match.notice))
        self.assertEqual(lh["공고 상세"], "https://apply.lh.or.kr/x")
        self.assertIn("LH청약플러스", lh)

    def test_mail_contains_summary_links_overview(self):
        msg = mailer.build_message(self.entries(), self.cfg.profile, TODAY, [], "a@b.c", "d@e.f")
        text, html = msg.get_body(("plain",)).get_content(), msg.get_body(("html",)).get_content()
        for body in (text, html):
            self.assertIn("한눈에 보기", body)
            self.assertIn("https://example.com/1", body)
            self.assertIn("https://apply.lh.or.kr/x", body)
            self.assertIn("map.naver.com", body)
        self.assertIn("요약: 경기도 남양주시 별내동 100의", text)
        self.assertIn("공고 상세", html)


class MailEnvTests(unittest.TestCase):
    def setUp(self):
        import os
        self.env = {k: os.environ.pop(k, None) for k in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO")}
        os.environ.update(SMTP_USER="sender@gmail.com", SMTP_PASSWORD="pw")
        self.addCleanup(self._restore)

    def _restore(self):
        import os
        for k, v in self.env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def test_recipient_from_config(self):
        cfg = load(ROOT / "config.toml")
        self.assertEqual(cfg.mail_to, "jos5324@gmail.com")
        self.assertEqual(MailEnv.from_env(cfg.mail_to).to, "jos5324@gmail.com")

    def test_env_override_and_blank_secret(self):
        import os
        os.environ["MAIL_TO"] = ""                       # 비어 있는 GitHub secret
        self.assertEqual(MailEnv.from_env("jos5324@gmail.com").to, "jos5324@gmail.com")
        os.environ["MAIL_TO"] = "other@example.com"
        self.assertEqual(MailEnv.from_env("jos5324@gmail.com").to, "other@example.com")


class ProfileTests(Base):
    def test_hints_for_this_household(self):
        p = self.cfg.profile
        hints = "\n".join(p.hints(TODAY))
        self.assertIn("혼인 8년 5개월", hints)
        self.assertIn("만 6세 이하 자녀", hints)           # 혼인 7년 초과 + 자녀
        self.assertIn("미성년 자녀 2명", hints)
        self.assertNotIn("신생아", hints)                  # 2024-08 출산 -> 2년 경과
        self.assertEqual(p.score(TODAY), {"무주택기간": 18, "부양가족": 20})

    def test_newborn_within_two_years(self):
        self.assertIn("신생아", "\n".join(self.cfg.profile.hints(date(2026, 3, 1))))

    def test_account_score(self):
        p = self.cfg.profile
        p.account_open = date(2016, 1, 1)                  # 10년 9개월
        self.assertEqual(p.score(TODAY)["통장가입기간"], 12)


if __name__ == "__main__":
    unittest.main()
