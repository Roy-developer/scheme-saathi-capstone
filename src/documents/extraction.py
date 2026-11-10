"""Suggest a name and date of birth from an uploaded synthetic document.

The suggestion is only a convenience for the person. Nothing here decides
anything: a human must accept or edit a value before the checker uses it, no
model interprets the text, and a suggestion never says a document is genuine.
Only values that sit next to a label such as "Name" or "DOB" are suggested.
"""

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_TEXT_CHARS = 20_000
MAX_VALUE_CHARS = 120
ANALYZE_TIMEOUT_SECONDS = 40
API_VERSION = "2024-11-30"

NAME_LABELS = r"(?:name|नाम|नांव|नाव)"
DOB_LABELS = r"(?:date\s+of\s+birth|d\.?o\.?b\.?|जन्म\s*तिथि|जन्मतारीख|जन्म\s*दिनांक)"
_NAME_PATTERN = re.compile(
    rf"(?im)^\s*(?!father|mother|husband|spouse|पिता|माता)[^\n:]{{0,20}}?\b{NAME_LABELS}\b"
    r"\s*[:\-]\s*([^\n]{2,%d})$" % MAX_VALUE_CHARS
)
_DOB_PATTERN = re.compile(
    rf"(?i){DOB_LABELS}\s*[:\-]?\s*(\d{{1,2}})[/\-.](\d{{1,2}})[/\-.](\d{{4}})"
)
_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


class ExtractionError(Exception):
    """Extraction was unavailable or failed; the message is safe to show."""


@dataclass(frozen=True)
class Suggestion:
    name: str | None
    date_of_birth: str | None
    engine: str


class Extractor(Protocol):
    engine: str

    def read_text(self, content: bytes) -> str: ...


def parse_suggestion(text: str, engine: str) -> Suggestion:
    """Pick label-adjacent values out of OCR text; never guess unlabeled ones."""

    text = text[:MAX_TEXT_CHARS].translate(_DEVANAGARI_DIGITS)
    name_match = _NAME_PATTERN.search(text)
    name = None
    if name_match:
        candidate = " ".join(name_match.group(1).split())
        if not any(character.isdigit() for character in candidate):
            name = candidate[:MAX_VALUE_CHARS]
    dob = None
    dob_match = _DOB_PATTERN.search(text)
    if dob_match:
        day, month, year = (int(part) for part in dob_match.groups())
        try:
            dob = date(year, month, day).isoformat()
        except ValueError:
            dob = None
    return Suggestion(name=name, date_of_birth=dob, engine=engine)


class AzureDocumentIntelligence:
    """Read text with Azure Document Intelligence's prebuilt-read model."""

    engine = "azure-document-intelligence"

    def __init__(self, endpoint: str, key: str) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.key = key

    def read_text(self, content: bytes) -> str:
        url = (
            f"{self.endpoint}/documentintelligence/documentModels/"
            f"prebuilt-read:analyze?api-version={API_VERSION}"
        )
        request = Request(
            url,
            data=content,
            headers={
                "Ocp-Apim-Subscription-Key": self.key,
                "Content-Type": "application/octet-stream",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                poll_url = response.headers["Operation-Location"]
            deadline = time.monotonic() + ANALYZE_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                poll = Request(poll_url, headers={"Ocp-Apim-Subscription-Key": self.key})
                with urlopen(poll, timeout=30) as response:
                    result = json.loads(response.read())
                if result.get("status") == "succeeded":
                    return str(result["analyzeResult"].get("content", ""))[:MAX_TEXT_CHARS]
                if result.get("status") == "failed":
                    break
                time.sleep(1)
        except (HTTPError, URLError, TimeoutError, KeyError, TypeError, json.JSONDecodeError):
            pass
        raise ExtractionError("The file could not be read. Please type the values.")


def get_extractor() -> Extractor | None:
    """Return the configured engine, or None when extraction is switched off."""

    endpoint = os.getenv("SCHEME_SAATHI_DOCINTEL_ENDPOINT")
    key = os.getenv("SCHEME_SAATHI_DOCINTEL_KEY")
    if endpoint and key:
        return AzureDocumentIntelligence(endpoint, key)
    return None
