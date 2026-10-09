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


def names(fields: dict) -> dict[str, list[str]]:
    """Each field's accepted names, preferred first. A config value may be one name or a list of them."""
    return {key: [value] if isinstance(value, str) else list(value) for key, value in fields.items()}


def _first(response: dict[str, str], accepted: list[str]) -> str:
    """The value under the first accepted name the submission has; "" when it has none of them."""
    return next((response[name] for name in accepted if name in response), "")


def parse(item: dict, fields: dict) -> FormSubmission:
    """One submission from the API's formSubmissions list, every value exactly as submitted."""
    fields = names(fields)
    response = {str(k): "" if v is None else str(v) for k, v in (item.get("formResponse") or {}).items()}
    when = str(item.get("dateSubmitted") or "")[:10]
    try:
        submitted = date.fromisoformat(when)
    except ValueError:
        submitted = datetime.now().date()
    known = {name for accepted in fields.values() for name in accepted}
    return FormSubmission(str(item.get("id", "")), submitted, *(_first(response, fields[k]) for k in (
        "name", "email", "phone", "business_name", "city", "website")),
        tuple(sorted(k for k in response if k not in known)))


def _mask(text: str, token: str) -> str:
    return text.replace(token, "<token>") if token else text


def fetch(token: str | None = None, *, transport: httpx.BaseTransport | None = None) -> list[FormSubmission]:
    """Every submission to the /digital form, oldest first. Raises IntakeError, token masked."""
    cfg = config()
    found = [parse(item, cfg["fields"]) for item in fetch_items(token, transport=transport)]
    return sorted(found, key=lambda s: (s.submitted, s.id))


def fetch_items(token: str | None = None, *, transport: httpx.BaseTransport | None = None) -> list[dict]:
    """The raw formSubmissions items, as Webflow returns them. Raises IntakeError, token masked."""
    token = token if token is not None else os.environ.get(TOKEN_ENV, "").strip()
    if not token:
        raise IntakeError(f"{TOKEN_ENV} is not set in .env, so no form submissions could be read")
    cfg = config()
    headers = {"Authorization": f"Bearer {token}", "accept": "application/json"}
    try:
        with httpx.Client(base_url=cfg["api"], headers=headers, timeout=TIMEOUT_SECONDS,
                          transport=transport or TRANSPORT) as client:
            items, ids = [], set()
            for form_id in _form_ids(client, cfg):
                offset = 0
                while True:
                    response = client.get(f"/forms/{form_id}/submissions",
                                          params={"limit": PAGE_SIZE, "offset": offset})
                    _raise_for(response, "reading the form submissions")
                    data = response.json()
                    batch = data.get("formSubmissions") or []
                    for item in batch:  # one submission can appear under more than one record
                        if str(item.get("id", "")) not in ids:
                            ids.add(str(item.get("id", "")))
                            items.append(item)
                    total = (data.get("pagination") or {}).get("total", offset + len(batch))
                    offset += len(batch)
                    if not batch or offset >= total:
                        break
    except httpx.HTTPError as exc:
        raise IntakeError(_mask(f"Webflow could not be reached: {type(exc).__name__}: {exc}", token)) from None
    except IntakeError as exc:
        raise IntakeError(_mask(str(exc), token)) from None
    return items


@dataclass(frozen=True)
class FieldCheck:
    submissions: int
    seen: dict[str, int]  # field name -> how many submissions carry it
    expected: dict[str, list[str]]  # our name -> Webflow's accepted names, preferred first (config/intake.yaml)
    already_processed: int

    def found_as(self, ours: str) -> str | None:
        """The accepted name a submission carried for this field, preferred first, or None."""
        return next((name for name in self.expected[ours] if name in self.seen), None)

    @property
    def missing(self) -> list[str]:
        """Our fields for which no submission carried any accepted name."""
        return sorted(ours for ours in self.expected if self.found_as(ours) is None)

    @property
    def unmapped(self) -> list[str]:
        """Field names that came back but intake does not read."""
        accepted = {name for names_ in self.expected.values() for name in names_}
        return sorted(name for name in self.seen if name not in accepted)


def check_fields(items: list[dict], seen_ids: set[str] | None = None) -> FieldCheck:
    """What a check-only run reports: counts and field names, never a submitted value."""
    counts: dict[str, int] = {}
    for item in items:
        for name in (item.get("formResponse") or {}):
            counts[str(name)] = counts.get(str(name), 0) + 1
    done = seen_ids if seen_ids is not None else seen()
    return FieldCheck(len(items), counts, names(config()["fields"]),
                      sum(1 for item in items if str(item.get("id", "")) in done))


def _form_ids(client: httpx.Client, cfg: dict) -> list[str]:
    """Every form record for the /digital form: same page, same form element. Webflow keeps several for one form."""
    response = client.get(f"/sites/{cfg['site_id']}/forms", params={"limit": PAGE_SIZE})
    _raise_for(response, "listing the site's forms")
    forms = response.json().get("forms") or []
    match = [f for f in forms if f.get("pageId") == cfg["page_id"]
             and f.get("formElementId", cfg["form_element_id"]) == cfg["form_element_id"]]
    if not match:
        raise IntakeError(f"found no form on the /digital page (page id {cfg['page_id']}, form element "
                          f"{cfg['form_element_id']})")
    return [str(f["id"]) for f in match]


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
