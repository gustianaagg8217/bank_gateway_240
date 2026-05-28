import asyncio
import logging
from datetime import datetime

logger = logging.getLogger("enterprise_gateway.worker")


async def queue_worker(stop_event: asyncio.Event) -> None:
    """Simple async worker that simulates settlement queue processing."""
    while not stop_event.is_set():
        logger.info("Queue worker heartbeat %s", datetime.utcnow().isoformat())
        await asyncio.sleep(5)
