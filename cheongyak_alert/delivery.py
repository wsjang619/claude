"""알림 전달: SMTP 시크릿이 있으면 메일로, 없으면 GitHub 이슈로(GitHub이 이메일로 알려준다)."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Callable

from . import mailer
from .config import MailEnv, Settings

Build = Callable[[str, str], EmailMessage]   # (보내는 사람, 받는 사람) -> 메시지


class DeliveryError(Exception):
    pass


def to_markdown(text: str) -> str:
    """본문 텍스트를 GitHub 마크다운으로. 들여쓰지 않은 짧은 줄은 제목, URL은 자동 링크."""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            out.append("")
        elif not raw[:1].isspace() and len(line) < 100 and not line.endswith("."):
            out.append(f"### {line}")
        elif line.startswith("- "):
            out.append(line)
        else:
            out.append(line + "  ")      # 줄 끝 공백 두 개 = 줄바꿈
    return "\n".join(out)


def _create_issue(title: str, body: str) -> str:
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or repo.split("/")[0]
    payload = json.dumps({"title": title, "body": f"@{owner}\n\n{body}"}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues", data=payload, method="POST",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "User-Agent": "cheongyak-alert/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp).get("html_url", "")
    except urllib.error.HTTPError as e:
        raise DeliveryError(f"GitHub 이슈 생성 실패 HTTP {e.code}: {e.read().decode(errors='replace')[:200]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise DeliveryError(f"GitHub 이슈 생성 실패: {e}") from None


def deliver(build: Build, cfg: Settings) -> str:
    """전달에 성공하면 어디로 보냈는지 설명을 돌려준다. 보낼 방법이 없으면 DeliveryError."""
    env = MailEnv.optional(cfg.mail_to)
    if env:
        mailer.send_smtp(build(env.user, env.to), env)
        return f"메일 발송 완료 -> {env.to}"
    if cfg.fallback_issue and os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY"):
        msg = build("github-actions", cfg.mail_to)
        body = to_markdown(msg.get_body(("plain",)).get_content())
        body += ("\n\n---\n이 알림은 메일 설정(`SMTP_USER`, `SMTP_PASSWORD` 시크릿)이 없어 GitHub 이슈로 보냈습니다. "
                 "시크릿을 등록하면 jos5324@gmail.com으로 직접 메일이 갑니다.")
        url = _create_issue(msg["Subject"], body)
        return f"SMTP 시크릿이 없어 GitHub 이슈로 알림 -> {url} (GitHub이 이메일로 알려줍니다)"
    raise DeliveryError("알림을 보낼 방법이 없습니다: SMTP_USER/SMTP_PASSWORD 시크릿이 필요합니다")
