import io
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from cheongyak_alert import __main__ as cli
from cheongyak_alert import delivery, links_digest
from cheongyak_alert.config import load
from cheongyak_alert.realestate import land_search_url
from cheongyak_alert.state import State

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 28)
ENV_KEYS = ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO", "GITHUB_TOKEN", "GITHUB_REPOSITORY",
            "GITHUB_REPOSITORY_OWNER", "DATA_GO_KR_SERVICE_KEY", "NAVER_LAND_TOKEN")


class Base(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}
        self.addCleanup(self._restore)
        self.cfg = load(ROOT / "config.toml")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = State(Path(self.tmp.name) / "s.json")

    def _restore(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


class LinkTests(Base):
    def test_land_url(self):
        a = self.cfg.listings.areas[0]
        url = land_search_url(a, self.cfg.listings.criteria)
        self.assertEqual(url, "https://new.land.naver.com/complexes?ms=37.6437,127.1279,16&a=APT:VL&b=B1&e=RETAIL")

    def test_digest_has_all_links(self):
        text = links_digest.build_text(self.cfg, {"cheongyak", "listings"}, ["네이버부동산: 연결 실패"])
        for want in ("applyhome.co.kr", "apply.lh.or.kr", "myhome.go.kr", "nyj.go.kr", "zigbang.com",
                     "dabangapp.com", "rt.molit.go.kr", "ms=37.6437,127.1279", "네이버부동산: 연결 실패",
                     "전세 3억원 이하", "59~85㎡"):
            self.assertIn(want, text)
        self.assertNotIn("zigbang", links_digest.build_text(self.cfg, {"cheongyak"}, []))
        html = links_digest.build_html(self.cfg, {"listings"}, [])
        self.assertIn("<a href='https://new.land.naver.com/complexes?ms=", html)


class DeliveryTests(Base):
    def build(self):
        return links_digest.make_builder(self.cfg, {"cheongyak"}, ["이유"])

    def test_markdown(self):
        md = delivery.to_markdown("제목 줄\n  - 항목: https://a.example\n  본문 한 줄\n\n문장입니다.")
        self.assertEqual(md.splitlines()[0], "### 제목 줄")
        self.assertIn("- 항목: https://a.example", md)
        self.assertIn("\n본문 한 줄  \n", md)       # 들여쓰기는 코드 블록이 되므로 제거
        self.assertTrue(md.endswith("문장입니다.  "))

    def test_smtp_preferred(self):
        os.environ.update(SMTP_USER="me@gmail.com", SMTP_PASSWORD="pw", GITHUB_TOKEN="t", GITHUB_REPOSITORY="o/r")
        with mock.patch.object(delivery.mailer, "send_smtp") as smtp, mock.patch.object(delivery, "_create_issue") as issue:
            msg = delivery.deliver(self.build(), self.cfg)
        smtp.assert_called_once()
        issue.assert_not_called()
        self.assertEqual(smtp.call_args[0][0]["To"], "jos5324@gmail.com")
        self.assertIn("jos5324@gmail.com", msg)

    def test_issue_fallback_without_smtp(self):
        os.environ.update(GITHUB_TOKEN="t", GITHUB_REPOSITORY="wsjang619/claude", GITHUB_REPOSITORY_OWNER="wsjang619")
        captured = {}

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_open(req, timeout=0):
            captured["url"], captured["body"] = req.full_url, json.loads(req.data)
            captured["auth"] = req.headers["Authorization"]
            return Resp(b'{"html_url": "https://github.com/wsjang619/claude/issues/1"}')

        with mock.patch.object(delivery.urllib.request, "urlopen", fake_open):
            msg = delivery.deliver(self.build(), self.cfg)
        self.assertEqual(captured["url"], "https://api.github.com/repos/wsjang619/claude/issues")
        self.assertTrue(captured["body"]["body"].startswith("@wsjang619"))        # 멘션해야 이메일이 온다
        self.assertIn("applyhome.co.kr", captured["body"]["body"])
        self.assertIn("SMTP_USER", captured["body"]["body"])
        self.assertIn("[링크모음]", captured["body"]["title"])
        self.assertIn("issues/1", msg)

    def test_no_channel_raises(self):
        with self.assertRaises(delivery.DeliveryError):
            delivery.deliver(self.build(), self.cfg)

    def test_fallback_can_be_disabled(self):
        os.environ.update(GITHUB_TOKEN="t", GITHUB_REPOSITORY="o/r")
        self.cfg.fallback_issue = False
        with self.assertRaises(delivery.DeliveryError):
            delivery.deliver(self.build(), self.cfg)


class SendLinksTests(Base):
    def run_send(self, **kw):
        with mock.patch.object(cli, "deliver", return_value="ok") as d:
            ok = cli.send_links(self.cfg, self.state, "listings", ["사유"], TODAY, **kw)
        return ok, d

    def test_once_per_day(self):
        self.state.path = Path(self.tmp.name) / "s.json"
        ok, d = self.run_send()
        self.assertTrue(ok)
        d.assert_called_once()
        ok2, d2 = self.run_send()
        self.assertTrue(ok2)
        d2.assert_not_called()
        self.assertTrue(State(self.state.path).sent_today("links:listings", TODAY))     # 저장됨
        ok3, d3 = self.run_send(force=True)
        d3.assert_called_once()

    def test_delivery_failure_not_marked(self):
        with mock.patch.object(cli, "deliver", side_effect=delivery.DeliveryError("x")):
            ok = cli.send_links(self.cfg, self.state, "listings", [], TODAY)
        self.assertFalse(ok)
        self.assertFalse(self.state.sent_today("links:listings", TODAY))


class MainFlowTests(Base):
    def write_cfg(self):
        text = (ROOT / "config.toml").read_text(encoding="utf-8")
        text = text.replace('path = "state/seen.json"', f'path = "{self.tmp.name}/seen.json"')
        text = text.replace('state_path = "state/listings.json"', f'state_path = "{self.tmp.name}/listings.json"')
        p = Path(self.tmp.name) / "config.toml"
        p.write_text(text, encoding="utf-8")
        return str(p)

    def test_no_key_sends_links_and_exits_zero(self):
        with mock.patch.object(cli, "deliver", return_value="ok") as d:
            code = cli.main(["--config", self.write_cfg(), "--today", "2026-10-28"])
        self.assertEqual(code, 0)
        d.assert_called_once()
        self.assertIn("DATA_GO_KR_SERVICE_KEY", links_digest.build_text(self.cfg, {"cheongyak"}, ["DATA_GO_KR_SERVICE_KEY"]))

    def test_no_key_and_no_channel_fails(self):
        with mock.patch.object(cli, "deliver", side_effect=delivery.DeliveryError("none")):
            code = cli.main(["--config", self.write_cfg(), "--today", "2026-10-28"])
        self.assertEqual(code, 2)

    def test_naver_blocked_sends_links(self):
        with mock.patch.object(cli, "NaverLandSource") as src, mock.patch.object(cli, "deliver", return_value="ok") as d:
            src.return_value.fetch.return_value = ([], ["네이버부동산: 연결 실패 timed out"])
            code = cli.main(["--config", self.write_cfg(), "--listings", "--today", "2026-10-28"])
        self.assertEqual(code, 0)
        d.assert_called_once()
        self.assertEqual(State(Path(self.tmp.name) / "listings.json").meta, {"links:listings": "2026-10-28"})

    def test_links_flag(self):
        with mock.patch.object(cli, "deliver", return_value="ok") as d:
            code = cli.main(["--config", self.write_cfg(), "--links", "--today", "2026-10-28"])
        self.assertEqual(code, 0)
        d.assert_called_once()


if __name__ == "__main__":
    unittest.main()
