"""New report requests from the form on /digital, read through the Webflow API. Report mode only.

The token is WEBFLOW_API_TOKEN in .env, read access to forms only. It travels in the Authorization header, never
in a URL, and every error message has it masked before anything is printed, logged or emailed.

What a submission becomes is decided in pipeline.py. This module only reads: the /digital form's submissions,
newest first, as Submission records with the fields exactly as submitted. Which ones are new is kept in
logs/intake-seen.json (gitignored), so no submission is ever processed twice.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import yaml

PATH = Path(__file__).parent.parent / "config" / "intake.yaml"
TOKEN_ENV = "WEBFLOW_API_TOKEN"
SEEN = Path("logs") / "intake-seen.json"
PAGE_SIZE = 100
TIMEOUT_SECONDS = 30
TRANSPORT: httpx.BaseTransport | None = None  # tests put a transport of their own here


class IntakeError(RuntimeError):
    """Intake could not read the form. The message never contains the token."""


@dataclass(frozen=True)
class FormSubmission:
    id: str
    submitted: date
    name: str
    email: str
    phone: str
    business_name: str
    city: str
    website: str
    unknown_fields: tuple[str, ...] = ()  # field names the config does not map, logged so a rename is noticed

    @property
    def domain(self) -> str:
        """The host of the website field, without www, or "" when none was given."""
        raw = self.website.strip()
        if not raw:
            return ""
        host = urlsplit(raw if "//" in raw else f"https://{raw}").hostname or ""
        return host.lower().rstrip(".").removeprefix("www.")


@lru_cache(maxsize=1)
def config(path: Path = PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def parse(item: dict, fields: dict[str, str]) -> FormSubmission:
    """One submission from the API's formSubmissions list, every value exactly as submitted."""
    response = {str(k): "" if v is None else str(v) for k, v in (item.get("formResponse") or {}).items()}
    when = str(item.get("dateSubmitted") or "")[:10]
    try:
        submitted = date.fromisoformat(when)
    except ValueError:
        submitted = datetime.now().date()
    known = set(fields.values())
    return FormSubmission(str(item.get("id", "")), submitted, *(response.get(fields[k], "") for k in (
        "name", "email", "phone", "business_name", "city", "website")),
        tuple(sorted(k for k in response if k not in known)))


def _mask(text: str, token: str) -> str:
    return text.replace(token, "<token>") if token else text


def fetch(token: str | None = None, *, transport: httpx.BaseTransport | None = None) -> list[FormSubmission]:
    """Every submission to the /digital form, oldest first. Raises IntakeError, token masked."""
    token = token if token is not None else os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise IntakeError(f"{TOKEN_ENV} is not set in .env, so no form submissions could be read")
    cfg = config()
    headers = {"Authorization": f"Bearer {token}", "accept": "application/json"}
    try:
        with httpx.Client(base_url=cfg["api"], headers=headers, timeout=TIMEOUT_SECONDS,
                          transport=transport or TRANSPORT) as client:
            form_id = _form_id(client, cfg)
            items, offset = [], 0
            while True:
                response = client.get(f"/forms/{form_id}/submissions", params={"limit": PAGE_SIZE, "offset": offset})
                _raise_for(response, "reading the form submissions")
                data = response.json()
                batch = data.get("formSubmissions") or []
                items += batch
                total = (data.get("pagination") or {}).get("total", len(items))
                offset += len(batch)
                if not batch or offset >= total:
                    break
    except httpx.HTTPError as exc:
        raise IntakeError(_mask(f"Webflow could not be reached: {type(exc).__name__}: {exc}", token)) from None
    except IntakeError as exc:
        raise IntakeError(_mask(str(exc), token)) from None
    found = [parse(item, cfg["fields"]) for item in items]
    return sorted(found, key=lambda s: (s.submitted, s.id))


def _form_id(client: httpx.Client, cfg: dict) -> str:
    response = client.get(f"/sites/{cfg['site_id']}/forms", params={"limit": PAGE_SIZE})
    _raise_for(response, "listing the site's forms")
    forms = response.json().get("forms") or []
    match = [f for f in forms if f.get("pageId") == cfg["page_id"]]
    if len(match) != 1:
        raise IntakeError(f"expected one form on the /digital page (page id {cfg['page_id']}), found {len(match)}")
    return str(match[0]["id"])


def _raise_for(response: httpx.Response, doing: str) -> None:
    if response.status_code != 200:
        raise IntakeError(f"Webflow answered {response.status_code} while {doing}")


# ---------- which submissions are new

def seen(path: Path | None = None) -> set[str]:
    path = path or SEEN
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return set()


def mark_seen(submission_id: str, path: Path | None = None) -> None:
    """Recorded before the report runs, so a crash midway can never send the same request round twice."""
    path = path or SEEN
    done = seen(path) | {submission_id}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(done), indent=2), encoding="utf-8")


def from_file(path: Path) -> list[FormSubmission]:
    """Submissions from a saved API response (the same JSON shape), for a test without Webflow."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return sorted((parse(item, config()["fields"]) for item in data.get("formSubmissions") or []),
                  key=lambda s: (s.submitted, s.id))
