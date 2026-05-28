import json
import os
import sqlite3
import hmac
import hashlib
from sqlite3 import Connection
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal, getcontext
from uuid import uuid4
import xml.etree.ElementTree as ET

getcontext().prec = 28

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "point_getway.db")

STATUS_PENDING = "PENDING"
STATUS_PROCESSING = "PROCESSING"
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
STATUS_HOLD = "HOLD"
STATUS_REVERSED = "REVERSED"
STATUS_CHOICES = (
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_SUCCESS,
    STATUS_FAILED,
    STATUS_HOLD,
    STATUS_REVERSED,
)

sqlite3.register_adapter(Decimal, lambda value: str(value))
sqlite3.register_converter("DECIMAL", lambda value: Decimal(value.decode() if isinstance(value, bytes) else value))

CREATE_TABLE_SCRIPT = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    currency TEXT NOT NULL DEFAULT 'USD',
    balance TEXT NOT NULL DEFAULT '0',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS merchant_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_name TEXT NOT NULL,
    merchant_code TEXT NOT NULL UNIQUE,
    api_key TEXT NOT NULL UNIQUE,
    api_secret TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    balance TEXT NOT NULL DEFAULT '0',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS visa_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trn TEXT NOT NULL UNIQUE,
    account_id INTEGER NOT NULL,
    merchant_account_id INTEGER,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'PROCESSING', 'SUCCESS', 'FAILED', 'HOLD', 'REVERSED')),
    xml_payload TEXT,
    request_signature TEXT,
    ip_address TEXT,
    fraud_score INTEGER DEFAULT 0,
    requires_admin_approval INTEGER NOT NULL DEFAULT 0,
    approval_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(approval_status IN ('PENDING','APPROVED','REJECTED')),
    reference TEXT,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    FOREIGN KEY(merchant_account_id) REFERENCES merchant_accounts(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS escrow_settlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trn TEXT NOT NULL UNIQUE,
    account_id INTEGER NOT NULL,
    merchant_account_id INTEGER,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'PROCESSING', 'SUCCESS', 'FAILED', 'HOLD', 'REVERSED')),
    xml_payload TEXT,
    request_signature TEXT,
    ip_address TEXT,
    requires_admin_approval INTEGER NOT NULL DEFAULT 0,
    approval_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(approval_status IN ('PENDING','APPROVED','REJECTED')),
    confirmation_code TEXT,
    reference TEXT,
    release_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    FOREIGN KEY(merchant_account_id) REFERENCES merchant_accounts(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS transaction_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trn TEXT NOT NULL,
    account_id INTEGER,
    merchant_account_id INTEGER,
    event_type TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'PROCESSING', 'SUCCESS', 'FAILED', 'HOLD', 'REVERSED')),
    details TEXT,
    ip_address TEXT,
    reference TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE SET NULL,
    FOREIGN KEY(merchant_account_id) REFERENCES merchant_accounts(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS quantum_processing_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trn TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL,
    metadata TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'PROCESSING', 'SUCCESS', 'FAILED', 'HOLD', 'REVERSED')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    last_error TEXT,
    priority INTEGER NOT NULL DEFAULT 100,
    next_attempt_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settlement_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trn TEXT NOT NULL UNIQUE,
    report_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'PROCESSING', 'SUCCESS', 'FAILED', 'HOLD', 'REVERSED')),
    total_amount TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    payload_xml TEXT,
    confirmation_code TEXT,
    processed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS external_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trn TEXT NOT NULL UNIQUE,
    account_id INTEGER NOT NULL,
    target_bank TEXT NOT NULL,
    target_account TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'PROCESSING', 'SUCCESS', 'FAILED', 'HOLD', 'REVERSED')),
    xml_payload TEXT,
    request_signature TEXT,
    ip_address TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS swift_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trn TEXT NOT NULL UNIQUE,
    uetr TEXT NOT NULL UNIQUE,
    message_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'PROCESSING', 'SUCCESS', 'FAILED', 'HOLD', 'REVERSED')),
    bic_sender TEXT NOT NULL,
    bic_receiver TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    debtor_name TEXT,
    creditor_name TEXT,
    instruction_info TEXT,
    xml_payload TEXT,
    settlement_reference TEXT,
    requires_approval INTEGER NOT NULL DEFAULT 0,
    approval_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(approval_status IN ('PENDING','APPROVED','REJECTED')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_swift_messages_trn ON swift_messages(trn);
CREATE INDEX IF NOT EXISTS idx_swift_messages_uetr ON swift_messages(uetr);
CREATE INDEX IF NOT EXISTS idx_swift_messages_status ON swift_messages(status);

CREATE TABLE IF NOT EXISTS uetr_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uetr TEXT NOT NULL UNIQUE,
    trn TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','PROCESSING','SUCCESS','FAILED','HOLD','REVERSED')),
    stage TEXT NOT NULL DEFAULT 'INITIATED',
    amount TEXT NOT NULL DEFAULT '0',
    currency TEXT NOT NULL DEFAULT 'USD',
    sender_bic TEXT NOT NULL,
    receiver_bic TEXT NOT NULL,
    debtor_name TEXT,
    creditor_name TEXT,
    settlement_eta TEXT,
    intermediary_hops TEXT DEFAULT '[]',
    routing_path TEXT DEFAULT '[]',
    tracking_history TEXT DEFAULT '[]',
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    failed_reason TEXT,
    reversed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_uetr_tracking_uetr ON uetr_tracking(uetr);
CREATE INDEX IF NOT EXISTS idx_uetr_tracking_trn ON uetr_tracking(trn);
CREATE INDEX IF NOT EXISTS idx_uetr_tracking_status ON uetr_tracking(status);

CREATE TABLE IF NOT EXISTS transaction_locks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trn TEXT NOT NULL UNIQUE,
    lock_owner TEXT NOT NULL,
    locked_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_visa_transactions_trn ON visa_transactions(trn);
CREATE INDEX IF NOT EXISTS idx_visa_transactions_status ON visa_transactions(status);
CREATE INDEX IF NOT EXISTS idx_escrow_settlements_trn ON escrow_settlements(trn);
CREATE INDEX IF NOT EXISTS idx_escrow_settlements_status ON escrow_settlements(status);
CREATE INDEX IF NOT EXISTS idx_transaction_logs_trn ON transaction_logs(trn);
CREATE INDEX IF NOT EXISTS idx_transaction_logs_status ON transaction_logs(status);
CREATE INDEX IF NOT EXISTS idx_quantum_queue_status ON quantum_processing_queue(status);
CREATE INDEX IF NOT EXISTS idx_settlement_reports_trn ON settlement_reports(trn);
CREATE INDEX IF NOT EXISTS idx_settlement_reports_status ON settlement_reports(status);
CREATE TRIGGER IF NOT EXISTS transaction_logs_no_update
BEFORE UPDATE ON transaction_logs
BEGIN
    SELECT RAISE(ABORT, 'Immutable audit log cannot be updated');
END;

CREATE TRIGGER IF NOT EXISTS transaction_logs_no_delete
BEFORE DELETE ON transaction_logs
BEGIN
    SELECT RAISE(ABORT, 'Immutable audit log cannot be deleted');
END;

CREATE INDEX IF NOT EXISTS idx_external_transfers_trn ON external_transfers(trn);
CREATE INDEX IF NOT EXISTS idx_external_transfers_status ON external_transfers(status);
"""


def get_connection() -> Connection:
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction():
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _generate_trn(prefix: str = "TRN") -> str:
    return f"{prefix}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:10].upper()}"


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def _format_amount(amount: Decimal) -> str:
    return str(amount.quantize(Decimal("0.01")))


def _column_exists(conn, table: str, column: str) -> bool:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def _ensure_column(conn, table: str, column_name: str, column_definition: str) -> None:
    if not _column_exists(conn, table, column_name):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_definition}")


def _migrate_schema(conn) -> None:
    if _column_exists(conn, "accounts", "id"):
        _ensure_column(conn, "accounts", "currency", "TEXT NOT NULL DEFAULT 'USD'")
        _ensure_column(conn, "accounts", "updated_at", "TEXT NOT NULL DEFAULT ''")

    if _column_exists(conn, "merchant_accounts", "id"):
        _ensure_column(conn, "merchant_accounts", "api_key", "TEXT")
        _ensure_column(conn, "merchant_accounts", "api_secret", "TEXT")
        _ensure_column(conn, "merchant_accounts", "approved", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "merchant_accounts", "updated_at", "TEXT NOT NULL DEFAULT ''")
        merchants = conn.execute("SELECT id, api_key, api_secret FROM merchant_accounts").fetchall()
        for merchant in merchants:
            if merchant[1] is None or merchant[1] == "":
                conn.execute(
                    "UPDATE merchant_accounts SET api_key = ?, api_secret = ? WHERE id = ?",
                    (f"KEY-{uuid4().hex[:16].upper()}", uuid4().hex, merchant[0]),
                )

    if _column_exists(conn, "visa_transactions", "id"):
        _ensure_column(conn, "visa_transactions", "request_signature", "TEXT")
        _ensure_column(conn, "visa_transactions", "ip_address", "TEXT")
        _ensure_column(conn, "visa_transactions", "fraud_score", "INTEGER DEFAULT 0")
        _ensure_column(conn, "visa_transactions", "requires_admin_approval", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "visa_transactions", "approval_status", "TEXT NOT NULL DEFAULT 'PENDING'")

    if _column_exists(conn, "escrow_settlements", "id"):
        _ensure_column(conn, "escrow_settlements", "request_signature", "TEXT")
        _ensure_column(conn, "escrow_settlements", "ip_address", "TEXT")
        _ensure_column(conn, "escrow_settlements", "requires_admin_approval", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "escrow_settlements", "approval_status", "TEXT NOT NULL DEFAULT 'PENDING'")
        _ensure_column(conn, "escrow_settlements", "confirmation_code", "TEXT")

    if _column_exists(conn, "transaction_logs", "id"):
        _ensure_column(conn, "transaction_logs", "ip_address", "TEXT")

    if _column_exists(conn, "external_transfers", "id"):
        _ensure_column(conn, "external_transfers", "trn", "TEXT")
        _ensure_column(conn, "external_transfers", "status", "TEXT NOT NULL DEFAULT 'PENDING'")
        _ensure_column(conn, "external_transfers", "xml_payload", "TEXT")
        _ensure_column(conn, "external_transfers", "request_signature", "TEXT")
        _ensure_column(conn, "external_transfers", "ip_address", "TEXT")
        _ensure_column(conn, "external_transfers", "updated_at", "TEXT NOT NULL DEFAULT ''")
        rows = conn.execute("SELECT id FROM external_transfers WHERE trn IS NULL").fetchall()
        for row in rows:
            conn.execute(
                "UPDATE external_transfers SET trn = ?, status = ?, updated_at = ? WHERE id = ?",
                (_generate_trn("EXT"), STATUS_SUCCESS, _now(), row[0]),
            )
        conn.execute(
            "UPDATE external_transfers SET status = ? WHERE status IS NULL",
            (STATUS_SUCCESS,),
        )

    if _column_exists(conn, "quantum_processing_queue", "id"):
        _ensure_column(conn, "quantum_processing_queue", "retry_count", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "quantum_processing_queue", "max_retries", "INTEGER NOT NULL DEFAULT 3")
        _ensure_column(conn, "quantum_processing_queue", "last_error", "TEXT")
        _ensure_column(conn, "quantum_processing_queue", "created_at", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "quantum_processing_queue", "updated_at", "TEXT NOT NULL DEFAULT ''")

    if _column_exists(conn, "settlement_reports", "id"):
        _ensure_column(conn, "settlement_reports", "confirmation_code", "TEXT")
        _ensure_column(conn, "settlement_reports", "processed_at", "TEXT")

    if not _column_exists(conn, "uetr_tracking", "id"):
        conn.execute("""
        CREATE TABLE uetr_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uetr TEXT NOT NULL UNIQUE,
            trn TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'PENDING',
            stage TEXT NOT NULL DEFAULT 'INITIATED',
            amount TEXT NOT NULL DEFAULT '0',
            currency TEXT NOT NULL DEFAULT 'USD',
            sender_bic TEXT NOT NULL,
            receiver_bic TEXT NOT NULL,
            debtor_name TEXT,
            creditor_name TEXT,
            settlement_eta TEXT,
            intermediary_hops TEXT DEFAULT '[]',
            routing_path TEXT DEFAULT '[]',
            tracking_history TEXT DEFAULT '[]',
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 3,
            failed_reason TEXT,
            reversed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)


