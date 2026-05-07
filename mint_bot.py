#!/usr/bin/env python3
"""
EVM Auto-Mint Bot v2
Paste a mint link → bot resolves contract, ABI, mint function, value → mints.

Supported link formats:
  - https://opensea.io/collection/xxx  (auto-resolves via OpenSea API)
  - https://mint.fun/0x...             (direct contract)
  - https://zora.co/collections/0x...  (direct contract)
  - https://0x...                      (raw contract address)
  - Any EVM contract address

Usage:
  python3 mint_bot.py --link "https://opensea.io/collection/stupidfacesnft/overview"
  python3 mint_bot.py --link "https://mint.fun/0x1234..." --chain base
  python3 mint_bot.py --chain base --contract 0x... --dry-run
  python3 mint_bot.py --link "https://opensea.io/collection/xxx" --qty 3 --live
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
        "priority_fee_gwei": 3,
        "max_fee_multiplier": 1.5,
    },
    "base": {
        "name": "Base",
        "rpc": os.environ.get("BASE_RPC", "https://base-rpc.publicnode.com"),
        "chain_id": 8453,
        "explorer": "https://basescan.org/tx/",
        "abi_url": "https://api.basescan.org/api",
        "api_key": os.environ.get("BASESCAN_KEY", ""),
        "priority_fee_gwei": 1,
        "max_fee_multiplier": 1.3,
    },
    "mega": {
        "name": "MegaETH",
        "rpc": os.environ.get("MEGA_RPC", "https://rpc.megaeth.com"),
        "chain_id": 6342,
        "explorer": "https://megaeth.com/tx/",
        "abi_url": None,
        "api_key": "",
        "priority_fee_gwei": 1,
        "max_fee_multiplier": 1.5,
    },
    "tempo": {
        "name": "Tempo",
        "rpc": os.environ.get("TEMPO_RPC", "https://rpc.tempo.build"),
        "chain_id": 9837,
        "explorer": "https://tempo.exchange/tx/",
        "abi_url": None,
        "api_key": "",
        "priority_fee_gwei": 1,
        "max_fee_multiplier": 1.5,
    },
    "sepolia": {
        "name": "Sepolia Testnet",
        "rpc": "https://ethereum-sepolia-rpc.publicnode.com",
        "chain_id": 11155111,
        "explorer": "https://sepolia.etherscan.io/tx/",
        "abi_url": "https://api-sepolia.etherscan.io/api",
        "api_key": os.environ.get("ETHERSCAN_KEY", ""),
        "priority_fee_gwei": 1,
        "max_fee_multiplier": 1.2,
    },
    "arbitrum": {
        "name": "Arbitrum",
        "rpc": os.environ.get("ARB_RPC", "https://arb1.arbitrum.io/rpc"),
        "chain_id": 42161,
        "explorer": "https://arbiscan.io/tx/",
        "abi_url": "https://api.arbiscan.io/api",
        "api_key": os.environ.get("ARBISCAN_KEY", ""),
        "priority_fee_gwei": 1,
        "max_fee_multiplier": 1.3,
    },
    "optimism": {
        "name": "Optimism",
        "rpc": os.environ.get("OP_RPC", "https://mainnet.optimism.io"),
        "chain_id": 10,
        "explorer": "https://optimistic.etherscan.io/tx/",
        "abi_url": "https://api-optimistic.etherscan.io/api",
        "api_key": os.environ.get("ETHERSCAN_KEY", ""),
        "priority_fee_gwei": 1,
        "max_fee_multiplier": 1.3,
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
        "abi_url": None,
        "api_key": "",
        "priority_fee_gwei": 1,
        "max_fee_multiplier": 1.5,
    },
    "avalanche": {
        "name": "Avalanche",
        "rpc": "https://api.avax.network/ext/bc/C/rpc",
        "chain_id": 43114,
        "explorer": "https://snowtrace.io/tx/",
        "abi_url": "https://api.snowtrace.io/api",
        "api_key": "",
        "priority_fee_gwei": 25,
        "max_fee_multiplier": 1.5,
    },
}

# Chain name mapping from OpenSea → CHAINS keys
OPENSEA_CHAIN_MAP = {
    "ethereum": "eth", "base": "base",
    "matic": "matic", "arbitrum": "arbitrum",
    "optimism": "optimism", "avalanche": "avalanche",
    "blast": "blast", "zora": "base",  # Zora is on Base
    "klaytn": "eth",  # fallback
}

# ═══════════════════════════════════════════════════════════════
# FALLBACK ABI
# ═══════════════════════════════════════════════════════════════
FALLBACK_ABI = [
    {
        "inputs": [{"name": "quantity", "type": "uint256"}],
        "name": "mint",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [{"name": "quantity", "type": "uint256"}],
        "name": "publicMint",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [{"name": "quantity", "type": "uint256"}],
        "name": "mintPublic",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "quantity", "type": "uint256"},
            {"name": "maxQuantity", "type": "uint256"},
            {"name": "proof", "type": "bytes32[]"}
        ],
        "name": "claim",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [{"name": "quantity", "type": "uint256"}],
        "name": "claim",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [{"name": "quantity", "type": "uint256"}],
        "name": "freeMint",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "name": "safeMint",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    # View functions
    {"inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "maxSupply", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "paused", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "price", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "mintPrice", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "isActive", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "saleActive", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "publicSaleActive", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "maxPerWallet", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "mintedCount", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "maxMintPerWallet", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "maxPerAddress", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "numberMinted", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]


class MintBot:
    def __init__(self, config: dict, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.chain = CHAINS[config["chain"]]
        self.w3 = Web3(Web3.HTTPProvider(
            self.chain["rpc"],
            request_kwargs={"timeout": 15}
        ))

        if not self.w3.is_connected():
            print(f"[FATAL] Cannot connect to {self.chain['name']} RPC: {self.chain['rpc']}")
            sys.exit(1)

        # Load wallet
        self.account = Account.from_key(config["private_key"])
        self.address = self.account.address

        # Contract (resolved later)
        self.contract_addr = None
        self.contract = None
        self.abi = None

        # Mint config
        self.quantity = config.get("quantity", 1)
        self.value_eth = config.get("value", None)
        self.max_gas_price = Web3.to_wei(config.get("max_gas_price_gwei", 100), "gwei")
        self.gas_limit_override = config.get("gas_limit", None)

        # Timing
        self.poll_interval = config.get("poll_interval_sec", 0.5)
        self.max_retries = config.get("max_retries", 10)
        self.retry_delay = config.get("retry_delay_sec", 0.3)
        self.mint_fn_override = config.get("mint_fn", None)

        # OpenSea
        self.opensea_key = os.environ.get("OPENSEA_API_KEY", "")

        # State
        self.minted = False
        self.tx_hash = None
        self.running = True

        signal.signal(signal.SIGINT, lambda s, f: self.stop())

    def log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{ts}] [{self.chain['name']}] {msg}")

    def stop(self):
        self.log("🛑 Stopping...")
        self.running = False

    # ═══════════════════════════════════════════════════════════
    # LINK PARSING
    # ═══════════════════════════════════════════════════════════

    def resolve_link(self, link: str) -> dict:
        """Parse any link format → {address, chain?}"""
        link = link.strip()

        # Raw address: 0x...
        if re.match(r'^0x[a-fA-F0-9]{40}$', link):
            self.log(f"Raw address: {link}")
            return {"address": link}

        parsed = urlparse(link)
        host = parsed.hostname or ""
        path = parsed.path

        # OpenSea
        if "opensea.io" in host:
            return self._parse_opensea(path)

        # mint.fun
        if "mint.fun" in host:
            return self._parse_mint_fun(path)

        # Zora
        if "zora.co" in host:
            return self._parse_zora(path)

        # Sound.xyz
        if "sound.xyz" in host:
            return self._parse_sound(path)

        # Direct contract in URL (any domain)
        addr_match = re.search(r'0x[a-fA-F0-9]{40}', link)
        if addr_match:
            self.log(f"Found address in URL: {addr_match.group(0)}")
            return {"address": addr_match.group(0)}

        raise ValueError(f"Cannot parse link: {link}")

    def _parse_opensea(self, path: str) -> dict:
        """Parse OpenSea path → use API to resolve"""
        self.log(f"Parsing OpenSea path: {path}")

        # /collection/xxx or /collection/xxx/overview
        if "/collection/" in path:
            slug = path.split("/collection/")[-1].split("/")[0].split("?")[0]
            return self._opensea_api_resolve(slug)

        # /assets/chain/0x.../id
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
        """Resolve OpenSea collection slug via API"""
        if not self.opensea_key:
            raise ValueError("OPENSEA_API_KEY required for OpenSea links. Get one at https://docs.opensea.io/reference/api-keys")

        url = f"https://api.opensea.io/api/v2/collections/{slug}"
        headers = {
            "x-api-key": self.opensea_key,
            "Accept": "application/json",
            "User-Agent": "mint-bot/2.0"
        }

        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 429:
            self.log("OpenSea rate limited, retrying in 2s...")
            time.sleep(2)
            resp = requests.get(url, headers=headers, timeout=15)

        if resp.status_code != 200:
            raise ValueError(f"OpenSea API error {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        contracts = data.get("contracts", [])
        if not contracts:
            raise ValueError(f"No contracts found for collection: {slug}")

        contract = contracts[0]
        addr = contract.get("address")
        os_chain = contract.get("chain", "ethereum")
        chain = OPENSEA_CHAIN_MAP.get(os_chain, os_chain)

        name = data.get("name", slug)
        total = data.get("total_supply", "?")
        desc = data.get("description", "")[:80]

        self.log(f"OpenSea resolved: {name} ({total} supply) → {addr} on {os_chain}")
        self.log(f"  Desc: {desc}")

        return {"address": addr, "chain": chain}

    def _parse_mint_fun(self, path: str) -> dict:
        addr_match = re.search(r'0x[a-fA-F0-9]{40}', path)
        if addr_match:
            self.log(f"mint.fun → {addr_match.group(0)}")
            return {"address": addr_match.group(0)}
        raise ValueError(f"Cannot parse mint.fun: {path}")

    def _parse_zora(self, path: str) -> dict:
        addr_match = re.search(r'0x[a-fA-F0-9]{40}', path)
        if addr_match:
            self.log(f"Zora → {addr_match.group(0)}")
            return {"address": addr_match.group(0), "chain": "base"}
        raise ValueError(f"Cannot parse Zora: {path}")

    def _parse_sound(self, path: str) -> dict:
        addr_match = re.search(r'0x[a-fA-F0-9]{40}', path)
        if addr_match:
            self.log(f"Sound.xyz → {addr_match.group(0)}")
            return {"address": addr_match.group(0)}
        raise ValueError(f"Cannot parse Sound.xyz: {path}")

    def _auto_set_chain(self, chain_key: str):
        """Switch to a different chain if detected"""
        if chain_key in CHAINS and chain_key != self.config["chain"]:
            self.log(f"Switching chain: {self.config['chain']} → {chain_key}")
            self.chain = CHAINS[chain_key]
            self.w3 = Web3(Web3.HTTPProvider(
                self.chain["rpc"],
                request_kwargs={"timeout": 15}
            ))
            self.config["chain"] = chain_key

    # ═══════════════════════════════════════════════════════════
    # ABI RESOLUTION
    # ═══════════════════════════════════════════════════════════

    def fetch_abi(self, contract_addr: str) -> list:
        """Fetch ABI from block explorer or use fallback"""
        abi_url = self.chain.get("abi_url")
        api_key = self.chain.get("api_key", "")

        if abi_url:
            try:
                params = {
                    "module": "contract",
                    "action": "getabi",
                    "address": contract_addr,
                }
                if api_key:
                    params["apikey"] = api_key

                resp = requests.get(abi_url, params=params, timeout=10)
                data = resp.json()

                if data.get("status") == "1" and data.get("result"):
                    abi = json.loads(data["result"])
                    self.log(f"✓ ABI from explorer ({len(abi)} entries)")
                    return abi
                else:
                    msg = data.get("message", "unknown")
                    self.log(f"Explorer ABI: {msg}")
            except Exception as e:
                self.log(f"Explorer ABI failed: {e}")

        self.log("Using fallback ABI")
        return FALLBACK_ABI

    # ═══════════════════════════════════════════════════════════
    # CONTRACT PROBING
    # ═══════════════════════════════════════════════════════════

    def setup_contract(self, contract_addr: str):
        self.contract_addr = Web3.to_checksum_address(contract_addr)
        self.abi = self.fetch_abi(self.contract_addr)
        self.contract = self.w3.eth.contract(
            address=self.contract_addr,
            abi=self.abi
        )

    def probe_contract(self):
        self.log(f"📋 Contract: {self.contract_addr}")

        try:
            code = self.w3.eth.get_code(self.contract_addr)
            if len(code) == 0:
                self.log(f"  ⚠️  No contract deployed!")
                return False
            self.log(f"  ✓ Deployed ({len(code)} bytes)")
        except Exception:
            self.log(f"  ⚠️  Cannot verify code")

        state_fns = [
            "totalSupply", "maxSupply", "price", "mintPrice",
            "paused", "isActive", "saleActive", "publicSaleActive",
            "maxPerWallet", "maxMintPerWallet", "maxPerAddress",
            "balanceOf", "mintedCount", "numberMinted"
        ]
        for fn_name in state_fns:
            try:
                fn = getattr(self.contract.functions, fn_name, None)
                if fn is None:
                    continue
                if fn_name in ("balanceOf", "mintedCount", "numberMinted"):
                    result = fn(self.address).call()
                else:
                    result = fn().call()

                if fn_name in ("price", "mintPrice"):
                    eth_val = Web3.from_wei(result, "ether")
                    self.log(f"  {fn_name}() = {eth_val} ETH")
                    if self.value_eth is None and result > 0:
                        self.value_eth = float(eth_val) * self.quantity
                        self.log(f"  → Auto value: {self.value_eth} ETH")
                elif fn_name in ("balanceOf", "mintedCount", "numberMinted"):
                    self.log(f"  {fn_name}({self.address[:8]}...) = {result}")
                else:
                    self.log(f"  {fn_name}() = {result}")
            except (ContractLogicError, Exception):
                pass

        mint_fns = self._find_mint_functions()
        if mint_fns:
            self.log(f"  🎯 Mint functions: {', '.join(mint_fns)}")
        else:
            self.log(f"  ⚠️  No mint functions in ABI")

        return True

    def _find_mint_functions(self) -> list:
        mint_keywords = ["mint", "claim", "publicMint", "mintPublic", "freeMint",
                         "safeMint", "presaleMint", "whitelistMint", "presale",
                         "publicSale", "mintTo"]
        found = []
        for item in self.abi:
            if item.get("type") == "function":
                name = item.get("name", "")
                if any(kw.lower() in name.lower() for kw in mint_keywords):
                    state = item.get("stateMutability", "")
                    if state in ("payable", "nonpayable"):
                        found.append(name)
        return found

    def detect_mint_function(self):
        if self.mint_fn_override:
            self.log(f"Using: {self.mint_fn_override}")
            return self.mint_fn_override

        mint_fns = self._find_mint_functions()
        if not mint_fns:
            raise ValueError("No mint function found")

        priority = ["mint", "publicMint", "mintPublic", "claim", "publicSale",
                     "presaleMint", "freeMint", "safeMint", "mintTo"]
        for preferred in priority:
            if preferred in mint_fns:
                self.log(f"Selected: {preferred}")
                return preferred

        self.log(f"Using: {mint_fns[0]}")
        return mint_fns[0]

    # ═══════════════════════════════════════════════════════════
    # TX BUILDING
    # ═══════════════════════════════════════════════════════════

    def build_mint_tx(self, mint_fn: str) -> dict:
        nonce = self.w3.eth.get_transaction_count(self.address, 'pending')

        try:
            latest_block = self.w3.eth.get_block('latest')
            base_fee = latest_block.get('baseFeePerGas', self.w3.eth.gas_price)
        except Exception:
            base_fee = self.w3.eth.gas_price

        priority_fee = Web3.to_wei(self.chain["priority_fee_gwei"], "gwei")
        max_fee = int(base_fee * self.chain["max_fee_multiplier"]) + priority_fee
        max_fee = min(max_fee, self.max_gas_price)

        tx = {
            "from": self.address,
            "chainId": self.chain["chain_id"],
            "nonce": nonce,
            "maxPriorityFeePerGas": priority_fee,
            "maxFeePerGas": max_fee,
            "type": 2,
        }

        fn_obj = getattr(self.contract.functions, mint_fn)

        fn_abi = None
        for item in self.abi:
            if item.get("type") == "function" and item.get("name") == mint_fn:
                fn_abi = item
                break

        if fn_abi:
            input_count = len(fn_abi.get("inputs", []))
            self.log(f"  {mint_fn}() inputs: {input_count}")

            if input_count == 0:
                fn_call = fn_obj()
            elif input_count == 1:
                fn_call = fn_obj(self.quantity)
            elif mint_fn == "claim" and input_count >= 3:
                fn_call = fn_obj(self.address, self.quantity, self.quantity, [])
            elif input_count == 2:
                fn_call = fn_obj(self.address, self.quantity)
            else:
                fn_call = fn_obj(self.quantity)
        else:
            fn_call = fn_obj(self.quantity)

        tx_data = fn_call.build_transaction(tx)
        tx.update(tx_data)

        if self.value_eth and self.value_eth > 0:
            tx["value"] = Web3.to_wei(self.value_eth, "ether")

        if self.gas_limit_override:
            tx["gas"] = self.gas_limit_override
        else:
            try:
                gas_estimate = self.w3.eth.estimate_gas(tx)
                tx["gas"] = int(gas_estimate * 1.3)
                self.log(f"Gas: {gas_estimate} → {tx['gas']}")
            except Exception as e:
                tx["gas"] = 300000
                self.log(f"Gas estimate failed ({e}), using 300000")

        return tx

    def send_mint(self, mint_fn: str) -> str:
        tx = self.build_mint_tx(mint_fn)
        signed = self.w3.eth.account.sign_transaction(tx, self.config["private_key"])
        self.log(f"📤 Sending (nonce={tx['nonce']}, gas={tx['gas']}, "
                 f"value={Web3.from_wei(tx.get('value', 0), 'ether')} ETH)...")
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
    # STATUS CHECKS
    # ═══════════════════════════════════════════════════════════

    def check_mint_status(self) -> bool:
        try:
            code = self.w3.eth.get_code(self.contract_addr)
            if len(code) == 0:
                return False
        except Exception:
            return False

        for fn_name in ["paused"]:
            try:
                if getattr(self.contract.functions, fn_name)().call():
                    self.log(f"⏸️  PAUSED")
                    return False
            except Exception:
                pass

        # Try sale-active checks first
        for fn_name in ["isActive", "saleActive", "publicSaleActive"]:
            try:
                if getattr(self.contract.functions, fn_name)().call():
                    return True
            except Exception:
                pass

        # If none of the active functions exist, assume mint is open
        # (contract exists and not paused = try it)
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
    # MAIN
    # ═══════════════════════════════════════════════════════════

    def mint(self):
        contract_addr = self.config.get("contract")
        link = self.config.get("link")

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
        self.log(f"🚀 EVM AUTO-MINT BOT v2")
        self.log(f"   Chain    : {self.chain['name']} (chain_id={self.chain['chain_id']})")
        self.log(f"   Contract : {self.contract_addr}")
        self.log(f"   Quantity : {self.quantity}")
        self.log(f"   Wallet   : {self.address}")
        self.log(f"   Mode     : {'🧪 DRY-RUN' if self.dry_run else '⚡ LIVE'}")
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
                self.log(f"   Data     : {tx.get('data', b'').hex()[:66]}...")
                self.log(f"\n✅ Dry-run OK! Add --live to mint.")
            except Exception as e:
                self.log(f"❌ Dry-run failed: {e}")
            return

        # LIVE
        self.log(f"\n⚡ LIVE MINT (poll {self.poll_interval}s)...")
        attempt = 0

        while self.running and not self.minted:
            try:
                if not self.check_mint_status():
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
                self.log(f"⚠️  Monitor: {e}")
                time.sleep(self.poll_interval)

        if self.minted:
            self.log(f"\n{'='*55}")
            self.log(f"🎉 DONE!")
            self.log(f"   TX   : {self.tx_hash}")
            if self.tx_hash:
                self.log(f"   🔗 {self.chain['explorer']}{self.tx_hash}")
            self.log(f"{'='*55}")
        else:
            self.log(f"\n❌ Failed after {attempt} attempts")


def load_wallet(chain: str) -> str:
    wallet_path = Path.home() / ".hermes" / "wallets" / "wallets.json"
    if wallet_path.exists():
        with open(wallet_path) as f:
            wallets = json.load(f)
        return wallets.get("evm", {}).get("private_key")
    return None


def main():
    parser = argparse.ArgumentParser(description="EVM Auto-Mint Bot v2")
    parser.add_argument("--link", "-l", help="Mint page URL (OpenSea, mint.fun, zora, etc)")
    parser.add_argument("--contract", "-c", help="Direct contract address")
    parser.add_argument("--chain", default="eth", choices=list(CHAINS.keys()),
                        help="Blockchain (default: eth)")
    parser.add_argument("--qty", "-q", type=int, default=1, help="Quantity")
    parser.add_argument("--value", "-v", type=float, default=None,
                        help="Value in ETH (auto-detect if omitted)")
    parser.add_argument("--mint-fn", help="Force mint function name")
    parser.add_argument("--gas-limit", type=int, help="Override gas limit")
    parser.add_argument("--max-gas", type=float, default=100, help="Max gas gwei")
    parser.add_argument("--private-key", "-k", help="Private key")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Simulate only")
    parser.add_argument("--live", action="store_true", help="Send live TX (default is dry-run)")
    parser.add_argument("--poll", type=float, default=0.5, help="Poll interval")
    parser.add_argument("--retries", type=int, default=10, help="Max retries")

    args = parser.parse_args()

    if not args.link and not args.contract:
        parser.error("Provide --link or --contract")

    private_key = args.private_key or load_wallet(args.chain)
    if not private_key:
        print("[FATAL] No private key. Set --private-key or add to wallets.json")
        sys.exit(1)

    config = {
        "chain": args.chain,
        "contract": args.contract,
        "link": args.link,
        "private_key": private_key,
        "quantity": args.qty,
        "value": args.value,
        "mint_fn": args.mint_fn,
        "gas_limit": args.gas_limit,
        "max_gas_price_gwei": args.max_gas,
        "poll_interval_sec": args.poll,
        "max_retries": args.retries,
        "retry_delay_sec": 0.3,
    }

    # Default: dry-run unless --live specified
    dry_run = not args.live

    bot = MintBot(config, dry_run=dry_run)
    bot.mint()


if __name__ == "__main__":
    main()
