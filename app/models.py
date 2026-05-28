import json
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class UETRTracking(Base):
    __tablename__ = "uetr_tracking"

    id = Column(Integer, primary_key=True, index=True)
    uetr = Column(String(64), unique=True, nullable=False, index=True)
    trn = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(32), default="PENDING", nullable=False)
    stage = Column(String(32), default="INITIATED", nullable=False)
    amount = Column(String(32), default="0", nullable=False)
    currency = Column(String(8), default="USD", nullable=False)
    sender_bic = Column(String(32), nullable=False)
    receiver_bic = Column(String(32), nullable=False)
    settlement_eta = Column(String(64), nullable=True)
    routing_path = Column(Text, default="[]")
    tracking_history = Column(Text, default="[]")
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    failed_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)


class SettlementAudit(Base):
    __tablename__ = "settlement_audit"

    id = Column(Integer, primary_key=True, index=True)
    trn = Column(String(64), nullable=False, index=True)
    event_type = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    details = Column(Text, nullable=True)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=func.now(), nullable=False)


class SwiftMessage(Base):
    __tablename__ = "swift_messages"

    id = Column(Integer, primary_key=True, index=True)
    trn = Column(String(64), unique=True, nullable=False)
    uetr = Column(String(64), unique=True, nullable=False)
    message_type = Column(String(32), nullable=False)
    status = Column(String(32), default="PENDING", nullable=False)
    bic_sender = Column(String(32), nullable=False)
    bic_receiver = Column(String(32), nullable=False)
    amount = Column(String(32), default="0", nullable=False)
    currency = Column(String(8), default="USD", nullable=False)
    xml_payload = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
