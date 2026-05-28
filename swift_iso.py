import re
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, Optional, Tuple
from uuid import uuid4

from db import (
    approve_swift_message,
    cancel_swift_message,
    create_swift_message,
    export_swift_xml,
    get_connection,
    get_swift_message,
    list_swift_messages,
    process_swift_settlement_queue,
    reverse_swift_message,
    retry_failed_swift_settlement_queue,
)


class SwiftValidationError(Exception):
    pass


class ISOMessageType(str, Enum):
    PACS_008 = "pacs.008"
    PACS_002 = "pacs.002"
    CAMT_056 = "camt.056"


class SwiftMessageStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    HOLD = "HOLD"
    REVERSED = "REVERSED"


BIC_PATTERN = re.compile(r"^[A-Z]{4}[A-Z]{2}[A-Z2-9][A-NP-Z0-9]([A-Z0-9]{3})?$")


def _now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


class SwiftXMLValidator:
    @classmethod
    def validate(cls, xml_payload: str, expected_type: ISOMessageType) -> bool:
        try:
            root = ET.fromstring(xml_payload)
        except ET.ParseError as exc:
            raise SwiftValidationError(f"XML parse error: {exc}")

        if root.tag != "Document":
            raise SwiftValidationError("Root element must be Document")

        if expected_type == ISOMessageType.PACS_008 and root.find("FIToFICstmrCdtTrf") is None:
            raise SwiftValidationError("Missing FIToFICstmrCdtTrf element for pacs.008")
        if expected_type == ISOMessageType.PACS_002 and root.find("FIToFIPmtStsRpt") is None:
            raise SwiftValidationError("Missing FIToFIPmtStsRpt element for pacs.002")
        if expected_type == ISOMessageType.CAMT_056 and root.find("camt.056.001.02") is None:
            raise SwiftValidationError("Missing camt.056.001.02 element for camt.056")
        return True


class ISO20022MessageFactory:
    @staticmethod
    def build_group_header(uetr: str, amount: Decimal, currency: str, debtor: str, creditor: str) -> ET.Element:
        grp = ET.Element("GrpHdr")
        ET.SubElement(grp, "MsgId").text = uetr
        ET.SubElement(grp, "CreDtTm").text = _now()
        ET.SubElement(grp, "NbOfTxs").text = "1"
        ET.SubElement(grp, "CtrlSum").text = str(amount.quantize(Decimal("0.01")))
        instg_agt = ET.SubElement(grp, "InstgAgt")
        ET.SubElement(instg_agt, "BICFI").text = "SIMULATEDXXX"
        instd_agt = ET.SubElement(grp, "InstdAgt")
        ET.SubElement(instd_agt, "BICFI").text = "RECEIVERXXX"
        return grp

    @staticmethod
    def generate_pacs_008(
        uetr: str,
        bic_sender: str,
        bic_receiver: str,
        amount: Decimal,
        currency: str,
        debtor_name: str,
        creditor_name: str,
        instruction_info: Optional[str] = None,
        settlement_reference: Optional[str] = None,
    ) -> str:
        root = ET.Element("Document")
        doc = ET.SubElement(root, "FIToFICstmrCdtTrf")
        grp = ISO20022MessageFactory.build_group_header(uetr, amount, currency, debtor_name, creditor_name)
        doc.append(grp)

        cdt_trf = ET.SubElement(doc, "CdtTrfTxInf")
        pmt_id = ET.SubElement(cdt_trf, "PmtId")
        ET.SubElement(pmt_id, "InstrId").text = uetr
        ET.SubElement(pmt_id, "EndToEndId").text = uetr
        ET.SubElement(pmt_id, "TxId").text = settlement_reference or f"SETTLE-{uuid4().hex[:12].upper()}"

        amt = ET.SubElement(cdt_trf, "Amt")
        instd_amt = ET.SubElement(amt, "InstdAmt", Ccy=currency)
        instd_amt.text = str(amount.quantize(Decimal("0.01")))

        cdtr_agt = ET.SubElement(cdt_trf, "CdtrAgt")
        instd_agt = ET.SubElement(cdtr_agt, "FinInstnId")
        ET.SubElement(instd_agt, "BICFI").text = bic_receiver

        cdtr = ET.SubElement(cdt_trf, "Cdtr")
        ET.SubElement(cdtr, "Nm").text = creditor_name

        dbtr_agt = ET.SubElement(cdt_trf, "DbtrAgt")
        dbtr_inst = ET.SubElement(dbtr_agt, "FinInstnId")
        ET.SubElement(dbtr_inst, "BICFI").text = bic_sender

        dbtr = ET.SubElement(cdt_trf, "Dbtr")
        ET.SubElement(dbtr, "Nm").text = debtor_name

        if instruction_info:
            ET.SubElement(cdt_trf, "Purp").text = instruction_info

        ET.SubElement(doc, "InstrForCdtrAgt").text = instruction_info or "SWIFT TRANSFER"
        return ET.tostring(root, encoding="unicode")

    @staticmethod
    def generate_pacs_002(trn: str, uetr: str, original_status: str, reason: str) -> str:
        root = ET.Element("Document")
        rpt = ET.SubElement(root, "FIToFIPmtStsRpt")
        grp = ISO20022MessageFactory.build_group_header(uetr, Decimal("0.00"), "USD", "SYSTEM", "SYSTEM")
        rpt.append(grp)
        tx_inf = ET.SubElement(rpt, "TxInfAndSts")
        ET.SubElement(tx_inf, "OrgnlInstrId").text = trn
        sts = ET.SubElement(tx_inf, "TxSts").text = original_status
        ET.SubElement(tx_inf, "StsRsnInf").text = reason
        return ET.tostring(root, encoding="unicode")

    @staticmethod
    def generate_camt_056(trn: str, uetr: str, message: str) -> str:
        root = ET.Element("Document")
        adv = ET.SubElement(root, "camt.056.001.02")
        ET.SubElement(adv, "Id").text = trn
        refs = ET.SubElement(adv, "Refs")
        ET.SubElement(refs, "UETR").text = uetr
        ET.SubElement(adv, "Msg").text = message
        ET.SubElement(adv, "CreDtTm").text = _now()
        return ET.tostring(root, encoding="unicode")


