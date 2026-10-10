"""Repair of UTF-8 text that was decoded as Latin-1 / Windows-1252 ("mojibake", e.g. "Iâ€™m" for "I’m").

Web pages served without a charset in their Content-Type header used to be decoded as ISO-8859-1
(requests' default), so their UTF-8 bytes were stored as mojibake. `repair_mojibake` reverses exactly
that: it only rewrites a lead character followed by the right number of continuation characters
when those bytes form valid UTF-8. Correctly encoded text — including "’", "é", "—" — never matches,
so it is returned unchanged.
"""

from typing import Optional

_CP1252_SPECIALS = {ch: b for b in range(0x80, 0xA0) for ch in [bytes([b]).decode("cp1252", errors="ignore")] if ch}


def _byte(ch: str) -> Optional[int]:
    """The single byte a Latin-1/cp1252 decoder turned into `ch`, if any."""
    code = ord(ch)
    if code < 0x100:
        return code
    return _CP1252_SPECIALS.get(ch)


def _continuations(lead: int) -> int:
    if 0xC2 <= lead <= 0xDF:
        return 1
    if 0xE0 <= lead <= 0xEF:
        return 2
    if 0xF0 <= lead <= 0xF4:
        return 3
    return 0


def repair_mojibake(text: Optional[str]) -> Optional[str]:
    if not text:
        return text
    out, i, n = [], 0, len(text)
    while i < n:
        lead = ord(text[i])
        need = _continuations(lead) if lead < 0x100 else 0
        if need:
            chunk = text[i + 1:i + 1 + need]
            raw = [_byte(c) for c in chunk]
            if len(chunk) == need and all(b is not None and 0x80 <= b <= 0xBF for b in raw):
                try:
                    out.append(bytes([lead, *raw]).decode("utf-8"))
                    i += 1 + need
                    continue
                except UnicodeDecodeError:
                    pass
        out.append(text[i])
        i += 1
    return "".join(out)


def has_mojibake(text: Optional[str]) -> bool:
    """True when text holds encoding damage: repairable mojibake, stray C1 control characters, or U+FFFD."""
    if not text:
        return False
    return "\ufffd" in text or any(0x80 <= ord(c) <= 0x9F for c in text) or repair_mojibake(text) != text
