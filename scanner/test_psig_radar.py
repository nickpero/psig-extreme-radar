from datetime import datetime, timezone, timedelta
from scanner.psig_radar import (
    Bar, _intraday_rvol, classify_episode, compute_live_signal,
    detect_daily_episodes, should_alert,
)


def b(day, o, h, l, c, v):
    return Bar(datetime.fromisoformat(day).replace(tzinfo=timezone.utc), o, h, l, c, v)


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


def test_session_slot_rvol_uses_et_slot():
    prior = []
    base = datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc)
    for i in range(20):
        prior.append(Bar(base + timedelta(days=i), 1, 1.01, .99, 1, 100))
    current = Bar(datetime(2026, 9, 1, 13, 30, tzinfo=timezone.utc), 1, 1.01, .99, 1, 300)
    assert _intraday_rvol(prior + [current], 20) == 3.0


def test_alert_transitions_and_material_increase():
    state = {}
    s = {"status": "WATCH", "score": 20, "timestamp": "t1", "price": 1}
    assert should_alert(s, state) is False
    s = {"status": "SETUP", "score": 60, "timestamp": "t2", "price": 2}
    assert should_alert(s, state) is True
    s = {"status": "SETUP", "score": 62, "timestamp": "t3", "price": 2.1}
    assert should_alert(s, state) is False
    s = {"status": "SETUP", "score": 78, "timestamp": "t4", "price": 2.4}
    assert should_alert(s, state) is True


def test_new_catalyst_can_alert_inside_setup():
    state = {"status": "SETUP", "last_signal": {"score": 65}, "last_catalyst_id": "old"}
    s = {"status": "SETUP", "score": 66, "timestamp": "t5", "price": 2.5, "catalyst_id": "new"}
    assert should_alert(s, state) is True
