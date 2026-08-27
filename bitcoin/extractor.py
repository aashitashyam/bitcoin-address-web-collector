"""
Finds strings in text that LOOK like Bitcoin addresses. This is a cheap
first-pass filter only - every candidate MUST be passed through
bitcoin.validator.validate_address() before you trust it, since random
alphanumeric strings can accidentally match the shape.
"""

import re

BTC_ADDRESS_REGEX = re.compile(
    r"""
    (?<![A-Za-z0-9])
    (?:
        [13][a-km-zA-HJ-NP-Z1-9]{25,34}     # legacy P2PKH / P2SH
        |
        bc1[ac-hj-np-z02-9]{11,71}          # bech32 / bech32m (segwit, taproot)
    )
    (?![A-Za-z0-9])
    """,
    re.VERBOSE | re.IGNORECASE,
)


def find_candidates(text: str) -> list[str]:
    """De-duplicated candidate strings, order preserved."""
    return list(dict.fromkeys(BTC_ADDRESS_REGEX.findall(text)))


def extract_context(text: str, address: str, window: int = 200) -> str:
    """Grab the text surrounding an address occurrence, for provenance."""
    pos = text.lower().find(address.lower())
    if pos == -1:
        return ""
    start = max(0, pos - window)
    end = min(len(text), pos + len(address) + window)
    return text[start:end]
