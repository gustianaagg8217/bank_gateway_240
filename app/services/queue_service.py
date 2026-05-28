import asyncio
import logging
from datetime import datetime
from typing import Dict, List

logger = logging.getLogger("enterprise_gateway.queue")


class QueueService:
    def __init__(self) -> None:
        self.queue: List[Dict[str, object]] = []

    def enqueue(self, item: Dict[str, object]) -> Dict[str, object]:
        item = {**item, "queued_at": datetime.utcnow().isoformat(), "retry_count": 0}
        self.queue.append(item)
        logger.info("Queued %s", item)
        return item

    def list(self) -> List[Dict[str, object]]:
        return list(self.queue)

    def retry_failed(self) -> int:
        for item in self.queue:
            if item.get("status") == "FAILED":
                item["status"] = "PENDING"
                item["retry_count"] = int(item.get("retry_count", 0)) + 1
        return sum(1 for item in self.queue if item.get("status") == "PENDING")
