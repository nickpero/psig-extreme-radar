"""PSIG Extreme Radar core: historical episodes, intraday signal engine and alert state."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

SYMBOL = "PSIG"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
ET = ZoneInfo("America/New_York")
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
    params = {"period1": int(start.timestamp()), "period2": int(end.timestamp()),
              "interval": interval, "events": "div,splits"}
    r = requests.get(YAHOO_CHART.format(symbol=symbol), params=params,
                     headers={"User-Agent": "Mozilla/5.0 PSIG-Extreme-Radar/2.0"}, timeout=20)
    r.raise_for_status()
    payload = r.json()
    result = ((payload.get("chart") or {}).get("result") or [])
    if not result:
        raise RuntimeError("Yahoo chart returned no data")
    item = result[0]
    timestamps = item.get("timestamp") or []
    quote = (item.get("indicators") or {}).get("quote", [{}])[0]
    bars: list[Bar] = []
    for i, ts in enumerate(timestamps):
        try:
            vals = (quote["open"][i], quote["high"][i], quote["low"][i],
                    quote["close"][i], quote["volume"][i])
            if any(v is None for v in vals):
                continue
            bars.append(Bar(datetime.fromtimestamp(ts, timezone.utc),
                            *(float(v) for v in vals)))
        except (IndexError, TypeError, ValueError):
            continue
    return bars


def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _rvol(bars: list[Bar], lookback: int = 20) -> float:
    if len(bars) <= lookback:
        return 0.0
    baseline = _mean(b.volume for b in bars[-lookback - 1:-1])
    return bars[-1].volume / baseline if baseline else 0.0


def _session_slot(bar: Bar) -> tuple[str, int] | None:
    """Return (ET session date, 5-minute slot) for regular-session bars."""
    et = bar.ts.astimezone(ET)
    if et.weekday() >= 5:
        return None
    minutes = (et.hour * 60 + et.minute) - (9 * 60 + 30)
    if minutes < 0 or minutes >= 390:
        return None
    return et.date().isoformat(), minutes // 5


def _intraday_rvol(bars: list[Bar], sessions: int = 20) -> float:
    """Compare current 5m volume with the same 5m slot on prior ET sessions."""
    if not bars:
        return 0.0
    latest = bars[-1]
    key = _session_slot(latest)
    if key is None:
        return 0.0
    _, slot = key
    by_day: dict[str, float] = {}
    for bar in bars[:-1]:
        k = _session_slot(bar)
        if k is not None and k[1] == slot:
            by_day[k[0]] = bar.volume
    prior = list(by_day.values())[-sessions:]
    baseline = _mean(prior)
    return latest.volume / baseline if baseline else 0.0


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
        rvol = _rvol(bars[:i + 1], 20)
        criteria = []
        if close_change >= 20: criteria.append("DAILY_UP_20")
        if close_change <= -20: criteria.append("DAILY_DOWN_20")
        if intraday >= 30: criteria.append("INTRADAY_RANGE_30")
        if intraday >= 50: criteria.append("EXTREME_INTRADAY_50")
        if rvol >= 5: criteria.append("VOLUME_5X")
        high_from_open = (b.high / b.open - 1) * 100 if b.open else 0
        close_from_high = (b.close / b.high - 1) * 100 if b.high else 0
        if high_from_open >= 20 and close_from_high <= -15:
            criteria.append("FAILED_SPIKE")
        if criteria:
            episodes.append({
                "date": b.ts.date().isoformat(), "open": b.open, "high": b.high,
                "low": b.low, "close": b.close, "previous_close": prev.close,
                "close_change_pct": round(close_change, 4),
                "intraday_range_pct": round(intraday, 4),
                "volume": int(b.volume), "rvol_20d": round(rvol, 4),
                "criteria": criteria, "classification": classify_episode(criteria),
            })
    return episodes


def _daily_context_score(daily_bars: list[Bar] | None) -> tuple[float, float]:
    if not daily_bars or len(daily_bars) < 21:
        return 0.0, 0.0
    rvol = _rvol(daily_bars, 20)
    recent_high = max(x.high for x in daily_bars[-21:-1])
    breakout = 10.0 if daily_bars[-1].close >= recent_high else 0.0
    return rvol, breakout


def compute_live_signal(bars: list[Bar], catalyst=False,
                        catalyst_type=None, catalyst_id=None,
                        daily_bars: list[Bar] | None = None):
    if len(bars) < 21:
        raise ValueError("At least 21 intraday bars are required")
    b, prev = bars[-1], bars[-2]
    intraday_rvol = _intraday_rvol(bars, 20)
    move = (b.close / prev.close - 1) * 100 if prev.close else 0
    intraday = (b.high / b.low - 1) * 100 if b.low else 0
    momentum = min(20.0, max(0.0, move) * 0.8)
    volume_score = min(25.0, max(0.0, (intraday_rvol - 1) * 4))
    range_score = min(10.0, max(0.0, (intraday - 10) * 0.25))
    daily_rvol, daily_breakout = _daily_context_score(daily_bars)
    prior_20_high = max(x.high for x in bars[-21:-1])
    intraday_breakout = 10.0 if b.close >= prior_20_high else 0.0
    breakout = bool(daily_breakout or intraday_breakout)
    catalyst_score = 15.0 if catalyst else 0.0
    prior_vol = _mean(x.volume for x in bars[-6:-1])
    accel = 10.0 if b.close > prev.close and prior_vol and b.volume > prior_vol * 2 else 0.0
    score = round(min(100.0, momentum + volume_score + range_score +
                      (10.0 if breakout else 0.0) + catalyst_score + accel), 1)
    status = "EXTREME" if score >= 80 else "SETUP" if score >= 60 else "WATCH"
    return {
        "ticker": SYMBOL, "timestamp": b.ts.isoformat(), "price": b.close,
        "move_pct": round(move, 2), "intraday_range_pct": round(intraday, 2),
        "rvol_20": round(intraday_rvol, 2), "daily_rvol_20": round(daily_rvol, 2),
        "breakout": breakout, "catalyst": catalyst, "catalyst_type": catalyst_type,
        "catalyst_id": catalyst_id, "score": score, "status": status,
        "informational_only": True,
    }


def format_telegram_signal(s):
    icon = {"WATCH": "🟢", "SETUP": "🟠", "EXTREME": "🚨"}[s["status"]]
    catalyst = s.get("catalyst_type") if s.get("catalyst") else "none identified"
    return "\n".join([
        f"{icon} PSIG RADAR — {s['status']}", "━━━━━━━━━━━━━━━━━━",
        f"💰 Price: \${s['price']:.2f}", f"📈 Move: {s['move_pct']:+.2f}%",
        f"📊 Intraday RVOL: {s['rvol_20']:.2f}×",
        f"📊 Daily RVOL: {s.get('daily_rvol_20', 0):.2f}×",
        f"⚡ Intraday range: {s['intraday_range_pct']:.2f}%",
        f"🚀 Breakout: {'YES' if s['breakout'] else 'NO'}",
        f"🧨 Catalyst: {catalyst}", f"🎯 PSIG Score: {s['score']:.0f}/100", "",
        "⚠️ Informational only — no automatic buy/sell signal.", "━━━━━━━━━━━━━━━━━━",
    ])


def load_state():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def should_alert(signal, state, min_score_realert=15.0) -> bool:
    """Alert on status upgrades, material score increases, or new catalysts."""
    status = signal["status"]
    previous_status = state.get("status")
    previous_score = float(state.get("last_signal", {}).get("score", 0.0))
    previous_catalyst = state.get("last_catalyst_id")
    rank = {"WATCH": 0, "SETUP": 1, "EXTREME": 2}
    new_catalyst = bool(signal.get("catalyst_id")) and signal.get("catalyst_id") != previous_catalyst
    upgraded = rank.get(status, 0) > rank.get(previous_status, 0)
    stronger = status in {"SETUP", "EXTREME"} and signal["score"] >= previous_score + min_score_realert
    alert = upgraded or stronger or (new_catalyst and status in {"SETUP", "EXTREME"})
    state["status"] = status
    state["last_signal"] = {
        "timestamp": signal["timestamp"], "score": signal["score"], "price": signal["price"],
    }
    if signal.get("catalyst_id"):
        state["last_catalyst_id"] = signal["catalyst_id"]
    return alert
