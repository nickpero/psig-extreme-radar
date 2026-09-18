"""PSIG Radar Phase 1: historical spike catalogue."""
import json
from pathlib import Path
from scanner.psig_radar import SYMBOL, fetch_yahoo, detect_daily_episodes
OUT = Path("data/psig")

def run():
    daily = fetch_yahoo(SYMBOL, "1d", 420)
    episodes = detect_daily_episodes(daily)
    recent = []
    error = None
    try:
        recent = fetch_yahoo(SYMBOL, "5m", 59)
    except Exception as exc:
        error = str(exc)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phase1_episodes.json").write_text(json.dumps({
        "ticker": SYMBOL, "daily_bars": len(daily), "episodes": episodes,
        "intraday_bars_5m": len(recent), "intraday_error": error,
        "methodology": {"daily_upside_pct": 20, "daily_downside_pct": -20,
        "intraday_range_pct": 30, "extreme_intraday_range_pct": 50,
        "volume_rvol_20d": 5, "failed_spike_high_from_open_pct": 20,
        "failed_spike_close_from_high_pct": -15}
    }, indent=2), encoding="utf-8")
    if recent:
        (OUT / "recent_5m.json").write_text(json.dumps([
            {"ts": b.ts.isoformat(), "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume}
            for b in recent
        ], indent=2), encoding="utf-8")
    return {"daily_bars": len(daily), "episodes": len(episodes), "intraday_bars": len(recent), "intraday_error": error}

if __name__ == "__main__": print(json.dumps(run(), indent=2))