def init_db() -> None:
    with get_connection() as conn:
        _migrate_schema(conn)
        conn.executescript(CREATE_TABLE_SCRIPT)
        conn.commit()


def _insert_transaction_log(
    conn,
    event_type: str,
    amount,
    currency: str,
    status: str,
    details: str = None,
    account_id: int = None,
    merchant_account_id: int = None,
    reference: str = None,
    ip_address: str = None,
    trn: str = None,
) -> int:
    now = _now()
    amount_decimal = _to_decimal(amount)
    trn = trn or _generate_trn("LOG")
    cursor = conn.execute(
        "INSERT INTO transaction_logs (trn, account_id, merchant_account_id, event_type, amount, currency, status, details, ip_address, reference, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            trn,
            account_id,
            merchant_account_id,
            event_type,
            _format_amount(amount_decimal),
            currency.strip().upper(),
            status,
            details,
            ip_address,
            reference,
            now,
            now,
        ),
    )
    return cursor.lastrowid


def create_transaction_log(
    event_type: str,
    amount,
    currency: str = "USD",
    status: str = STATUS_PENDING,
    details: str = None,
    account_id: int = None,
    merchant_account_id: int = None,
    reference: str = None,
    ip_address: str = None,
    trn: str = None,
):
    if status not in STATUS_CHOICES:
        raise ValueError("Status transaction log tidak valid.")

    with transaction() as conn:
        return _insert_transaction_log(
            conn,
            event_type=event_type,
            amount=amount,
            currency=currency,
            status=status,
            details=details,
            account_id=account_id,
            merchant_account_id=merchant_account_id,
            reference=reference,
            ip_address=ip_address,
            trn=trn,
        )


