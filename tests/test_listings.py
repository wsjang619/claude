import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from cheongyak_alert import listing_mail, listing_runner
from cheongyak_alert.config import load
from cheongyak_alert.models import SourceError
from cheongyak_alert.molit import Market, load_market, months_back, parse_trades
from cheongyak_alert.realestate import NaverLandSource, fmt_money, parse_price
from cheongyak_alert.state import State

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 26)

ARTICLES = [
    {"articleNo": "1001", "articleName": "별내이편한세상", "realEstateTypeName": "아파트", "tradeTypeName": "전세",
     "dealOrWarrantPrc": "2억 8,000", "area2": "59.9", "floorInfo": "5/15", "articleFeatureDesc": "올수리, 역세권",
     "realtorName": "별내공인", "articleConfirmYmd": "20261025"},
    {"articleNo": "1002", "articleName": "별내 행복빌", "realEstateTypeName": "빌라", "tradeTypeName": "전세",
     "dealOrWarrantPrc": "1억 9,500", "area2": "72.1", "floorInfo": "2/4", "articleConfirmYmd": "20261024"},
    {"articleNo": "1003", "articleName": "비싼집", "tradeTypeName": "전세", "dealOrWarrantPrc": "3억 5,000", "area2": "70"},
    {"articleNo": "1004", "articleName": "작은집", "tradeTypeName": "전세", "dealOrWarrantPrc": "1억", "area2": "40"},
    {"articleNo": "1005", "articleName": "월세집", "tradeTypeName": "월세", "dealOrWarrantPrc": "1,000", "area2": "60"},
]
RENT_XML = """<response><header><resultCode>000</resultCode><resultMsg>OK</resultMsg></header><body><items>
<item><aptNm>별내이편한세상</aptNm><umdNm>별내동</umdNm><excluUseAr>59.99</excluUseAr><deposit>27,000</deposit>
<monthlyRent>0</monthlyRent><dealYear>2026</dealYear><dealMonth>9</dealMonth><dealDay>12</dealDay><floor>7</floor></item>
<item><aptNm>별내이편한세상</aptNm><umdNm>별내동</umdNm><excluUseAr>59.99</excluUseAr><deposit>28,500</deposit>
<monthlyRent>0</monthlyRent><dealYear>2026</dealYear><dealMonth>10</dealMonth><dealDay>3</dealDay><floor>3</floor></item>
<item><aptNm>별내이편한세상</aptNm><umdNm>별내동</umdNm><excluUseAr>59.99</excluUseAr><deposit>1,000</deposit>
<monthlyRent>80</monthlyRent><dealYear>2026</dealYear><dealMonth>10</dealMonth><dealDay>5</dealDay><floor>3</floor></item>
</items></body></response>"""


def make_fetch(articles=ARTICLES, fail_articles=None):
    calls = []

    def fetch_json(url, params, headers=None):
        calls.append(url)
        if url.endswith("/api/regions/list"):
            tree = {"4100000000": [{"cortarNo": "4136000000", "cortarName": "남양주시"},
                                   {"cortarNo": "4131000000", "cortarName": "구리시"}],
                    "4136000000": [{"cortarNo": "4136011100", "cortarName": "별내동"},
                                   {"cortarNo": "4136025000", "cortarName": "별내면"},
                                   {"cortarNo": "4136010900", "cortarName": "다산동"},
                                   {"cortarNo": "4136025300", "cortarName": "퇴계원읍"}],
                    "4131000000": [{"cortarNo": "4131010400", "cortarName": "갈매동"}]}
            return {"regionList": tree[params["cortarNo"]]}
        if fail_articles:
            raise SourceError(fail_articles)
        return {"articleList": articles if params["cortarNo"] == "4136011100" and params["page"] == 1 else [],
                "isMoreData": False}

    def fetch_text(url, params, headers=None):
        if "complexes" in url:
            return '<script>{"token":"eyJhbGciOi.abc.def"}</script>'
        return RENT_XML

    return fetch_json, fetch_text, calls


class Base(unittest.TestCase):
    def setUp(self):
        self.cfg = load(ROOT / "config.toml")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = State(Path(self.tmp.name) / "l.json")

    def source(self, **kw):
        j, t, calls = make_fetch(**kw)
        self.calls = calls
        L = self.cfg.listings
        return NaverLandSource(j, t, L.criteria, L.areas, delay=0, sleep=lambda s: None)


class PriceTests(unittest.TestCase):
    def test_parse_and_format(self):
        for text, want in (("2억 5,000", 25000), ("3억", 30000), ("9,500", 9500), ("10억 1,000", 101000), ("", None), ("협의", None)):
            self.assertEqual(parse_price(text), want, text)
        self.assertEqual(fmt_money(28000), "2억 8,000만원")
        self.assertEqual(fmt_money(30000), "3억원")
        self.assertEqual(fmt_money(9500), "9,500만원")


