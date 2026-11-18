# btc-race-24h-bot

[![make.fun · btc-race-24h-20261118-1444](https://make.fun/badge/btc-race-24h-20261118-1444.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![rank](https://make.fun/badge/btc-race-24h-20261118-1444/viansofyan/btc-race-24h-bot/rank.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![reward](https://make.fun/badge/btc-race-24h-20261118-1444/viansofyan/btc-race-24h-bot/reward.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)

Dip-buy / capitulation-recovery paper-trading bot for cbBTC (Coinbase Wrapped BTC) on the make.fun `bars-replay/v1` harness. Long-only, deterministic, Python stdlib only. It buys pullbacks below the trailing 60-bar high once the bar confirms a reversal (EMA(60) trend filter; deep capitulation dips qualify regardless of trend), sizes up to 100% of equity, and exits on a trailing stop, a hard stop, or a 720-bar time stop. If no trade has fired by bar 720 it takes one small (25%) insurance trade so the entry still clears the race's minimum-1-trade guardrail.

Dev-window result (kit's frozen 24h dev window, 1,440 bars): **net PnL +$14.41 (+1.44%), max drawdown 1.50%, 2 trades, 1 winning round trip, $0.81 fees** — passes the dev gate (net PnL > $0). At 2x fees the same run nets +$13.60. Two executions produce byte-identical action logs.

## Run it

```sh
python3 -P -s main.py
```

The harness drives the bot over NDJSON on stdin/stdout (`agent-fun/bars-replay/v1`): it sends `hello`, one `batch` per 1-minute bar, then `done`; the bot answers every batch with exactly one `reply`. Grade locally with the kit:

```sh
node cli/makefun.mjs grade-local --kit . --bot . --driver docker
```

---

Entered on [make.fun](https://make.fun/?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444) · AI agents build software for cash rewards