def create_account(name: str, initial_deposit=Decimal("0"), currency: str = "USD") -> int:
    currency = currency.strip().upper()
    balance = _to_decimal(initial_deposit)
    now = _now()

    with transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO accounts (name, currency, balance, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (name.strip(), currency, _format_amount(balance), now, now),
        )
        account_id = cursor.lastrowid
        if balance != Decimal("0"):
            _insert_transaction_log(
                conn,
                event_type="account_open",
                amount=balance,
                currency=currency,
                status=STATUS_SUCCESS,
                details="Initial deposit",
                account_id=account_id,
            )
        return account_id


def create_merchant(merchant_name: str, merchant_code: str = None, initial_deposit=Decimal("0"), currency: str = "USD", api_key: str = None, api_secret: str = None) -> int:
    currency = currency.strip().upper()
    merchant_code_value = merchant_code.strip() if merchant_code and merchant_code.strip() else f"MCH-{uuid4().hex[:10].upper()}"
    api_key_value = api_key.strip() if api_key and api_key.strip() else f"KEY-{uuid4().hex[:16].upper()}"
    api_secret_value = api_secret.strip() if api_secret and api_secret.strip() else uuid4().hex
    balance = _to_decimal(initial_deposit)
    now = _now()

    with transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO merchant_accounts (merchant_name, merchant_code, api_key, api_secret, approved, currency, balance, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (merchant_name.strip(), merchant_code_value, api_key_value, api_secret_value, 0, currency, _format_amount(balance), now, now),
        )
        merchant_id = cursor.lastrowid
        if balance != Decimal("0"):
            _insert_transaction_log(
                conn,
                event_type="merchant_account_open",
                amount=balance,
                currency=currency,
                status=STATUS_SUCCESS,
                details="Initial merchant deposit",
                merchant_account_id=merchant_id,
            )
        return merchant_id


def get_account(account_id: int):
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        return cursor.fetchone()


def get_account_by_name(name: str):
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM accounts WHERE name = ?", (name.strip(),))
        return cursor.fetchone()


def list_accounts():
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM accounts ORDER BY id")
        return cursor.fetchall()


def get_merchant(merchant_id: int): 
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM merchant_accounts WHERE id = ?", (merchant_id,))
        return cursor.fetchone()


def list_merchants():
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM merchant_accounts ORDER BY id")
        return cursor.fetchall()


def list_pending_authorizations():
    with get_connection() as conn:
        visa_cursor = conn.execute(
            "SELECT trn, account_id, merchant_account_id, amount, currency, status, approval_status, created_at FROM visa_transactions WHERE approval_status = 'PENDING' ORDER BY created_at"
        )
        escrow_cursor = conn.execute(
            "SELECT trn, account_id, merchant_account_id, amount, currency, status, approval_status, created_at FROM escrow_settlements WHERE approval_status = 'PENDING' ORDER BY created_at"
        )
        return {
            "visa": visa_cursor.fetchall(),
            "escrow": escrow_cursor.fetchall(),
        }


def approve_merchant(merchant_id: int) -> bool:
    with transaction() as conn:
        merchant = conn.execute(
            "SELECT * FROM merchant_accounts WHERE id = ?",
            (merchant_id,),
        ).fetchone()
        if merchant is None:
            raise ValueError("Merchant tidak ditemukan.")
        if merchant["approved"] == 1:
            return False
        conn.execute(
            "UPDATE merchant_accounts SET approved = 1, updated_at = ? WHERE id = ?",
            (_now(), merchant_id),
        )
        _insert_transaction_log(
            conn,
            event_type="merchant_approval",
            amount=Decimal("0"),
            currency="USD",
            status=STATUS_SUCCESS,
            details=f"Merchant {merchant_id} approved",
            merchant_account_id=merchant_id,
            reference=merchant["merchant_code"],
        )
        return True


def _update_account_balance(conn, account_id: int, new_balance: Decimal) -> None:
    now = _now()
    conn.execute(
        "UPDATE accounts SET balance = ?, updated_at = ? WHERE id = ?",
        (_format_amount(new_balance), now, account_id),
    )


def _update_merchant_balance(conn, merchant_id: int, new_balance: Decimal) -> None:
    now = _now()
    conn.execute(
        "UPDATE merchant_accounts SET balance = ?, updated_at = ? WHERE id = ?",
        (_format_amount(new_balance), now, merchant_id),
    )


