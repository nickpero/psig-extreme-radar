"""Phase 1C: PSIG pre-event pattern discovery and threshold statistics.

This module deliberately avoids look-ahead: every feature is computed only from
bars available at or before the anchor day. It compares pre-event snapshots
against non-event control days and tests candidate thresholds.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean, median
from typing import Iterable

from scanner.psig_radar import Bar, SYMBOL, detect_daily_episodes, fetch_yahoo

OUT = Path("data/psig")
SNAPSHOTS = [-10, -5, -3, -2, -1]
RVOL_THRESHOLDS = [1.5, 2, 2.5, 3, 4, 5, 7.5, 10]
MOMENTUM_THRESHOLDS = [3, 5, 8, 10, 15, 20]
RANGE_THRESHOLDS = [10, 15, 20, 25, 30, 40, 50]


def _pct(a: float, b: float) -> float | None:
    return round((a / b - 1) * 100, 4) if b else None


def _mean(values: Iterable[float]) -> float:
    vals = list(values)
    return mean(vals) if vals else 0.0


def _stdev(values: Iterable[float]) -> float:
    vals = list(values)
    if len(vals) < 2:
        return 0.0
    m = mean(vals)
    return math.sqrt(sum((x - m) ** 2 for x in vals) / (len(vals) - 1))


def _rolling_mean(bars: list[Bar], end: int, lookback: int) -> float:
    start = max(0, end - lookback)
    return _mean(b.volume for b in bars[start:end])


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
    """Features available after session i closes. No future bars are used."""
    b = bars[i]
    prev = bars[i - 1] if i > 0 else None
    def ret(days: int):
        j = i - days
        return _pct(b.close, bars[j].close) if j >= 0 else None

    vol20 = _rolling_mean(bars, i, 20)
    vol10 = _rolling_mean(bars, i, 10)
    vol5 = _rolling_mean(bars, i, 5)
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
        "date": b.ts.date().isoformat(),
        "close": b.close,
        "volume": int(b.volume),
        "return_1d": ret(1),
        "return_3d": ret(3),
        "return_5d": ret(5),
        "return_10d": ret(10),
        "gap_pct": _pct(b.open, prev.close) if prev and prev.close else None,
        "range_pct": range_pct,
        "body_pct": body_pct,
        "close_position": round(close_position, 4),
        "rvol20": round(rvol20, 4),
        "rvol10": round(rvol10, 4),
        "rvol5": round(rvol5, 4),
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

    # Event snapshots: offsets are relative to the event session.
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
                "event_date": ep["date"],
                "event_classification": ep["classification"],
                "event_offset": offset,
                "is_event_snapshot": True,
                "event_criteria": ep["criteria"],
            })
            rows.append(row)

    # Controls: non-event sessions with the same feature schema. Exclude the
    # immediate +/- 1 day around events to reduce contamination.
    control_rows = []
    for i in range(20, len(bars)):
        date = bars[i].ts.date().isoformat()
        if date in event_dates:
            continue
        nearby_event = any(
            abs((bars[i].ts.date() - __import__("datetime").date.fromisoformat(d)).days) <= 1
            for d in event_dates
        )
        if nearby_event:
            continue
        row = feature_snapshot(bars, i)
        row.update({
            "event_date": None,
            "event_classification": None,
            "event_offset": None,
            "is_event_snapshot": False,
            "event_criteria": [],
        })
        control_rows.append(row)

    # Keep all controls; downstream stats are prevalence-aware.
    rows.extend(control_rows)
    return {
        "ticker": SYMBOL,
        "snapshot_offsets": SNAPSHOTS,
        "event_count": len(episodes),
        "event_snapshot_count": len(rows) - len(control_rows),
        "control_count": len(control_rows),
        "rows": rows,
    }


def _metric(y_event: list[bool], y_control: list[bool]) -> dict:
    tp = sum(y_event)
    fn = len(y_event) - tp
    fp = sum(y_control)
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


def threshold_stats(dataset: dict) -> list[dict]:
    events = [r for r in dataset["rows"] if r["is_event_snapshot"]]
    controls = [r for r in dataset["rows"] if not r["is_event_snapshot"]]
    specs = [
        ("rvol20_gte", "rvol20", RVOL_THRESHOLDS),
        ("return_5d_gte", "return_5d", MOMENTUM_THRESHOLDS),
        ("range_pct_gte", "range_pct", RANGE_THRESHOLDS),
        ("atr14_pct_gte", "atr14_pct", [2, 3, 4, 5, 7.5, 10, 15]),
    ]
    out = []
    for name, field, thresholds in specs:
        for threshold in thresholds:
            for offset in SNAPSHOTS:
                ev = [r.get(field) is not None and r[field] >= threshold
                      for r in events if r["event_offset"] == offset]
                ct = [r.get(field) is not None and r[field] >= threshold
                      for r in controls]
                if not ev:
                    continue
                m = _metric(ev, ct)
                m.update({"feature": field, "operator": ">=", "threshold": threshold, "offset": offset})
                out.append(m)
    return out


def discover_patterns(dataset: dict) -> dict:
    stats = threshold_stats(dataset)
    # Candidate ranking is descriptive, not a trading recommendation. Require
    # reasonable coverage and a low control false-positive rate.
    candidates = [
        s for s in stats
        if s["recall"] >= 0.25 and s["precision"] >= 0.50
        and s["false_positive_rate"] <= 0.25
        and (s["lift"] is None or s["lift"] >= 1.5)
    ]
    candidates.sort(key=lambda s: (
        s["offset"] if s["offset"] is not None else 0,
        -(s["lift"] or 999999),
        -s["recall"],
    ))
    return {
        "method": "descriptive threshold discovery; no P&L optimization",
        "candidate_count": len(candidates),
        "candidates": candidates[:50],
        "all_threshold_stats": stats,
    }


def run() -> dict:
    bars = fetch_yahoo(SYMBOL, "1d", 420)
    episodes = detect_daily_episodes(bars)
    dataset = build_dataset(bars, episodes)
    discovery = discover_patterns(dataset)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phase1c_dataset.json").write_text(json.dumps(dataset, indent=2), encoding="utf-8")
    (OUT / "phase1c_feature_stats.json").write_text(json.dumps(discovery, indent=2), encoding="utf-8")

    lead_times = {}
    for ep in episodes:
        offsets = [r["event_offset"] for r in dataset["rows"]
                   if r["event_date"] == ep["date"]]
        lead_times[ep["date"]] = min(offsets) if offsets else None

    summary = {
        "ticker": SYMBOL,
        "daily_bars": len(bars),
        "events": len(episodes),
        "controls": dataset["control_count"],
        "candidates": discovery["candidate_count"],
        "snapshot_offsets": SNAPSHOTS,
        "lead_time_snapshot_min": lead_times,
        "note": "Candidate thresholds are research outputs only. Walk-forward validation remains a required next stage before Signal Engine V1 thresholds are adopted.",
    }
    (OUT / "phase1c_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    run()
