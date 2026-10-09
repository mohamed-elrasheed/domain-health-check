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
# The only address this tool ever sends to. Hard-coded, not configurable: no setting, argument or submission can
# make it send anywhere else, and send() refuses any message addressed to anyone else.
REVIEWER = "mo@mizangroupllc.com"
REVIEW_SUBJECT = "REVIEW BEFORE SENDING"
FAILED_SUBJECT = "REPORT RUN FAILED"


class MailerNotConfigured(RuntimeError):
    """Raised when the credentials are absent. Never contains the password."""


@dataclass(frozen=True)
class MailerConfig:
    host: str
    port: int
    username: str
    password: str = field(repr=False)  # never in a repr, so never in a traceback or a log line

    @property
    def recipient(self) -> str:
        return REVIEWER

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
    msg["To"] = REVIEWER
    # The fixed phrase is what a mail filter matches on. Do not reword it.
    msg["Subject"] = f"Website health report · {domain}" + (f" · {score} out of 100" if score is not None else "")
    # Every report is report.pdf on disk; the attachment is named for the domain and the run day.
    attachment = f"{domain}-{pdf.parent.name}.pdf" if pdf.name == "report.pdf" else pdf.name
    msg.set_content(_plain_body(domain, score, band, counts, headlines, attachment, unreachable))
    msg.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf", filename=attachment)
    return msg


def message_for(cfg: MailerConfig, report: DomainReport, pdf: Path) -> EmailMessage:
    """The email for one report, from the same layout the documents use."""
    score, band = layout.headline(report)
    counts = {"checks passed" if report.count(Status.PASS) != 1 else "check passed": report.count(Status.PASS),
              "could be improved": report.count(Status.WARN),
              "need action": report.count(Status.FAIL), "for information": report.count(Status.INFO),
              "not checked": len(report.not_checked)}
    # The same list as the report's top section and its one-line reading: one list, three surfaces. If the
    # reading says one thing is costing customers, the email shows that one thing.
    findings = [f"{r.name}: {r.summary}" for r in layout.worth_doing(report)]
    return build_message(cfg, report.domain, pdf, score=score, band=band, counts=counts, headlines=findings,
                         unreachable=report.unreachable)


class SendFailed(RuntimeError):
    """Sending failed. The message never contains the password."""


class WrongRecipient(RuntimeError):
    """A message addressed to anyone but the reviewer. Never sent."""


def recipients(msg: EmailMessage) -> set[str]:
    from email.utils import getaddresses
    return {address.lower() for _, address in getaddresses(msg.get_all("To", []) + msg.get_all("Cc", [])
                                                           + msg.get_all("Bcc", []))}


def send(msg: EmailMessage, cfg: MailerConfig, *, smtp_factory=smtplib.SMTP) -> None:
    """Send one message, to the reviewer and nobody else. smtp_factory is injectable so tests never open a socket.

    starttls gets a verifying context: smtplib's default does not check the server's certificate, so
    anything in between could pose as smtp.gmail.com and collect the app password."""
    if recipients(msg) != {REVIEWER}:
        raise WrongRecipient(f"Refused to send: this tool only ever emails {REVIEWER}, and this message was "
                             f"addressed to {', '.join(sorted(recipients(msg))) or 'nobody'}.")
    try:
        with smtp_factory(cfg.host, cfg.port, timeout=30) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(cfg.username, cfg.password)
            server.send_message(msg, to_addrs=[REVIEWER])
    except (smtplib.SMTPException, OSError) as exc:
        reason = f"{type(exc).__name__}: {exc}".replace(cfg.password, "<password>")
        raise SendFailed(f"Could not send the report to {cfg.recipient}. {reason}") from None


# ---------- the automated pipeline: every message to the reviewer, none to the business

EXIT_MEANING = {0: "complete", 2: "the run could not do what was asked", 3: "written, but incomplete"}


def draft_to_business(report: DomainReport) -> str:
    """A draft for the reviewer to edit and send, if they choose. It names the top three findings and asks nothing
    of the business: no call, no reply, no offer. Team voice, plain English."""
    lines = ["Hello,", "", f"Thank you for asking us to look at {report.domain}. Your report is attached.", ""]
    worth = layout.worth_doing(report)
    if worth:
        lines += ["These are the findings we would look at first:", ""]
        lines += [f"- {r.name}: {r.summary}" for r in worth]
    else:
        lines += [layout.NOTHING_FIRST]
    lines += ["", "Each finding in the report says what we found, why it matters and what to do about it.", "",
              "Mizan Digital Services", f"{layout.contact()['phone']} · {layout.contact()['email']}"]
    return "\n".join(lines)


def review_message(cfg: MailerConfig, report: DomainReport, pdf: Path | None, exit_code: int,
                   submitted: str) -> EmailMessage:
    """The reviewer's copy of one automated run: the PDF, the exit code, anything incomplete, and a draft to the
    business that is never sent by this tool."""
    score, band = layout.headline(report)
    msg = EmailMessage()
    msg["From"] = cfg.username
    msg["To"] = REVIEWER
    msg["Subject"] = (f"{REVIEW_SUBJECT} · {report.domain}" + (f" · {score} out of 100" if score is not None else ""))
    incomplete = [f"- {reason}" for reason in report.incomplete] or ["- none"]
    lines = [f"Report for {report.domain}, run {report.checked_at:%d %B %Y at %H:%M} UTC.", "",
             f"Exit code: {exit_code} ({EXIT_MEANING.get(exit_code, 'unexpected')}).", "",
             "Incomplete:", *incomplete, "",
             f"Score: {score} out of 100. {band}" if score is not None else band, "",
             f"Requested: {submitted}", "",
             "The PDF is attached." if pdf else "No PDF could be written; the Markdown report is on disk.",
             "Nothing has been sent to the business. Read the report before anything goes to them.", "",
             "Draft message to the business (not sent):", "-" * 40, draft_to_business(report), "-" * 40]
    msg.set_content("\n".join(lines))
    if pdf:
        msg.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf",
                           filename=f"{report.domain}-{pdf.parent.name}.pdf")
    return msg


def failure_message(cfg: MailerConfig, what: str, error: str) -> EmailMessage:
    """A failed run never goes silent: the reviewer gets the error."""
    msg = EmailMessage()
    msg["From"] = cfg.username
    msg["To"] = REVIEWER
    msg["Subject"] = f"{FAILED_SUBJECT} · {what}"
    msg.set_content(f"{what} failed.\n\n{error}\n\nNothing was sent to anyone else.")
    return msg


def notice_message(cfg: MailerConfig, subject: str, body: str) -> EmailMessage:
    """Something the reviewer should know about a submission that produced no report."""
    msg = EmailMessage()
    msg["From"] = cfg.username
    msg["To"] = REVIEWER
    msg["Subject"] = subject
    msg.set_content(body)
    return msg
