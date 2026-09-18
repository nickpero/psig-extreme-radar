"""Phase 1B: PSIG historical event-study framework."""
import json
from pathlib import Path
from scanner.psig_radar import SYMBOL, fetch_yahoo, detect_daily_episodes
OUT = Path("data/psig")
WINDOWS = [-60, -30, -15, -5, 0, 5, 15, 30, 60]

def _pct(a, b): return round((a / b - 1) * 100, 4) if b else None

def build_daily_event_study(bars, episodes):
    by_date = {b.ts.date().isoformat(): i for i, b in enumerate(bars)}
    studies = []
    for ep in episodes:
        i = by_date.get(ep["date"])
        if i is None: continue
        row = {"date": ep["date"], "classification": ep["classification"], "criteria": ep["criteria"], "windows": {}}
        for w in [-10, -5, -3, -2, -1, 0, 1, 3, 5]:
            j = i + w
            if 0 <= j < len(bars):
                b = bars[j]
                base = bars[i - 1].close if i > 0 else None
                row["windows"][str(w)] = {"close": b.close, "volume": b.volume,
                    "return_vs_prior_close": _pct(b.close, bars[j - 1].close) if j > 0 else None,
                    "return_vs_event_prev_close": _pct(b.close, base)}
        studies.append(row)
    return studies

def run():
    bars = fetch_yahoo(SYMBOL, "1d", 420)
    episodes = detect_daily_episodes(bars)
    studies = build_daily_event_study(bars, episodes)
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {"ticker": SYMBOL, "windows_intraday_minutes": WINDOWS, "daily_event_studies": studies,
               "note": "Intraday pre-spike study is populated when sufficiently long historical 5m data is available; free endpoints may restrict older intraday history."}
    (OUT / "phase1_event_study.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"episodes": len(episodes), "studies": len(studies)}, indent=2))

if __name__ == "__main__": run()
