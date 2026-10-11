"""Isolated HTTP transport fault injection: server commits then disconnects.

No external network, credentials or customer systems are used. Tests a real
TCP/HTTP lost-ack pattern rather than just raising a synthetic Python error.
"""
import asyncio
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from src.governance.store import SqliteStore
from src.governance.identity import IdentityRegistry, AgentIdentity
from src.governance.budget import BudgetManager, Budget
from src.governance.gateway import GovernanceGateway, GovernanceError
from src.governance.operation_ledger import OperationLedger, OperationConflict
from src.protocols.canonical import CanonicalCall


class CommitThenDisconnect(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(size)
        self.server.effects.append(self.path)
        # The simulated target records its side effect but does not send a
        # response, matching an acknowledgement lost after possible commit.
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()

    def log_message(self, *args):
        pass


def test_real_loopback_transport_loses_ack_and_does_not_reexecute(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), CommitThenDisconnect)
    server.effects = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    store = SqliteStore(str(tmp_path / "transport.db"))
    try:
        identities = IdentityRegistry(store)
        identities.register(AgentIdentity.generate("agent"))
        budgets = BudgetManager(store)
        budgets.set_budget("agent", Budget(spend_limit=1.0, rate_limit=20))
        gateway = GovernanceGateway(identities=identities, budgets=budgets)
        wire = gateway.registry.get("openai").from_canonical_call(
            CanonicalCall("charge", {"amount": 100}))
        url = f"http://127.0.0.1:{server.server_address[1]}/simulated-charge"

        async def real_http_invoke(dst_wire):
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.post(url, json=dst_wire)
                response.raise_for_status()
                return response.json()

        params=dict(agent_id="agent",src_proto="openai",dst_proto="mcp",
                    src_wire=wire,invoke=real_http_invoke,cost=1.0,
                    operation_id="loopback-test-operation-00001")
        with pytest.raises(httpx.TransportError):
            asyncio.run(gateway.route_call(**params))
        assert server.effects == ["/simulated-charge"]
        assert OperationLedger(store).get("agent", params["operation_id"])["state"]=="unknown"
        assert budgets.get("agent").reserved == 1.0
        with pytest.raises((OperationConflict, GovernanceError)):
            asyncio.run(gateway.route_call(**params))
        assert server.effects == ["/simulated-charge"]
    finally:
        store.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
