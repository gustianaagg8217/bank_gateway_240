import os
import sys
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, getcontext
from enum import Enum
from typing import Dict, Optional, Tuple
from uuid import uuid4

from db import (
    create_account,
    create_merchant,
    create_escrow_transaction,
    create_visa_transaction,
    create_transaction_log,
    create_settlement_report,
    create_external_transfer,
    generate_settlement_xml,
    get_account,
    get_account_by_name,
    get_merchant,
    init_db,
    list_accounts,
    list_merchants,
    list_pending_authorizations,
    approve_merchant,
    admin_approve_transaction,
    process_quantum_queue,
    release_escrow,
    enqueue_quantum_task,
    change_balance,
    validate_merchant_api_key,
    verify_hmac_signature,
)
from swift_iso import SwiftService
from uetr_tracking import RoutingService, TrackingService, UETRService

getcontext().prec = 28

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("BankGateway")

SUPPORTED_CURRENCIES: Dict[str, Decimal] = {
    "USD": Decimal("1.00"),
    "EUR": Decimal("1.10"),
    "GBP": Decimal("1.25"),
    "JPY": Decimal("0.0075"),
    "IDR": Decimal("0.000065"),
}

FEE_PERCENTAGE = Decimal("0.015")
FEE_FIXED = Decimal("1.00")

RECEIPT_TEMPLATE = """
========================
Receipt ID : {receipt_id}
Reference  : {reference}
Type       : {transaction_type}
Status     : {status}
Amount     : {amount} {currency}
Fee        : {fee} {currency}
Total      : {total} {currency}
Date       : {timestamp}
UETR       : {uetr}
Details    : {details}
========================
"""


