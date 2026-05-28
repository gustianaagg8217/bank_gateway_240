import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.config import ADMIN_TOKEN, BASE_DIR
from app.database import get_db, init_db
from app.schemas import DashboardSummary, UETRCreateRequest, UETRResponse
from app.services.aml_service import AMLService
from app.services.fraud_service import FraudService
from app.services.iso20022_service import ISO20022Service
from app.services.mt103_service import MT103Service
from app.services.queue_service import QueueService
from app.services.routing_service import RoutingService
from app.services.settlement_service import SettlementService
from app.services.uetr_service import UETRService as UETRDomainService
from app.websocket import manager
from app.worker import queue_worker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("enterprise_gateway")

stop_event = asyncio.Event()
worker_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker_task
    init_db()
    worker_task = asyncio.create_task(queue_worker(stop_event))
    yield
    stop_event.set()
    if worker_task:
        worker_task.cancel()


app = FastAPI(title="Enterprise SWIFT Gateway", version="2.50", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


async def require_admin(x_admin_token: str = Header(default="")):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin token required")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "enterprise-swift-gateway"}


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard() -> HTMLResponse:
    with open(str(BASE_DIR / "static" / "index.html"), "r", encoding="utf-8") as handle:
        return HTMLResponse(handle.read())


@app.get("/api/dashboard/summary", response_model=DashboardSummary)
async def dashboard_summary(db: Session = Depends(get_db), admin: None = Depends(require_admin)):
    uetr_service = UETRDomainService(db)
    rows = uetr_service.list()
    return DashboardSummary(
        total_uetr=len(rows),
        pending_uetr=sum(1 for r in rows if r.status == "PENDING"),
        success_uetr=sum(1 for r in rows if r.status == "SUCCESS"),
        failed_uetr=sum(1 for r in rows if r.status in ("FAILED", "REVERSED")),
    )


@app.post("/api/uetr", response_model=UETRResponse)
async def create_uetr(payload: UETRCreateRequest, db: Session = Depends(get_db), admin: None = Depends(require_admin)):
    service = UETRDomainService(db)
    record = service.create(payload.amount, payload.currency, payload.sender_bic, payload.receiver_bic, payload.debtor_name, payload.creditor_name)
    return UETRResponse.model_validate(record)


@app.get("/api/uetr", response_model=list[UETRResponse])
async def list_uetr(db: Session = Depends(get_db), admin: None = Depends(require_admin)):
    service = UETRDomainService(db)
    return [UETRResponse.model_validate(row) for row in service.list()]


@app.post("/api/settlement/mt103")
async def generate_mt103(amount: float, bic_sender: str, bic_receiver: str, db: Session = Depends(get_db), admin: None = Depends(require_admin)):
    service = SettlementService(db)
    return {"record": service.generate_mt103(amount, bic_sender, bic_receiver).trn}


@app.post("/api/settlement/aml")
async def aml_score(amount: float, sender_bic: str, receiver_bic: str, admin: None = Depends(require_admin)):
    return AMLService().score(amount, sender_bic, receiver_bic)


@app.post("/api/settlement/fraud")
async def fraud_analysis(amount: float, sender_bic: str, receiver_bic: str, admin: None = Depends(require_admin)):
    return FraudService().analyze(amount, sender_bic, receiver_bic)


@app.post("/api/settlement/route")
async def route_sim(amount: float, sender_bic: str, receiver_bic: str, admin: None = Depends(require_admin)):
    return RoutingService().simulate_route(sender_bic, receiver_bic, amount)


@app.post("/api/settlement/iso20022")
async def iso20022_generate(uetr: str, amount: float, currency: str, sender_bic: str, receiver_bic: str, admin: None = Depends(require_admin)):
    return {"xml": ISO20022Service().generate_pacs008(uetr, amount, currency, sender_bic, receiver_bic)}


@app.get("/api/queue")
async def queue_list(admin: None = Depends(require_admin)):
    return QueueService().list()


@app.get("/api/audit")
async def audit_log(db: Session = Depends(get_db), admin: None = Depends(require_admin)):
    return [{"id": row.id, "trn": row.trn, "event_type": row.event_type, "status": row.status, "details": row.details} for row in SettlementService(db).audit_log()]


@app.websocket("/ws/track")
async def websocket_track(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_text("connected")
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
