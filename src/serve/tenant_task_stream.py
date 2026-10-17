"""Bounded tenant-native status SSE; no execution or A2A conformance claim."""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from dataclasses import asdict

from starlette.responses import StreamingResponse

_pending_cleanup = set()


async def acquire_stream_lease(coordinator, principal, release_local):
    """Release an allocation even if its requester leaves during SQL admission.

    Cancelling to_thread cannot stop its database operation. Keep its result
    alive and clean up after the worker completes; lease expiry remains the
    recovery path if this process itself dies or SQL cleanup is unavailable.
    """
    pending = asyncio.create_task(asyncio.to_thread(coordinator.acquire, principal))
    try:
        return await asyncio.shield(pending)
    except BaseException:
        release_local()

        async def cleanup():
            with suppress(Exception, asyncio.CancelledError):
                lease = await pending
                await asyncio.to_thread(coordinator.release, lease)

        task = asyncio.create_task(cleanup())
        _pending_cleanup.add(task)
        task.add_done_callback(_pending_cleanup.discard)
        raise


class TenantTaskStream(StreamingResponse):
    def __init__(self, request, session, task_id, *, after_sequence, coordinator, lease, limits, release_local):
        self.session, self.coordinator, self.lease = session, coordinator, lease
        self.release_local = release_local
        self.seconds = min(limits.max_seconds, coordinator.limits.max_seconds)
        self.send_seconds = min(coordinator.limits.lease_seconds / 2, 1)

        async def events():
            cursor = after_sequence
            heartbeat = time.monotonic()
            deadline = time.monotonic() + self.seconds
            while time.monotonic() < deadline and not await request.is_disconnected():
                rows = await asyncio.to_thread(session.task_events, task_id, after_sequence=cursor, limit=limits.page_size)
                for task in rows:
                    cursor = task.sequence
                    yield "id: " + str(cursor) + "\ndata: " + json.dumps(asdict(task), separators=(",", ":")) + "\n\n"
                    if task.terminal or task.state.value in ("input-required", "auth-required"):
                        return
                if not rows:
                    current = await asyncio.to_thread(session.task, task_id)
                    # A state change between the empty page and this read must
                    # still be replayed on the next poll, including its final event.
                    if current.sequence == cursor and (
                        current.terminal or current.state.value in ("input-required", "auth-required")
                    ):
                        return
                if time.monotonic() - heartbeat >= limits.heartbeat_seconds:
                    yield ": keep-alive\n\n"
                    heartbeat = time.monotonic()
                # Renewal/check during quiet periods, not only when data exists.
                await asyncio.to_thread(coordinator.renew, session.principal, lease)
                await asyncio.sleep(limits.poll_seconds)

        super().__init__(events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    async def __call__(self, scope, receive, send):
        started = False
        before_start_error = None

        async def fenced_send(message):
            nonlocal started, before_start_error
            # Check immediately before ASGI send, including buffered pages and
            # response headers. This cannot retract bytes already sent to TCP.
            try:
                await asyncio.to_thread(self.coordinator.renew, self.session.principal, self.lease)
            except Exception as exc:
                if not started:
                    before_start_error = exc
                raise
            await asyncio.wait_for(send(message), timeout=self.send_seconds)
            if message["type"] == "http.response.start":
                started = True

        try:
            async with asyncio.timeout(self.seconds):
                await super().__call__(scope, receive, fenced_send)
        except (Exception, asyncio.CancelledError):
            if not started:
                # Let exception middleware map a denial before headers. Sending
                # a body here would violate ASGI and turn it into a server error.
                # Starlette treats PermissionError (an OSError) as disconnect;
                # retain the actual initial check error for the HTTP handler.
                if before_start_error is not None:
                    raise before_start_error
                raise
            # A started response cannot change its HTTP status. Closing preserves
            # uncertainty; reconnect uses a new signed request and cursor.
            with suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(send({"type": "http.response.body", "body": b"", "more_body": False}), timeout=.1)
        finally:
            self.release_local()
            with suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(asyncio.to_thread(self.coordinator.release, self.lease)), timeout=.2)
