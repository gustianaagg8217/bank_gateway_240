from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class UETRCreateRequest(BaseModel):
    amount: Decimal
    currency: str = "USD"
    sender_bic: str
    receiver_bic: str
    debtor_name: str
    creditor_name: str


class UETRResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uetr: str
    trn: str
    status: str
    stage: str
    amount: str
    currency: str
    sender_bic: str
    receiver_bic: str
    settlement_eta: Optional[str]
    routing_path: str
    tracking_history: str


class SettlementAuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trn: str
    event_type: str
    status: str
    details: Optional[str]
    metadata_json: str


class DashboardSummary(BaseModel):
    total_uetr: int
    pending_uetr: int
    success_uetr: int
    failed_uetr: int
