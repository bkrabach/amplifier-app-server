"""Chat API for Cortex Core interaction."""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from amplifier_server.session_manager import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# Injected managers
_session_manager: SessionManager | None = None


def inject_managers(session_manager: SessionManager) -> None:
    """Inject session manager."""
    global _session_manager
    _session_manager = session_manager


@router.websocket("/cortex")
async def chat_cortex_core(websocket: WebSocket):
    """WebSocket endpoint for chatting with Cortex Core.

    Connects to the long-running cortex-core session and enables
    conversational interaction.
    """
    await websocket.accept()

    if not _session_manager:
        await websocket.send_json({"error": "Session manager not available"})
        await websocket.close()
        return

    try:
        # Session should exist (created at startup)
        core_id = "cortex-core"

        logger.info("Chat connection established to Cortex Core")

        # Chat loop
        while True:
            # Receive message from user
            data = await websocket.receive_json()
            message = data.get("message", "")

            if not message:
                continue

            logger.info(f"User message: {message[:100]}")

            # Execute in Core session
            try:
                response = await _session_manager.execute(
                    session_id=core_id,
                    prompt=message,
                )

                # Send response back
                await websocket.send_json(
                    {
                        "response": response,
                        "session_id": core_id,
                    }
                )

            except Exception as e:
                logger.error(f"Core execution error: {e}")
                await websocket.send_json({"error": str(e)})

    except WebSocketDisconnect:
        logger.info("Chat connection closed")
    except Exception as e:
        logger.error(f"Chat error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass
