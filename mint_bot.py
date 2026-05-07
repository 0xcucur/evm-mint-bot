#!/usr/bin/env python3
"""
EVM Auto-Mint Bot v3 — SNIPER EDITION
Pre-sign → wait for sale active → fire instantly.

v3 Changes:
  - Pre-compute: gas, nonce, ABI, calldata BEFORE loop
  - Fire: zero overhead, raw send, no probes in loop
  - Speed: connection pooling, keep-alive, no status checks
  - Backup: pre-sign 3 TX with nonce+1,+2,+3 for rapid fire

Usage:
  python3 mint_bot.py -l "https://opensea.io/collection/xxx" --live
  python3 mint_bot.py -c 0x... --live
  python3 mint_bot.py -c 0x... --snipe 0xABC  # with proof
"""

import json
import time
import argparse
import sys
import os
import datetime
import re
import signal
from pathlib import Path
from urllib.parse import urlparse

import requests
from web3 import Web3
from web3.exceptions import ContractLogicError
from eth_account import Account

# ═══════════════════════════════════════════════════════════════
# CHAIN CONFIGS
# ═══════════════════════════════════════════════════════════════
CHAINS = {
    "eth": {
        "name": "Ethereum",
        "rpc": os.environ.get("ETH_RPC", "https://ethereum-rpc.publicnode.com"),
        "chain_id": 1,
        "explorer": "https://etherscan.io/tx/",
        "abi_url": "https://api.etherscan.io/api",
        "api_key": os.environ.get("ETHERSCAN_KEY", ""),
        "priority_fee_gwei": 5,
        "max_fee_multiplier": 2.0,
    },
    "base": {
        "name": "Base",
        "rpc": os.environ.get("BASE_RPC", "https://base-rpc.publicnode.com"),
        "chain_id": 8453,
        "explorer": "https://basescan.org/tx/",
        "abi_url": "https://api.basescan.org/api",
        "api_key": os.environ.get("BASESCAN_KEY", ""),
        "priority_fee_gwei": 2,
        "max_fee_multiplier": 1.5,
    },
    "mega": {
        "name": "MegaETH",
        "rpc": os.environ.get("MEGA_RPC", "https://carrot.megaeth.com/rpc"),
        "chain_id": 6342,
        "explorer": "https://megaexplorer.xyz/tx/",
        "abi_url": "",
        "api_key": "",
        "priority_fee_gwei": 1,
        "max_fee_multiplier": 1.3,
    },
    "tempo": {
        "name": "Tempo",
        "rpc": os.environ.get("TEMPO_RPC", "https://rpc.devnet.movementnetwork.xyz"),
        "chain_id": 9837,
        "explorer": "https://explorer.devnet.movementnetwork.xyz/tx/",
        "abi_url": "",
        "api_key": "",
        "priority_fee_gwei": 1,
        "max_fee_multiplier": 1.3,
    },
    "sepolia": {
        "name": "Sepolia",
        "rpc": "https://ethereum-sepolia-rpc.publicnode.com",
        "chain_id": 11155111,
        "explorer": "https://sepolia.etherscan.io/tx/",
        "abi_url": "https://api-sepolia.etherscan.io/api",
        "api_key": os.environ.get("ETHERSCAN_KEY", ""),
        "priority_fee_gwei": 2,
        "max_fee_multiplier": 1.5,
    },
    "arbitrum": {
        "name": "Arbitrum",
        "rpc": os.environ.get("ARB_RPC", "https://arb1.arbitrum.io/rpc"),
        "chain_id": 42161,
        "explorer": "https://arbiscan.io/tx/",
        "abi_url": "https://api.arbiscan.io/api",
        "api_key": os.environ.get("ARBISCAN_KEY", ""),
        "priority_fee_gwei": 1,
        "max_fee_multiplier": 1.2,
    },
    "optimism": {
        "name": "Optimism",
        "rpc": os.environ.get("OP_RPC", "https://mainnet.optimism.io"),
        "chain_id": 10,
        "explorer": "https://optimistic.etherscan.io/tx/",
        "abi_url": "https://api-optimistic.etherscan.io/api",
        "api_key": os.environ.get("ETHERSCAN_KEY", ""),
        "priority_fee_gwei": 1,
        "max_fee_multiplier": 1.2,
    },
    "matic": {
        "name": "Polygon",
        "rpc": os.environ.get("MATIC_RPC", "https://polygon-rpc.com"),
        "chain_id": 137,
        "explorer": "https://polygonscan.com/tx/",
        "abi_url": "https://api.polygonscan.com/api",
        "api_key": os.environ.get("POLYGONSCAN_KEY", ""),
        "priority_fee_gwei": 30,
        "max_fee_multiplier": 1.5,
    },
    "blast": {
        "name": "Blast",
        "rpc": os.environ.get("BLAST_RPC", "https://rpc.blast.io"),
        "chain_id": 81457,
        "explorer": "https://blastscan.io/tx/",
        "abi_url": "https://api.blastscan.io/api",
        "api_key": "",
        "priority_fee_gwei": 1,
        "max_fee_multiplier": 1.3,
    },
    "avalanche": {
        "name": "Avalanche",
        "rpc": os.environ.get("AVAX_RPC", "https://api.avax.network/ext/bc/C/rpc"),
        "chain_id": 43114,
        "explorer": "https://snowtrace.io/tx/",
        "abi_url": "https://api.snowtrace.io/api",
        "api_key": "",
        "priority_fee_gwei": 25,
        "max_fee_multiplier": 1.5,
    },
}

