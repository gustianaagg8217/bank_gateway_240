from decimal import Decimal
from typing import Dict, List
from datetime import datetime


class RoutingService:
    def simulate_route(self, sender_bic: str, receiver_bic: str, amount: Decimal) -> Dict[str, object]:
        hops = [sender_bic[:4], sender_bic[4:6], receiver_bic[:4], receiver_bic[4:6]]
        eta_hours = max(1, int(Decimal(str(amount)) / Decimal("50000")))
        return {
            "route_status": "ROUTED",
            "intermediary_hops": hops,
            "correspondent_banks": ["SIM-CORE", "SIM-CORR", "SIM-END"],
            "settlement_eta_hours": eta_hours,
            "simulated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
