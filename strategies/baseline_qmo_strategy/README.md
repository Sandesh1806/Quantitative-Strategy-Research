# 📈 Baseline + QMO Breakout Algorithmic Trading Bot

A fully automated, high-frequency quantitative trading system integrated with **MetaTrader 5 (MT5)**. This bot is architected to execute a rigorous trend-following and reversal strategy on crypto assets (default: BTCUSDT), currently deployed on an **AWS EC2 instance** to ensure 24/7 market participation.

---

## 🎯 Strategy Overview
The strategy leverages a multi-indicator confluence approach to eliminate emotional bias. 

### Core Components
* **Baseline (Kijun-sen):** A 26-period equilibrium calculation ($(\text{Highest High} + \text{Lowest Low}) / 2$) used to define the medium-term trend and as a "return-to-mean" anchor.
* **Quantum Motion Oscillator (QMO):** A custom momentum oscillator. It aggregates 50-period SMAs across multiple timeframes, applies a 20-period Linear Regression, and uses a triple-EMA smoothing technique (10, 20, 55 periods) to identify high-probability trend shifts.

### Execution Logic
1. **State Management:** The bot enforces a "baseline touch" rule after any trade closure, preventing "FOMO" entries.
2. **Breakout Confirmation:** It waits for the subsequent candle to breach the high/low of the setup candle before executing.
3. **Dynamic Risk:** Stop-losses are calculated based on structural swing points (last 15 candles).

---
# 📈 BTCUSDT Algorithmic Trading Report

## 📊 Executive Performance Summary (4-Day Schedule)
This system utilizes time-based filtering to optimize for changing market regimes. Data is filtered for **Monday, Wednesday, Thursday, and Friday**.

| Configuration | Total PnL | Win Rate | Profit Factor | Max Drawdown | Sortino Ratio |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Top 8 Golden** | **+$1,080.03** | 45.1% | 1.33 | -$542.74 | 1.85 |
| **10-Hour Perfect** | **+$966.01** | 48.5% | 1.45 | -$403.72 | 1.42 |
| **Top 5 Elite** | **+$895.92** | 50.4% | 1.71 | -$365.97 | 1.68 |
| **Raw (No Filter)** | **-$76.06** | 39.9% | 0.99 | -$979.47 | -0.15 |

---

<img width="3000" height="1800" alt="equity_curve" src="https://github.com/user-attachments/assets/8222bde9-ec38-4045-b90f-0900a40d976a" />


## 📉 Weekly Performance Matrix (4-Day Filter Applied)
*Note: The 4-Day Filter restricts trading to Monday, Wednesday, Thursday, and Friday.*

| Week | 10-Hour Perfect | Top 8 Golden | Top 5 Elite | Raw (Unfiltered) |
| :--- | :--- | :--- | :--- | :--- |
| **Week 7** | +$250.60 | +$664.67 | +$377.47 | +$314.17 |
| **Week 8** | +$54.20 | -$96.91 | +$14.83 | -$184.33 |
| **Week 9** | +$355.61 | +$490.18 | +$382.70 | +$167.66 |
| **Week 10** | +$433.26 | +$407.09 | +$514.52 | +$280.92 |
| **Week 11** | +$217.58 | -$45.01 | -$110.18 | -$349.49 |
| **Week 12** | +$132.56 | -$141.32 | -$132.12 | +$82.69 |
| **Week 13** | +$27.39 | +$43.98 | +$22.76 | -$165.59 |
| **Week 14** | -$103.13 | +$91.45 | +$52.82 | +$33.79 |
| **Week 15** | -$282.92 | -$30.22 | +$48.55 | -$230.64 |
| **Week 16** | -$119.14 | -$303.88 | -$275.43 | -$45.26 |

---

## 💡 System Analysis & Market Regimes
The algorithm experienced a significant **Regime Shift** starting in mid-April.
- **The Sideways Strategy (10-Hour Perfect Week):** Excelled during the low-volatility consolidation of February and March, providing consistent alpha.
- **The Trend Strategies (Elite/Golden):** Showed higher resilience during the April breakout. 
- **The Raw Data Reality:** The "Raw (No Filter)" data demonstrates the necessity of our filters. Without time-based exclusion, the system is fundamentally unprofitable (-$76.06) due to exposure during high-risk/low-liquidity hours.

---r Data Science & Quantitative Trading.*
