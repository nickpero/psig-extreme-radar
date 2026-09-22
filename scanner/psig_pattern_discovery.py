"""Phase 1C: PSIG pre-event pattern discovery and walk-forward validation."""
from __future__ import annotations

from datetime import date
import json
import math
from pathlib import Path
from statistics import mean
from typing import Iterable

from scanner.psig_radar import Bar, SYMBOL, detect_daily_episodes, fetch_yahoo

OUT = Path("data/psig")
SNAPSHOTS = [-10, -5, -3, -2, -1]
RVOL_THRESHOLDS = [1.5, 2, 2.5, 3, 4, 5, 7.5, 10]
MOMENTUM_THRESHOLDS = [3, 5, 8, 10, 15, 20]
RANGE_THRESHOLDS = [10, 15, 20, 25, 30, 40, 50]
ATR_THRESHOLDS = [2, 3, 4, 5, 7.5, 10, 15]


def _pct(a: float, b: float) -> float | None:
    return round((a / b - 1) * 100, 4) if b else None


def _mean(values: Iterable[float]) -> float:
    vals = list(values)
    return mean(vals) if vals else 0.0


def _atr_pct(bars: list[Bar], end: int, lookback: int = 14) -> float:
    if end <= 0:
        return 0.0
    start = max(1, end - lookback + 1)
    trs = []
    for i in range(start, end + 1):
        prev_close = bars[i - 1].close
        trs.append(max(
            bars[i].high - bars[i].low,
            abs(bars[i].high - prev_close),
            abs(bars[i].low - prev_close),
        ))
    return (_mean(trs) / bars[end].close * 100) if bars[end].close else 0.0


def feature_snapshot(bars: list[Bar], i: int) -> dict:
    b = bars[i]
    prev = bars[i - 1] if i > 0 else None

    def ret(days: int):
        j = i - days
        return _pct(b.close, bars[j].close) if j >= 0 else None

    vol20 = _mean(x.volume for x in bars[max(0, i - 20):i])
    vol10 = _mean(x.volume for x in bars[max(0, i - 10):i])
    vol5 = _mean(x.volume for x in bars[max(0, i - 5):i])
    rvol20 = b.volume / vol20 if vol20 else 0.0
    rvol10 = b.volume / vol10 if vol10 else 0.0
    rvol5 = b.volume / vol5 if vol5 else 0.0
    prior20 = bars[max(0, i - 20):i]
    prior_high20 = max((x.high for x in prior20), default=b.high)
    prior_low20 = min((x.low for x in prior20), default=b.low)
    range_pct = _pct(b.high, b.low) if b.low else 0.0
    body_pct = _pct(b.close, b.open) if b.open else 0.0
    close_position = ((b.close - b.low) / (b.high - b.low)) if b.high > b.low else 0.5
    return {
        "date": b.ts.date().isoformat(), "close": b.close, "volume": int(b.volume),
        "return_1d": ret(1), "return_3d": ret(3), "return_5d": ret(5), "return_10d": ret(10),
        "gap_pct": _pct(b.open, prev.close) if prev and prev.close else None,
        "range_pct": range_pct, "body_pct": body_pct, "close_position": round(close_position, 4),
        "rvol20": round(rvol20, 4), "rvol10": round(rvol10, 4), "rvol5": round(rvol5, 4),
        "volume_accel_5v20": round((vol5 / vol20) if vol20 else 0.0, 4),
        "high20_breakout": bool(i >= 20 and b.close > prior_high20),
        "low20_breakdown": bool(i >= 20 and b.close < prior_low20),
        "atr14_pct": round(_atr_pct(bars, i), 4),
        "drawdown_from_20d_high_pct": round(_pct(b.close, prior_high20), 4) if prior_high20 else 0.0,
    }


def build_dataset(bars: list[Bar], episodes: list[dict]) -> dict:
    by_date = {b.ts.date().isoformat(): i for i, b in enumerate(bars)}
    event_dates = {ep["date"] for ep in episodes}
    rows = []

    for ep in episodes:
        event_i = by_date.get(ep["date"])
        if event_i is None:
            continue
        for offset in SNAPSHOTS:
            i = event_i + offset
            if i < 20 or i >= len(bars):
                continue
            row = feature_snapshot(bars, i)
            row.update({
                "event_date": ep["date"], "event_classification": ep["classification"],
                "event_offset": offset, "is_event_snapshot": True,
                "event_criteria": ep["criteria"],
            })
            rows.append(row)

    control_rows = []
    for i in range(20, len(bars)):
        d = bars[i].ts.date()
        date_text = d.isoformat()
        if date_text in event_dates:
            continue
        nearby_event = any(abs((d - date.fromisoformat(ed)).days) <= 1 for ed in event_dates)
        if nearby_event:
            continue
        row = feature_snapshot(bars, i)
        row.update({
            "event_date": None, "event_classification": None, "event_offset": None,
            "is_event_snapshot": False, "event_criteria": [],
        })
        control_rows.append(row)

    rows.extend(control_rows)
    return {
        "ticker": SYMBOL, "snapshot_offsets": SNAPSHOTS, "event_count": len(episodes),
        "event_snapshot_count": len(rows) - len(control_rows),
        "control_count": len(control_rows), "rows": rows,
    }


def _metric(y_event: list[bool], y_control: list[bool]) -> dict:
    tp = sum(y_event)
    fp = sum(y_control)
    fn = len(y_event) - tp
    tn = len(y_control) - fp
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / len(y_event) if y_event else 0.0
    specificity = tn / len(y_control) if y_control else 0.0
    fpr = 1 - specificity
    event_prev = tp / len(y_event) if y_event else 0.0
    control_prev = fp / len(y_control) if y_control else 0.0
    lift = event_prev / control_prev if control_prev else (float("inf") if event_prev else 0.0)
    return {
        "event_n": len(y_event), "control_n": len(y_control),
        "precision": round(precision, 4), "recall": round(recall, 4),
        "specificity": round(specificity, 4), "false_positive_rate": round(fpr, 4),
        "lift": None if math.isinf(lift) else round(lift, 4),
    }


