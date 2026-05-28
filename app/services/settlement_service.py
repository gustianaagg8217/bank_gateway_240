import logging
from decimal import Decimal
from typing import List

from sqlalchemy.orm import Session

from app.models import SettlementAudit, SwiftMessage

logger = logging.getLogger("enterprise_gateway")


class SettlementService:
    def __init__(self, db: Session):
        self.db = db

    def generate_mt103(self, amount: Decimal, bic_sender: str, bic_receiver: str) -> SwiftMessage:
        record = SwiftMessage(
            trn=f"MT103-{amount}",
            uetr="UETR-ENTERPRISE",
            message_type="MT103",
            status="PROCESSING",
            bic_sender=bic_sender,
            bic_receiver=bic_receiver,
            amount=str(amount.quantize(Decimal("0.01"))),
            currency="USD",
            xml_payload="<MT103>Simulated</MT103>",
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        logger.info("Generated MT103 simulation for %s", record.trn)
        self.db.add(SettlementAudit(trn=record.trn, event_type="MT103_GENERATED", status="PROCESSING", details="MT103 simulation created", metadata_json="{}"))
        self.db.commit()
        return record

    def audit_log(self) -> List[SettlementAudit]:
        return self.db.query(SettlementAudit).order_by(SettlementAudit.created_at.desc()).limit(50).all()
