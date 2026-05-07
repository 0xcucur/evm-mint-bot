#!/bin/bash
# EVM Mint Bot launcher — sets env before running
export ETH_RPC="https://eth-mainnet.g.alchemy.com/v2/7buu4S60OTzXYC_kCwRou"
export OPENSEA_API_KEY="2277165990274137af975f8c5936c5a3"

cd "$(dirname "$0")"
python3 mint_bot.py "$@"
