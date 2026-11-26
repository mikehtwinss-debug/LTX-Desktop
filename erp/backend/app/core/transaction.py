"""One database transaction per HTTP request, owned by the route wrapper."""

from collections.abc import Callable, Coroutine
from typing import Any

import anyio
from fastapi import Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.routing import APIRoute


class TransactionalRoute(APIRoute):
    """Creates the request session, commits before the response is returned, rolls back on any error.

    The commit happens here, not in a `yield` dependency, because dependency teardown runs after the
    response has been sent: a client could otherwise see a success for data that failed to commit.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def transactional_handler(request: Request) -> Response:
            session = request.app.state.session_factory()
            request.state.db = session
            try:
                response = await handler(request)
                await run_in_threadpool(session.commit)
            except BaseException:
                # Shielded so the connection is cleaned up even when the request task was cancelled.
                with anyio.CancelScope(shield=True):
                    await run_in_threadpool(session.rollback)
                raise
            finally:
                with anyio.CancelScope(shield=True):
                    await run_in_threadpool(session.close)
            return response

        return transactional_handler
