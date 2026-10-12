"""Minimal bounded sandbox CONNECT relay with DNS/IP enforcement.

Reference isolated egress gateway; not a production-reviewed proxy. It only
accepts HTTP CONNECT host:443, resolves once, rejects mixed/private addresses,
connects to a pinned numeric IP and tunnels bytes without inspecting TLS.
"""
import asyncio
import hmac
import os
from .egress_policy import EgressDenied, parse_allowed_hosts, parse_connect_target, resolve_global_addresses


async def serve_client(reader, writer, hosts, auth_token=None):
    upstream = None
    try:
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        if len(header) > 8192:
            raise EgressDenied("oversized headers")
        lines = header.split(b"\r\n")
        if len(lines) < 3 or len(lines) > 32:
            raise EgressDenied("malformed request headers")
        try:
            request = lines[0].decode("ascii")
        except UnicodeError as exc:
            raise EgressDenied("non-ASCII request") from exc
        words = request.split(" ")
        if len(words) != 3 or words[0] != "CONNECT" or words[2] != "HTTP/1.1":
            raise EgressDenied("CONNECT is the only supported method")
        if any(line and (line.startswith((b" ", b"\t")) or b":" not in line)
               for line in lines[1:-2]):
            raise EgressDenied("malformed HTTP headers")
        # Reject request-smuggling ambiguity: CONNECT has no HTTP body,
        # repeated Host/Authorization headers, or connection re-framing.
        for line in lines[1:-2]:
            if b"\x00" in line:
                raise EgressDenied("NUL in HTTP header")
            try:
                name, value = line.split(b":", 1)
            except ValueError as exc:
                raise EgressDenied("malformed header field") from exc
            if not name or not all(
                (65 <= c <= 90) or (97 <= c <= 122) or (48 <= c <= 57) or c == 45
                for c in name
            ):
                raise EgressDenied("invalid header name")
            if name.lower() in (
                b"transfer-encoding", b"content-length", b"proxy-connection",
                b"upgrade", b"connection",
            ):
                raise EgressDenied("framing or connection headers forbidden on CONNECT")
        if auth_token is not None:
            proxy_auth = [line.split(b":", 1)[1].strip() for line in lines[1:-2]
                          if line.lower().startswith(b"proxy-authorization:")]
            if (len(proxy_auth) != 1
                    or not hmac.compare_digest(proxy_auth[0], b"Bearer " + auth_token)):
                raise EgressDenied("proxy caller not authenticated")
        host, port = parse_connect_target(words[1], hosts)
        # Reject potentially ambiguous Host header or proxy authentication.
        provided_host = [line.split(b":", 1)[1].strip().lower()
                         for line in lines[1:-2] if line.lower().startswith(b"host:")]
        if len(provided_host) != 1 or provided_host[0] != words[1].lower().encode():
            raise EgressDenied("Host header must match CONNECT authority")
        addresses = await asyncio.wait_for(
            asyncio.to_thread(resolve_global_addresses, host, port), timeout=5)
        for ip in addresses:
            try:
                upstream = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=5)
                break
            except (OSError, asyncio.TimeoutError):
                continue
        if upstream is None:
            raise EgressDenied("destination unavailable")
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        remote_reader, remote_writer = upstream

        async def relay(source, target):
            try:
                while data := await source.read(16384):
                    target.write(data)
                    await target.drain()
            finally:
                target.close()

        await asyncio.wait_for(
            asyncio.gather(relay(reader, remote_writer),
                           relay(remote_reader, writer)),
            timeout=120)
    except (EgressDenied, asyncio.IncompleteReadError, asyncio.LimitOverrunError,
            UnicodeError, asyncio.TimeoutError, OSError, ValueError):
        if not writer.is_closing():
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            try:
                await writer.drain()
            except OSError:
                pass
    finally:
        if upstream is not None:
            upstream[1].close()
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


async def start(host="127.0.0.1", port=3128):
    hosts = parse_allowed_hosts(os.environ.get("AGENTBRIDGE_EGRESS_ALLOWED_HOSTS", ""))
    if host not in ("127.0.0.1", "::1"):
        # Bind to the private container interface only in the disposable,
        # separately networked integration drill. No production exposure.
        if (host != "0.0.0.0"
                or os.getenv("AGENTBRIDGE_EGRESS_DRILL_ONLY") != "1"
                or os.getenv("AGENTBRIDGE_ENV", "").lower() in ("prod", "production")):
            raise ValueError("non-loopback reference proxy requires isolated drill mode")
    token = None
    if host == "0.0.0.0":
        token_value = os.getenv("AGENTBRIDGE_EGRESS_DRILL_BEARER_TOKEN", "")
        if len(token_value) < 32 or len(token_value) > 1024 or not token_value.isascii():
            raise ValueError("isolated drill relay requires a long bearer token")
        token = token_value.encode("ascii")
    return await asyncio.start_server(
        lambda r, w: serve_client(r, w, hosts, auth_token=token), host, port, limit=8192)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=3128)
    args = p.parse_args()
    async def run():
        srv = await start(args.host, args.port)
        async with srv:
            await srv.serve_forever()
    asyncio.run(run())


if __name__ == "__main__":
    main()
