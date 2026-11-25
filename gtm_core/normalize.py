"""Normalisation helpers. Every record from every source passes through here
before dedupe, so matching keys are comparable across tools."""
from __future__ import annotations

import re
from urllib.parse import urlparse

_LEGAL_SUFFIXES = r"\b(inc|incorporated|llc|ltd|limited|gmbh|ag|plc|corp|corporation|co|company|pvt|private|sa|bv|srl|oy|ab)\b\.?"
_FREE_EMAIL = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com",
    "aol.com", "proton.me", "protonmail.com", "live.com", "yandex.com", "rediffmail.com",
}
_COUNTRY_ALIASES = {
    "united states": "US", "usa": "US", "us": "US", "united states of america": "US",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB", "gb": "GB",
    "germany": "DE", "deutschland": "DE", "de": "DE",
    "india": "IN", "in": "IN",
    "united arab emirates": "AE", "uae": "AE", "ae": "AE",
    "france": "FR", "fr": "FR", "netherlands": "NL", "nl": "NL",
    "canada": "CA", "ca": "CA", "singapore": "SG", "sg": "SG",
    "australia": "AU", "au": "AU", "japan": "JP", "jp": "JP",
}


def domain(value: str | None) -> str | None:
    """'https://www.Acme.com/about' -> 'acme.com'. Emails also accepted."""
    if not value:
        return None
    v = str(value).strip().lower()
    if "@" in v and "/" not in v:
        v = v.split("@", 1)[1]
    if "://" not in v:
        v = "http://" + v
    host = urlparse(v).hostname or ""
    host = host.removeprefix("www.")
    return host or None


def is_free_email_domain(d: str | None) -> bool:
    return (d or "").lower() in _FREE_EMAIL


def email(value: str | None) -> str | None:
    if not value:
        return None
    v = str(value).strip().lower()
    return v if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v) else None


def company_name(value: str | None) -> str | None:
    """'ACME Analytics, Inc.' -> 'acme analytics' (matching key, not display name)."""
    if not value:
        return None
    v = str(value).lower()
    v = re.sub(r"[^\w\s&-]", " ", v)
    v = re.sub(_LEGAL_SUFFIXES, " ", v)
    return re.sub(r"\s+", " ", v).strip() or None


def country(value: str | None) -> str | None:
    if not value:
        return None
    v = str(value).strip().lower()
    if v in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[v]
    return v.upper() if len(v) == 2 else None


def to_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return None


def split_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = re.split(r"[;,|]", str(value))
    return sorted({i.strip().lower() for i in items if i and i.strip()})


def seniority(title: str | None) -> str:
    t = (title or "").lower()
    if re.search(r"\b(chief|ceo|cfo|cto|coo|cro|cmo|founder|owner|president)\b", t):
        return "c_level"
    if re.search(r"\b(vp|vice president|svp|evp|head of)\b", t):
        return "vp"
    if re.search(r"\bdirector\b", t):
        return "director"
    if re.search(r"\b(manager|lead|principal)\b", t):
        return "manager"
    return "ic"


def committee_role(title: str | None, role_map: dict[str, list[str]]) -> str | None:
    """Map a job title to a buying-committee role using config keyword lists.
    Longest keyword match wins so 'head of revenue' beats 'head of'."""
    def _clean(s: str) -> str:
        s = re.sub(r"\b(of|the|and|&)\b", " ", s.lower())
        return re.sub(r"\s+", " ", s).strip()

    t = _clean(title or "")
    best: tuple[int, str] | None = None
    for role, keywords in role_map.items():
        for kw in keywords:
            if re.search(rf"\b{re.escape(_clean(kw))}\b", t):
                if best is None or len(kw) > best[0]:
                    best = (len(kw), role)
    return best[1] if best else None