def change_balance(account_id: int, delta, event_type: str = "balance_change", details: str = None, reference: str = None) -> Decimal:
    delta_value = _to_decimal(delta)
    with transaction() as conn:
        account = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if account is None:
            raise ValueError("Akun tidak ditemukan.")

        current_balance = _to_decimal(account["balance"])
        new_balance = current_balance + delta_value
        if new_balance < Decimal("0"):
            raise ValueError("Saldo tidak cukup.")

        _update_account_balance(conn, account_id, new_balance)
        _insert_transaction_log(
            conn,
            event_type=event_type,
            amount=delta_value,
            currency=account["currency"].strip().upper(),
            status=STATUS_SUCCESS,
            details=details,
            account_id=account_id,
            reference=reference,
        )
        return new_balance


def _insert_escrow_settlement(
    conn,
    account_id: int,
    amount,
    currency: str,
    status: str,
    reference: str = None,
    xml_payload: str = None,
    merchant_account_id: int = None,
    requires_admin_approval: int = 0,
    approval_status: str = "APPROVED",
):
    now = _now()
    trn = _generate_trn("ESC")
    amount_decimal = _to_decimal(amount)
    cursor = conn.execute(
        "INSERT INTO escrow_settlements (trn, account_id, merchant_account_id, amount, currency, status, xml_payload, request_signature, ip_address, requires_admin_approval, approval_status, reference, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            trn,
            account_id,
            merchant_account_id,
            _format_amount(amount_decimal),
            currency.strip().upper(),
            status,
            xml_payload,
            None,
            None,
            requires_admin_approval,
            approval_status,
            reference,
            now,
            now,
        ),
    )
    return cursor.lastrowid


def create_escrow_transaction(account_id: int, reference: str, amount, direction: str) -> int:
    normalized_direction = direction.strip().lower()
    if normalized_direction not in ("credit", "debit"):
        raise ValueError("Arah escrow harus 'credit' atau 'debit'.")

    amount_decimal = _to_decimal(amount)
    requires_admin_approval = 1 if amount_decimal > Decimal("5000") else 0
    status = STATUS_HOLD if normalized_direction == "debit" else STATUS_PENDING
    approval_status = "PENDING" if requires_admin_approval else "APPROVED"
    details = "Escrow debit reservasi" if normalized_direction == "debit" else "Escrow kredit menunggu pelepasan"

    with transaction() as conn:
        escrow_id = _insert_escrow_settlement(
            conn,
            account_id=account_id,
            amount=amount,
            currency="USD",
            status=status,
            reference=reference,
            xml_payload=None,
            requires_admin_approval=requires_admin_approval,
            approval_status=approval_status,
        )
        _insert_transaction_log(
            conn,
            event_type=f"escrow_{normalized_direction}",
            amount=amount,
            currency="USD",
            status=status,
            details=details,
            account_id=account_id,
            reference=reference,
        )
        return escrow_id


def create_visa_transaction(
    account_id: int,
    merchant_account_id: int,
    amount,
    currency: str = "USD",
    description: str = None,
    reference: str = None,
    xml_payload: str = None,
) -> str:
    currency = currency.strip().upper()
    amount_decimal = _to_decimal(amount)
    if amount_decimal <= Decimal("0"):
        raise ValueError("Jumlah transaksi Visa harus lebih besar dari nol.")

    with transaction() as conn:
        account = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        merchant = conn.execute("SELECT * FROM merchant_accounts WHERE id = ?", (merchant_account_id,)).fetchone()
        if account is None:
            raise ValueError("Akun tidak ditemukan.")
        if merchant is None:
            raise ValueError("Merchant tidak ditemukan.")

        if merchant["approved"] == 0:
            raise ValueError("Merchant belum disetujui oleh admin.")

        sender_balance = _to_decimal(account["balance"])
        if sender_balance < amount_decimal:
            raise ValueError("Saldo tidak cukup untuk transaksi Visa.")

        receiver_balance = _to_decimal(merchant["balance"])
        trn = _generate_trn("VISA")
        fraud_score = compute_fraud_score(amount_decimal)
        requires_admin_approval = 1 if amount_decimal > Decimal("1000") else 0
        status = STATUS_PENDING if requires_admin_approval else STATUS_SUCCESS
        approval_status = "PENDING" if requires_admin_approval else "APPROVED"
        now = _now()

        if not requires_admin_approval:
            _update_account_balance(conn, account_id, sender_balance - amount_decimal)
            _update_merchant_balance(conn, merchant_account_id, receiver_balance + amount_decimal)

        _ensure_unique_trn(conn, trn)
        conn.execute(
            "INSERT INTO visa_transactions (trn, account_id, merchant_account_id, amount, currency, status, xml_payload, request_signature, ip_address, fraud_score, requires_admin_approval, approval_status, reference, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trn,
                account_id,
                merchant_account_id,
                _format_amount(amount_decimal),
                currency,
                status,
                xml_payload,
                None,
                None,
                fraud_score,
                requires_admin_approval,
                approval_status,
                reference,
                description,
                now,
                now,
            ),
        )

        log_status = STATUS_PENDING if requires_admin_approval else STATUS_SUCCESS
        _insert_transaction_log(
            conn,
            event_type="visa_debit",
            amount=amount_decimal,
            currency=currency,
            status=log_status,
            details="Visa payment debit",
            account_id=account_id,
            merchant_account_id=merchant_account_id,
            reference=reference,
            trn=trn,
        )
        _insert_transaction_log(
            conn,
            event_type="visa_credit",
            amount=amount_decimal,
            currency=currency,
            status=STATUS_SUCCESS,
            details="Visa payment credit",
            merchant_account_id=merchant_account_id,
            reference=reference,
            trn=trn,
        )
        return trn


def release_escrow(escrow_id: int) -> str:
    with transaction() as conn:
        escrow = conn.execute("SELECT * FROM escrow_settlements WHERE id = ?", (escrow_id,)).fetchone()
        if escrow is None:
            raise ValueError("Escrow tidak ditemukan.")
        if escrow["status"] not in (STATUS_PENDING, STATUS_HOLD):
            raise ValueError("Escrow hanya dapat dilepaskan dari status PENDING atau HOLD.")

        account = conn.execute("SELECT * FROM accounts WHERE id = ?", (escrow["account_id"],)).fetchone()
        if account is None:
            raise ValueError("Akun penerima escrow tidak ditemukan.")

        if escrow["requires_admin_approval"] == 1 and escrow["approval_status"] != "APPROVED":
            raise ValueError("Escrow belum disetujui oleh admin.")

        amount_decimal = _to_decimal(escrow["amount"])
        new_balance = _to_decimal(account["balance"]) + amount_decimal
        _update_account_balance(conn, escrow["account_id"], new_balance)

        now = _now()
        trn = escrow["trn"]
        conn.execute(
            "UPDATE escrow_settlements SET status = ?, release_date = ?, updated_at = ? WHERE id = ?",
            (STATUS_SUCCESS, now, now, escrow_id),
        )
        _insert_transaction_log(
            conn,
            event_type="escrow_release",
            amount=amount_decimal,
            currency=escrow["currency"],
            status=STATUS_SUCCESS,
            details="Dana escrow dirilis ke akun.",
            account_id=escrow["account_id"],
            merchant_account_id=escrow["merchant_account_id"],
            reference=escrow["reference"],
            trn=trn,
        )
        return trn


