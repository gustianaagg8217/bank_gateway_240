from decimal import Decimal
from typing import Dict


class FraudService:
    def analyze(self, amount: Decimal, sender_bic: str, receiver_bic: str) -> Dict[str, object]:
        score = min(100, int(Decimal(str(amount)) / Decimal("1000")) + (15 if sender_bic == receiver_bic else 0))
        return {
            "fraud_score": score,
            "decision": "ALLOW" if score < 60 else "REVIEW",
            "reason": "Amount and route pattern analyzed",
        }
