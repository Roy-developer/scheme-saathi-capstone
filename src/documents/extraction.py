"""Suggest a name and date of birth from an uploaded synthetic document.

The suggestion is only a convenience for the person. A human must accept or
edit a value before the checker uses it as typed input. The free Nemotron
vision model only transcribes text; plain code picks values that sit next to a
label such as "Name" or "DOB". A suggestion never says a document is genuine.
"""

import base64
import json
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Protocol

MAX_TEXT_CHARS = 20_000
MAX_VALUE_CHARS = 120
VISION_TIMEOUT_SECONDS = 90
# The free Nemotron model reasons before answering; 512 tokens is all thinking.
VISION_MAX_TOKENS = 6000
DEFAULT_VISION_MODEL = "nvidia/nemotron-3.5-super-vl:free"
VISION_PROMPT = (
    "Transcribe all text visible in this image exactly as written, one "
    "'Label: value' pair per line (keep Hindi/Marathi text as is). Do not "
    "guess, translate, summarise or add anything that is not visible."
)

NAME_LABELS = r"(?:name|नाम|नांव|नाव)"
DOB_LABELS = r"(?:date\s+of\s+birth|d\.?o\.?b\.?|जन्म\s*तिथि|जन्मतारीख|जन्म\s*दिनांक)"
_NAME_PATTERN = re.compile(
    rf"(?im)^\s*(?!father|mother|husband|spouse|family|पिता|माता|पारिवार|परिवार|पति|पत्नी|वडील|वडिल|आई|कुटुंबाचे)[^\n:]{{0,20}}?\b{NAME_LABELS}\b"
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


class OpenRouterVisionExtractor:
    """Transcribe an image with a vision model served through OpenRouter.

    The model only copies visible text; the same label-adjacent parser used
    for OCR then picks the values, so the model never decides what a value is.
    """

    engine = "openrouter-vision"

    def __init__(self, api_key: str, model: str = DEFAULT_VISION_MODEL) -> None:
        self.api_key = api_key
        self.model = model

    def read_text(self, content: bytes) -> str:
        mime = _image_mime(content)
        if mime is None:
            raise ExtractionError(
                "Only JPG or PNG images can be read automatically. Please type the values."
            )
        from langchain_core.messages import HumanMessage

        from src.llm_client import openrouter_chat_model

        data_url = f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"
        message = HumanMessage(content=[
            {"type": "text", "text": VISION_PROMPT},
            {"type": "image_url", "image_url": {"url": data_url}},
        ])
        try:
            reply = openrouter_chat_model(
                self.api_key, self.model,
                timeout=VISION_TIMEOUT_SECONDS, max_tokens=VISION_MAX_TOKENS,
                reasoning_effort="low",
            ).invoke([message])
        except Exception as error:  # provider, network and rate-limit errors
            raise ExtractionError(
                "The file could not be read. Please type the values."
            ) from error
        from src.observability.metrics import record_usage_metadata

        record_usage_metadata({self.model: getattr(reply, "usage_metadata", None)})
        text = reply.content
        if isinstance(text, list):
            text = " ".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in text
            )
        text = str(text).strip()[:MAX_TEXT_CHARS]
        if not text:
            raise ExtractionError("The file could not be read. Please type the values.")
        return text


def _image_mime(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def get_extractor() -> Extractor | None:
    """Return the free Nemotron extractor, or None when it is not configured."""

    api_key = os.getenv("OPENROUTER_API_KEY_FREE")
    if api_key:
        return OpenRouterVisionExtractor(api_key)
    return None
