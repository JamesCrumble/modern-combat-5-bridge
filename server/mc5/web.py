"""A small stand-in for FastAPI on plain Starlette (documentation/architecture.md).

The bridge runs the server on the phone under CPython 3.14 for Android: pydantic-core (FastAPI's dependency) has no Android build and pydantic 1.x
does not support 3.14. The server uses only a little of FastAPI: route decorators, parameters taken from the path / query string by the function
signature, `Request`, and answers that are Response objects or JSON-able values. That is all done here; the same module runs on the PC.
  @app.get("/x/{name}") def f(name: str, n: int = 3, request: Request): ...   (sync handlers run in a thread, async ones in the loop)
A parameter named `request` (or annotated `Request`) gets the request; a name in the path gets the path value; any other is a query parameter
(`str` default "" when the function says so, cast by the annotation for int / float / bool); a missing one without default -> 422 like FastAPI.
"""
import inspect
from typing import Callable, List, Optional

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, Router

__all__ = ["FastAPI", "Request"]


def _cast(value: str, annotation):
    if annotation is int:
        return int(value)
    if annotation is float:
        return float(value)
    if annotation is bool:
        return value.lower() in ("1", "true", "yes", "on")
    return value


def _adapter(fn: Callable):
    sig = inspect.signature(fn)
    is_async = inspect.iscoroutinefunction(fn)

    async def endpoint(request: Request):
        kwargs = {}
        missing: List[str] = []
        for name, p in sig.parameters.items():
            if name == "request" or p.annotation is Request:
                kwargs[name] = request
            elif name in request.path_params:
                kwargs[name] = request.path_params[name]
            elif name in request.query_params:
                try:
                    kwargs[name] = _cast(request.query_params[name], p.annotation)
                except ValueError:
                    return JSONResponse({"detail": "invalid value for %s" % name}, status_code=422)
            elif p.default is inspect.Parameter.empty:
                missing.append(name)
        if missing:
            return JSONResponse({"detail": [{"loc": ["query", n], "msg": "field required"} for n in missing]}, status_code=422)
        out = await fn(**kwargs) if is_async else await run_in_threadpool(fn, **kwargs)
        return out if isinstance(out, Response) else JSONResponse(out)

    endpoint.__name__ = fn.__name__
    return endpoint


class FastAPI:
    def __init__(self, title: str = ""):
        self.title = title
        self.routes: List[Route] = []
        self._router: Optional[Router] = None

    def api_route(self, path: str, methods=None):
        def deco(fn):
            self.routes.append(Route(path, _adapter(fn), methods=list(methods or ["GET"])))
            self._router = None
            return fn
        return deco

    def get(self, path: str):
        return self.api_route(path, ["GET"])

    def post(self, path: str):
        return self.api_route(path, ["POST"])

    def put(self, path: str):
        return self.api_route(path, ["PUT"])

    def delete(self, path: str):
        return self.api_route(path, ["DELETE"])

    async def __call__(self, scope, receive, send):
        if self._router is None:
            self._router = Router(routes=list(self.routes))
        await self._router(scope, receive, send)
