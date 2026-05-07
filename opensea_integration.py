#!/usr/bin/env python3
"""
OpenSea Integration for mint_bot.py
Resolves collection slugs → contract address via OpenSea API.
Supports: drop mint, fulfill listing, collection lookup.
"""

import os
import json
import subprocess
import sys
import requests

OPENSEA_API_KEY = os.environ.get("OPENSEA_API_KEY", "")
OPENSEA_BASE = "https://api.opensea.io"

def headers():
    h = {
        "Accept": "application/json",
        "User-Agent": "mint-bot/1.0"
    }
    if OPENSEA_API_KEY:
        h["x-api-key"] = OPENSEA_API_KEY
    return h


def resolve_collection(slug: str) -> dict:
    """Resolve OpenSea collection slug → contract info"""
    url = f"{OPENSEA_BASE}/api/v2/collections/{slug}"
    resp = requests.get(url, headers=headers(), timeout=15)
    
    if resp.status_code == 429:
        print(f"[OpenSea] Rate limited, retrying in 2s...")
        import time; time.sleep(2)
        resp = requests.get(url, headers=headers(), timeout=15)
    
    if resp.status_code != 200:
        raise ValueError(f"OpenSea API error {resp.status_code}: {resp.text[:200]}")
    
    data = resp.json()
    contracts = data.get("contracts", [])
    
    if not contracts:
        raise ValueError(f"No contracts found for collection: {slug}")
    
    contract = contracts[0]
    result = {
        "address": contract.get("address"),
        "chain": contract.get("chain", "ethereum"),
        "name": data.get("name", slug),
        "total_supply": data.get("total_supply", "?"),
        "description": data.get("description", "")[:100],
    }
    
    # Detect chain name mapping
    chain_map = {
        "ethereum": "eth", "base": "base", 
        "matic": "matic", "arbitrum": "arbitrum",
        "optimism": "optimism", "avalanche": "avalanche",
        "blast": "blast", "zora": "zora"
    }
    result["chain_short"] = chain_map.get(result["chain"], result["chain"])
    
    return result


def resolve_drop(slug: str) -> dict:
    """Check if collection is a mintable drop"""
    url = f"{OPENSEA_BASE}/api/v2/drops/{slug}"
    resp = requests.get(url, headers=headers(), timeout=15)
    
    if resp.status_code == 200:
        data = resp.json()
        return {
            "is_drop": True,
            "name": data.get("name"),
            "slug": slug,
            "supply": data.get("supply"),
            "price": data.get("price"),
            "currency": data.get("payment_token", {}).get("symbol", "ETH"),
            "start_date": data.get("start_date"),
            "end_date": data.get("end_date"),
        }
    return {"is_drop": False}


def get_drop_mint_tx(slug: str, minter_address: str, quantity: int = 1) -> dict:
    """Get ready-to-sign TX data for drop mint"""
    if not OPENSEA_API_KEY:
        raise ValueError("OPENSEA_API_KEY required for drop mint")
    
    url = f"{OPENSEA_BASE}/api/v2/drops/{slug}/mint"
    body = {
        "minter": minter_address,
        "quantity": quantity
    }
    
    resp = requests.post(url, headers=headers(), json=body, timeout=30)
    
    if resp.status_code != 200:
        raise ValueError(f"Drop mint API error {resp.status_code}: {resp.text[:300]}")
    
    return resp.json()


def get_fulfill_listing_tx(chain: str, order_hash: str, fulfiller: str) -> dict:
    """Get TX data to buy an NFT from secondary market"""
    if not OPENSEA_API_KEY:
        raise ValueError("OPENSEA_API_KEY required for fulfill listing")
    
    protocol = "0x0000000000000068f116a894984e2db1123eb395"
    url = f"{OPENSEA_BASE}/api/v2/listings/fulfillment_data"
    body = {
        "listing": {
            "hash": order_hash,
            "chain": chain,
            "protocol_address": protocol
        },
        "fulfiller": {
            "address": fulfiller
        }
    }
    
    resp = requests.post(url, headers=headers(), json=body, timeout=30)
    
    if resp.status_code != 200:
        raise ValueError(f"Fulfill listing API error {resp.status_code}: {resp.text[:300]}")
    
    return resp.json()


def get_listings(slug: str, chain: str = "ethereum") -> list:
    """Get active listings for a collection"""
    url = f"{OPENSEA_BASE}/api/v2/listings/collection/{slug}"
    params = {"chain": chain}
    
    resp = requests.get(url, headers=headers(), params=params, timeout=15)
    
    if resp.status_code != 200:
        raise ValueError(f"Listings API error {resp.status_code}: {resp.text[:200]}")
    
    data = resp.json()
    return data.get("listings", [])


def get_collection_stats(slug: str) -> dict:
    """Get collection floor price, volume, etc."""
    url = f"{OPENSEA_BASE}/api/v2/collections/{slug}/stats"
    resp = requests.get(url, headers=headers(), timeout=15)
    
    if resp.status_code == 200:
        return resp.json()
    return {}


if __name__ == "__main__":
    # Quick test
    if len(sys.argv) < 2:
        print("Usage: opensea_integration.py <collection_slug>")
        sys.exit(1)
    
    slug = sys.argv[1]
    print(f"Resolving: {slug}")
    
    try:
        info = resolve_collection(slug)
        print(json.dumps(info, indent=2))
    except Exception as e:
        print(f"Error: {e}")
