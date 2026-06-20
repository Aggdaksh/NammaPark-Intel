"""Circuit breaker helper for optional external services."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar


T = TypeVar("T")


def optional_service(default: T) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return fn(*args, **kwargs)
            except Exception:
                return default

        return wrapper

    return decorator