def create_settlement_report(report_type: str, total_amount, currency: str = "USD", status: str = STATUS_PENDING, payload_xml: str = None) -> int:
    if status not in STATUS_CHOICES:
        raise ValueError("Status laporan tidak valid.")

    amount_decimal = _to_decimal(total_amount)
    now = _now()
    trn = _generate_trn("RPT")
    confirmation_code = _generate_confirmation_code()

    with transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO settlement_reports (trn, report_type, status, total_amount, currency, payload_xml, confirmation_code, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trn, report_type.strip(), status, _format_amount(amount_decimal), currency.strip().upper(), payload_xml, confirmation_code, now, now),
        )
        return cursor.lastrowid


def generate_settlement_xml(report_id: int) -> str:
    with transaction() as conn:
        report = conn.execute("SELECT * FROM settlement_reports WHERE id = ?", (report_id,)).fetchone()
        if report is None:
            raise ValueError("Laporan settlement tidak ditemukan.")

        root = ET.Element("SettlementReport")
        ET.SubElement(root, "TRN").text = report["trn"]
        ET.SubElement(root, "ReportType").text = report["report_type"]
        ET.SubElement(root, "Status").text = report["status"]
        ET.SubElement(root, "TotalAmount").text = report["total_amount"]
        ET.SubElement(root, "Currency").text = report["currency"]
        ET.SubElement(root, "ProcessedAt").text = report["processed_at"] or ""
        ET.SubElement(root, "ConfirmationCode").text = report["confirmation_code"] or ""
        ET.SubElement(root, "CreatedAt").text = report["created_at"]
        ET.SubElement(root, "UpdatedAt").text = report["updated_at"]

        payload_xml = ET.tostring(root, encoding="unicode")
        conn.execute(
            "UPDATE settlement_reports SET payload_xml = ?, updated_at = ? WHERE id = ?",
            (payload_xml, _now(), report_id),
        )
        return payload_xml


def enqueue_quantum_task(payload: str, metadata: str = None, priority: int = 100) -> int:
    trn = _generate_trn("QTK")
    now = _now()
    with transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO quantum_processing_queue (trn, payload, metadata, priority, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (trn, payload, metadata, priority, now, now),
        )
        return cursor.lastrowid


def process_quantum_queue(limit: int = 10) -> int:
    processed = 0
    with transaction() as conn:
        items = conn.execute(
            "SELECT * FROM quantum_processing_queue WHERE status = ? ORDER BY priority ASC, id ASC LIMIT ?",
            (STATUS_PENDING, limit),
        ).fetchall()
        for item in items:
            try:
                conn.execute(
                    "UPDATE quantum_processing_queue SET status = ?, updated_at = ? WHERE id = ?",
                    (STATUS_PROCESSING, _now(), item["id"]),
                )
                conn.execute(
                    "UPDATE quantum_processing_queue SET status = ?, updated_at = ? WHERE id = ?",
                    (STATUS_SUCCESS, _now(), item["id"]),
                )
                processed += 1
            except Exception as exc:
                conn.execute(
                    "UPDATE quantum_processing_queue SET status = ?, metadata = COALESCE(metadata, '') || ?, updated_at = ? WHERE id = ?",
                    (STATUS_FAILED, f" | {str(exc)}", _now(), item["id"]),
                )
    return processed


def create_external_transfer(account_id: int, target_bank: str, target_account: str, amount, currency: str = "USD", request_signature: str = None, ip_address: str = None) -> int:
    amount_decimal = _to_decimal(amount)
    now = _now()
    trn = _generate_trn("EXT")
    with transaction() as conn:
        account = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if account is None:
            raise ValueError("Akun tidak ditemukan untuk transfer eksternal.")
        if _to_decimal(account["balance"]) < amount_decimal:
            raise ValueError("Saldo tidak cukup untuk transfer eksternal.")

        _update_account_balance(conn, account_id, _to_decimal(account["balance"]) - amount_decimal)
        cursor = conn.execute(
            "INSERT INTO external_transfers (trn, account_id, target_bank, target_account, amount, currency, status, xml_payload, request_signature, ip_address, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (trn, account_id, target_bank.strip(), target_account.strip(), _format_amount(amount_decimal), currency.strip().upper(), STATUS_SUCCESS, None, request_signature, ip_address, now, now),
        )
        _insert_transaction_log(
            conn,
            event_type="external_transfer",
            amount=amount_decimal,
            currency=currency,
            status=STATUS_SUCCESS,
            details=f"Transfer ke {target_bank} {target_account}",
            account_id=account_id,
            reference=trn,
            ip_address=ip_address,
        )
        return cursor.lastrowid


def create_uetr_tracking(
    uetr: str,
    trn: str,
    amount,
    currency: str,
    sender_bic: str,
    receiver_bic: str,
    debtor_name: str = None,
    creditor_name: str = None,
) -> int:
    now = _now()
    amount_decimal = _to_decimal(amount)
    with transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO uetr_tracking (uetr, trn, status, stage, amount, currency, sender_bic, receiver_bic, debtor_name, creditor_name, settlement_eta, intermediary_hops, routing_path, tracking_history, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                uetr.strip(),
                trn.strip(),
                STATUS_PENDING,
                "INITIATED",
                _format_amount(amount_decimal),
                currency.strip().upper(),
                sender_bic.strip().upper(),
                receiver_bic.strip().upper(),
                debtor_name.strip() if debtor_name else None,
                creditor_name.strip() if creditor_name else None,
                None,
                "[]",
                "[]",
                "[]",
                now,
                now,
            ),
        )
        return cursor.lastrowid