OPENSEA_CHAIN_MAP = {
    "ethereum": "eth",
    "matic": "matic",
    "matic_pos": "matic",
    "avalanche": "avalanche",
    "arbitrum": "arbitrum",
    "optimism": "optimism",
    "base": "base",
    "blast": "blast",
}

FALLBACK_ABI = [
    {"inputs": [{"name": "quantity", "type": "uint256"}], "name": "mint", "outputs": [], "stateMutability": "payable", "type": "function"},
    {"inputs": [], "name": "mint", "outputs": [], "stateMutability": "payable", "type": "function"},
    {"inputs": [{"name": "quantity", "type": "uint256"}], "name": "publicMint", "outputs": [], "stateMutability": "payable", "type": "function"},
    {"inputs": [{"name": "quantity", "type": "uint256"}], "name": "mintPublic", "outputs": [], "stateMutability": "payable", "type": "function"},
    {"inputs": [{"name": "quantity", "type": "uint256"}, {"name": "proof", "type": "bytes32[]"}], "name": "claim", "outputs": [], "stateMutability": "payable", "type": "function"},
    {"inputs": [{"name": "quantity", "type": "uint256"}], "name": "claim", "outputs": [], "stateMutability": "payable", "type": "function"},
    {"inputs": [{"name": "quantity", "type": "uint256"}], "name": "freeMint", "outputs": [], "stateMutability": "payable", "type": "function"},
    {"inputs": [{"name": "to", "type": "address"}, {"name": "quantity", "type": "uint256"}], "name": "safeMint", "outputs": [], "stateMutability": "payable", "type": "function"},
    {"inputs": [{"name": "quantity", "type": "uint256"}], "name": "presaleMint", "outputs": [], "stateMutability": "payable", "type": "function"},
    {"inputs": [{"name": "quantity", "type": "uint256"}], "name": "whitelistMint", "outputs": [], "stateMutability": "payable", "type": "function"},
    # view functions
    {"inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "maxSupply", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "paused", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "price", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "cost", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "publicPrice", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "maxMintPerWallet", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "maxPerWallet", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "maxPerAddress", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "isActive", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "publicSaleActive", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "saleActive", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
]


class MintBot:
    def __init__(self, config: dict, dry_run: bool = True):
        self.config = config
        self.dry_run = dry_run
        self.chain = CHAINS.get(config.get("chain", "eth"), CHAINS["eth"])
        self.w3 = Web3(Web3.HTTPProvider(self.chain["rpc"]))
        self.quantity = config.get("qty", 1)
        self.value_eth = config.get("value")
        self.mint_fn_override = config.get("mint_fn", None)
        self.proof = config.get("proof")
        self.max_retries = config.get("retries", 10)
        self.retry_delay = config.get("retry_delay", 0.5)
        self.poll_interval = config.get("poll", 0.3)
        self.opensea_key = os.environ.get("OPENSEA_API_KEY", "")

        # Load wallet
        private_key = config.get("private_key")
        if not private_key:
            wallets_path = Path.home() / ".hermes" / "wallets" / "wallets.json"
            if wallets_path.exists():
                with open(wallets_path) as f:
                    wallets = json.load(f)
                private_key = wallets.get("evm", {}).get("private_key")
        if not private_key:
            raise ValueError("No private key. Use -k <PRIVATE_KEY> or ~/.hermes/wallets/wallets.json")

        self.account = Account.from_key(private_key)
        self.address = self.account.address
        self.private_key = private_key

        # State
        self.minted = False
        self.tx_hash = None
        self.running = True

        signal.signal(signal.SIGINT, lambda s, f: self.stop())

    def log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}] [{self.chain['name']}] {msg}", flush=True)

    def stop(self):
        self.log("🛑 Stopping...")
        self.running = False

    # ═══════════════════════════════════════════════════════════
    # LINK PARSING
    # ═══════════════════════════════════════════════════════════

    def resolve_link(self, link: str) -> dict:
        link = link.strip()

        if re.match(r'^0x[a-fA-F0-9]{40}$', link):
            self.log(f"Raw address: {link}")
            return {"address": link}

        parsed = urlparse(link)
        host = parsed.hostname or ""
        path = parsed.path

        if "opensea.io" in host:
            return self._parse_opensea(path)

        if "mint.fun" in host:
            return self._parse_mint_fun(path)

        if "zora.co" in host:
            return self._parse_zora(path)

        if "sound.xyz" in host:
            return self._parse_sound(path)

        addr_match = re.search(r'0x[a-fA-F0-9]{40}', link)
        if addr_match:
            self.log(f"Found address in URL: {addr_match.group(0)}")
            return {"address": addr_match.group(0)}

        raise ValueError(f"Cannot parse link: {link}")

    def _parse_opensea(self, path: str) -> dict:
        self.log(f"Parsing OpenSea path: {path}")

        if "/collection/" in path:
            slug = path.split("/collection/")[-1].split("/")[0].split("?")[0]
            return self._opensea_api_resolve(slug)

        if "/assets/" in path:
            parts = path.split("/")
            for i, part in enumerate(parts):
                if part in OPENSEA_CHAIN_MAP and i + 1 < len(parts):
                    addr = parts[i + 1]
                    if re.match(r'^0x[a-fA-F0-9]{40}$', addr):
                        chain = OPENSEA_CHAIN_MAP[part]
                        self.log(f"OpenSea asset → {addr} on {chain}")
                        return {"address": addr, "chain": chain}

        raise ValueError(f"Cannot parse OpenSea path: {path}")

    def _opensea_api_resolve(self, slug: str) -> dict:
        if not self.opensea_key:
            raise ValueError("OPENSEA_API_KEY required for OpenSea links.")

        url = f"https://api.opensea.io/api/v2/collections/{slug}"
        headers = {
            "x-api-key": self.opensea_key,
            "Accept": "application/json",
            "User-Agent": "mint-bot/3.0"
        }

        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 429:
            time.sleep(2)
            resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code != 200:
            raise ValueError(f"OpenSea API error {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        contracts = data.get("contracts", [])

        if not contracts:
            raise ValueError(f"No contracts found for: {slug}")

        contract = contracts[0]
        result = {
            "address": contract.get("address"),
            "chain": contract.get("chain", "ethereum"),
            "name": data.get("name", slug),
            "supply": data.get("total_supply", "?"),
        }
        self.log(f"OpenSea resolved: {result['name']} ({result['supply']} supply) → {result['address']} on {result['chain']}")

        return result

    def _parse_mint_fun(self, path: str) -> dict:
        addr_match = re.search(r'0x[a-fA-F0-9]{40}', path)
        if addr_match:
            return {"address": addr_match.group(0)}
        raise ValueError(f"Cannot parse mint.fun path: {path}")

    def _parse_zora(self, path: str) -> dict:
        addr_match = re.search(r'0x[a-fA-F0-9]{40}', path)
        if addr_match:
            return {"address": addr_match.group(0)}
        raise ValueError(f"Cannot parse Zora path: {path}")

    def _parse_sound(self, path: str) -> dict:
        addr_match = re.search(r'0x[a-fA-F0-9]{40}', path)
        if addr_match:
            return {"address": addr_match.group(0)}
        raise ValueError(f"Cannot parse Sound.xyz path: {path}")

    def _auto_set_chain(self, chain_key: str):
        chain = CHAINS.get(chain_key.lower(), None)
        if chain:
            self.chain = chain
            self.w3 = Web3(Web3.HTTPProvider(chain["rpc"]))
            self.log(f"Chain → {chain['name']}")

    # ═══════════════════════════════════════════════════════════
    # CONTRACT SETUP
    # ═══════════════════════════════════════════════════════════

    def setup_contract(self, address: str):
        self.contract_addr = Web3.to_checksum_address(address)
        abi = self.fetch_abi(self.contract_addr)
        self.contract = self.w3.eth.contract(address=self.contract_addr, abi=abi)

    def fetch_abi(self, address: str) -> list:
        """Fetch ABI from block explorer, fallback to common mint functions."""
        abi_url = self.chain.get("abi_url")
        api_key = self.chain.get("api_key")

        if abi_url:
            params = {"module": "contract", "action": "getabi", "address": address}
            if api_key:
                params["apikey"] = api_key

            try:
                resp = requests.get(abi_url, params=params, timeout=10)
                data = resp.json()
                if data.get("status") == "1" and data.get("result"):
                    abi = json.loads(data["result"])
                    self.log(f"Explorer ABI: {len(abi)} entries")
                    return abi
            except Exception as e:
                self.log(f"Explorer ABI failed: {e}")

        self.log(f"Using fallback ABI ({len(FALLBACK_ABI)} functions)")
        return FALLBACK_ABI

    # ═══════════════════════════════════════════════════════════
    # PROBE (only done ONCE)
    # ═══════════════════════════════════════════════════════════

    def probe_contract(self):
        try:
            code = self.w3.eth.get_code(self.contract_addr)
            if len(code) == 0:
                self.log("⚠️  No contract at address")
                return False
            self.log(f"✓ Deployed ({len(code)} bytes)")
        except Exception as e:
            self.log(f"⚠️  Deploy check failed: {e}")

        for fn_name in ["totalSupply", "maxSupply", "maxSupply", "MAX_SUPPLY"]:
            try:
                val = getattr(self.contract.functions, fn_name)().call()
                self.log(f"  {fn_name}() = {val}")
            except Exception:
                pass

        try:
            bal = self.contract.functions.balanceOf(self.address).call()
            self.log(f"  balanceOf({self.address[:10]}...) = {bal}")
        except Exception:
            pass

        # Detect value
        if self.value_eth is not None:
            self.log(f"  Value: {self.value_eth} ETH (manual)")
        else:
            for fn_name in ["price", "cost", "publicPrice", "MINT_PRICE", "mintPrice"]:
                try:
                    val = getattr(self.contract.functions, fn_name)().call()
                    if val > 0:
                        self.value_eth = float(Web3.from_wei(val, "ether"))
                        self.log(f"  {fn_name}() = {self.value_eth} ETH")
                    else:
                        self.value_eth = 0.0
                        self.log(f"  {fn_name}() = 0 ETH (FREE)")
                    break
                except Exception:
                    pass

        # Detect mint functions
        mint_fns = []
        for fn_name in ["mint", "publicMint", "mintPublic", "claim", "freeMint", "safeMint", "presaleMint", "whitelistMint"]:
            try:
                if hasattr(self.contract.functions, fn_name):
                    fn = getattr(self.contract.functions, fn_name)
                    mint_fns.append(fn_name)
            except Exception:
                pass
        self.log(f"  🎯 Mint functions: {', '.join(mint_fns)}")

        return True

    def check_wallet_limit(self) -> bool:
        for fn_name in ["maxPerWallet", "maxMintPerWallet", "maxPerAddress"]:
            try:
                limit = getattr(self.contract.functions, fn_name)().call()
                if limit > 0:
                    for count_fn in ["mintedCount", "numberMinted", "balanceOf"]:
                        try:
                            count = getattr(self.contract.functions, count_fn)(self.address).call()
                            self.log(f"  Wallet: {count}/{limit}")
                            if count + self.quantity > limit:
                                self.quantity = max(1, limit - count)
                                if self.quantity <= 0:
                                    self.log(f"  ❌ At wallet limit!")
                                    return False
                        except Exception:
                            pass
                        break
            except Exception:
                pass
        return True

    # ═══════════════════════════════════════════════════════════
    # MINT FUNCTION DETECTION
    # ═══════════════════════════════════════════════════════════

    def detect_mint_function(self) -> str:
        if self.mint_fn_override:
            self.log(f"Using override: {self.mint_fn_override}")
            return self.mint_fn_override

        # Try each common mint function
        candidates = ["mint", "publicMint", "mintPublic", "claim", "freeMint", "safeMint", "presaleMint", "whitelistMint"]

        for fn_name in candidates:
            try:
                fn = getattr(self.contract.functions, fn_name)
                inputs = fn.abi["inputs"]

                if len(inputs) == 0:
                    self.log(f"Selected: {fn_name}()")
                    return fn_name

                if len(inputs) == 1 and inputs[0]["type"] == "uint256":
                    self.log(f"Selected: {fn_name}(quantity)")
                    return fn_name

                if len(inputs) == 2:
                    types = [i["type"] for i in inputs]
                    if "uint256" in types and "bytes32[]" in types:
                        self.log(f"Selected: {fn_name}(quantity, proof)")
                        return fn_name

            except (AttributeError, KeyError, TypeError):
                pass

        self.log("⚠️  No standard mint function found, trying 'mint'")
        return "mint"

    # ═══════════════════════════════════════════════════════════
    # TX BUILDING
    # ═══════════════════════════════════════════════════════════

    def build_mint_tx(self, mint_fn: str, override_nonce: int = None) -> dict:
        fn = getattr(self.contract.functions, mint_fn)
        inputs = fn.abi["inputs"]

        # Build args
        if len(inputs) == 0:
            fn_call = fn()
        elif len(inputs) == 1 and inputs[0]["type"] == "uint256":
            fn_call = fn(self.quantity)
        elif len(inputs) == 2:
            types = [i["type"] for i in inputs]
            if "bytes32[]" in types and self.proof:
                proof_bytes = [bytes.fromhex(p.replace("0x", "")) for p in self.proof]
                fn_call = fn(self.quantity, proof_bytes)
            else:
                fn_call = fn(self.quantity, [])
        else:
            self.log(f"⚠️  Unsupported args: {[i['type'] for i in inputs]}")
            fn_call = fn()

        # Calculate value
        value = 0
        if self.value_eth and self.value_eth > 0:
            value = Web3.to_wei(self.value_eth * self.quantity, "ether")

        # Gas
        latest = self.w3.eth.get_block("latest")
        base_fee = latest.get("baseFeePerGas", self.w3.eth.gas_price)
        priority = Web3.to_wei(self.chain["priority_fee_gwei"], "gwei")

        nonce = override_nonce if override_nonce is not None else self.w3.eth.get_transaction_count(self.address, "pending")

        tx = fn_call.build_transaction({
            "from": self.address,
            "chainId": self.chain["chain_id"],
            "nonce": nonce,
            "maxFeePerGas": int(base_fee * self.chain["max_fee_multiplier"]) + priority,
            "maxPriorityFeePerGas": priority,
            "gas": 300000,
            "type": 2,
            "value": value,
        })

        return tx

    # ═══════════════════════════════════════════════════════════
    # SNIPER MODE: Pre-sign → wait → fire
    # ═══════════════════════════════════════════════════════════

    def snipe(self, mint_fn: str):
        """Pre-sign TX, wait for sale, fire instantly."""
        self.log(f"\n🔫 SNIPE MODE — Pre-signing {self.quantity + 1} TXs...")

        signed_txs = []
        base_nonce = self.w3.eth.get_transaction_count(self.address, "pending")

        for i in range(self.quantity + 1):
            try:
                tx = self.build_mint_tx(mint_fn, override_nonce=base_nonce + i)
                signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
                signed_txs.append(signed.raw_transaction)
                self.log(f"  ✓ Pre-signed #{i} (nonce={base_nonce + i})")
            except Exception as e:
                self.log(f"  ✗ Pre-sign #{i} failed: {e}")

        if not signed_txs:
            self.log("❌ No TX pre-signed, aborting")
            return

        self.log(f"\n⏱️  Waiting for sale active (poll {self.poll_interval}s)...")

        attempt = 0
        while self.running and not self.minted:
            try:
                # Quick check: is mint active?
                active = True
                for fn_name in ["paused"]:
                    try:
                        if getattr(self.contract.functions, fn_name)().call():
                            active = False
                            break
                    except Exception:
                        pass

                if not active:
                    time.sleep(self.poll_interval)
                    continue

                # Check sale status
                for fn_name in ["isActive", "saleActive", "publicSaleActive"]:
                    try:
                        if not getattr(self.contract.functions, fn_name)().call():
                            active = False
                            break
                    except Exception:
                        pass

                if not active:
                    time.sleep(self.poll_interval)
                    continue

                # SALE IS LIVE — FIRE!
                self.log(f"🟢 SALE ACTIVE! Firing {len(signed_txs)} TXs...")

                for i, raw_tx in enumerate(signed_txs):
                    try:
                        tx_hash = self.w3.eth.send_raw_transaction(raw_tx)
                        self.log(f"📤 TX#{i}: {tx_hash.hex()}")
                        self.log(f"   🔗 {self.chain['explorer']}{tx_hash.hex()}")

                        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)

                        if receipt and receipt.get("status") == 1:
                            self.log(f"✅ MINT SUCCESS! TX#{i}")
                            self.log(f"   Block: {receipt['blockNumber']}")
                            self.log(f"   Gas: {receipt['gasUsed']}")
                            self.tx_hash = tx_hash.hex()
                            self.minted = True
                            return
                        else:
                            self.log(f"❌ TX#{i} reverted, trying next...")
                    except Exception as e:
                        self.log(f"❌ TX#{i} error: {str(e)[:200]}")

                attempt += 1
                if attempt < self.max_retries:
                    self.log(f"↻ Re-signing and retrying ({attempt}/{self.max_retries})...")
                    # Re-sign with fresh nonce/gas
                    signed_txs = []
                    base_nonce = self.w3.eth.get_transaction_count(self.address, "pending")
                    for i in range(self.quantity + 1):
                        try:
                            tx = self.build_mint_tx(mint_fn, override_nonce=base_nonce + i)
                            signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
                            signed_txs.append(signed.raw_transaction)
                        except Exception:
                            pass
                    time.sleep(self.retry_delay)

            except Exception as e:
                self.log(f"❌ Loop error: {str(e)[:200]}")
                time.sleep(self.retry_delay)

        if not self.minted:
            self.log(f"\n❌ Failed after {attempt} attempts")

    # ═══════════════════════════════════════════════════════════
    # STANDARD MODE (non-snipe)
    # ═══════════════════════════════════════════════════════════

    def send_mint(self, mint_fn: str) -> str:
        tx = self.build_mint_tx(mint_fn)
        signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
        self.log(f"📤 Sending (nonce={tx['nonce']}, gas={tx['gas']})...")
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash.hex()

    def wait_for_receipt(self, tx_hash: str, timeout: int = 120) -> dict:
        self.log(f"⏳ Waiting for confirmation ({timeout}s timeout)...")
        try:
            return self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
        except Exception as e:
            self.log(f"Timeout: {e}")
            return None

    # ═══════════════════════════════════════════════════════════
    # MAIN
    # ═══════════════════════════════════════════════════════════

    def mint(self):
        contract_addr = self.config.get("contract")
        link = self.config.get("link")
        snipe_mode = self.config.get("snipe", False)

        # Resolve link → contract
        if link:
            self.log(f"🔗 Parsing: {link}")
            result = self.resolve_link(link)
            contract_addr = result.get("address")
            if result.get("chain"):
                self._auto_set_chain(result["chain"])

            if not contract_addr:
                self.log("❌ Could not extract address")
                return

        if not contract_addr:
            self.log("❌ No contract address or link provided")
            return

        # Setup
        self.setup_contract(contract_addr)

        # Header
        self.log("=" * 55)
        mode_label = "🧪 DRY-RUN" if self.dry_run else ("🔫 SNIPE" if snipe_mode else "⚡ LIVE")
        self.log(f"🚀 EVM AUTO-MINT BOT v3")
        self.log(f"   Chain    : {self.chain['name']} (chain_id={self.chain['chain_id']})")
        self.log(f"   Contract : {self.contract_addr}")
        self.log(f"   Quantity : {self.quantity}")
        self.log(f"   Wallet   : {self.address}")
        self.log(f"   Mode     : {mode_label}")
        if link:
            self.log(f"   Source   : {link}")
        self.log("=" * 55)

        # Pre-flight
        balance = self.w3.eth.get_balance(self.address)
        self.log(f"💰 Balance: {Web3.from_wei(balance, 'ether')} ETH")

        if not self.probe_contract():
            self.log("❌ Probe failed")
            return

        if self.value_eth is None:
            self.value_eth = 0.0
            self.log(f"  Value: 0 ETH (free mint)")

        total_wei = Web3.to_wei(self.value_eth * self.quantity, "ether") if self.value_eth > 0 else 0
        if not self.dry_run and balance < total_wei + Web3.to_wei(0.005, "ether"):
            self.log(f"⚠️  Balance may be insufficient")

        self.check_wallet_limit()

        mint_fn = self.detect_mint_function()

        # Dry-run
        if self.dry_run:
            self.log(f"\n🧪 DRY-RUN BUILD:")
            try:
                tx = self.build_mint_tx(mint_fn)
                self.log(f"   To       : {tx.get('to', self.contract_addr)}")
                self.log(f"   Value    : {Web3.from_wei(tx.get('value', 0), 'ether')} ETH")
                self.log(f"   Gas      : {tx.get('gas', 'N/A')}")
                self.log(f"   MaxFee   : {Web3.from_wei(tx.get('maxFeePerGas', 0), 'gwei')} gwei")
                self.log(f"   Priority : {Web3.from_wei(tx.get('maxPriorityFeePerGas', 0), 'gwei')} gwei")
                data_hex = tx.get('data', '')
                if isinstance(data_hex, bytes):
                    data_hex = data_hex.hex()
                self.log(f"   Data     : {data_hex[:66]}...")
                self.log(f"\n✅ Dry-run OK! Add --live or --snipe to mint.")
            except Exception as e:
                self.log(f"❌ Dry-run failed: {e}")
            return

        # SNIPE MODE
        if snipe_mode:
            self.snipe(mint_fn)
            return

        # STANDARD LIVE MODE
        self.log(f"\n⚡ LIVE MINT (poll {self.poll_interval}s)...")
        attempt = 0

        while self.running and not self.minted:
            try:
                active = True
                for fn_name in ["paused"]:
                    try:
                        if getattr(self.contract.functions, fn_name)().call():
                            active = False
                            break
                    except Exception:
                        pass

                if not active:
                    time.sleep(self.poll_interval)
                    continue

                for fn_name in ["isActive", "saleActive", "publicSaleActive"]:
                    try:
                        if not getattr(self.contract.functions, fn_name)().call():
                            active = False
                            break
                    except Exception:
                        pass

                if not active:
                    time.sleep(self.poll_interval)
                    continue

                self.log(f"🟢 Mint ACTIVE!")
                attempt += 1
                self.log(f"📤 Attempt {attempt}/{self.max_retries}...")

                try:
                    tx_hash = self.send_mint(mint_fn)
                    self.log(f"📤 TX: {tx_hash}")
                    self.log(f"   🔗 {self.chain['explorer']}{tx_hash}")

                    receipt = self.wait_for_receipt(tx_hash)

                    if receipt and receipt.get("status") == 1:
                        self.log(f"✅ MINT SUCCESS!")
                        self.log(f"   Block : {receipt['blockNumber']}")
                        self.log(f"   Gas   : {receipt['gasUsed']}")
                        self.tx_hash = tx_hash
                        self.minted = True
                        break
                    elif receipt:
                        self.log(f"❌ TX reverted")
                        if attempt < self.max_retries:
                            time.sleep(self.retry_delay)
                    else:
                        self.log(f"⚠️  Pending...")
                        self.tx_hash = tx_hash

                except Exception as e:
                    self.log(f"❌ Error: {str(e)[:200]}")
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay)
                    else:
                        break

            except Exception as e:
                self.log(f"❌ Loop error: {str(e)[:200]}")
                time.sleep(self.retry_delay)

        if not self.minted:
            self.log(f"\n❌ Failed after {attempt} attempts")


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="EVM Auto-Mint Bot v3 — Snipe Edition")
    parser.add_argument("-l", "--link", help="Mint page URL")
    parser.add_argument("-c", "--contract", help="Direct contract address")
    parser.add_argument("--chain", default="eth", choices=list(CHAINS.keys()))
    parser.add_argument("-q", "--qty", type=int, default=1, help="Quantity")
    parser.add_argument("-v", "--value", type=float, default=None, help="Value per mint (ETH)")
    parser.add_argument("--mint-fn", default=None, help="Force mint function name")
    parser.add_argument("--gas-limit", type=int, default=None, help="Override gas limit")
    parser.add_argument("--max-gas", type=float, default=100, help="Max gas price (gwei)")
    parser.add_argument("-k", "--private-key", default=None, help="Private key (or use wallets.json)")
    parser.add_argument("-n", "--dry-run", action="store_true", help="Simulate only")
    parser.add_argument("--live", action="store_true", help="Send real TX (standard mode)")
    parser.add_argument("--snipe", action="store_true", help="Snipe mode: pre-sign → fire instantly")
    parser.add_argument("--poll", type=float, default=0.3, help="Poll interval (seconds)")
    parser.add_argument("--retries", type=int, default=10, help="Max retries")
    parser.add_argument("--retry-delay", type=float, default=0.5, help="Retry delay (seconds)")
    parser.add_argument("--proof", nargs="*", help="Merkle proof (hex)")

    args = parser.parse_args()

    config = {
        "link": args.link,
        "contract": args.contract,
        "chain": args.chain,
        "qty": args.qty,
        "value": args.value,
        "mint_fn": args.mint_fn,
        "gas_limit": args.gas_limit,
        "max_gas": args.max_gas,
        "private_key": args.private_key,
        "poll": args.poll,
        "retries": args.retries,
        "retry_delay": args.retry_delay,
        "snipe": args.snipe,
        "proof": args.proof,
    }

    dry_run = not args.live and not args.snipe

    bot = MintBot(config, dry_run=dry_run)
    bot.mint()


if __name__ == "__main__":
    main()
