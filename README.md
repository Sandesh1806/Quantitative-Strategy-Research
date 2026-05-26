# Quant Trading Strategies Repository

Algorithmic trading strategies for:
- MetaTrader 5 (MT5)
- Delta Exchange
- Crypto Futures & Options
- Automated Recovery Systems
- Quantitative Momentum Strategies

This repository contains live-tested, experimental, and research-based trading systems with performance reports and deployment-ready configurations.

---

# Repository Structure

```bash
strategies/
│
├── baseline_qmo_strategy/
│   ├── Reports/
│   │   ├── hourly_pnl_distribution_analysis(filtered).xlsx.xlsx
│   │   ├── live_forward_test_report(raw).xlsx.xlsx
│   │   └── session_performance_analysis(filtered).xlsx.xlsx
│   │
│   ├── README.md
│   ├── btc_qmo_strategy.py
│   ├── config.json
│   ├── hourly_pnl_distribution_analysis(filtered).xlsx.xlsx
│   ├── live_forward_test_report(raw).xlsx.xlsx
│   └── session_performance_analysis(filtered).xlsx.xlsx
│
├── recovery_scalping/
│   ├── config.json
│   └── profit_recovery_engine.py
│
├── .gitignore
└── LICENSE
```

---

# Current Strategies

## 1. Baseline QMO Strategy

A quantitative momentum breakout strategy designed for BTC trading.

### Features
- Momentum-based entries
- Session analysis
- Forward-tested reports
- Configurable parameters
- Risk-reward logic
- Automated execution

### Includes
- Python strategy script
- Config file
- Performance reports
- PnL distribution analysis
- Session analytics

---

## 2. Recovery Scalping Engine

A recovery-based reversal scalping system for high-volatility markets.

### Features
- Reverse trade logic
- Dynamic volume progression
- Automated TP/SL handling
- MT5 execution support
- Config-driven setup

### Warning
This strategy uses recovery-style volume escalation and carries significant risk during strong market trends or extreme volatility.

---

# Technologies Used

- Python
- MetaTrader5 API
- Delta Exchange API
- AWS Deployment
- Pandas
- Quantitative Analysis
- Automated Risk Management

---

# Deployment

Some strategies are deployed and monitored on AWS cloud infrastructure for continuous execution and live forward testing.

---

# Setup

## Install Dependencies

```bash
pip install -r requirements.txt
```

## Configure Strategy

Edit:

```bash
config.json
```

Add your:
- broker credentials
- API keys
- trading parameters

---

# Security Notice

Do NOT upload:
- API keys
- MT5 passwords
- exchange secrets
- private credentials

Use:
- `.env`
- ignored private configs
- encrypted secrets management

---

# Risk Disclaimer

Algorithmic trading involves substantial financial risk.

These strategies are experimental/research systems and are not financial advice.

Past performance does not guarantee future results.

Use proper risk management and test thoroughly before live deployment.

---

# Future Roadmap

Planned additions:
- HFT execution engine
- Options volatility models
- ML-based signal filtering
- Real-time dashboards
- WebSocket execution layer
- Multi-exchange support
- Portfolio risk engine

---

# Author

Sandesh

AI & Data Science Engineering Student  
Algorithmic Trading & Quant Research Enthusiast
