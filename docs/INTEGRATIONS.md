# Framework integrations

Agent frameworks — **LangChain, CrewAI, AutoGen, LlamaIndex**, the OpenAI SDK — all emit
tool calls in the **OpenAI function-calling shape**. So one helper lets any of them reach a
tool or agent that lives behind a *different* protocol (MCP, A2A, ACP, Gemini, AGNTCY)
through the bridge — without that framework implementing those protocols itself.

Zero new dependencies. The helper (`src/integrations`) is a thin, tested convenience over
the canonical mesh.

## The 2-line core

```python
from src.integrations import bridge_tool_call

# Route a framework tool call to a live target on ANY protocol; get an OpenAI
# tool-result back that your framework can consume directly.
result = await bridge_tool_call("add", {"a": 2, "b": 3}, to="mcp", invoke=call_mcp_tool)
```

`invoke(target_wire)` is your transport — it delivers the translated call to the live target
and returns its response. Ready-made clients (MCP stdio, A2A HTTP, ACP REST) live in
`src/proxy/transport.py`.

Pure translation, no network:

```python
from src.integrations import translate_tool_call
translate_tool_call("add", {"a": 2, "b": 3}, to="a2a")   # -> a real A2A task
```

---

## Recipes (wrap it for your framework)

> The core helper is unit-tested. The snippets below are integration *patterns* — adapt to
> your installed framework version.

### LangChain — expose any A2A/ACP/MCP agent as a LangChain `Tool`

```python
from langchain_core.tools import StructuredTool
from src.integrations import bridge_tool_call
from src.proxy import transport

async def remote_add(a: int, b: int) -> str:
    res = await bridge_tool_call("add", {"a": a, "b": b}, to="mcp",
                                 invoke=lambda w: transport.call_mcp_tool(
                                     "python", ["mcp_server_agent.py"], w["params"]["name"], w["params"]["arguments"]))
    return res["content"]

tool = StructuredTool.from_function(coroutine=remote_add, name="remote_add",
                                    description="Add two numbers via a remote MCP agent")
```

### CrewAI — give an agent a cross-protocol tool

```python
from crewai.tools import tool
from src.integrations import bridge_tool_call

@tool("remote_add")
async def remote_add(a: int, b: int) -> str:
    "Add two numbers via a remote agent on another protocol."
    res = await bridge_tool_call("add", {"a": a, "b": b}, to="a2a", invoke=my_a2a_transport)
    return res["content"]
```

### AutoGen — register a function the assistant can call

```python
from src.integrations import bridge_tool_call

async def remote_add(a: int, b: int) -> str:
    res = await bridge_tool_call("add", {"a": a, "b": b}, to="acp", invoke=my_acp_transport)
    return res["content"]

# autogen: register_function(remote_add, caller=assistant, executor=user_proxy, name="remote_add", ...)
```

### LlamaIndex — a `FunctionTool`

```python
from llama_index.core.tools import FunctionTool
from src.integrations import bridge_tool_call

async def remote_add(a: int, b: int) -> str:
    res = await bridge_tool_call("add", {"a": a, "b": b}, to="gemini", invoke=my_transport)
    return res["content"]

tool = FunctionTool.from_defaults(async_fn=remote_add, name="remote_add")
```

---

## Why this is the wedge

Your LangChain/CrewAI/AutoGen agent stays exactly as it is. It calls a normal tool. Behind
that tool, AgentBridge translates the call to whatever protocol the real tool/agent speaks,
optionally governs it (identity, budget, audit — see `examples/demo_story.py`), and hands
back a result in the shape your framework expects. One integration, every protocol.
