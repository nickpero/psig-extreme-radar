# PSIG Extreme Radar

Independent monitoring and research system for PSIG (NASDAQ: PSIG).

## Scope
- Historical event catalogue
- Daily event study
- Phase 1C pre-event pattern discovery
- Chronological walk-forward validation
- Intraday 5-minute monitoring using the New York regular-session clock
- Daily + intraday context in Signal Engine V1
- SEC filing/catalyst monitoring
- Telegram alerts with transition/material-change deduplication

## Alert philosophy
The radar is designed to identify configurations that deserve attention before or during exceptional PSIG moves. It is not an automatic trading system and does not issue buy/sell recommendations.

Alerts are suppressed when the signal remains unchanged. A new alert can occur when:
- status upgrades WATCH -> SETUP -> EXTREME;
- the score increases materially while already in SETUP/EXTREME;
- a new SEC catalyst arrives while the signal is already SETUP/EXTREME;
- a new financing-related SEC filing is detected.

## Research guardrails
Phase 1C thresholds are descriptive research outputs. They are not copied directly into the live engine. Walk-forward validation is required before any threshold is promoted to a future Signal Engine version.

The repository is intentionally separate from Pharma Radar.
