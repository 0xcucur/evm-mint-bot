# EVM Auto-Mint Bot

Paste a mint link → bot resolves contract, ABI, mint function, and sends TX.

## Features

- 🔗 **Link auto-resolve** — OpenSea, mint.fun, zora, sound.xyz, raw addresses
- ⚡ **10 chains** — Ethereum, Base, MegaETH, Tempo, Sepolia, Arbitrum, Optimism, Polygon, Blast, Avalanche
- 🔍 **Auto-detect** — mint function, value, gas, chain from OpenSea API
- 🧪 **Dry-run by default** — `--live` flag required for real TX
- 🛡️ **EIP-1559 gas** — priority fee + maxFee auto-estimate
- 📊 **Wallet limit check** — auto-adjust qty if near max per wallet
- 🎯 **7 mint patterns** — mint, publicMint, claim, freeMint, safeMint, presaleMint, whitelistMint

## Quick Start

```bash
# Install deps
pip install -r requirements.txt

# Setup env
cp .env.example .env
# Edit .env with your API keys

# Dry-run (safe, no TX sent)
python3 mint_bot.py -l "https://opensea.io/collection/riot-rabbitz-69978810/overview"

# Live mint
python3 mint_bot.py -l "https://opensea.io/collection/xxx" --live
```

## Usage

```bash
# Paste link, auto-resolve everything
python3 mint_bot.py -l "https://opensea.io/collection/xxx/overview"

# With custom private key (for WL mint)
python3 mint_bot.py -l "https://opensea.io/collection/xxx" -k <YOUR_PRIVATE_KEY> --live

# Mint 3 at once
python3 mint_bot.py -l "https://opensea.io/collection/xxx" -q 3 --live

# Specific chain
python3 mint_bot.py -l "https://opensea.io/collection/xxx" --chain base --live

# Direct contract address
python3 mint_bot.py -c 0x7a3aB6DF11b9556043963195e8c08080Ce3eEB52 --live

# Custom gas
python3 mint_bot.py -l "https://opensea.io/collection/xxx" --max-gas 50 --live

# Custom mint function
python3 mint_bot.py -c 0x... --mint-fn publicMint --live
```

## Supported Chains

| Chain | Key | Chain ID |
|-------|-----|----------|
| Ethereum | `eth` | 1 |
| Base | `base` | 8453 |
| MegaETH | `mega` | 6342 |
| Tempo | `tempo` | 9837 |
| Sepolia | `sepolia` | 11155111 |
| Arbitrum | `arbitrum` | 42161 |
| Optimism | `optimism` | 10 |
| Polygon | `matic` | 137 |
| Blast | `blast` | 81457 |
| Avalanche | `avalanche` | 43114 |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENSEA_API_KEY` | Yes (for OpenSea links) | Get from [OpenSea](https://docs.opensea.io/reference/api-keys) |
| `ETHERSCAN_KEY` | No | For ABI fetch (fallback works without) |
| `BASESCAN_KEY` | No | For Base ABI fetch |
| `ETH_RPC` | No | Custom Ethereum RPC |
| `BASE_RPC` | No | Custom Base RPC |

## How It Works

```
OpenSea Link → OpenSea API → contract address + chain
                          ↓
                    Block Explorer API → contract ABI
                          ↓
                    Web3 probe → detect mint function, price, supply
                          ↓
                    Build TX → estimate gas → sign → send
                          ↓
                    Wait receipt → success/fail
```

## Flags

| Flag | Short | Description | Default |
|------|-------|-------------|---------|
| `--link` | `-l` | Mint page URL | — |
| `--contract` | `-c` | Direct contract address | — |
| `--chain` | | Target chain | `eth` |
| `--qty` | `-q` | Quantity | 1 |
| `--value` | `-v` | Value in ETH | auto-detect |
| `--mint-fn` | | Force mint function name | auto-detect |
| `--gas-limit` | | Override gas limit | auto-estimate |
| `--max-gas` | | Max gas price (gwei) | 100 |
| `--private-key` | `-k` | Private key (or wallets.json) | — |
| `--dry-run` | `-n` | Simulate only (same as default) | true |
| `--live` | | Send real TX | false |
| `--poll` | | Poll interval (seconds) | 0.5 |
| `--retries` | | Max mint attempts | 10 |

## Security

- **No secrets in code** — all API keys via environment variables
- **Dry-run default** — `--live` required for real transactions
- **PK never saved** — private key stays in memory only
- `.gitignore` blocks `wallets.json`, `*.key`, `*.pem`, `.env`
- Copy `.env.example` → `.env` for local config

## License

MIT