def threshold_stats(dataset: dict, rows_override: list[dict] | None = None) -> list[dict]:
    rows = rows_override if rows_override is not None else dataset["rows"]
    events = [r for r in rows if r["is_event_snapshot"]]
    controls = [r for r in rows if not r["is_event_snapshot"]]
    specs = [
        ("rvol20", RVOL_THRESHOLDS), ("return_5d", MOMENTUM_THRESHOLDS),
        ("range_pct", RANGE_THRESHOLDS), ("atr14_pct", ATR_THRESHOLDS),
    ]
    out = []
    for field, thresholds in specs:
        for threshold in thresholds:
            for offset in SNAPSHOTS:
                ev_rows = [r for r in events if r["event_offset"] == offset]
                if not ev_rows:
                    continue
                ev = [r.get(field) is not None and r[field] >= threshold for r in ev_rows]
                ct = [r.get(field) is not None and r[field] >= threshold for r in controls]
                m = _metric(ev, ct)
                m.update({"feature": field, "operator": ">=", "threshold": threshold, "offset": offset})
                out.append(m)
    return out


def discover_patterns(dataset: dict) -> dict:
    stats = threshold_stats(dataset)
    candidates = [
        s for s in stats
        if s["recall"] >= 0.25 and s["precision"] >= 0.50
        and s["false_positive_rate"] <= 0.25
        and (s["lift"] is None or s["lift"] >= 1.5)
    ]
    candidates.sort(key=lambda s: (
        s["offset"], -(s["lift"] or 999999), -s["recall"],
    ))
    return {
        "method": "descriptive threshold discovery; no P&L optimization",
        "candidate_count": len(candidates), "candidates": candidates[:50],
        "all_threshold_stats": stats,
    }


def _event_dates(rows: list[dict]) -> list[str]:
    return sorted({r["event_date"] for r in rows if r["is_event_snapshot"] and r["event_date"]})


def walk_forward_validate(dataset: dict) -> dict:
    """Chronological expanding validation.

    Thresholds are selected only on the training period, then measured on the
    next block. This is the gate before any threshold is promoted to V1.
    """
    rows = dataset["rows"]
    dates = _event_dates(rows)
    if len(dates) < 12:
        return {"status": "INSUFFICIENT_EVENTS", "folds": []}

    # Three chronological blocks; each validation block is never used to choose
    # its own threshold.
    n = len(dates)
    cut1 = max(6, n // 2)
    cut2 = max(cut1 + 3, (3 * n) // 4)
    cut2 = min(cut2, n - 1)
    boundaries = [(cut1, cut2), (cut2, n)]

    folds = []
    for fold_no, (train_end, test_end) in enumerate(boundaries, 1):
        train_dates = set(dates[:train_end])
        test_dates = set(dates[train_end:test_end])
        train_rows = [
            r for r in rows
            if (r["is_event_snapshot"] and r["event_date"] in train_dates)
            or (not r["is_event_snapshot"] and r["date"] < min(test_dates))
        ]
        test_rows = [
            r for r in rows
            if (r["is_event_snapshot"] and r["event_date"] in test_dates)
            or (not r["is_event_snapshot"] and r["date"] >= min(test_dates) and r["date"] <= max(test_dates))
        ]
        train_stats = threshold_stats(dataset, train_rows)
        eligible = [
            s for s in train_stats
            if s["precision"] >= 0.50 and s["recall"] >= 0.20 and s["false_positive_rate"] <= 0.25
        ]
        if not eligible:
            folds.append({"fold": fold_no, "status": "NO_TRAIN_CANDIDATE",
                          "train_events": len(train_dates), "test_events": len(test_dates)})
            continue
        chosen = max(eligible, key=lambda s: (s["precision"] * s["recall"], s["lift"] or 0))
        matching_test = [
            r for r in test_rows
            if r["event_offset"] == chosen["offset"]
        ]
        ev = [r[chosen["feature"]] >= chosen["threshold"] for r in matching_test if r["is_event_snapshot"]]
        ct = [r[chosen["feature"]] >= chosen["threshold"] for r in matching_test if not r["is_event_snapshot"]]
        measured = _metric(ev, ct)
        folds.append({
            "fold": fold_no, "status": "VALIDATED",
            "train_events": len(train_dates), "test_events": len(test_dates),
            "chosen_threshold": chosen, "test_metrics": measured,
        })
    return {"status": "OK", "folds": folds}


def run() -> dict:
    bars = fetch_yahoo(SYMBOL, "1d", 420)
    episodes = detect_daily_episodes(bars)
    dataset = build_dataset(bars, episodes)
    discovery = discover_patterns(dataset)
    validation = walk_forward_validate(dataset)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phase1c_dataset.json").write_text(json.dumps(dataset, indent=2), encoding="utf-8")
    (OUT / "phase1c_feature_stats.json").write_text(json.dumps(discovery, indent=2), encoding="utf-8")
    (OUT / "phase1c_walk_forward.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")

    summary = {
        "ticker": SYMBOL, "daily_bars": len(bars), "events": len(episodes),
        "controls": dataset["control_count"], "candidates": discovery["candidate_count"],
        "snapshot_offsets": SNAPSHOTS,
        "walk_forward_status": validation["status"],
        "note": "Research outputs only. Thresholds are not promoted to Signal Engine V1 until walk-forward robustness is acceptable.",
    }
    (OUT / "phase1c_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    run()
