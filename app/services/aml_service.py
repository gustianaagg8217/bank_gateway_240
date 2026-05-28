import logging
from decimal import Decimal
from typing import Dict

logger = logging.getLogger("enterprise_gateway.aml")


class AMLService:
    def score(self, amount: Decimal, sender_bic: str, receiver_bic: str) -> Dict[str, object]:
        amount_value = Decimal(str(amount))
        score = min(100, int(amount_value / Decimal("1000")) + (10 if sender_bic.startswith("BMR") else 0))
        return {
            "risk_score": score,
            "risk_level": "HIGH" if score >= 70 else "MEDIUM" if score >= 30 else "LOW",
            "sanctions_check": True,
            "aml_status": "PASSED" if score < 80 else "REVIEW",
        }
