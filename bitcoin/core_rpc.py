"""
Minimal JSON-RPC client for Bitcoin Core, used to enrich web-discovered
addresses with on-chain reality.

IMPORTANT LIMITATION: Bitcoin Core does not index arbitrary addresses by
default (no built-in "give all transactions for address X").  
`scantxoutset` checks the CURRENT UTXO set only. 
True = the address currently holds unspent funds (solid evidence it's real and was funded). 
False proves nothing about history - a spent-out address that was used heavily in the past will also
show False, since scantxoutset can't see spent outputs. 
"""

from __future__ import annotations

import httpx

from config import RPC


class BitcoinRPCError(Exception):
    pass


def _call(method: str, params: list | None = None):
    if not RPC.enabled:
        raise BitcoinRPCError("Bitcoin Core RPC is disabled. Set BTC_RPC_ENABLED=true in .env.")

    url = f"http://{RPC.host}:{RPC.port}/"
    payload = {"jsonrpc": "1.0", "id": "btc_collector", "method": method, "params": params or []}

    response = httpx.post(url, json=payload, auth=(RPC.user, RPC.password), timeout=120)
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise BitcoinRPCError(str(data["error"]))
    return data["result"]


def get_blockchain_info() -> dict:
    return _call("getblockchaininfo")


def scan_address(address: str) -> dict:
    """
    Checks the CURRENT UTXO set for this address via scantxoutset.
    Does not require txindex. Can take a while on a full node the first
    time (it scans the whole UTXO set), so don't call this per-address
    in a tight loop against a busy node - batch it, or run scantxoutset
    with multiple descriptors at once if you need to check many addresses.
    """
    descriptor = {"desc": f"addr({address})"}
    result = _call("scantxoutset", ["start", [descriptor]])
    return {
        "address": address,
        "has_utxo": result.get("total_amount", 0) > 0,
        "total_amount_btc": result.get("total_amount", 0),
        "utxo_count": len(result.get("unspents", [])),
        "unspents": result.get("unspents", []),
    }
