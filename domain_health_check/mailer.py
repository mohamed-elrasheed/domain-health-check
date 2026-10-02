"""Send a finished report to the reviewer.

This tool NEVER emails the person whose site was scanned. Reports go to the
reviewer, a human reads them, and the human decides what to send on. An
automated finding that turns out to be wrong costs more than the lead was
worth, and three real runs produced four wrong statements before anyone
looked at them.

The email is plain text: score, band, counts, findings as plain bullets, then
where the document is. No call to action and no marketing copy; the report is
the pitch, and a sales email makes the findings look like a pretext. Plain text
also means Gmail's dark mode has no background colour to strip.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path

from . import layout
from .models import DomainReport, Status

DEFAULT_HOST = "smtp.gmail.com"
DEFAULT_PORT = 587


class MailerNotConfigured(RuntimeError):
    """Raised when the credentials are absent. Never contains the password."""


@dataclass(frozen=True)
class MailerConfig:
    host: str
    port: int
    username: str
    password: str = field(repr=False)  # never in a repr, so never in a traceback or a log line
    recipient: str = ""

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "MailerConfig":
        env = os.environ if env is None else env
        username = env.get("SMTP_USERNAME", "").strip()
        password = env.get("SMTP_PASSWORD", "").strip()
        missing = [n for n, v in (("SMTP_USERNAME", username), ("SMTP_PASSWORD", password)) if not v]
        if missing:
            raise MailerNotConfigured(
                "Email is not configured. Set " + " and ".join(missing) + " in .env. "
                "SMTP_PASSWORD is a Google app password, not the account password."
            )
        return cls(
            host=env.get("SMTP_HOST", DEFAULT_HOST).strip(),
            port=int(env.get("SMTP_PORT", DEFAULT_PORT)),
            username=username,
            password=password,
            recipient=env.get("REPORT_RECIPIENT", username).strip(),
        )


def _plain_body(domain: str, score: int | None, band: str, counts: dict[str, int],
                headlines: list[str], filename: str, unreachable: str = "") -> str:
    lines = [f"Website health report for {domain}.", ""]
    lines += [f"Score {score} out of 100. {band}" if score is not None else band, ""]
    if unreachable:
        lines += [unreachable, ""]
    lines += [
        ", ".join(f"{v} {k}" for k, v in counts.items() if v) + ".",
        "",
    ]
    if headlines:
        lines += ["Worth doing:"] + [f"- {h}" for h in headlines] + [""]
    lines += [
        f"The full report is attached as {filename}.",
        "",
        "Read it before any of it goes to the site owner.",
    ]
    return "\n".join(lines)


def build_message(cfg: MailerConfig, domain: str, pdf: Path, *, score: int | None,
                  band: str, counts: dict[str, int], headlines: list[str], unreachable: str = "") -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = cfg.username
    msg["To"] = cfg.recipient
    # The fixed phrase is what a mail filter matches on. Do not reword it.
    msg["Subject"] = f"Website health report · {domain}" + (f" · {score} out of 100" if score is not None else "")
    msg.set_content(_plain_body(domain, score, band, counts, headlines, pdf.name, unreachable))
    msg.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf", filename=pdf.name)
    return msg


def message_for(cfg: MailerConfig, report: DomainReport, pdf: Path) -> EmailMessage:
    """The email for one report, from the same layout the documents use."""
    score, band = layout.headline(report)
    counts = {"checks passed": report.count(Status.PASS), "could be improved": report.count(Status.WARN),
              "need action": report.count(Status.FAIL), "for information": report.count(Status.INFO),
              "not checked": len(report.not_checked)}
    findings = [f"{r.name}: {r.summary}" for r in layout.worth_doing(report) + layout.also_worth_improving(report)]
    return build_message(cfg, report.domain, pdf, score=score, band=band, counts=counts, headlines=findings,
                         unreachable=report.unreachable)


class SendFailed(RuntimeError):
    """Sending failed. The message never contains the password."""


def send(msg: EmailMessage, cfg: MailerConfig, *, smtp_factory=smtplib.SMTP) -> None:
    """Send one message. smtp_factory is injectable so tests never open a socket.

    starttls gets a verifying context: smtplib's default does not check the server's certificate, so
    anything in between could pose as smtp.gmail.com and collect the app password."""
    try:
        with smtp_factory(cfg.host, cfg.port, timeout=30) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(cfg.username, cfg.password)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        reason = f"{type(exc).__name__}: {exc}".replace(cfg.password, "<password>")
        raise SendFailed(f"Could not send the report to {cfg.recipient}. {reason}") from None
