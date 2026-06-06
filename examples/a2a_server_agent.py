"""
A real, runnable A2A server agent (official a2a-sdk, JSON-RPC transport).

This is a genuine A2A agent — not a mock. It serves an AgentCard at
/.well-known/agent-card.json and handles message/send over JSON-RPC. Used by
live_a2a_handshake.py to prove the bridge can sit in front of a real A2A agent.

Run standalone:  python examples/a2a_server_agent.py   (serves on 127.0.0.1:8731)
"""

import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.agent_execution import AgentExecutor
from a2a.types import AgentCard, AgentCapabilities, AgentSkill
from a2a.utils import new_agent_text_message

HOST = "127.0.0.1"
PORT = 8731


class EchoExecutor(AgentExecutor):
    """Minimal real A2A agent: echoes the user's text back as an agent message."""

    async def execute(self, context, event_queue):
        text = context.get_user_input() or ""
        await event_queue.enqueue_event(new_agent_text_message(f"echo: {text}"))

    async def cancel(self, context, event_queue):
        raise Exception("cancel not supported by demo agent")


def build_app():
    card = AgentCard(
        name="agentbridge-demo-a2a",
        description="Demo A2A echo agent for live bridge testing",
        url=f"http://{HOST}:{PORT}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(
                id="echo",
                name="Echo",
                description="Echoes the provided text back to the caller",
                tags=["demo"],
            )
        ],
    )
    handler = DefaultRequestHandler(
        agent_executor=EchoExecutor(),
        task_store=InMemoryTaskStore(),
    )
    return A2AStarletteApplication(agent_card=card, http_handler=handler).build()


if __name__ == "__main__":
    uvicorn.run(build_app(), host=HOST, port=PORT, log_level="warning")
