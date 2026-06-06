"""
A real, runnable ACP agent (Agent Communication Protocol — IBM/BeeAI / Linux Foundation).

NOTE: acp-sdk 1.0.3's bundled `Server` class is broken against current uvicorn
(references removed `uvicorn.config` symbols). So this serves the real ACP REST shape
with FastAPI/uvicorn directly, while validating every request and response against the
OFFICIAL `acp_sdk.models` (RunCreateRequest / Run / Message). The wire bytes are real ACP.

Endpoint: POST /runs  (sync mode) -> returns a completed Run whose output echoes the input.

Run standalone:  python examples/acp_server_agent.py   (serves on 127.0.0.1:8732)
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

from acp_sdk.models import RunCreateRequest, Run, RunStatus, Message, MessagePart

HOST, PORT = "127.0.0.1", 8732
app = FastAPI(title="agentbridge-demo-acp")


def _input_text(req: RunCreateRequest) -> str:
    texts = []
    for msg in req.input:
        for part in msg.parts:
            if (part.content_type or "").startswith("text/") and part.content:
                texts.append(part.content)
    return " ".join(texts)


@app.get("/agents")
async def agents():
    # Minimal ACP-style discovery.
    return {"agents": [{"name": "echo", "description": "Echoes input text"}]}


@app.post("/runs")
async def create_run(request: Request):
    body = await request.json()
    # Validate the incoming body against the REAL ACP schema.
    req = RunCreateRequest.model_validate(body)
    reply = f"echo: {_input_text(req)}"
    run = Run(
        agent_name=req.agent_name,
        status=RunStatus("completed"),
        output=[Message(role="agent",
                        parts=[MessagePart(content=reply, content_type="text/plain")])],
    )
    return JSONResponse(run.model_dump(mode="json", exclude_none=True))


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