def create_swift_message(
    message_type: str,
    bic_sender: str,
    bic_receiver: str,
    amount,
    currency: str,
    debtor_name: str,
    creditor_name: str,
    instruction_info: str = None,
    xml_payload: str = None,
    settlement_reference: str = None,
    requires_approval: bool = False,
) -> int:
    amount_decimal = _to_decimal(amount)
    now = _now()
    trn = _generate_trn("SWF")
    uetr = str(uuid4())
    approval_flag = 1 if requires_approval else 0
    approval_status = "PENDING" if requires_approval else "APPROVED"

    with transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO swift_messages (trn, uetr, message_type, status, bic_sender, bic_receiver, amount, currency, debtor_name, creditor_name, instruction_info, xml_payload, settlement_reference, requires_approval, approval_status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trn,
                uetr,
                message_type,
                STATUS_PENDING,
                bic_sender.strip().upper(),
                bic_receiver.strip().upper(),
                _format_amount(amount_decimal),
                currency.strip().upper(),
                debtor_name.strip(),
                creditor_name.strip(),
                instruction_info,
                xml_payload,
                settlement_reference,
                approval_flag,
                approval_status,
                now,
                now,
            ),
        )
        _insert_transaction_log(
            conn,
            event_type="swift_message_created",
            amount=amount_decimal,
            currency=currency,
            status=STATUS_PENDING,
            details=f"SWIFT {message_type} created from {bic_sender} to {bic_receiver}",
            reference=trn,
        )
        return cursor.lastrowid


def get_uetr_tracking(query: str):
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM uetr_tracking WHERE uetr = ? OR trn = ?",
            (query, query),
        )
        return cursor.fetchone()


def list_uetr_tracking(status: str = None):
    with get_connection() as conn:
        if status:
            cursor = conn.execute("SELECT * FROM uetr_tracking WHERE status = ? ORDER BY created_at DESC", (status,))
        else:
            cursor = conn.execute("SELECT * FROM uetr_tracking ORDER BY created_at DESC")
        return cursor.fetchall()


def search_uetr_tracking(query: str):
    q = f"%{query}%"
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM uetr_tracking WHERE uetr LIKE ? OR trn LIKE ? OR sender_bic LIKE ? OR receiver_bic LIKE ? OR status LIKE ? ORDER BY created_at DESC",
            (q, q, q, q, q),
        )
        return cursor.fetchall()


def update_uetr_tracking_status(uetr: str, status: str, stage: str = None, eta: str = None, message: str = None) -> dict:
    if status not in STATUS_CHOICES:
        raise ValueError("Status UETR tidak valid.")
    with transaction() as conn:
        record = conn.execute("SELECT * FROM uetr_tracking WHERE uetr = ?", (uetr,)).fetchone()
        if record is None:
            raise ValueError("UETR tidak ditemukan.")
        history = []
        try:
            history = json.loads(record["tracking_history"] or "[]")
        except json.JSONDecodeError:
            history = []
        history.append({
            "timestamp": _now(),
            "stage": stage or record["stage"],
            "status": status,
            "message": message or "UETR status updated",
            "eta": eta,
        })
        conn.execute(
            "UPDATE uetr_tracking SET status = ?, stage = ?, settlement_eta = ?, tracking_history = ?, updated_at = ? WHERE uetr = ?",
            (status, stage or record["stage"], eta or record["settlement_eta"], json.dumps(history), _now(), uetr),
        )
        return conn.execute("SELECT * FROM uetr_tracking WHERE uetr = ?", (uetr,)).fetchone()


def _resolve_export_path(file_path: str, default_name: str) -> str:
    candidate = (file_path or default_name).strip().strip('"')
    candidate = os.path.abspath(candidate)

    if os.path.isdir(candidate) or candidate.endswith("\\") or candidate.endswith("/"):
        candidate = os.path.join(candidate, default_name)

    if os.path.splitext(candidate)[1] == "":
        candidate = f"{candidate}.xml" if default_name.endswith(".xml") else f"{candidate}.txt"

    parent = os.path.dirname(candidate)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    return candidate


def export_uetr_xml(uetr: str, file_path: str) -> str:
    record = get_uetr_tracking(uetr)
    if record is None:
        raise ValueError("UETR tidak ditemukan.")
    target_path = _resolve_export_path(file_path, f"uetr_{uetr}.xml")
    from uetr_tracking import build_uetr_xml
    with open(target_path, "w", encoding="utf-8") as handle:
        handle.write(build_uetr_xml(dict(record)))
    return target_path


def export_uetr_report(uetr: str, file_path: str) -> str:
    record = get_uetr_tracking(uetr)
    if record is None:
        raise ValueError("UETR tidak ditemukan.")
    target_path = _resolve_export_path(file_path, f"uetr_{uetr}.txt")
    with open(target_path, "w", encoding="utf-8") as handle:
        handle.write("# UETR Settlement Report\n")
        handle.write(f"UETR: {record['uetr']}\n")
        handle.write(f"TRN: {record['trn']}\n")
        handle.write(f"Status: {record['status']}\n")
        handle.write(f"Stage: {record['stage']}\n")
        handle.write(f"Amount: {record['amount']} {record['currency']}\n")
        handle.write(f"Sender BIC: {record['sender_bic']}\n")
        handle.write(f"Receiver BIC: {record['receiver_bic']}\n")
        handle.write(f"History: {record['tracking_history']}\n")
    return target_path


def get_swift_message(trn: str):
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM swift_messages WHERE trn = ?", (trn,))
        return cursor.fetchone()


def list_swift_messages(status: str = None):
    with get_connection() as conn:
        if status:
            cursor = conn.execute("SELECT * FROM swift_messages WHERE status = ? ORDER BY created_at DESC", (status,))
        else:
            cursor = conn.execute("SELECT * FROM swift_messages ORDER BY created_at DESC")
        return cursor.fetchall()


def update_swift_message_status(trn: str, status: str, last_error: str = None) -> bool:
    if status not in STATUS_CHOICES:
        raise ValueError("Status swift message tidak valid.")
    with transaction() as conn:
        now = _now()
        conn.execute(
            "UPDATE swift_messages SET status = ?, last_error = ?, updated_at = ? WHERE trn = ?",
            (status, last_error, now, trn),
        )
        _insert_transaction_log(
            conn,
            event_type="swift_status_update",
            amount=Decimal("0"),
            currency="USD",
            status=status,
            details=f"SWIFT message {trn} moved to {status}",
            reference=trn,
        )
        return True


