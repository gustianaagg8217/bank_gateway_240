from decimal import Decimal
from datetime import datetime
from xml.etree import ElementTree as ET
from typing import Dict


class ISO20022Service:
    def generate_pacs008(self, uetr: str, amount: Decimal, currency: str, sender_bic: str, receiver_bic: str) -> str:
        amount_value = Decimal(str(amount)).quantize(Decimal("0.01"))
        root = ET.Element("Document")
        cdt = ET.SubElement(root, "CdtTrfTxInf")
        ET.SubElement(cdt, "UETR").text = uetr
        ET.SubElement(cdt, "Amount").text = str(amount_value)
        ET.SubElement(cdt, "Currency").text = currency
        ET.SubElement(cdt, "DebtorBIC").text = sender_bic
        ET.SubElement(cdt, "CreditorBIC").text = receiver_bic
        ET.SubElement(cdt, "CreDtTm").text = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        return ET.tostring(root, encoding="unicode")
