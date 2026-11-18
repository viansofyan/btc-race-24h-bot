"""Dip-buy / capitulation-recovery bot for make.fun btc-race-24h-20261118-1444.

Long-only, deterministic, stdlib-only. One asset (CBBTC), one open position.
Entry: price dips below its trailing 60-bar high AND the latest bar closed up
from its open (confirmed reversal). Above the EMA(60) trend a normal pullback
qualifies; below trend only a deep capitulation dip qualifies. Size is 100%
of equity. Exit: trailing stop once armed (+1.5% arm, -1.0% from peak), hard
stop -1.5%, or a 720-bar time stop; forced flat before the window's last bars
so nothing is left to the end-of-window flatten. No take-profit: the move is
ridden. Race insurance: if no trade has fired by bar 720, a shallower dip
qualifies at 25% size so the entry still clears the race's minimum-1-trade
guardrail on a choppy window.

All decisions are integer (bps) math on the closes the harness sent; no
randomness, no wall clock, no network, no files. Parameters are the module
constants below (tuned on the published dev window).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# --- strategy parameters (tunable; tuned on the published dev window) ---
EMA_LEN = 60            # trend filter length (bars)
DIP_BPS = 50            # entry: dip below trailing 60-bar high, in bps (0.50%)
CAP_BPS = 200           # deep capitulation: dip that qualifies regardless of trend
FRACTION_BPS = 10000    # size per entry, bps of equity (100%)
TRANCHE2_DROP_BPS = 0   # 0 = off; else buy a second equal tranche this far below entry
TP_BPS = 0              # take profit above entry, bps; 0 = no TP, ride the move
SL_BPS = 150            # hard stop below entry, bps (1.50%)
EMA_EXIT = 0            # 1 = also exit when the close falls below EMA(60) (trend break)
TRAIL_ARM_BPS = 150     # trailing arms once price is this far above entry
TRAIL_DROP_BPS = 100    # trailing exits this far below the peak since entry
TIME_STOP = 720         # exit after this many bars in a position
NO_ENTRY_AFTER = 1410   # never open after this batch seq
FORCE_EXIT_AT = 1430    # sell everything still held at this batch seq
BUY_MAX_SLIP_BPS = 300  # buy fill must be within 3% above the latest close
SELL_MAX_SLIP_BPS = 1000  # sell fill must be within 10% below the latest close
MIN_NOTIONAL = 1_000_000  # $1 in micro-USDC (harness min_notional_quote_units)
REV_MODE = 1            # reversal filter: 0 close>prev_close, 1 close>=open, 2 none
FALLBACK_AFTER = 720    # if no trade yet by this seq, relax entry (race insurance)
FALLBACK_DIP_BPS = 30   # relaxed dip threshold after FALLBACK_AFTER
FALLBACK_CAP_BPS = 150  # relaxed capitulation threshold after FALLBACK_AFTER
FALLBACK_FRACTION_BPS = 2500  # small size for the insurance trade (25%)

# --- per-run state (rebuilt from the wire every run; nothing persists) ---
closes = []             # closes seen, oldest first (ints, price scale)
last_bar_t = None       # t of the last bar appended
ema = None              # EMA(60) over closes, scaled x1000 for integer precision
entry_price = None      # fill price of the open position (price scale)
entry_seq = None        # batch seq whose fills opened the position
peak = None             # highest close seen since entry
trailing_armed = False
was_above_ema = None    # whether the close was above EMA(60) on the prior bar
tranche2_done = False   # a second (averaging-down) tranche was already bought
tranche2_filled = False  # set when this batch's fills include the 2nd tranche
traded = False          # any buy fill has been observed this run


def _update_history(state, batch):
    """Append the new bar's close (once) and update the EMA."""
    global last_bar_t, ema
    bar = None
    for b in batch.get("bars", []):
        if b["symbol"] == SYMBOL:
            bar = b
            break
    if bar is None or bar["t"] == last_bar_t:
        return
    last_bar_t = bar["t"]
    close = int(bar["c"])
    closes.append(close)
    if ema is None:
        ema = close * 1000
    else:
        # alpha = 2 / (EMA_LEN + 1), kept in thousandths
        ema = ema + (2 * (close * 1000 - ema)) // (EMA_LEN + 1)


def _note_fills(batch, seq):
    """Record entry price/seq from any buy fill delivered in this batch."""
    global entry_price, entry_seq, peak, trailing_armed, was_above_ema
    global tranche2_filled, traded
    for f in batch.get("fills", []):
        if f["symbol"] != SYMBOL or f["status"] != "filled":
            continue
        if f["side"] == "buy":
            traded = True
            if entry_price is None:
                entry_price = int(f["price"])
                entry_seq = seq
                peak = entry_price
                trailing_armed = False
                was_above_ema = None
            else:
                # Second tranche: entry becomes the cost-basis average;
                # on_batch recomputes it from the holding.
                tranche2_filled = True


