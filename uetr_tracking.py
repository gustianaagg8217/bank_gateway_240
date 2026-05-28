import json
import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, getcontext
from typing import Any, Dict, List, Optional
from uuid import uuid4

from db import (
    create_uetr_tracking,
    export_uetr_report as db_export_report,
    export_uetr_xml as db_export_xml,
    get_uetr_tracking,
    list_uetr_tracking,
    search_uetr_tracking,
    update_uetr_tracking_status,
)

getcontext().prec = 28

logger = logging.getLogger("UETRDashboard")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


class UETRValidationError(Exception):
    pass


@dataclass
class TrackingEvent:
    stage: str
    status: str
    message: str
    timestamp: str
    eta: Optional[str] = None


class UETRService:
    def __init__(self):
        self.logger = logger

    def create(self, amount: Decimal, currency: str, sender_bic: str, receiver_bic: str,
               debtor_name: str, creditor_name: str, trn: Optional[str] = None) -> Dict[str, Any]:
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        if amount <= 0:
            raise UETRValidationError("Amount must be greater than zero.")
        uetr = str(uuid4())
        tracking_id = create_uetr_tracking(
            uetr=uetr,
            trn=trn or f"TRN-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8].upper()}",
            amount=amount,
            currency=currency.strip().upper(),
            sender_bic=sender_bic.strip().upper(),
            receiver_bic=receiver_bic.strip().upper(),
            debtor_name=debtor_name.strip(),
            creditor_name=creditor_name.strip(),
        )
        self.logger.info("UETR created", extra={"uetr": uetr, "tracking_id": tracking_id})
        return get_uetr_tracking(uetr)

    def search(self, query: str) -> List[Dict[str, Any]]:
        return search_uetr_tracking(query)

    def list(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        return list_uetr_tracking(status)

    def export_xml(self, uetr: str, file_path: str) -> str:
        return db_export_xml(uetr, file_path)

    def export_report(self, uetr: str, file_path: str) -> str:
        return db_export_report(uetr, file_path)


class TrackingService:
    def __init__(self):
        self.logger = logger

    def update_stage(self, uetr: str, stage: str, status: str, message: str, eta_hours: int = 0) -> Dict[str, Any]:
        eta = None
        if eta_hours:
            eta = (datetime.utcnow() + timedelta(hours=eta_hours)).replace(microsecond=0).isoformat() + "Z"
        updated = update_uetr_tracking_status(uetr, status=status, stage=stage, eta=eta, message=message)
        self.logger.info("UETR stage updated", extra={"uetr": uetr, "stage": stage, "status": status})
        return updated

    def view_history(self, uetr: str) -> List[Dict[str, Any]]:
        record = get_uetr_tracking(uetr)
        history = json.loads(record["tracking_history"] or "[]") if record else []
        return history

    def progress_visual(self, uetr: str) -> str:
        record = get_uetr_tracking(uetr)
        if record is None:
            raise UETRValidationError("UETR not found.")
        stages = ["INITIATED", "ROUTED", "SETTLED", "CONFIRMED", "RELEASED"]
        current_index = stages.index(record["stage"]) if record["stage"] in stages else 0
        bar = "#" * (current_index + 1) + "-" * (len(stages) - current_index - 1)
        return f"[{bar}] {record['status']} (ETA: {record['settlement_eta'] or 'TBD'})"


class RoutingService:
    def __init__(self):
        self.logger = logger

    def simulate_routing(self, sender_bic: str, receiver_bic: str, amount: Decimal) -> Dict[str, Any]:
        hops = [sender_bic[:4], sender_bic[4:6], receiver_bic[:4]]
        eta_hours = max(1, int(Decimal(str(amount)) / Decimal("50000")))
        return {
            "correspondent_banks": ["SIM-CORE", "SIM-CORR", "SIM-END"],
            "intermediary_hops": hops,
            "settlement_eta_hours": eta_hours,
            "route_status": "ROUTED",
            "simulated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }

    def settlement_eta(self, amount: Decimal) -> int:
        return max(1, int(Decimal(str(amount)) / Decimal("100000")))


def build_uetr_xml(record: Dict[str, Any]) -> str:
    root = ET.Element("UETRTracking")
    ET.SubElement(root, "UETR").text = record["uetr"]
    ET.SubElement(root, "TRN").text = record["trn"]
    ET.SubElement(root, "Status").text = record["status"]
    ET.SubElement(root, "Stage").text = record["stage"]
    ET.SubElement(root, "Currency").text = record["currency"]
    ET.SubElement(root, "Amount").text = str(record["amount"])
    ET.SubElement(root, "SenderBIC").text = record["sender_bic"]
    ET.SubElement(root, "ReceiverBIC").text = record["receiver_bic"]
    ET.SubElement(root, "SettlementETA").text = record["settlement_eta"] or ""
    ET.SubElement(root, "History").text = record["tracking_history"] or "[]"
    return ET.tostring(root, encoding="unicode")
