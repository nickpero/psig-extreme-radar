from scanner.psig_pattern_discovery import build_dataset, discover_patterns, feature_snapshot
from scanner.psig_radar import Bar
from datetime import datetime, timezone

def b(day, o, h, l, c, v):
    return Bar(datetime.fromisoformat(day).replace(tzinfo=timezone.utc), o, h, l, c, v)

def test_feature_snapshot_uses_only_history():
    bars = [b(f"2026-01-{i:02d}", 2, 2.1, 1.9, 2, 1000) for i in range(1, 22)]
    bars[-1] = b("2026-01-21", 2, 2.2, 1.9, 2.1, 3000)
    x = feature_snapshot(bars, 20)
    assert x["rvol20"] > 1
    assert x["return_1d"] > 0
    assert "high20_breakout" in x

def test_dataset_has_event_and_control_rows():
    bars = [b(f"2026-01-{i:02d}", 2, 2.1, 1.9, 2, 1000) for i in range(1, 31)]
    bars[-1] = b("2026-01-30", 2, 3, 1.9, 2.5, 6000)
    episodes = [{
        "date": "2026-01-30",
        "classification": "MAJOR_UPSIDE",
        "criteria": ["DAILY_UP_20"],
    }]
    ds = build_dataset(bars, episodes)
    assert ds["event_snapshot_count"] >= 1
    assert ds["control_count"] >= 1
    assert all("rvol20" in r for r in ds["rows"])

def test_discovery_returns_stats():
    ds = {
        "rows": [
            {"is_event_snapshot": True, "event_offset": -1, "rvol20": 5, "return_5d": 10, "range_pct": 20, "atr14_pct": 5},
            {"is_event_snapshot": True, "event_offset": -1, "rvol20": 6, "return_5d": 12, "range_pct": 25, "atr14_pct": 6},
            {"is_event_snapshot": False, "event_offset": None, "rvol20": 1, "return_5d": 0, "range_pct": 5, "atr14_pct": 2},
            {"is_event_snapshot": False, "event_offset": None, "rvol20": 1.2, "return_5d": 1, "range_pct": 6, "atr14_pct": 2.5},
        ],
    }
    out = discover_patterns(ds)
    assert out["all_threshold_stats"]
