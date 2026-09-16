"""Evidentiary Regulatory Audit Dossier Generator.

Produces SEC, FINRA, and NASDAQ-grade formal compliance packets with order book depth
reconstruction, chronological audit trails, and quantitative factor attribution.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from aegiswatch.core.order_book import LimitOrderBook
from aegiswatch.detectors.base import AbuseType, SurveillanceAlert


class RegulatoryDossierGenerator:
    """Compiles formal forensic audit packets for financial regulatory enforcement."""

    @staticmethod
    def generate_dossier(alert: SurveillanceAlert, book: LimitOrderBook) -> Dict[str, Any]:
        timestamp_iso = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(alert.timestamp_us / 1_000_000))
        dossier_id = f"DOSSIER-{alert.alert_id}-{int(alert.timestamp_us / 1_000_000)}"

        # Reconstructed book snapshot
        depth = book.get_l2_depth(levels=8)

        # Recent chronological audit messages related to this event
        recent_orders = [
            {
                "order_id": o.order_id,
                "trader_id": o.trader_id,
                "side": o.side.value,
                "price": o.price,
                "quantity": o.quantity,
                "status": o.status.value,
                "lifetime_ms": round(o.lifetime_ms, 2) if o.lifetime_ms is not None else None,
                "timestamp_iso": time.strftime("%H:%M:%S.%f", time.gmtime(o.timestamp_us / 1_000_000))[:-3],
            }
            for o in list(book.order_history)[-15:]
        ]

        recent_trades = [
            {
                "trade_id": t.trade_id,
                "price": t.price,
                "quantity": t.quantity,
                "buyer_id": t.buyer_id,
                "seller_id": t.seller_id,
                "aggressor_side": t.aggressor_side.value,
                "timestamp_iso": time.strftime("%H:%M:%S.%f", time.gmtime(t.timestamp_us / 1_000_000))[:-3],
            }
            for t in list(book.trade_history)[-10:]
        ]

        # Recommended regulatory enforcement action
        recommended_action = RegulatoryDossierGenerator._get_recommended_action(alert.abuse_type, alert.severity.value)

        return {
            "dossier_id": dossier_id,
            "case_number": f"SEC/FINRA-ENF-{alert.alert_id}",
            "generated_at": timestamp_iso,
            "jurisdiction": "United States Securities & Exchange Commission (SEC) / FINRA Market Surveillance",
            "exchange_venue": f"NASDAQ Exchange ({book.symbol} Matching Engine)",
            "alert_summary": {
                "alert_id": alert.alert_id,
                "abuse_type": alert.abuse_type.value,
                "severity": alert.severity.value,
                "confidence_score": f"{alert.confidence * 100:.1f}%",
                "target_participant": alert.target_trader_id or "UNKNOWN_ENTITY",
                "affected_side": alert.affected_side or "BOTH",
                "description": alert.description,
            },
            "statutory_violations": alert.regulatory_rules,
            "forensic_attribution": {
                factor: f"{pct * 100:.1f}%" for factor, pct in alert.feature_attribution.items()
            },
            "evidentiary_data": {
                "metric_evidence": alert.evidence,
                "reconstructed_lob_depth": depth,
                "chronological_order_trail": recent_orders,
                "correlated_executions": recent_trades,
            },
            "enforcement_recommendation": recommended_action,
        }

    @staticmethod
    def _get_recommended_action(abuse_type: AbuseType, severity: str) -> Dict[str, Any]:
        if abuse_type == AbuseType.SPOOFING:
            return {
                "tier": "TIER-1 IMMEDIATE DISCIPLINARY REFERRAL",
                "action": "Issue Formal Request for Information (RFI) under FINRA Rule 8210. Institute temporary algorithmic gateway throttling under SEC Rule 15c3-5.",
                "statutory_remedy": "Civil monetary penalties, disgorgement of illicit trading profits, and suspension of direct market access (DMA).",
            }
        elif abuse_type == AbuseType.WASH_TRADING:
            return {
                "tier": "TIER-1 STATUTORY FRAUD INVESTIGATION",
                "action": "Immediate freeze of trading privileges for target account. Freeze clearing account settlement for affected trade IDs.",
                "statutory_remedy": "Referral to SEC Division of Enforcement for manipulation under Section 9(a)(1) of the Securities Exchange Act of 1934.",
            }
        elif abuse_type == AbuseType.QUOTE_STUFFING:
            return {
                "tier": "TIER-2 INFRASTRUCTURE ABUSE SANCTION",
                "action": "Impose NASDAQ excessive messaging ratio surcharges. Throttle participant FIX session gateway band.",
                "statutory_remedy": "Mandatory technical review of algorithmic trading logic under SEC Rule 15c3-5.",
            }
        elif abuse_type == AbuseType.LAYERING:
            return {
                "tier": "TIER-1 ORDER BOOK MANIPULATION REFERRAL",
                "action": "Demand order-audit-trail-system (OATS/CAT) full execution logs. Conduct forensic cross-broker account linkage.",
                "statutory_remedy": "Enforcement proceedings under FINRA Notice to Members 15-09.",
            }
        else:
            return {
                "tier": "TIER-3 SURVEILLANCE INQUIRY",
                "action": "Flag participant trading profile for enhanced 30-day algorithmic surveillance monitoring.",
                "statutory_remedy": "Internal compliance review request.",
            }
