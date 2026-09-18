"""PSIG Extreme Radar core."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import requests

SYMBOL = "PSIG"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
STATE_PATH = Path("state/psig_alert_state.json")

@dataclass
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

def fetch_yahoo(symbol: str = SYMBOL, interval: str = "1d", period_days: int = 400) -> list[Bar]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=period_days)
    params = {"period1": int(start.timestamp()), "period2": int(end.timestamp()), "interval": interval, "events": "div,splits"}
    r = requests.get(YAHOO_CHART.format(symbol=symbol), params=params, headers={"User-Agent": "Mozilla/5.0 PSIG-Radar/1.0"}, timeout=20)
    r.raise_for_status()
    payload = r.json()
    result = ((payload.get("chart") or {}).get("result") or [])
    if not result:
        raise RuntimeError("Yahoo chart returned no data")
    item = result[0]
    timestamps = item.get("timestamp") or []
    quote = (item.get("indicators") or {}).get("quote", [{}])[0]
    bars = []
    for i, ts in enumerate(timestamps):
        try:
            vals = (quote["open"][i], quote["high"][i], quote["low"][i], quote["close"][i], quote["volume"][i])
            if any(v is None for v in vals):
                continue
            bars.append(Bar(datetime.fromtimestamp(ts, timezone.utc), *(float(v) for v in vals)))
        except (IndexError, TypeError, ValueError):
            continue
    return bars

def _mean(values):
    return sum(values) / len(values) if values else 0.0

def _rvol(bars, lookback=20):
    if len(bars) <= lookback:
        return 0.0
    baseline = _mean([b.volume for b in bars[-lookback-1:-1]])
    return bars[-1].volume / baseline if baseline else 0.0

def _intraday_rvol(bars, sessions=20):
    """Compare latest bar with the same UTC time slot on prior sessions.

    This is a deliberately simple baseline. Phase 1C will replace it with a
    market-session slot calculation once robust intraday history is available.
    """
    if not bars:
        return 0.0
    latest = bars[-1]
    slot = (latest.ts.hour, latest.ts.minute)
    prior = [b.volume for b in bars[:-1] if (b.ts.hour, b.ts.minute) == slot]
    prior = prior[-sessions:]
    return latest.volume / _mean(prior) if prior and _mean(prior) > 0 else 0.0

def classify_episode(criteria):
    s = set(criteria)
    if "EXTREME_INTRADAY_50" in s and "FAILED_SPIKE" in s:
        return "EXTREME_REVERSAL"
    if "FAILED_SPIKE" in s:
        return "FAILED_SPIKE"
    if "VOLUME_5X" in s and ("DAILY_UP_20" in s or "INTRADAY_RANGE_30" in s):
        return "VOLUME_MOMENTUM_SPIKE"
    if "DAILY_DOWN_20" in s:
        return "MAJOR_DOWNSIDE"
    if "DAILY_UP_20" in s:
        return "MAJOR_UPSIDE"
    return "EXTREME_INTRADAY"

def detect_daily_episodes(bars):
    episodes = []
    for i, b in enumerate(bars):
        if i == 0:
            continue
        prev = bars[i - 1]
        close_change = (b.close / prev.close - 1) * 100 if prev.close else 0
        intraday = (b.high / b.low - 1) * 100 if b.low else 0
        rvol = _rvol(bars[:i+1], 20)
        criteria = []
        if close_change >= 20: criteria.append("DAILY_UP_20")
        if close_change <= -20: criteria.append("DAILY_DOWN_20")
        if intraday >= 30: criteria.append("INTRADAY_RANGE_30")
        if intraday >= 50: criteria.append("EXTREME_INTRADAY_50")
        if rvol >= 5: criteria.append("VOLUME_5X")
        high_from_open = (b.high / b.open - 1) * 100 if b.open else 0
        close_from_high = (b.close / b.high - 1) * 100 if b.high else 0
        if high_from_open >= 20 and close_from_high <= -15: criteria.append("FAILED_SPIKE")
        if criteria:
            episodes.append({
                "date": b.ts.date().isoformat(), "open": b.open, "high": b.high, "low": b.low,
                "close": b.close, "previous_close": prev.close,
                "close_change_pct": round(close_change, 4), "intraday_range_pct": round(intraday, 4),
                "volume": int(b.volume), "rvol_20d": round(rvol, 4), "criteria": criteria,
                "classification": classify_episode(criteria),
            })
    return episodes

def compute_live_signal(bars, catalyst=False, catalyst_type=None):
    if len(bars) < 21:
        raise ValueError("At least 21 bars are required")
    b, prev = bars[-1], bars[-2]
    rvol = _intraday_rvol(bars, 20)
    move = (b.close / prev.close - 1) * 100 if prev.close else 0
    intraday = (b.high / b.low - 1) * 100 if b.low else 0
    momentum = min(20, max(0, move) * 0.8)
    volume_score = min(25, max(0, (rvol - 1) * 4))
    range_score = min(10, max(0, (intraday - 10) * 0.25))
    breakout = 10 if b.close >= max(x.high for x in bars[-21:-1]) else 0
    catalyst_score = 15 if catalyst else 0
    accel = 10 if b.close > prev.close and b.volume > _mean([x.volume for x in bars[-6:-1]]) * 2 else 0
    score = round(min(100, momentum + volume_score + range_score + breakout + catalyst_score + accel), 1)
    status = "EXTREME" if score >= 80 else "SETUP" if score >= 60 else "WATCH"
    return {"ticker": SYMBOL, "timestamp": b.ts.isoformat(), "price": b.close, "move_pct": round(move, 2), "intraday_range_pct": round(intraday, 2), "rvol_20": round(rvol, 2), "breakout": bool(breakout), "catalyst": catalyst, "catalyst_type": catalyst_type, "score": score, "status": status, "informational_only": True}

def format_telegram_signal(s):
    icon = {"WATCH": "🟢", "SETUP": "🟠", "EXTREME": "🚨"}[s["status"]]
    catalyst = s.get("catalyst_type") if s.get("catalyst") else "none identified"
    price = "$" + format(s["price"], ".2f")
    return "\n".join([
        f"{icon} PSIG RADAR — {s['status']}", "━━━━━━━━━━━━━━━━━━",
        f"💰 Price: {price}", f"📈 Move: {s['move_pct']:+.2f}%",
        f"📊 RVOL 20D: {s['rvol_20']:.2f}×", f"⚡ Intraday range: {s['intraday_range_pct']:.2f}%",
        f"🚀 Breakout: {'YES' if s['breakout'] else 'NO'}", f"🧨 Catalyst: {catalyst}",
        f"🎯 PSIG Score: {s['score']:.0f}/100", "",
        "⚠️ Informational only — no automatic buy/sell signal.", "━━━━━━━━━━━━━━━━━━"
    ])

def load_state():
    try: return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {}

def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

def should_alert(signal, state):
    """Alert on upward status transitions, not every 5-minute timestamp."""
    status = signal["status"]
    previous = state.get("status")
    state["status"] = status
    state["last_signal"] = {
        "timestamp": signal["timestamp"],
        "score": signal["score"],
        "price": signal["price"],
    }
    if status not in {"SETUP", "EXTREME"}:
        return False
    rank = {"WATCH": 0, "SETUP": 1, "EXTREME": 2}
    return previous is None or rank.get(status, 0) > rank.get(previous, 0)
