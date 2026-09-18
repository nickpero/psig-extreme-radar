from datetime import datetime, timezone
from scanner.psig_radar import Bar, classify_episode, compute_live_signal, detect_daily_episodes

def b(day, o, h, l, c, v): return Bar(datetime.fromisoformat(day).replace(tzinfo=timezone.utc), o, h, l, c, v)

def test_classification():
    assert classify_episode(["DAILY_UP_20"]) == "MAJOR_UPSIDE"
    assert classify_episode(["DAILY_UP_20", "VOLUME_5X"]) == "VOLUME_MOMENTUM_SPIKE"
    assert classify_episode(["EXTREME_INTRADAY_50", "FAILED_SPIKE"]) == "EXTREME_REVERSAL"

def test_spike_detection():
    bars = [b(f"2026-08-{i:02d}", 2, 2.1, 1.9, 2, 1000) for i in range(1, 22)]
    bars[-1] = b("2026-08-25", 2, 3, 1.9, 2.6, 6000)
    events = detect_daily_episodes(bars)
    assert events
    assert "DAILY_UP_20" in events[-1]["criteria"]
    assert "VOLUME_5X" in events[-1]["criteria"]

def test_signal_status():
    bars = [b(f"2026-09-{i:02d}", 2, 2.1, 1.9, 2, 1000) for i in range(1, 22)]
    bars[-1] = b("2026-09-21", 2, 3, 1.9, 2.7, 8000)
    signal = compute_live_signal(bars)
    assert signal["status"] in {"SETUP", "EXTREME"}
    assert signal["informational_only"] is True