class SwiftService:
    def __init__(self):
        self.bic_pattern = BIC_PATTERN

    def validate_bic(self, bic: str) -> str:
        if not bic or not self.bic_pattern.match(bic.strip().upper()):
            raise SwiftValidationError(f"BIC tidak valid: {bic}")
        return bic.strip().upper()

    def validate_currency(self, currency: str) -> str:
        code = currency.strip().upper()
        if len(code) != 3:
            raise SwiftValidationError(f"Currency code tidak valid: {code}")
        return code

    def generate_settlement_reference(self) -> str:
        return f"SET-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8].upper()}"

    def compliance_check(self, bic_sender: str, bic_receiver: str, amount: Decimal) -> bool:
        self.validate_bic(bic_sender)
        self.validate_bic(bic_receiver)
        if amount <= Decimal("0"):
            raise SwiftValidationError("Jumlah harus lebih besar dari nol.")
        if amount > Decimal("500000000"):
            raise SwiftValidationError("Transfer internasional melebihi batas compliance simulasi.")
        return True

    def create_swift_payment(
        self,
        bic_sender: str,
        bic_receiver: str,
        amount: Decimal,
        currency: str,
        debtor_name: str,
        creditor_name: str,
        instruction_info: Optional[str] = None,
    ) -> Tuple[str, str]:
        bic_sender = self.validate_bic(bic_sender)
        bic_receiver = self.validate_bic(bic_receiver)
        currency = self.validate_currency(currency)
        self.compliance_check(bic_sender, bic_receiver, amount)

        uetr = str(uuid4())
        settlement_reference = self.generate_settlement_reference()
        xml_payload = ISO20022MessageFactory.generate_pacs_008(
            uetr=uetr,
            bic_sender=bic_sender,
            bic_receiver=bic_receiver,
            amount=amount,
            currency=currency,
            debtor_name=debtor_name,
            creditor_name=creditor_name,
            instruction_info=instruction_info,
            settlement_reference=settlement_reference,
        )
        swift_id = create_swift_message(
            message_type=ISOMessageType.PACS_008.value,
            bic_sender=bic_sender,
            bic_receiver=bic_receiver,
            amount=amount,
            currency=currency,
            debtor_name=debtor_name,
            creditor_name=creditor_name,
            instruction_info=instruction_info,
            xml_payload=xml_payload,
            settlement_reference=settlement_reference,
            requires_approval=amount > Decimal("50000"),
        )
        message = get_swift_message_by_id(swift_id)
        return message["trn"], message["uetr"]

    def validate_swift_message(self, trn: str) -> bool:
        message = get_swift_message(trn)
        if message is None:
            raise SwiftValidationError("SWIFT message tidak ditemukan.")
        if message["xml_payload"] is None:
            raise SwiftValidationError("SWIFT message tidak memiliki payload XML.")
        return SwiftXMLValidator.validate(message["xml_payload"], ISOMessageType(message["message_type"]))

    def generate_status_report(self, trn: str, reason: str) -> str:
        message = get_swift_message(trn)
        if message is None:
            raise SwiftValidationError("SWIFT message tidak ditemukan.")
        return ISO20022MessageFactory.generate_pacs_002(
            trn=trn,
            uetr=message["uetr"],
            original_status=message["status"],
            reason=reason,
        )

    def generate_advice_message(self, trn: str, message_text: str) -> str:
        message = get_swift_message(trn)
        if message is None:
            raise SwiftValidationError("SWIFT message tidak ditemukan.")
        return ISO20022MessageFactory.generate_camt_056(
            trn=trn,
            uetr=message["uetr"],
            message=message_text,
        )

    def process_settlement_queue(self, limit: int = 10) -> int:
        return process_swift_settlement_queue(limit)

    def retry_failed_settlements(self, max_retries: int = 3) -> int:
        return retry_failed_swift_settlement_queue(max_retries)

    def export_to_file(self, trn: str, file_path: str) -> str:
        return export_swift_xml(trn, file_path)

    def approve(self, trn: str, approve: bool = True) -> bool:
        return approve_swift_message(trn, approve)

    def cancel(self, trn: str) -> bool:
        return cancel_swift_message(trn)

    def reverse(self, trn: str) -> bool:
        return reverse_swift_message(trn)

    def list_messages(self, status: str = None):
        return list_swift_messages(status)


def get_swift_message_by_id(swift_id: int):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM swift_messages WHERE id = ?", (swift_id,)).fetchone()