class ProcessingState(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    HOLD = "HOLD"
    REVERSED = "REVERSED"


@dataclass
class TransactionReceipt:
    receipt_id: str
    reference: str
    transaction_type: str
    status: str
    amount: Decimal
    fee: Decimal
    total: Decimal
    currency: str
    timestamp: str
    details: str
    uetr: str = ""

    def render(self) -> str:
        return RECEIPT_TEMPLATE.format(
            receipt_id=self.receipt_id,
            reference=self.reference,
            transaction_type=self.transaction_type,
            status=self.status,
            amount=f"{self.amount:.2f}",
            fee=f"{self.fee:.2f}",
            total=f"{self.total:.2f}",
            currency=self.currency,
            timestamp=self.timestamp,
            uetr=self.uetr or "-",
            details=self.details,
        )


class ValidationError(Exception):
    pass


class UserCancel(Exception):
    pass


class AccountService:
    def __init__(self):
        self.exchange_rates = SUPPORTED_CURRENCIES

    def validate_currency(self, currency: str) -> str:
        code = currency.strip().upper()
        if code not in self.exchange_rates:
            raise ValidationError(f"Mata uang tidak valid: {code}")
        return code

    def convert_amount(self, amount: Decimal, source_currency: str, target_currency: str) -> Decimal:
        source = self.validate_currency(source_currency)
        target = self.validate_currency(target_currency)
        usd_value = amount * self.exchange_rates[source]
        converted = usd_value / self.exchange_rates[target]
        return converted.quantize(Decimal("0.01"))

    def calculate_fee(self, amount: Decimal) -> Decimal:
        fee = (amount * FEE_PERCENTAGE) + FEE_FIXED
        return fee.quantize(Decimal("0.01"))

    def create_account(self, name: str, currency: str, initial_deposit: Decimal) -> int:
        currency_code = self.validate_currency(currency)
        account_id = create_account(name, initial_deposit, currency_code)
        logger.info("Created account %s in %s", account_id, currency_code)
        return account_id

    def deposit(self, account_id: int, amount: Decimal, currency: str) -> TransactionReceipt:
        currency_code = self.validate_currency(currency)
        account = get_account(account_id)
        if account is None:
            raise ValidationError("Akun tidak ditemukan.")

        currency_account = account["currency"].strip().upper()
        if currency_account != currency_code:
            amount = self.convert_amount(amount, currency_code, currency_account)

        fee = self.calculate_fee(amount)
        total_credit = amount - fee
        if total_credit <= Decimal("0"):
            raise ValidationError("Jumlah deposit setelah biaya harus lebih besar daripada 0.")

        new_balance = change_balance(account_id, total_credit, event_type="deposit", details="Deposit bank")
        create_transaction_log(
            event_type="deposit",
            amount=total_credit,
            currency=currency_account,
            status=ProcessingState.SUCCESS.value,
            details=f"Deposit dari {currency_code}",
            account_id=account_id,
            reference=str(uuid4()),
        )

        receipt = self._build_receipt(
            transaction_type="Deposit",
            reference=str(uuid4()),
            status=ProcessingState.SUCCESS.value,
            amount=amount,
            fee=fee,
            total=total_credit,
            currency=currency_account,
            details=f"Setor ke akun {account_id}",
        )
        return receipt

    def withdraw(self, account_id: int, amount: Decimal) -> TransactionReceipt:
        account = get_account(account_id)
        if account is None:
            raise ValidationError("Akun tidak ditemukan.")

        currency = account["currency"].strip().upper()
        fee = self.calculate_fee(amount)
        total_debit = amount + fee
        current_balance = Decimal(account["balance"])
        if current_balance < total_debit:
            raise ValidationError("Saldo tidak cukup untuk penarikan ini.")

        new_balance = change_balance(account_id, -total_debit, event_type="withdrawal", details="Penarikan tunai")
        create_transaction_log(
            event_type="withdrawal",
            amount=amount,
            currency=currency,
            status=ProcessingState.SUCCESS.value,
            details="Tarik tunai dengan biaya",
            account_id=account_id,
            reference=str(uuid4()),
        )

        receipt = self._build_receipt(
            transaction_type="Withdrawal",
            reference=str(uuid4()),
            status=ProcessingState.SUCCESS.value,
            amount=amount,
            fee=fee,
            total=total_debit,
            currency=currency,
            details=f"Tarik dari akun {account_id}",
        )
        return receipt

    def transfer(self, from_account_id: int, to_account_id: int, amount: Decimal, currency: str) -> TransactionReceipt:
        if from_account_id == to_account_id:
            raise ValidationError("Akun pengirim dan penerima harus berbeda.")

        from_account = get_account(from_account_id)
        to_account = get_account(to_account_id)
        if from_account is None or to_account is None:
            raise ValidationError("Salah satu akun tidak ditemukan.")

        from_currency = from_account["currency"].strip().upper()
        to_currency = to_account["currency"].strip().upper()
        amount_in_from_currency = amount
        if currency.strip().upper() != from_currency:
            amount_in_from_currency = self.convert_amount(amount, currency, from_currency)

        fee = self.calculate_fee(amount_in_from_currency)
        total_debit = amount_in_from_currency + fee
        if Decimal(from_account["balance"]) < total_debit:
            raise ValidationError("Saldo pengirim tidak cukup untuk transfer ini.")

        if from_currency != to_currency:
            amount_in_to_currency = self.convert_amount(amount_in_from_currency, from_currency, to_currency)
        else:
            amount_in_to_currency = amount_in_from_currency

        uetr = str(uuid4())
        change_balance(from_account_id, -total_debit, event_type="transfer_out", details=f"Transfer ke akun {to_account_id} UETR={uetr}", reference=str(uuid4()))
        change_balance(to_account_id, amount_in_to_currency, event_type="transfer_in", details=f"Transfer dari akun {from_account_id} UETR={uetr}", reference=str(uuid4()))

        create_transaction_log(
            event_type="transfer",
            amount=amount_in_from_currency,
            currency=from_currency,
            status=ProcessingState.SUCCESS.value,
            details=f"Transfer dari {from_account_id} ke {to_account_id} UETR={uetr}",
            account_id=from_account_id,
            reference=str(uuid4()),
        )

        receipt = self._build_receipt(
            transaction_type="Transfer",
            reference=str(uuid4()),
            status=ProcessingState.SUCCESS.value,
            amount=amount,
            fee=fee,
            total=total_debit,
            currency=from_currency,
            details=f"Transfer ke akun {to_account_id}",
            uetr=uetr,
        )
        return receipt

    def _build_receipt(
        self,
        transaction_type: str,
        reference: str,
        status: str,
        amount: Decimal,
        fee: Decimal,
        total: Decimal,
        currency: str,
        details: str,
        uetr: str = "",
    ) -> TransactionReceipt:
        return TransactionReceipt(
            receipt_id=str(uuid4()),
            reference=reference,
            transaction_type=transaction_type,
            status=status,
            amount=amount.quantize(Decimal("0.01")),
            fee=fee.quantize(Decimal("0.01")),
            total=total.quantize(Decimal("0.01")),
            currency=currency.strip().upper(),
            timestamp=datetime.now().isoformat(sep=" ", timespec="seconds"),
            details=details,
            uetr=uetr,
        )


class EscrowService:
    def __init__(self, account_service: AccountService):
        self.account_service = account_service

    def hold(self, account_id: int, amount: Decimal, reference: str) -> Tuple[str, TransactionReceipt]:
        account = get_account(account_id)
        if account is None:
            raise ValidationError("Akun tidak ditemukan untuk escrow.")

        currency = account["currency"].strip().upper()
        fee = self.account_service.calculate_fee(amount)
        total_hold = amount + fee
        if Decimal(account["balance"]) < total_hold:
            raise ValidationError("Saldo tidak cukup untuk hold escrow.")

        escrow_id = create_escrow_transaction(account_id, reference, amount, "debit")
        change_balance(account_id, -total_hold, event_type="escrow_hold", details=f"Hold escrow {reference}", reference=str(uuid4()))
        logger.info("Escrow hold created %s", escrow_id)

        receipt = self.account_service._build_receipt(
            transaction_type="Escrow Hold",
            reference=reference,
            status=ProcessingState.PENDING.value,
            amount=amount,
            fee=fee,
            total=total_hold,
            currency=currency,
            details=f"Escrow hold untuk {reference}",
        )
        return escrow_id, receipt

    def release(self, escrow_id: int) -> TransactionReceipt:
        trn = release_escrow(escrow_id)
        receipt = self.account_service._build_receipt(
            transaction_type="Escrow Release",
            reference=trn,
            status=ProcessingState.SUCCESS.value,
            amount=Decimal("0.00"),
            fee=Decimal("0.00"),
            total=Decimal("0.00"),
            currency="USD",
            details=f"Escrow released {trn}",
        )
        logger.info("Escrow released %s", trn)
        return receipt


class VisaGatewayService:
    def __init__(self, account_service: AccountService):
        self.account_service = account_service

    def validate_merchant(self, merchant_id: int) -> bool:
        merchant = get_merchant(merchant_id) 
        if merchant is None:
            return False
        return merchant["approved"] == 1

    def fraud_check(self, amount: Decimal, reference: str) -> bool:
        logger.debug("Fraud check placeholder for %s %s", amount, reference)
        return True

    def process_payment(
        self,
        account_id: int,
        merchant_account_id: int,
        amount: Decimal,
        currency: str,
        reference: str,
    ) -> TransactionReceipt:
        if not self.validate_merchant(merchant_account_id):
            raise ValidationError("Merchant tidak valid.")

        if not self.fraud_check(amount, reference):
            raise ValidationError("Pembayaran ditolak oleh fraud check.")

        trn = create_visa_transaction(account_id, merchant_account_id, amount, currency, description="Visa payment", reference=reference)
        receipt = self.account_service._build_receipt(
            transaction_type="Visa Payment",
            reference=trn,
            status=ProcessingState.SUCCESS.value,
            amount=amount,
            fee=self.account_service.calculate_fee(amount),
            total=amount + self.account_service.calculate_fee(amount),
            currency=currency,
            details=f"Visa payment ke merchant {merchant_account_id}",
        )
        logger.info("Visa payment processed %s", trn)
        return receipt


class QuantumProcessorService:
    def enqueue_task(self, payload: str, metadata: str = None, priority: int = 100) -> int:
        task_id = enqueue_quantum_task(payload, metadata, priority)
        logger.info("Enqueued quantum task %s", task_id)
        return task_id

    def process_pending(self, limit: int = 5) -> int:
        processed = process_quantum_queue(limit)
        logger.info("Processed %s quantum tasks", processed)
        return processed


class SettlementService:
    def __init__(self, account_service: AccountService):
        self.account_service = account_service

    def generate_report(self, report_type: str, total_amount: Decimal, currency: str) -> Tuple[int, str]:
        currency_code = self.account_service.validate_currency(currency)
        report_id = create_settlement_report(report_type, total_amount, currency_code)
        payload_xml = generate_settlement_xml(report_id)
        logger.info("Created settlement report %s", report_id)
        return report_id, payload_xml

    def settle(self, report_id: int) -> str:
        try:
            payload_xml = generate_settlement_xml(report_id)
            logger.info("Settlement %s succeeded", report_id)
            return payload_xml
        except Exception as exc:
            logger.error("Settlement %s failed: %s", report_id, exc)
            raise


def clear_console() -> None:
    os.system("cls" if os.name == "nt" else "clear")


CANCEL_COMMANDS = {"batal", "cancel", "keluar", "exit"}


def prompt_decimal(prompt_text: str) -> Decimal:
    while True:
        raw = input(prompt_text).strip()
        if raw.lower() in CANCEL_COMMANDS:
            raise UserCancel()
        try:
            value = Decimal(raw)
        except (InvalidOperation, ValueError):
            print("Masukkan angka yang valid.")
            continue
        if value < 0:
            print("Nilai tidak boleh negatif.")
            continue
        return value.quantize(Decimal("0.01"))


def prompt_int(prompt_text: str) -> int:
    while True:
        raw = input(prompt_text).strip()
        if raw.lower() in CANCEL_COMMANDS:
            raise UserCancel()
        if not raw.isdigit():
            print("Masukkan angka valid.")
            continue
        return int(raw)


def prompt_text(prompt_text: str) -> str:
    raw = input(prompt_text).strip()
    if raw.lower() in CANCEL_COMMANDS:
        raise UserCancel()
    return raw


def show_menu() -> None:
    title = "BANKING GATEWAY v2.40"
    width = 45
    print("\n" + "=" * width)
    print(title.center(width))
    print("=" * width)
    print(" 1. Merchant registration")
    print(" 2. Create customer account")
    print(" 3. Deposit")
    print(" 4. Withdraw")
    print(" 5. Transfer between accounts")
    print(" 6. External bank transfer")
    print(" 7. Escrow hold")
    print(" 8. Escrow release")
    print(" 9. Visa endpoint x")
    print("10. Quantum queue processing")
    print("11. Settlement report")
    print("12. Show accounts")
    print("13. Show merchants")
    print("14. Approve merchant account")
    print("15. Review pending approvals")
    print("16. Admin approve authorization")
    print("17. SWIFT international transfer")
    print("18. SWIFT settlement queue processing")
    print("19. Generate SWIFT status report")
    print("20. Generate SWIFT advice message")
    print("21. Export SWIFT XML")
    print("22. Show SWIFT messages")
    print("23. Approve SWIFT message")
    print("24. Cancel SWIFT message")
    print("25. Reverse SWIFT message")
    print("26. UETR tracking dashboard")
    print("27. Search UETR")
    print("28. List UETR tracking")
    print("29. Export UETR XML")
    print("30. Export UETR report")
    print(" 0. Exit")
    print("=" * width)


def print_receipt(receipt: TransactionReceipt) -> None:
    print(receipt.render())


def print_table_header(columns):
    print(" | ".join(columns))
    print("-+-".join("-" * len(col) for col in columns))


def format_money(value: Decimal) -> str:
    return f"{value:,.2f}".rjust(15)


def register_merchant(service: AccountService) -> None:
    print("\n[Merchant Registration]")
    merchant_name = prompt_text("Merchant name: ")
    merchant_code = prompt_text("Merchant code (optional): ")
    currency = prompt_text("Currency (USD, EUR, GBP, JPY, IDR): ") or "USD"
    initial_deposit = prompt_decimal("Initial deposit: ")
    api_key = prompt_text("API key (optional, leave blank to auto-generate): ")
    api_secret = prompt_text("API secret (optional, leave blank to auto-generate): ")
    try:
        currency_code = service.validate_currency(currency)
        merchant_id = create_merchant(
            merchant_name,
            merchant_code,
            initial_deposit,
            currency_code,
            api_key=api_key or None,
            api_secret=api_secret or None,
        )
        merchant = get_merchant(merchant_id)
        logger.info("Merchant %s registered", merchant_id)
        print(f"Merchant registered with ID {merchant_id}.")
        if merchant is not None:
            print(f"API Key: {merchant['api_key']}")
            print(f"API Secret: {merchant['api_secret']}")
            print("Merchant status: Pending approval. Use the admin approval menu to activate this merchant.")
    except Exception as exc:
        print(f"Failed to register merchant: {exc}")


def create_customer_account(service: AccountService) -> None:
    print("\n[Create Customer Account]")
    customer_name = prompt_text("Customer name: ")
    currency = prompt_text("Currency (USD, EUR, GBP, JPY, IDR): ") or "USD"
    initial_deposit = prompt_decimal("Initial deposit: ")
    try:
        currency_code = service.validate_currency(currency)
        account_id = service.create_account(customer_name, currency_code, initial_deposit)
        print(f"Account created with ID {account_id}.")
    except Exception as exc:
        print(f"Failed to create account: {exc}")


def deposit_flow(service: AccountService) -> None:
    print("\n[Deposit]")
    account_id = prompt_int("Account ID: ")
    amount = prompt_decimal("Amount: ")
    currency = prompt_text("Deposit currency: ") or "USD"
    try:
        receipt = service.deposit(account_id, amount, currency)
        print_receipt(receipt)
    except Exception as exc:
        print(f"Deposit failed: {exc}")


def withdraw_flow(service: AccountService) -> None:
    print("\n[Withdraw]")
    account_id = prompt_int("Account ID: ")
    amount = prompt_decimal("Amount: ")
    try:
        receipt = service.withdraw(account_id, amount)
        print_receipt(receipt)
    except Exception as exc:
        print(f"Withdrawal failed: {exc}")


def transfer_flow(service: AccountService) -> None:
    print("\n[Transfer Between Accounts]")
    from_account_id = prompt_int("From account ID: ")
    to_account_id = prompt_int("To account ID: ")
    amount = prompt_decimal("Amount: ")
    currency = prompt_text("Currency: ") or "USD"
    try:
        receipt = service.transfer(from_account_id, to_account_id, amount, currency)
        print_receipt(receipt)
    except Exception as exc:
        print(f"Transfer failed: {exc}")


def external_transfer_flow(service: AccountService) -> None:
    print("\n[External Bank Transfer]")
    from_account_id = prompt_int("From account ID: ")
    target_bank = prompt_text("Target bank name: ")
    target_account_number = prompt_text("Target account number: ")
    amount = prompt_decimal("Amount: ")
    currency = prompt_text("Currency: ") or "USD"
    try:
        currency_code = service.validate_currency(currency)
        fee = service.calculate_fee(amount)
        total = amount + fee
        transfer_id = create_external_transfer(
            from_account_id,
            target_bank,
            target_account_number,
            amount,
            currency_code,
        )
        receipt = service._build_receipt(
            transaction_type="External Transfer",
            reference=str(uuid4()),
            status=ProcessingState.SUCCESS.value,
            amount=amount,
            fee=fee,
            total=total,
            currency=currency_code,
            details=f"External transfer to {target_bank} {target_account_number}",
        )
        print(f"External transfer queued with ID {transfer_id}.")
        print_receipt(receipt)
    except Exception as exc:
        print(f"External transfer failed: {exc}")


def escrow_hold_flow(service: EscrowService) -> None:
    print("\n[Escrow Hold]")
    account_id = prompt_int("Account ID: ")
    amount = prompt_decimal("Amount: ")
    reference = prompt_text("Escrow reference: ") or str(uuid4())
    try:
        escrow_id, receipt = service.hold(account_id, amount, reference)
        print(f"Escrow hold created with ID {escrow_id}.")
        print_receipt(receipt)
    except Exception as exc:
        print(f"Escrow hold failed: {exc}")


def escrow_release_flow(service: EscrowService) -> None:
    print("\n[Escrow Release]")
    escrow_id = prompt_int("Escrow ID: ")
    try:
        receipt = service.release(escrow_id)
        print_receipt(receipt)
    except Exception as exc:
        print(f"Escrow release failed: {exc}")

def visa_flow(service: VisaGatewayService) -> None:
    print("\n[Visa Endpoint ]")
    account_id = prompt_int("Customer account ID: ")
    merchant_id = prompt_int("Merchant account ID: ")
    merchant_api_key = prompt_text("Merchant API key (optional): ")
    signature = prompt_text("Request HMAC signature (optional): ")
    amount = prompt_decimal("Amount: ")
    currency = prompt_text("Currency: ") or "USD"
    reference = str(uuid4())
    try:
        if merchant_api_key:
            if not validate_merchant_api_key(merchant_id, merchant_api_key):
                raise ValidationError("API key merchant tidak valid.")
            if signature:
                merchant = get_merchant(merchant_id)
                if merchant is None:
                    raise ValidationError("Merchant tidak ditemukan.")
                payload = f"{account_id}:{merchant_id}:{amount}:{currency}:{reference}"
                if not verify_hmac_signature(payload, merchant['api_secret'], signature):
                    raise ValidationError("Signature HMAC tidak valid.")

        receipt = service.process_payment(account_id, merchant_id, amount, currency, reference)
        print_receipt(receipt)
    except Exception as exc:
        print(f"Visa payment failed: {exc}")


def pending_approvals_flow() -> None:
    print("\n[Pending Authorizations]")
    pending = list_pending_authorizations()
    if not pending["visa"] and not pending["escrow"]:
        print("Tidak ada persetujuan yang tertunda.")
        return

    if pending["visa"]:
        print("\nVisa transactions pending approval:")
        print("TRN                     | Account | Merchant | Amount      | Currency | Status")
        print("-------------------------+---------+----------+-------------+----------+---------")
        for row in pending["visa"]:
            print(
                f"{row['trn']:<25} | {row['account_id']:>7} | {row['merchant_account_id'] or 'N/A':>8} | {Decimal(row['amount']):>11,.2f} | {row['currency']:<8} | {row['status']}"
            )

    if pending["escrow"]:
        print("\nEscrow settlements pending approval:")
        print("TRN                     | Account | Amount      | Currency | Status")
        print("-------------------------+---------+-------------+----------+---------")
        for row in pending["escrow"]:
            print(
                f"{row['trn']:<25} | {row['account_id']:>7} | {Decimal(row['amount']):>11,.2f} | {row['currency']:<8} | {row['status']}"
            )


def approve_merchant_flow() -> None:
    print("\n[Approve Merchant Account]")
    merchant_id = prompt_int("Merchant ID: ")
    try:
        approved = approve_merchant(merchant_id)
        if approved:
            print(f"Merchant account {merchant_id} disetujui.")
        else:
            print(f"Merchant account {merchant_id} sudah disetujui atau tidak ditemukan.")
    except Exception as exc:
        print(f"Merchant approval failed: {exc}")


def admin_approval_flow() -> None:
    print("\n[Admin Approval]")
    table_name = prompt_text("Approval table (visa_transactions or escrow_settlements): ").strip()
    trn = prompt_text("Transaction TRN: ").strip()
    approve_option = prompt_text("Approve? (y/n): ").strip().lower()
    approve = approve_option in ("y", "yes")
    try:
        result = admin_approve_transaction(table_name, trn, approve)
        if result:
            print(f"Transaction {trn} has been {'approved' if approve else 'rejected'}.")
        else:
            print(f"No pending transaction found for {trn} in {table_name}.")
    except Exception as exc:
        print(f"Admin approval failed: {exc}")


def quantum_flow(service: QuantumProcessorService) -> None:
    print("\n[Quantum Queue Processing]")
    try:
        processed = service.process_pending()
        print(f"Processed {processed} queued quantum tasks.")
    except Exception as exc:
        print(f"Quantum processing failed: {exc}")


def settlement_flow(service: SettlementService) -> None:
    print("\n[Settlement Report]")
    report_type = prompt_text("Report type: ") or "DAILY"
    total_amount = prompt_decimal("Total settlement amount: ")
    currency = prompt_text("Currency: ") or "USD"
    try:
        report_id, payload = service.generate_report(report_type, total_amount, currency)
        print(f"Settlement report created with ID {report_id}.")
        print("XML payload:")
        print(payload)
    except Exception as exc:
        print(f"Settlement generation failed: {exc}")


def swift_transfer_flow(service: SwiftService) -> None:
    print("\n[SWIFT International Transfer]")
    bic_sender = prompt_text("Sender BIC: ")
    bic_receiver = prompt_text("Receiver BIC: ")
    debtor_name = prompt_text("Debtor name: ")
    creditor_name = prompt_text("Creditor name: ")
    amount = prompt_decimal("Amount: ")
    currency = prompt_text("Currency: ") or "USD"
    instruction = prompt_text("Payment purpose (optional): ")
    try:
        trn, uetr = service.create_swift_payment(
            bic_sender=bic_sender,
            bic_receiver=bic_receiver,
            amount=amount,
            currency=currency,
            debtor_name=debtor_name,
            creditor_name=creditor_name,
            instruction_info=instruction,
        )
        print(f"SWIFT message created with TRN {trn} and UETR {uetr}.")
    except Exception as exc:
        print(f"SWIFT transfer failed: {exc}")


def swift_settlement_queue_flow(service: SwiftService) -> None:
    print("\n[SWIFT Settlement Queue Processing]")
    try:
        processed = service.process_settlement_queue()
        print(f"Processed {processed} SWIFT settlement messages.")
    except Exception as exc:
        print(f"SWIFT queue processing failed: {exc}")


def swift_status_report_flow(service: SwiftService) -> None:
    print("\n[Generate SWIFT Status Report]")
    trn = prompt_text("SWIFT TRN: ")
    reason = prompt_text("Status reason: ")
    try:
        xml = service.generate_status_report(trn, reason)
        print("Generated SWIFT status report:")
        print(xml)
    except Exception as exc:
        print(f"SWIFT status generation failed: {exc}")


def swift_advice_flow(service: SwiftService) -> None:
    print("\n[Generate SWIFT Advice Message]")
    trn = prompt_text("SWIFT TRN: ")
    message = prompt_text("Advice message: ")
    try:
        xml = service.generate_advice_message(trn, message)
        print("Generated SWIFT advice message:")
        print(xml)
    except Exception as exc:
        print(f"SWIFT advice generation failed: {exc}")


def swift_export_flow(service: SwiftService) -> None:
    print("\n[Export SWIFT XML]")
    trn = prompt_text("SWIFT TRN: ")
    file_path = prompt_text("File path: ") or f"swift_{trn}.xml"
    try:
        path = service.export_to_file(trn, file_path)
        print(f"SWIFT XML exported to {path}.")
    except Exception as exc:
        print(f"SWIFT XML export failed: {exc}")


def show_swift_messages_flow(service: SwiftService) -> None:
    print("\n[SWIFT Messages]")
    status = prompt_text("Status filter (optional): ") or None
    try:
        rows = service.list_messages(status)
        if not rows:
            print("Tidak ada pesan SWIFT.")
            return
        print("TRN                       | UETR                             | Type      | Status    | Amount      | Currency | Sender      | Receiver")
        print("---------------------------+----------------------------------+-----------+-----------+-------------+----------+-------------+-------------")
        for row in rows:
            print(
                f"{row['trn']:<27} | {row['uetr']:<34} | {row['message_type']:<9} | {row['status']:<9} | {Decimal(row['amount']):>11,.2f} | {row['currency']:<8} | {row['bic_sender']:<11} | {row['bic_receiver']:<11}"
            )
    except Exception as exc:
        print(f"Failed to show SWIFT messages: {exc}")


def approve_swift_flow(service: SwiftService) -> None:
    print("\n[Approve SWIFT Message]")
    trn = prompt_text("SWIFT TRN: ")
    approve_option = prompt_text("Approve? (y/n): ").strip().lower()
    approve = approve_option in ("y", "yes")
    try:
        result = service.approve(trn, approve)
        print(f"SWIFT message {trn} {'approved' if approve else 'rejected'}.") if result else print(f"SWIFT message {trn} not found or not pending.")
    except Exception as exc:
        print(f"SWIFT approval failed: {exc}")


def cancel_swift_flow(service: SwiftService) -> None:
    print("\n[Cancel SWIFT Message]")
    trn = prompt_text("SWIFT TRN: ")
    try:
        result = service.cancel(trn)
        print(f"SWIFT message {trn} cancelled.") if result else print(f"SWIFT message {trn} could not be cancelled.")
    except Exception as exc:
        print(f"SWIFT cancellation failed: {exc}")


def reverse_swift_flow(service: SwiftService) -> None:
    print("\n[Reverse SWIFT Message]")
    trn = prompt_text("SWIFT TRN: ")
    try:
        result = service.reverse(trn)
        print(f"SWIFT message {trn} reversed.") if result else print(f"SWIFT message {trn} could not be reversed.")
    except Exception as exc:
        print(f"SWIFT reversal failed: {exc}")


def uetr_dashboard_flow(uetr_service: UETRService, tracking_service: TrackingService, routing_service: RoutingService) -> None:
    print("\n[UETR Tracking Dashboard]")
    amount = prompt_decimal("Amount: ")
    currency = prompt_text("Currency: ") or "USD"
    sender_bic = prompt_text("Sender BIC: ")
    receiver_bic = prompt_text("Receiver BIC: ")
    debtor_name = prompt_text("Debtor name: ")
    creditor_name = prompt_text("Creditor name: ")
    record = uetr_service.create(amount, currency, sender_bic, receiver_bic, debtor_name, creditor_name)
    route = routing_service.simulate_routing(sender_bic, receiver_bic, amount)
    tracking_service.update_stage(record["uetr"], "ROUTED", "PROCESSING", "Routing simulated between correspondent banks", eta_hours=route["settlement_eta_hours"])
    print("UETR created:", record["uetr"])
    print("Route:", route)
    print("Progress:", tracking_service.progress_visual(record["uetr"]))


def search_uetr_flow(service: UETRService) -> None:
    print("\n[Search UETR]")
    query = prompt_text("Search by UETR / TRN / BIC / status: ")
    rows = service.search(query)
    if not rows:
        print("No tracking records found.")
        return
    for row in rows:
        print(f"{row['uetr']} | {row['trn']} | {row['status']} | {row['stage']} | {row['amount']} {row['currency']}")


def list_uetr_flow(service: UETRService) -> None:
    print("\n[List UETR Tracking]")
    rows = service.list()
    if not rows:
        print("No UETR records found.")
        return
    for row in rows:
        print(f"{row['uetr']} | {row['trn']} | {row['status']} | {row['stage']} | {row['amount']} {row['currency']} | ETA {row['settlement_eta'] or 'TBD'}")


def export_uetr_xml_flow(service: UETRService) -> None:
    print("\n[Export UETR XML]")
    uetr = prompt_text("UETR: ")
    file_path = prompt_text("Output file path: ") or f"uetr_{uetr}.xml"
    print("Exported to", service.export_xml(uetr, file_path))


def export_uetr_report_flow(service: UETRService) -> None:
    print("\n[Export UETR Report]")
    uetr = prompt_text("UETR: ")
    file_path = prompt_text("Output file path: ") or f"uetr_{uetr}.txt"
    print("Exported to", service.export_report(uetr, file_path))


def show_accounts_flow() -> None:
    print("\n[Daftar Akun]")
    rows = list_accounts()
    if not rows:
        print("Tidak ada akun.")
        return
    print("ID  | Name                 | Currency | Balance        | Created")
    print("----+----------------------+----------+----------------+---------------------")
    for row in rows:
        print(
            f"{row['id']:>3} | {row['name']:<20} | {row['currency']:<8} | {Decimal(row['balance']):>14,.2f} | {row['created_at']}"
        )


def show_merchants_flow() -> None:
    print("\n[Daftar Merchant]")
    rows = list_merchants()
    if not rows:
        print("Tidak ada merchant.")
        return
    print("ID  | Merchant Name         | Code        | Currency | Balance        | Created")
    print("----+----------------------+-------------+----------+----------------+---------------------")
    for row in rows:
        print(
            f"{row['id']:>3} | {row['merchant_name']:<20} | {row['merchant_code']:<11} | {row['currency']:<8} | {Decimal(row['balance']):>14,.2f} | {row['created_at']}"
        )


def main() -> None:
    init_db()
    account_service = AccountService()
    escrow_service = EscrowService(account_service)
    visa_service = VisaGatewayService(account_service)
    quantum_service = QuantumProcessorService()
    settlement_service = SettlementService(account_service)

    swift_service = SwiftService()
    uetr_service = UETRService()
    tracking_service = TrackingService()
    routing_service = RoutingService()
    while True:
        show_menu()
        choice = prompt_text("Select menu: ")

        try:
            if choice == "1":
                register_merchant(account_service)
            elif choice == "2":
                create_customer_account(account_service)
            elif choice == "3":
                deposit_flow(account_service)
            elif choice == "4":
                withdraw_flow(account_service)
            elif choice == "5":
                transfer_flow(account_service)
            elif choice == "6":
                external_transfer_flow(account_service)
            elif choice == "7":
                escrow_hold_flow(escrow_service)
            elif choice == "8":
                escrow_release_flow(escrow_service)
            elif choice == "9":
                visa_flow(visa_service)
            elif choice == "10":
                quantum_flow(quantum_service)
            elif choice == "11":
                settlement_flow(settlement_service)
            elif choice == "12":
                show_accounts_flow()
            elif choice == "13":
                show_merchants_flow()
            elif choice == "14":
                approve_merchant_flow()
            elif choice == "15":
                pending_approvals_flow()
            elif choice == "16":
                admin_approval_flow()
            elif choice == "17":
                swift_transfer_flow(swift_service)
            elif choice == "18":
                swift_settlement_queue_flow(swift_service)
            elif choice == "19":
                swift_status_report_flow(swift_service)
            elif choice == "20":
                swift_advice_flow(swift_service)
            elif choice == "21":
                swift_export_flow(swift_service)
            elif choice == "22":
                show_swift_messages_flow(swift_service)
            elif choice == "23":
                approve_swift_flow(swift_service)
            elif choice == "24":
                cancel_swift_flow(swift_service)
            elif choice == "25":
                reverse_swift_flow(swift_service)
            elif choice == "26":
                uetr_dashboard_flow(uetr_service, tracking_service, routing_service)
            elif choice == "27":
                search_uetr_flow(uetr_service)
            elif choice == "28":
                list_uetr_flow(uetr_service)
            elif choice == "29":
                export_uetr_xml_flow(uetr_service)
            elif choice == "30":
                export_uetr_report_flow(uetr_service)
            elif choice == "0":
                print("Exiting banking gateway simulation.")
                break
            else:
                print("Invalid selection.")
        except UserCancel:
            print("Operasi dibatalkan. Kembali ke menu utama.")
        except ValidationError as exc:
            logger.warning("Validation failed: %s", exc)
            print(f"Validation error: {exc}")
        except Exception as exc:
            logger.exception("Unexpected error")
            print(f"An unexpected error occurred: {exc}")

        input("\nPress Enter to continue...")
        clear_console()


if __name__ == "__main__":
    main()