class NaverTests(Base):
    def test_filters_and_resolves_regions(self):
        found, errors = self.source().fetch()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(l.uid for l in found), ["1001", "1002"])    # 고가·소형·월세 제외
        first = next(l for l in found if l.uid == "1001")
        self.assertEqual((first.deposit, first.area_m2, first.area.name), (28000, 59.9, "별내동"))
        self.assertEqual(first.url, "https://m.land.naver.com/article/info/1001")

    def test_exact_dong_name_not_myeon(self):
        # '별내동'을 찾을 때 '별내면'과 혼동하지 않는다
        src = self.source()
        self.assertEqual(src._resolve(src.areas[0]), "4136011100")

    def test_token_missing_is_reported(self):
        j, _, _ = make_fetch()
        L = self.cfg.listings
        src = NaverLandSource(j, lambda *a, **k: "<html></html>", L.criteria, L.areas, delay=0, sleep=lambda s: None)
        found, errors = src.fetch()
        self.assertEqual(found, [])
        self.assertIn("토큰", errors[0])

    def test_token_from_env(self):
        os.environ["NAVER_LAND_TOKEN"] = "envtoken"
        self.addCleanup(os.environ.pop, "NAVER_LAND_TOKEN")
        src = self.source()
        src.fetch()
        self.assertEqual(src.token, "envtoken")

    def test_block_stops_further_calls(self):
        src = self.source(fail_articles="HTTP 429 too many")
        found, errors = src.fetch()
        self.assertEqual(found, [])
        self.assertEqual(len(errors), 1)       # 첫 지역에서 차단되면 나머지 지역은 호출하지 않는다


class RunnerTests(Base):
    def test_baseline_then_only_new(self):
        found, _ = self.source().fetch()
        res = listing_runner.select(found, self.state, max_items=30)
        self.assertTrue(res.baseline)
        self.assertEqual(len(res.new), 2)
        listing_runner.commit(res, self.state, TODAY)
        self.state.save(TODAY)

        state2 = State(self.state.path)
        again = listing_runner.select(found, state2, max_items=30)
        self.assertFalse(again.baseline)
        self.assertEqual(again.new, [])
        extra = {"articleNo": "1006", "articleName": "신규", "tradeTypeName": "전세", "dealOrWarrantPrc": "2억", "area2": "60"}
        found2, _ = self.source(articles=ARTICLES + [extra]).fetch()
        self.assertEqual([l.uid for l in listing_runner.select(found2, state2, max_items=30).new], ["1006"])

    def test_cap_marks_overflow_seen(self):
        found, _ = self.source().fetch()
        res = listing_runner.select(found, self.state, max_items=1)
        self.assertEqual((len(res.shown), res.overflow), (1, 1))
        self.assertEqual(res.shown[0].uid, "1002")      # 같은 순위면 보증금 낮은 순
        listing_runner.commit(res, self.state, TODAY)
        self.assertEqual(listing_runner.select(found, self.state, max_items=1).new, [])


class MolitTests(unittest.TestCase):
    def test_parse_trades_and_errors(self):
        trades = parse_trades(RENT_XML, "아파트", ("aptNm",))
        self.assertEqual(len(trades), 3)
        self.assertEqual(trades[0].deposit, 27000)
        with self.assertRaises(SourceError):
            parse_trades("<response><header><resultCode>30</resultCode><resultMsg>KEY ERROR</resultMsg></header></response>",
                         "아파트", ("aptNm",))
        with self.assertRaises(SourceError):
            parse_trades("not xml", "아파트", ("aptNm",))

    def test_months_back(self):
        self.assertEqual(months_back(date(2026, 1, 15), 3), ["202601", "202512", "202511"])

    def test_market_jeonse_only_and_stats(self):
        _, t, _ = make_fetch()
        market, errors = load_market(t, "k", {"41360"}, TODAY, months=1, area_min=59, area_max=85)
        self.assertEqual(errors, [])
        self.assertEqual(len(market.trades), 4)   # 아파트 2 + 연립다세대 2 (월세 80짜리는 제외)
        s = market.stats("별내동")
        self.assertEqual((s.low, s.high), (27000, 28500))
        recent = market.recent("별내이편한세상", "별내동", 1)
        self.assertEqual(recent[0].deposit, 28500)
        self.assertEqual(market.recent("전혀다른이름", "별내동"), [])


class MailTests(Base):
    def render(self, with_market=True):
        found, _ = self.source().fetch()
        res = listing_runner.select(found, self.state, max_items=30)
        res.errors = ["실거래 아파트 41360/202610: HTTP 500"]
        _, t, _ = make_fetch()
        market, _ = load_market(t, "k", {"41360"}, TODAY, months=1, area_min=59, area_max=85)
        msg = listing_mail.build_message(res, self.cfg.listings.criteria, market if with_market else None,
                                         TODAY, "a@b.c", "jos5324@gmail.com")
        return msg, msg.get_body(("plain",)).get_content(), msg.get_body(("html",)).get_content()

    def test_content(self):
        msg, text, html = self.render()
        self.assertEqual(msg["To"], "jos5324@gmail.com")
        self.assertIn("기준선", msg["Subject"])
        self.assertIn("최저 1억 9,500만원", msg["Subject"])
        for body in (text, html):
            self.assertIn("2억 8,000만원", body)
            self.assertIn("https://m.land.naver.com/article/info/1001", body)
            self.assertIn("map.naver.com", body)
            self.assertIn("HTTP 500", body)
        self.assertIn("별내동 최근 전세 실거래", text)
        self.assertIn("같은 단지 최근 전세 실거래: 10/3 59.99㎡ 2억 8,500만원", text)

    def test_without_market(self):
        _, text, _ = self.render(with_market=False)
        self.assertNotIn("실거래:", text)


class ConfigTests(Base):
    def test_listing_settings(self):
        L = self.cfg.listings
        self.assertEqual((L.criteria.max_deposit, L.criteria.area_min, L.criteria.area_max), (30000, 59, 85))
        self.assertEqual(L.criteria.types, ("APT", "VL"))
        self.assertEqual([a.name for a in L.areas][:1], ["별내동"])


if __name__ == "__main__":
    unittest.main()
