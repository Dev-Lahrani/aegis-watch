"""Base models and definitions for surveillance anomaly detectors and alerts."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AlertSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AbuseType(str, Enum):
    SPOOFING = "SPOOFING"
    LAYERING = "LAYERING"
    QUOTE_STUFFING = "QUOTE_STUFFING"
    WASH_TRADING = "WASH_TRADING"
    MOMENTUM_IGNITION = "MOMENTUM_IGNITION"
    ANOMALOUS_MICROSTRUCTURE = "ANOMALOUS_MICROSTRUCTURE"


REGULATORY_CITATIONS: Dict[AbuseType, List[str]] = {
    AbuseType.SPOOFING: [
        "Dodd-Frank Wall Street Reform Act § 747 (Prohibition of Spoofing)",
        "Commodity Exchange Act (CEA) Section 4c(a)(5)(C)",
        "FINRA Rule 5210 (Publication of Transactions and Quotations)",
        "SEC Rule 10b-5 (Employment of Manipulative and Deceptive Devices)",
    ],
    AbuseType.LAYERING: [
        "Dodd-Frank Act § 747",
        "FINRA Rule 5210 / Notice to Members 15-09",
        "Market Abuse Regulation (MAR) Article 12 (UK/EU)",
    ],
    AbuseType.QUOTE_STUFFING: [
        "SEC Rule 15c3-5 (Market Access Rule - Algorithmic Controls)",
        "NASDAQ Rule 4613 (Market Maker Obligations and Order Flow Throttle)",
    ],
    AbuseType.WASH_TRADING: [
        "Securities Exchange Act of 1934 Section 9(a)(1)",
        "Commodity Exchange Act Section 4c(a)(A)",
        "FINRA Rule 6140 (Other Trading Practices)",
    ],
    AbuseType.MOMENTUM_IGNITION: [
        "SEC Section 9(a)(2) (Inducing Purchase or Sale by False Appearance)",
        "FINRA Regulatory Notice 12-15",
    ],
    AbuseType.ANOMALOUS_MICROSTRUCTURE: [
        "FINRA Rule 3110 (Supervision and Surveillance Responsibilities)",
        "MiFID II RTS 25 (Order Record Keeping and Microstructure Anomaly Monitoring)",
    ],
}


@dataclass
class SurveillanceAlert:
    alert_id: str
    timestamp_us: float
    abuse_type: AbuseType
    severity: AlertSeverity
    confidence: float  # 0.0 to 1.0
    symbol: str
    description: str
    target_trader_id: Optional[str] = None
    affected_side: Optional[str] = None
    regulatory_rules: List[str] = field(default_factory=list)
    feature_attribution: Dict[str, float] = field(default_factory=dict)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "timestamp_us": self.timestamp_us,
            "timestamp_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(self.timestamp_us / 1_000_000)),
            "abuse_type": self.abuse_type.value,
            "severity": self.severity.value,
            "confidence": round(self.confidence, 4),
            "symbol": self.symbol,
            "description": self.description,
            "target_trader_id": self.target_trader_id,
            "affected_side": self.affected_side,
            "regulatory_rules": self.regulatory_rules,
            "feature_attribution": {k: round(v, 4) for k, v in self.feature_attribution.items()},
            "evidence": self.evidence,
        }
