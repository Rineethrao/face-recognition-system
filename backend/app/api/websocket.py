import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.detection_service import detection_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WebSocket Integration"])

@router.websocket("/ws/live")
async def websocket_live_feed(websocket: WebSocket):
    """
    WebSocket endpoint broadcasting real-time recognition events and live system metrics.
    Connect at ws://127.0.0.1:8000/ws/live
    """
    await websocket.accept()
    logger.info("New WebSocket client connected to /ws/live")
    last_event_count = 0

    try:
        while True:
            # Check for new recognition events
            current_events = detection_service.recent_events
            if len(current_events) > last_event_count:
                new_events = current_events[last_event_count:]
                last_event_count = len(current_events)

                payload = {
                    "type": "RECOGNITION_EVENT",
                    "events": [e.model_dump() if hasattr(e, "model_dump") else e.dict() for e in new_events]
                }
                await websocket.send_json(payload)

            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from /ws/live")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
