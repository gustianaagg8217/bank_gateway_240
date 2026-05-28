import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import SettlementAudit, UETRTracking

logger = logging.getLogger("enterprise_gateway")


class UETRService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, amount: Decimal, currency: str, sender_bic: str, receiver_bic: str,
               debtor_name: str, creditor_name: str) -> UETRTracking:
        uetr = str(uuid4())
        trn = f"TRN-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8].upper()}"
        record = UETRTracking(
            uetr=uetr,
            trn=trn,
            status="PENDING",
            stage="INITIATED",
            amount=str(amount.quantize(Decimal("0.01"))),
            currency=currency.strip().upper(),
            sender_bic=sender_bic.strip().upper(),
            receiver_bic=receiver_bic.strip().upper(),
            settlement_eta=None,
            routing_path=json.dumps([sender_bic.strip().upper(), receiver_bic.strip().upper()]),
            tracking_history=json.dumps([{"stage": "INITIATED", "status": "PENDING", "message": "Record created", "timestamp": datetime.utcnow().isoformat()}]),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        logger.info("Created UETR %s", uetr)
        self._audit(trn, "UETR_CREATED", "PENDING", f"Created UETR {uetr}")
        return record

    def list(self) -> List[UETRTracking]:
        return self.db.query(UETRTracking).order_by(UETRTracking.created_at.desc()).all()

    def get(self, uetr: str) -> UETRTracking:
        return self.db.query(UETRTracking).filter(UETRTracking.uetr == uetr).first()

    def update_status(self, uetr: str, status: str, stage: str, message: str) -> UETRTracking:
        record = self.get(uetr)
        if not record:
            raise ValueError("UETR not found")
        record.status = status
        record.stage = stage
        record.settlement_eta = (datetime.utcnow() + timedelta(hours=2)).isoformat() + "Z"
        history = json.loads(record.tracking_history or "[]")
        history.append({"stage": stage, "status": status, "message": message, "timestamp": datetime.utcnow().isoformat()})
        record.tracking_history = json.dumps(history)
        self.db.commit()
        self.db.refresh(record)
        self._audit(record.trn, "UETR_STATUS_UPDATED", status, message)
        return record

    def _audit(self, trn: str, event_type: str, status: str, details: str) -> None:
        self.db.add(SettlementAudit(trn=trn, event_type=event_type, status=status, details=details, metadata_json=json.dumps({"timestamp": datetime.utcnow().isoformat()})))
        self.db.commit()
