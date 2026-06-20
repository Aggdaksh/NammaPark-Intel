"""Cache helper hooks for API read paths."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar


T = TypeVar("T")


def cache_first(read_cache: Callable[[], T | None], read_origin: Callable[[], T]) -> T:
    cached = read_cache()
    return cached if cached is not None else read_origin()


def cache_first_decorator(read_cache: Callable[..., Any | None]) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            cached = read_cache(*args, **kwargs)
            return cached if cached is not None else fn(*args, **kwargs)

        return wrapper

    return decorator