def _sell_all(state):
    holding = state.positions.get(SYMBOL)
    if holding is None or holding.qty <= 0:
        return []
    return [{"side": "sell", "symbol": SYMBOL, "qty": holding.qty,
             "max_slippage_bps": SELL_MAX_SLIP_BPS}]


def on_batch(state, batch):
    global entry_price, entry_seq, peak, trailing_armed
    global tranche2_done, tranche2_filled
    seq = batch["seq"]
    _update_history(state, batch)
    _note_fills(batch, seq)

    close = state.close(SYMBOL)
    if close is None:
        return []
    holding = state.positions.get(SYMBOL)
    in_position = holding is not None and holding.qty > 0

    if tranche2_filled and in_position:
        # Second tranche landed: entry is now the cost-basis average.
        entry_price = (holding.cost * 10 ** (8 + 5)
                       // (holding.qty * 10 ** 6))
        tranche2_filled = False
        tranche2_done = True

    if in_position:
        # --- second tranche (average down on a deeper dip) ---
        if (TRANCHE2_DROP_BPS > 0 and not tranche2_done
                and entry_price is not None
                and close * 10000 <= entry_price * (10000 - TRANCHE2_DROP_BPS)):
            notional = state.equity * FRACTION_BPS // 10000
            room = state.weight_room(SYMBOL)
            if room < notional:
                notional = room
            if notional > state.cash:
                notional = state.cash
            if notional >= MIN_NOTIONAL:
                tranche2_done = True
                return [{"side": "buy", "symbol": SYMBOL,
                         "notional_quote_units": notional,
                         "max_slippage_bps": BUY_MAX_SLIP_BPS}]
        # --- exits ---
        if entry_price is None:
            # Position seen before any fill was observed (should not happen);
            # derive entry from cost basis.
            entry_price = (holding.cost * 10 ** (8 + 5)
                           // (holding.qty * 10 ** 6))
            entry_seq = seq
            peak = entry_price
        if close > peak:
            peak = close
        if not trailing_armed and close * 10000 >= entry_price * (10000 + TRAIL_ARM_BPS):
            trailing_armed = True
        above_ema = ema is not None and close * 1000 >= ema
        ema_broke = (EMA_EXIT == 1 and was_above_ema is True
                     and not above_ema)
        was_above_ema = above_ema
        exit_now = False
        if seq >= FORCE_EXIT_AT:
            exit_now = True
        elif entry_seq is not None and seq - entry_seq >= TIME_STOP:
            exit_now = True
        elif TP_BPS > 0 and close * 10000 >= entry_price * (10000 + TP_BPS):
            exit_now = True
        elif close * 10000 <= entry_price * (10000 - SL_BPS):
            exit_now = True
        elif ema_broke:
            exit_now = True
        elif trailing_armed and close * 10000 <= peak * (10000 - TRAIL_DROP_BPS):
            exit_now = True
        if exit_now:
            entry_price = None
            entry_seq = None
            peak = None
            trailing_armed = False
            was_above_ema = None
            tranche2_done = False
            return _sell_all(state)
        return []

    # --- entries (flat) ---
    if seq >= NO_ENTRY_AFTER or len(closes) < EMA_LEN + 1:
        return []
    prev_close = closes[-2]
    bar_open = None
    for b in batch.get("bars", []):
        if b["symbol"] == SYMBOL:
            bar_open = int(b["o"])
            break
    if REV_MODE == 0 and close <= prev_close:
        return []  # no confirmed reversal (close above previous close)
    if REV_MODE == 1 and (bar_open is None or close < bar_open):
        return []  # no confirmed reversal (bar closed up from its open)
    high60 = max(closes[-EMA_LEN:])
    dip_bps = (high60 - close) * 10000 // high60 if high60 > 0 else 0
    # Race insurance: if nothing has traded by FALLBACK_AFTER, accept a
    # shallower dip so the entry still clears the race's min-1-trade bar.
    dip_need = DIP_BPS
    cap_need = CAP_BPS
    fraction = FRACTION_BPS
    if not traded and seq >= FALLBACK_AFTER:
        dip_need = FALLBACK_DIP_BPS
        cap_need = FALLBACK_CAP_BPS
        fraction = FALLBACK_FRACTION_BPS
    if dip_bps < dip_need:
        return []
    above_trend = close * 1000 >= ema
    if not above_trend and dip_bps < cap_need:
        return []  # below trend and not a deep capitulation dip
    notional = state.equity * fraction // 10000
    room = state.weight_room(SYMBOL)
    if room < notional:
        notional = room
    if notional > state.cash:
        notional = state.cash
    if notional < MIN_NOTIONAL:
        return []
    return [{"side": "buy", "symbol": SYMBOL,
             "notional_quote_units": notional,
             "max_slippage_bps": BUY_MAX_SLIP_BPS}]


def on_hello(state):
    # The SDK already validated the hello; nothing to keep beyond it.
    hello = state.hello
    sys.stderr.write("hello: capital %s, fees %s, caps %s\n" % (
        hello["capital"], hello["fees"], hello["caps"]))


makefun_bars.run(on_batch, on_hello=on_hello)
