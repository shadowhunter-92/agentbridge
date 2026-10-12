"""Actual loopback network tests for the bounded CONNECT reference relay."""
import asyncio
import socket
import pytest

from src.proxy.restricted_connect import serve_client


async def _roundtrip(request, allowed=frozenset({"api.example.com"})):
    server = await asyncio.start_server(
        lambda reader, writer: serve_client(reader, writer, allowed),
        "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(request)
        await writer.drain()
        response = await asyncio.wait_for(reader.read(2048), 5)
        writer.close()
        await writer.wait_closed()
        return response
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize("raw_request", [
    b"GET http://api.example.com/ HTTP/1.1\r\nHost: api.example.com\r\n\r\n",
    b"CONNECT 127.0.0.1:443 HTTP/1.1\r\nHost: 127.0.0.1:443\r\n\r\n",
    b"CONNECT evil.example.com:443 HTTP/1.1\r\nHost: evil.example.com:443\r\n\r\n",
    b"CONNECT api.example.com:80 HTTP/1.1\r\nHost: api.example.com:80\r\n\r\n",
    b"CONNECT api.example.com:443 HTTP/1.1\r\nHost: evil.example.com:443\r\n\r\n",
    b"CONNECT api.example.com:443 HTTP/1.1\r\nHost: api.example.com:443\r\nContent-Length: 1\r\n\r\n",
    b"CONNECT api.example.com:443 HTTP/1.1\r\nHost: api.example.com:443\r\nTransfer-Encoding: chunked\r\n\r\n",
    b"CONNECT api.example.com:443 HTTP/1.1\r\nHost: api.example.com:443\r\nHost: api.example.com:443\r\n\r\n",
    b"CONNECT api.example.com:443 HTTP/1.1\r\nHost: api.example.com:443\r\nBad_Header: invalid\r\n\r\n",
    b"CONNECT api.example.com:443 HTTP/1.1\r\n\r\n",
])
def test_restricted_proxy_rejects_malformed_and_nonallowlisted_network_requests(raw_request):
    response = asyncio.run(_roundtrip(raw_request))
    assert response.startswith(b"HTTP/1.1 403 Forbidden")
