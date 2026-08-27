"""
Real validation of Bitcoin mainnet addresses - not just a regex shape check.

Implements:
  - Base58Check decode + checksum verification (legacy P2PKH / P2SH)
  - BIP173 (bech32) / BIP350 (bech32m) decode + checksum verification
    (native SegWit v0, Taproot v1)

No external dependencies. A regex can tell you a string LOOKS like an
address; only checksum verification tells you it IS one.
"""

from __future__ import annotations

import hashlib

# ---------------- Base58Check (legacy addresses) ----------------

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

_LEGACY_VERSION_TYPES = {
    0x00: "p2pkh",  # addresses starting with '1'
    0x05: "p2sh",  # addresses starting with '3'
}


def _b58decode(s: str) -> bytes:
    num = 0
    for char in s:
        if char not in _BASE58_ALPHABET:
            raise ValueError(f"invalid base58 character: {char!r}")
        num = num * 58 + _BASE58_ALPHABET.index(char)

    n_leading_ones = len(s) - len(s.lstrip("1"))
    body = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    return b"\x00" * n_leading_ones + body


def _b58decode_check(s: str) -> bytes:
    decoded = _b58decode(s)
    if len(decoded) < 4:
        raise ValueError("base58check payload too short")
    payload, checksum = decoded[:-4], decoded[-4:]
    digest = hashlib.sha256(hashlib.sha256(payload).digest()).digest()
    if digest[:4] != checksum:
        raise ValueError("bad base58check checksum")
    return payload


def _validate_legacy(address: str) -> dict | None:
    try:
        payload = _b58decode_check(address)
    except ValueError:
        return None
    if len(payload) != 21:
        return None
    version = payload[0]
    addr_type = _LEGACY_VERSION_TYPES.get(version)
    if addr_type is None:
        return None
    return {"type": addr_type, "network": "mainnet"}


# ---------------- Bech32 / Bech32m (BIP173 / BIP350) ----------------

_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_CONST = 1
_BECH32M_CONST = 0x2BC830A3


def _polymod(values: list[int]) -> int:
    generator = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (top >> i) & 1:
                chk ^= generator[i]
    return chk


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _bech32_decode(bech: str):
    if any(ord(c) < 33 or ord(c) > 126 for c in bech):
        return None
    if bech.lower() != bech and bech.upper() != bech:
        return None  # mixed case is invalid per spec
    bech = bech.lower()

    pos = bech.rfind("1")
    if pos < 1 or pos + 7 > len(bech) or len(bech) > 90:
        return None

    hrp, data_part = bech[:pos], bech[pos + 1:]
    if not all(c in _CHARSET for c in data_part):
        return None

    data = [_CHARSET.index(c) for c in data_part]
    checksum_const = _polymod(_hrp_expand(hrp) + data)

    if checksum_const == _BECH32_CONST:
        spec = "bech32"
    elif checksum_const == _BECH32M_CONST:
        spec = "bech32m"
    else:
        return None

    return hrp, data[:-6], spec


def _convertbits(data: list[int], frombits: int, tobits: int, pad: bool = True):
    acc = 0
    bits = 0
    ret: list[int] = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret


def _validate_bech32(address: str) -> dict | None:
    decoded = _bech32_decode(address)
    if decoded is None:
        return None
    hrp, data, spec = decoded
    if hrp != "bc" or not data:
        return None

    witness_version = data[0]
    program = _convertbits(data[1:], 5, 8, False)
    if program is None:
        return None

    if witness_version == 0:
        if spec != "bech32" or len(program) not in (20, 32):
            return None
        addr_type = "p2wpkh" if len(program) == 20 else "p2wsh"
    elif 1 <= witness_version <= 16:
        if spec != "bech32m" or not (2 <= len(program) <= 40):
            return None
        addr_type = (
            "p2tr" if witness_version == 1 and len(program) == 32 else f"p2wsh_v{witness_version}"
        )
    else:
        return None

    return {"type": addr_type, "network": "mainnet"}


# ---------------- public entrypoint ----------------

def validate_address(address: str) -> dict | None:
    """
    Returns {'type': <p2pkh|p2sh|p2wpkh|p2wsh|p2tr>, 'network': 'mainnet'}
    if `address` is a checksum-valid Bitcoin mainnet address, else None.
    """
    if address.startswith(("1", "3")):
        return _validate_legacy(address)
    if address.lower().startswith("bc1"):
        return _validate_bech32(address)
    return None
