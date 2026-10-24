# What CarbonGuard costs to run

Gas is **measured** by `scripts/gas_report.js` against the real contract. Dollar figures are **estimates** that
assume ETH = $3000 and 2 gwei on Ethereum mainnet (assumed typical base + priority fee); 0.01 gwei on Base (L2) (L2 execution only; excludes the L1 data fee).
Rerun with current prices before quoting them.

| Action | Gas | Ethereum mainnet | Base (L2) |
|---|---:|---:|---:|
| Deploy contract (one-off) | 2,854,970 | $17.13 | $0.09 |
| Bridge a registry batch (registerBatch) | 395,784 | $2.37 | $0.01 |
| Write AI score + reasons + hashes (longest real explanation) | 240,334 | $1.44 | $0.0072 |
| Transfer credits to a buyer | 60,028 | $0.36 | $0.0018 |
| Retire credits (voluntary claim, with certificate) | 289,168 | $1.74 | $0.0087 |
| Retire credits (Article 6 compliance claim) | 233,122 | $1.40 | $0.0070 |
| Verifier vote (1 of 2) | 79,495 | $0.48 | $0.0024 |
| Verifier vote that unfreezes (2 of 2) | 68,569 | $0.41 | $0.0021 |
| Marketplace: list credits for sale | 172,168 | $1.03 | $0.0052 |
| Marketplace: buy credits | 108,599 | $0.65 | $0.0033 |

A retirement costs the same whether it covers 1 tonne or 1 million tonnes.