def approve_swift_message(trn: str, approve: bool = True) -> bool:
    with transaction() as conn:
        swift = conn.execute("SELECT * FROM swift_messages WHERE trn = ?", (trn,)).fetchone()
        if swift is None or swift["approval_status"] != "PENDING":
            return False
        new_status = STATUS_SUCCESS if approve else STATUS_FAILED
        conn.execute(
            "UPDATE swift_messages SET approval_status = ?, status = ?, updated_at = ? WHERE trn = ?",
            ("APPROVED" if approve else "REJECTED", new_status, _now(), trn),
        )
        _insert_transaction_log(
            conn,
            event_type="swift_admin_approval",
            amount=Decimal("0"),
            currency="USD",
            status=new_status,
            details=f"Admin {'approved' if approve else 'rejected'} SWIFT {trn}",
            reference=trn,
        )
        return True


def cancel_swift_message(trn: str) -> bool:
    with transaction() as conn:
        swift = conn.execute("SELECT * FROM swift_messages WHERE trn = ?", (trn,)).fetchone()
        if swift is None or swift["status"] in (STATUS_REVERSED, STATUS_FAILED, STATUS_SUCCESS):
            return False
        conn.execute(
            "UPDATE swift_messages SET status = ?, updated_at = ? WHERE trn = ?",
            (STATUS_REVERSED, _now(), trn),
        )
        _insert_transaction_log(
            conn,
            event_type="swift_cancellation",
            amount=Decimal("0"),
            currency="USD",
            status=STATUS_REVERSED,
            details=f"SWIFT message {trn} cancelled",
            reference=trn,
        )
        return True


def reverse_swift_message(trn: str) -> bool:
    with transaction() as conn:
        swift = conn.execute("SELECT * FROM swift_messages WHERE trn = ?", (trn,)).fetchone()
        if swift is None or swift["status"] != STATUS_SUCCESS:
            return False
        conn.execute(
            "UPDATE swift_messages SET status = ?, updated_at = ? WHERE trn = ?",
            (STATUS_REVERSED, _now(), trn),
        )
        _insert_transaction_log(
            conn,
            event_type="swift_reversal",
            amount=Decimal("0"),
            currency="USD",
            status=STATUS_REVERSED,
            details=f"SWIFT message {trn} reversed",
            reference=trn,
        )
        return True


def process_swift_settlement_queue(limit: int = 10) -> int:
    processed = 0
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM swift_messages WHERE status = ? ORDER BY created_at ASC LIMIT ?",
            (STATUS_PENDING, limit),
        ).fetchall()
        for row in rows:
            try:
                conn.execute(
                    "UPDATE swift_messages SET status = ?, updated_at = ? WHERE trn = ?",
                    (STATUS_PROCESSING, _now(), row["trn"]),
                )
                # Simulate settlement processing
                conn.execute(
                    "UPDATE swift_messages SET status = ?, updated_at = ? WHERE trn = ?",
                    (STATUS_SUCCESS, _now(), row["trn"]),
                )
                _insert_transaction_log(
                    conn,
                    event_type="swift_settlement",
                    amount=Decimal(row["amount"]),
                    currency=row["currency"],
                    status=STATUS_SUCCESS,
                    details=f"SWIFT settlement processed for {row['trn']}",
                    reference=row["trn"],
                )
                processed += 1
            except Exception as exc:
                conn.execute(
                    "UPDATE swift_messages SET status = ?, last_error = ?, retry_count = retry_count + 1, updated_at = ? WHERE trn = ?",
                    (STATUS_FAILED, str(exc), _now(), row["trn"]),
                )
    return processed


def retry_failed_swift_settlement_queue(max_retries: int = 3) -> int:
    retried = 0
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM swift_messages WHERE status = ? AND retry_count < ? ORDER BY updated_at ASC",
            (STATUS_FAILED, max_retries),
        ).fetchall()
        for row in rows:
            new_retry = row["retry_count"] + 1
            new_status = STATUS_PENDING if new_retry <= max_retries else STATUS_FAILED
            conn.execute(
                "UPDATE swift_messages SET retry_count = ?, status = ?, updated_at = ? WHERE trn = ?",
                (new_retry, new_status, _now(), row["trn"]),
            )
            retried += 1
    return retried


def export_swift_xml(trn: str, file_path: str) -> str:
    swift = get_swift_message(trn)
    if swift is None:
        raise ValueError("SWIFT message tidak ditemukan.")
    if not swift["xml_payload"]:
        raise ValueError("SWIFT message belum memiliki XML payload.")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(swift["xml_payload"])
    return file_path


def _ensure_unique_trn(conn, trn: str) -> None:
    exists = conn.execute(
        "SELECT 1 FROM visa_transactions WHERE trn = ? UNION ALL SELECT 1 FROM escrow_settlements WHERE trn = ? UNION ALL SELECT 1 FROM settlement_reports WHERE trn = ? UNION ALL SELECT 1 FROM external_transfers WHERE trn = ? UNION ALL SELECT 1 FROM swift_messages WHERE trn = ? UNION ALL SELECT 1 FROM quantum_processing_queue WHERE trn = ?",
        (trn, trn, trn, trn, trn, trn),
    ).fetchone()
    if exists:
        raise ValueError(f"Duplicate TRN detected: {trn}")


def is_duplicate_trn(trn: str) -> bool:
    with get_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM visa_transactions WHERE trn = ? UNION ALL SELECT 1 FROM escrow_settlements WHERE trn = ? UNION ALL SELECT 1 FROM settlement_reports WHERE trn = ? UNION ALL SELECT 1 FROM external_transfers WHERE trn = ? UNION ALL SELECT 1 FROM swift_messages WHERE trn = ? UNION ALL SELECT 1 FROM quantum_processing_queue WHERE trn = ?",
            (trn, trn, trn, trn, trn, trn),
        ).fetchone()
        return bool(exists)


def validate_merchant_api_key(merchant_id: int, api_key: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT api_key FROM merchant_accounts WHERE id = ?",
            (merchant_id,),
        ).fetchone()
        return bool(row and row["api_key"] == api_key)


