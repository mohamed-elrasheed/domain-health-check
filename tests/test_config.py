import re
from pathlib import Path

import pytest

from domain_health_check.config import ConfigError, load_config, normalize_domain

REPO_ROOT = Path(__file__).resolve().parent.parent


def write(tmp_path, text):
    path = tmp_path / "domains.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_mappings_and_plain_entries(tmp_path):
    path = write(tmp_path, """
domains:
  - name: Example.COM.
    dkim_selectors: [google, selector1]
  - example.org
""")
    domains = load_config(path)
    assert [d.name for d in domains] == ["example.com", "example.org"]
    assert domains[0].dkim_selectors == ["google", "selector1"]
    assert domains[1].dkim_selectors == []


def test_missing_file_explains_what_to_do(tmp_path):
    with pytest.raises(ConfigError, match="domains.example.yaml"):
        load_config(tmp_path / "domains.yaml")


@pytest.mark.parametrize("text", ["", "domains: []", "domains: example.com", "- example.com"])
def test_rejects_missing_or_empty_domain_list(tmp_path, text):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, text))


def test_rejects_duplicates(tmp_path):
    with pytest.raises(ConfigError, match="more than once"):
        load_config(write(tmp_path, "domains: [example.com, EXAMPLE.com]"))


def test_rejects_bad_selector(tmp_path):
    with pytest.raises(ConfigError, match="selector"):
        load_config(write(tmp_path, "domains:\n  - name: example.com\n    dkim_selectors: ['../evil']\n"))


@pytest.mark.parametrize("bad", ["https://example.com", "example", "exa mple.com", "../../etc", "-bad.example.com", 42])
def test_normalize_domain_rejects_non_domains(bad):
    with pytest.raises(ConfigError):
        normalize_domain(bad)


def test_example_config_is_valid_and_only_uses_reserved_domains():
    """The repo is public: the example file must never contain a real domain."""
    path = REPO_ROOT / "domains.example.yaml"
    reserved = ("example.com", "example.net", "example.org")

    def is_reserved(name: str) -> bool:
        return name in reserved or name.endswith((".example", *(f".{r}" for r in reserved)))

    for d in load_config(path):
        assert is_reserved(d.name), d.name

    # Also catch domain-like strings hidden in comments.
    text = path.read_text(encoding="utf-8").lower()
    for token in re.findall(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", text):
        if not token.endswith(".yaml"):
            assert is_reserved(token), f"non-example domain {token!r} in domains.example.yaml"


def test_real_domains_file_is_gitignored():
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "domains.yaml" in ignored
    assert "reports/" in ignored
