"""Patent search sources for the synthesizer.

KIPRIS Plus is the source whenever KIPRIS_API_KEY is set. Without it no search is
possible and ideas are held, unless IDEA_FACTORY_PATENTS=unchecked explicitly lets them
through stamped as unchecked.

Google Patents' internal endpoint was tried as an interim source on 2026-10-19: after a
few queries Google answered 503 with its bot-detection page, so it is not used by
default and must not be retried around that block.
"""
from __future__ import annotations

import os
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Protocol

import httpx


@dataclass(slots=True)
class PatentHit:
    number: str
    title: str
    snippet: str
    source: str
    url: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


class PatentSource(Protocol):
    name: str

    def search(self, query: str, limit: int = 8) -> list[PatentHit]: ...


class GooglePatentsSource:
    name = "google-patents (interim)"
    _min_interval = 2.0

    def __init__(self) -> None:
        self._last = 0.0

    def search(self, query: str, limit: int = 8) -> list[PatentHit]:
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        inner = urllib.parse.urlencode({"q": query, "num": str(limit)})
        response = httpx.get("https://patents.google.com/xhr/query",
                             params={"url": inner, "exp": ""},
                             headers={"User-Agent": "Mozilla/5.0 (all-tomorrow idea factory)"}, timeout=30)
        response.raise_for_status()
        hits = []
        for cluster in response.json().get("results", {}).get("cluster", []):
            for result in cluster.get("result", []):
                patent = result.get("patent", {})
                number = patent.get("publication_number", "")
                hits.append(PatentHit(number=number, title=_clean(patent.get("title", "")),
                                      snippet=_clean(patent.get("snippet", ""))[:400], source=self.name,
                                      url=f"https://patents.google.com/patent/{number}"))
        return hits[:limit]


class KiprisSource:
    name = "kipris-plus"
    endpoint = "http://plus.kipris.or.kr/kipo-api/kipi/patUtiModInfoSearchSevice/getWordSearch"

    def __init__(self, service_key: str) -> None:
        self._key = service_key

    def search(self, query: str, limit: int = 8) -> list[PatentHit]:
        response = httpx.get(self.endpoint, params={"word": query, "year": "0", "numOfRows": str(limit),
                                                    "ServiceKey": self._key}, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        if root.findtext(".//successYN") == "N":
            raise RuntimeError(f"KIPRIS error {root.findtext('.//resultCode')}: {root.findtext('.//resultMsg')}")
        hits = []
        for item in root.iter("item"):
            number = item.findtext("applicationNumber") or ""
            hits.append(PatentHit(number=number, title=item.findtext("inventionTitle") or "",
                                  snippet=(item.findtext("astrtCont") or "")[:400], source=self.name,
                                  url=f"https://doi.org/10.8080/{number}" if number else ""))
        return hits[:limit]


def _clean(text: str) -> str:
    for tag in ("<b>", "</b>", "&hellip;"):
        text = text.replace(tag, "" if tag != "&hellip;" else "…")
    return " ".join(text.split())


class NoSource:
    """No permitted source configured: every search fails, so the synthesizer holds the idea."""
    name = "없음 (KIPRIS_API_KEY 미설정)"
    unchecked = False

    def search(self, query: str, limit: int = 8) -> list[PatentHit]:
        raise RuntimeError("no patent source configured")


class UncheckedSource:
    """Explicit opt-in: skip the patent gate; proposals are stamped as unchecked."""
    name = "특허 미검사"
    unchecked = True

    def search(self, query: str, limit: int = 8) -> list[PatentHit]:
        return []


def default_source() -> PatentSource:
    key = os.environ.get("KIPRIS_API_KEY")
    if key:
        return KiprisSource(key)
    if os.environ.get("IDEA_FACTORY_PATENTS") == "unchecked":
        return UncheckedSource()
    return NoSource()
