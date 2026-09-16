# AegisWatch 🛡️
> **Microsecond Limit Order Book (LOB) Market Abuse Surveillance & Anomaly Engine**  
> *Track: AI in FinTech · Sponsor: NASDAQ · Problem Statement #2: Unusual Activity Watchdog [Hard]*  
> *Synapse 1.0 — SIT Flagship Hackathon 2026*

---

## ⚡ Overview

**AegisWatch** is an institutional-grade, real-time market surveillance system engineered to detect high-frequency market manipulation (spoofing, layering, quote stuffing, wash trading, and momentum ignition) at the microsecond level.

Unlike legacy surveillance platforms that rely on end-of-day T+1 batch SQL threshold queries (which produce >95% false positives), AegisWatch reconstructs the full electronic Limit Order Book (LOB) in real time and applies a **Dual-Head Hybrid Surveillance Engine**:
1. **Head 1 (Deterministic Microstructure Filter)**: Fast sub-millisecond rule gates enforcing SEC Rule 10b-5, Dodd-Frank § 747, and FINRA Rule 5210 anti-manipulation standards.
2. **Head 2 (Unsupervised Behavioral Anomaly ML)**: Isolation Forest and multivariate statistical outlier modeling computing Order Flow Imbalance (OFI), Cancel-to-Trade Ratios (CTR), and Volume-Synchronized Probability of Toxicity (VPIN).
3. **Forensic Audit Dossier Generator**: Instantly produces an SEC/FINRA-grade evidentiary packet with order book depth reconstruction, participant tracing, and SHAP-inspired explainability.

---

## 🏗️ Architecture

```
                                      ┌──────────────────────────────────────────────┐
                                      │        High-Frequency Tick Tape              │
                                      │      (ITCH 5.0 / L2/L3 Message Stream)       │
                                      └──────────────────────┬───────────────────────┘
                                                             │
                                                             ▼
                                      ┌──────────────────────────────────────────────┐
                                      │         Limit Order Book (LOB) Engine        │
                                      │   - In-memory Bids & Asks Sorted Ladders     │
                                      │   - Microsecond Order Lifecycle Tracking     │
                                      └──────────────────────┬───────────────────────┘
                                                             │
                                                             ▼
                                      ┌──────────────────────────────────────────────┐
                                      │      Microstructure Feature Extractor        │
                                      │     - Order Flow Imbalance (OFI)             │
                                      │     - Cancel-to-Trade Ratio (CTR)            │
                                      │     - Toxicity Clock (VPIN)                  │
                                      │     - Order Lifetime & Flashing Ratios       │
                                      └──────────────────────┬───────────────────────┘
                                                             │
                                                             ▼
                                      ┌──────────────────────────────────────────────┐
                                      │        Dual-Head Surveillance Pipeline       │
                                      │  ┌────────────────────┐ ┌──────────────────┐ │
                                      │  │ Deterministic Gate │ │ Isolation Forest │ │
                                      │  │ (Spoof/Layer/Wash) │ │ (Multivariate ML)│ │
                                      │  └─────────┬──────────┘ └─────────┬────────┘ │
                                      │            └──────────┬───────────┘          │
                                      │                       ▼                      │
                                      │            Ensemble Anomaly Scorer           │
                                      │       + SHAP Feature Attribution             │
                                      └──────────────────────┬───────────────────────┘
                                                             │
                                                             ▼
                                      ┌──────────────────────────────────────────────┐
                                      │        FastAPI Event Bus & WebSockets        │
                                      │      - Tick & L2 Depth Stream                │
                                      │      - Real-Time Alerts & Evidentiary Dossier│
                                      └──────────────────────┬───────────────────────┘
                                                             │
                                                             ▼
                                      ┌──────────────────────────────────────────────┐
                                      │      AegisWatch Institutional HUD Terminal   │
                                      │   - Live 10-level Bids/Asks Depth Heatmap    │
                                      │   - Time & Sales Tape                        │
                                      │   - Interactive Attack Injection Simulator   │
                                      │   - One-Click Regulatory Dossier Inspector   │
                                      └──────────────────────────────────────────────┘
```

---

## 🚀 Quickstart

### Prerequisites
- Python 3.10+
- Modern web browser (Chrome, Firefox, Safari, Edge)

### Installation
```bash
cd aegiswatch
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Running the Engine & Terminal HUD
```bash
python3 -m aegiswatch
```
Open your browser and navigate to: **`http://127.0.0.1:8000`**

---

## 🎯 Demo & Judging Walkthrough

AegisWatch includes a built-in **Live Market Simulator** with real-time **Abuse Injection Controls**:

1. **Normal Market Regime**: Watch realistic microsecond liquidity flow with top-10 bid/ask depth updates, steady Order Flow Imbalance (OFI), and low Cancel-to-Trade Ratios (CTR).
2. **Inject Spoofing Attack**: Triggers large non-bona-fide phantom buy orders at depth ($3\times$ average size), immediately followed by sub-50ms cancellations after an aggressive sell fills. Notice the **CRITICAL Spoofing Alert** trigger and the CTR spike.
3. **Inject Layering Attack**: Cascades multi-level fake orders on one side to manipulate price perception.
4. **Inject Quote Stuffing**: Inundates the book with 200+ rapid micro-orders within 100ms.
5. **Inject Wash Trading**: Crosses trades between identical participant accounts with zero net inventory change.
6. **Inspect Dossier**: Click on any alert card to open the **Evidentiary Forensic Dossier**, showing the exact reconstructed book snapshot, participant IDs, violated regulations (e.g. Dodd-Frank § 747), and percentage factor contributions.

---

## 🧪 Testing

Run the automated test suite:
```bash
pytest tests -v
```
