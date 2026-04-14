---

# Volume Profile Trading Engine

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Status](https://img.shields.io/badge/Status-Active-success)
![Strategy](https://img.shields.io/badge/Type-Intraday%20Trading-orange)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

A rule-based intraday trading engine that leverages Volume Profile, Price Action, and Market Structure to generate high-quality trading signals with built-in risk management and trade lifecycle control.

---

## Features

* Volume Profile (POC, VAH, VAL)
* Market Regime Detection (Trend / Balance / Normal)
* Price Journey Tracking (Context-aware trading)
* Multi-strategy Signal Engine
* Dynamic Stop Loss and Targeting
* Advanced Trade Management (Trailing and Breakeven)
* Strong Risk Controls (Daily limits, cooldowns)

---

## Strategy Philosophy

This system does not just react to price — it interprets how price behaves around value.

The engine focuses on:

* Acceptance vs Rejection
* Movement relative to value areas
* Market intent (trend vs balance)
* Context-driven entries instead of indicator-only signals

---

## Architecture Overview

```
Live Market Data
       ↓
Zone Tracking (get_zone)
       ↓
Signal Engine (detect_signal)
       ↓
Trade Execution
       ↓
Trade Manager (check_stop)
       ↓
Exit / Trail / Risk Control
```

---

## Core Components

### 1. `get_zone(live_data)`

Tracks whether price is:

* above VAH
* inside value area
* below VAL

Maintains a rolling zone history used for behavioral analysis.

---

### 2. `detect_signal(...)`

Core decision engine.

Handles:

#### Market Context

* Initial Balance (IB)
* ATR and volatility
* Volume analysis

#### Market Regime

* trend_up
* trend_down
* balance
* normal

#### Strategy Types

| Strategy            | Description              |
| ------------------- | ------------------------ |
| Breakouts           | Strong directional moves |
| Fades               | Reversals at extremes    |
| POC Retests         | Mean reversion           |
| Value Area Fills    | Traversing value         |
| Previous Day Levels | Institutional zones      |

#### Decision Priority

1. Reclaim moves
2. Migration
3. Fades
4. Value fills
5. Retests

#### Trade Filtering

* Impulse validation
* Candle confirmation
* Acceptance logic
* Score-based filtering

---

### 3. `check_stop(...)`

Trade lifecycle manager.

#### Dynamic Trade Management

| Tier   | Condition  | Action                     |
| ------ | ---------- | -------------------------- |
| Tier 1 | 40% target | Move SL to breakeven       |
| Tier 2 | 70% target | Trail SL and extend target |
| Tier 3 | 85% target | Lock profits               |

#### Exit Conditions

* Stop Loss hit
* Target achieved
* Time-based exit
* Daily risk limits

---

### 4. Volume Profile Utilities

#### `get_volume_profile_live(df)`

* Builds profile directly from price-volume data
* Computes:

  * POC
  * VAH
  * VAL

#### `get_volume_profile_stats(df, bin_size=0.05)`

* Adds price binning
* Reduces noise
* Produces smoother levels

---

## Configuration

All strategy behavior is controlled via a parameter dictionary:

```python
para = {
    "range_len": 20,
    "range_m": 1.5,
    "vol_m": 1.5,
    "trend_atr_m": 1.2,
    "bal_atr_m": 0.5,
    "break_sl_m": 1.2,
    "fade_sl_m": 0.8,
    "cooldown": 5,
    "max_loss": 1000,
    "max_profit": 2000
}
```

---

## Input Data Format

```python
live_data = {
    "prices": [],
    "high_prices": [],
    "low_prices": [],
    "open_prices": [],
    "volume": [],
    "live_time": [],
    "live_price": float,

    "curr_vah": float,
    "curr_val": float,
    "curr_poc": float,

    "prv_vah": float,
    "prv_val": float,
    "prv_poc": float,

    "trade_allowed": True,
    "trade_exit_time": int
}
```

---

## Output Signal

```python
{
    "side": "buy" | "sell",
    "entry": float,
    "sl": float,
    "target": float,
    "score": int,
    "strategy": str,
    "regime": str,
    "journey": str
}
```

---

## Risk Management

The system enforces strict safeguards:

* Stops trading after max loss
* Locks profits progressively
* Enforces cooldown between trades
* Avoids low-quality setups via scoring
* Prevents trading against macro trend

---

## Use Cases

* Intraday trading systems
* Algorithmic trading bots
* Backtesting engines
* Strategy research and experimentation

---

## Setup

```bash
pip install pandas numpy pandas_ta fyers-apiv3 setuptools math scipy

```

---

## Example Usage

```python
get_zone(live_data)

signal = detect_signal(live_data, executed_trades, para, logger)

if signal:
    execute_trade(signal)
```

---

## Disclaimer

This project is for educational and research purposes only.

Trading involves risk. Use with proper:

* Backtesting
* Risk management
* Capital allocation

---

## Final Thought

Markets are not random — they are contextual.

This engine attempts to capture that context:

* Where price is
* Where it came from
* What it is likely trying to do

---