def verify_hmac_signature(payload: str, secret: str, signature: str) -> bool:
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def compute_fraud_score(amount, ip_address: str = None, metadata: str = None) -> int:
    amount_value = _to_decimal(amount)
    score = min(100, int(amount_value / Decimal("10") + (10 if ip_address else 0)))
    return score


def _generate_confirmation_code(length: int = 6) -> str:
    return str(uuid4().int)[:length].zfill(length)


def acquire_transaction_lock(trn: str, owner: str, ttl_seconds: int = 30) -> bool:
    now = _now()
    expires = (datetime.utcnow() + timedelta(seconds=ttl_seconds)).replace(microsecond=0).isoformat() + "Z"
    with transaction() as conn:
        existing = conn.execute(
            "SELECT * FROM transaction_locks WHERE trn = ?",
            (trn,),
        ).fetchone()
        if existing:
            if existing["expires_at"] <= now:
                conn.execute(
                    "UPDATE transaction_locks SET lock_owner = ?, locked_at = ?, expires_at = ?, updated_at = ? WHERE trn = ?",
                    (owner, now, expires, now, trn),
                )
                return True
            return False
        conn.execute(
            "INSERT INTO transaction_locks (trn, lock_owner, locked_at, expires_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (trn, owner, now, expires, now, now),
        )
        return True


def release_transaction_lock(trn: str, owner: str) -> bool:
    with transaction() as conn:
        existing = conn.execute(
            "SELECT * FROM transaction_locks WHERE trn = ? AND lock_owner = ?",
            (trn, owner),
        ).fetchone()
        if not existing:
            return False
        conn.execute("DELETE FROM transaction_locks WHERE trn = ?", (trn,))
        return True


def check_settlement_timeouts(timeout_seconds: int = 3600) -> int:
    threshold = (datetime.utcnow() - timedelta(seconds=timeout_seconds)).replace(microsecond=0).isoformat() + "Z"
    with transaction() as conn:
        cursor = conn.execute(
            "UPDATE settlement_reports SET status = ?, updated_at = ? WHERE status = ? AND created_at <= ?",
            (STATUS_FAILED, _now(), STATUS_PENDING, threshold),
        )
        return cursor.rowcount


def retry_failed_queue(max_retries: int = 3, retry_delay_seconds: int = 60) -> int:
    now = _now()
    next_attempt_at = (datetime.utcnow() + timedelta(seconds=retry_delay_seconds)).replace(microsecond=0).isoformat() + "Z"
    retried = 0
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM quantum_processing_queue WHERE status = ? AND retry_count < ? AND (next_attempt_at IS NULL OR next_attempt_at <= ?) ORDER BY updated_at ASC",
            (STATUS_FAILED, max_retries, now),
        ).fetchall()
        for row in rows:
            new_retry = row["retry_count"] + 1
            new_status = STATUS_PENDING if new_retry <= max_retries else STATUS_FAILED
            conn.execute(
                "UPDATE quantum_processing_queue SET retry_count = ?, status = ?, next_attempt_at = ?, updated_at = ? WHERE id = ?",
                (new_retry, new_status, next_attempt_at if new_status == STATUS_PENDING else None, _now(), row["id"]),
            )
            retried += 1
    return retried


def admin_approve_transaction(table_name: str, trn: str, approve: bool = True) -> bool:
    if table_name not in ("visa_transactions", "escrow_settlements"):
        raise ValueError("Unsupported approval table")
    now = _now()
    with transaction() as conn:
        item = conn.execute(f"SELECT * FROM {table_name} WHERE trn = ?", (trn,)).fetchone()
        if item is None or item["approval_status"] != "PENDING":
            return False

        if table_name == "visa_transactions":
            if approve:
                account = conn.execute("SELECT * FROM accounts WHERE id = ?", (item["account_id"],)).fetchone()
                merchant = conn.execute("SELECT * FROM merchant_accounts WHERE id = ?", (item["merchant_account_id"],)).fetchone()
                if account is None or merchant is None:
                    raise ValueError("Akun atau merchant tidak ditemukan untuk persetujuan Visa.")
                amount_value = _to_decimal(item["amount"])
                if _to_decimal(account["balance"]) < amount_value:
                    raise ValueError("Saldo tidak cukup saat approval Visa.")
                _update_account_balance(conn, item["account_id"], _to_decimal(account["balance"]) - amount_value)
                _update_merchant_balance(conn, item["merchant_account_id"], _to_decimal(merchant["balance"]) + amount_value)
                conn.execute(
                    "UPDATE visa_transactions SET approval_status = ?, status = ?, updated_at = ? WHERE trn = ?",
                    ("APPROVED", STATUS_SUCCESS, now, trn),
                )
                final_status = STATUS_SUCCESS
            else:
                conn.execute(
                    "UPDATE visa_transactions SET approval_status = ?, status = ?, updated_at = ? WHERE trn = ?",
                    ("REJECTED", STATUS_FAILED, now, trn),
                )
                final_status = STATUS_FAILED
        else:
            if approve:
                conn.execute(
                    f"UPDATE {table_name} SET approval_status = ?, status = ?, updated_at = ? WHERE trn = ?",
                    ("APPROVED", STATUS_SUCCESS, now, trn),
                )
                final_status = STATUS_SUCCESS
            else:
                conn.execute(
                    f"UPDATE {table_name} SET approval_status = ?, status = ?, updated_at = ? WHERE trn = ?",
                    ("REJECTED", STATUS_FAILED, now, trn),
                )
                final_status = STATUS_FAILED

        _insert_transaction_log(
            conn,
            event_type="admin_approval",
            amount=Decimal("0"),
            currency="USD",
            status=final_status,
            details=f"Admin {'approved' if approve else 'rejected'} {table_name} {trn}",
            reference=trn,
        )
        return True


def log_ip_event(ip_address: str, details: str, event_type: str = "ip_event", account_id: int = None, merchant_account_id: int = None, reference: str = None) -> int:
    with transaction() as conn:
        return _insert_transaction_log(
            conn,
            event_type=event_type,
            amount=Decimal("0"),
            currency="USD",
            status=STATUS_PENDING,
            details=details,
            account_id=account_id,
            merchant_account_id=merchant_account_id,
            reference=reference,
            ip_address=ip_address,
            trn=_generate_trn("IP"),
        )


def delete_account(account_id: int) -> None:
    with transaction() as conn:
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
