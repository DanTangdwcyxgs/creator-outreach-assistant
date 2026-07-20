from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime


IOS_TIME_FIRST = re.compile(
    r"^\[(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?),\s*"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\]\s*"
    r"(?P<sender>[^:]+):\s?(?P<body>.*)$",
    re.IGNORECASE,
)
IOS_DATE_FIRST = re.compile(
    r"^\[(?P<date>\d{1,2}/\d{1,2}/\d{2,4}),\s*"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)\]\s*"
    r"(?P<sender>[^:]+):\s?(?P<body>.*)$",
    re.IGNORECASE,
)
ANDROID = re.compile(
    r"^(?P<date>\d{1,2}/\d{1,2}/\d{2,4}),\s*"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)\s+-\s+"
    r"(?P<sender>[^:]+):\s?(?P<body>.*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedMessage:
    sent_at: str
    sender: str
    body: str
    fingerprint: str


def _normalise_timestamp(date_text: str, time_text: str) -> str:
    cleaned = f"{date_text.strip()} {time_text.strip().upper()}"
    formats = (
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%y %I:%M %p",
        "%m/%d/%y %I:%M:%S %p",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
    )
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).isoformat(timespec="seconds")
        except ValueError:
            continue
    return cleaned


def _compact_body(lines: list[str]) -> str:
    body = "\n".join(lines).replace("\u200e", "").replace("\u202a", "")
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def _fingerprint(sent_at: str, sender: str, body: str) -> str:
    payload = "\x1f".join((sent_at, sender.casefold().strip(), body.strip()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_whatsapp_text(text: str) -> list[ParsedMessage]:
    messages: list[ParsedMessage] = []
    current: dict[str, object] | None = None

    def flush() -> None:
        nonlocal current
        if not current:
            return
        body = _compact_body(current["lines"])  # type: ignore[arg-type]
        sender = str(current["sender"]).strip()
        sent_at = str(current["sent_at"])
        if body:
            messages.append(
                ParsedMessage(sent_at, sender, body, _fingerprint(sent_at, sender, body))
            )
        current = None

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip().replace("\u200e", "").replace("\u202a", "").replace("\u202c", "")
        match = IOS_TIME_FIRST.match(line) or IOS_DATE_FIRST.match(line) or ANDROID.match(line)
        if match:
            flush()
            data = match.groupdict()
            current = {
                "sent_at": _normalise_timestamp(data["date"], data["time"]),
                "sender": data["sender"],
                "lines": [data.get("body", "")],
            }
        elif current is not None:
            current["lines"].append(line)  # type: ignore[union-attr]
    flush()
    return messages


def participants(messages: list[ParsedMessage]) -> list[str]:
    seen: dict[str, str] = {}
    for message in messages:
        seen.setdefault(message.sender.casefold(), message.sender)
    return list(seen.values())
