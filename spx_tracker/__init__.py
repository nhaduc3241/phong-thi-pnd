from .cache import TrackingCache
from .models import Event, SpxError, SpxNotFound, TrackingResult, parse_order_info

__all__ = [
    "SpxTracker",
    "TrackingCache",
    "TrackingResult",
    "Event",
    "SpxError",
    "SpxNotFound",
    "parse_order_info",
]


def __getattr__(name):
    # Import lười để parser/cache dùng được mà không cần cài Playwright
    if name == "SpxTracker":
        from .tracker import SpxTracker

        return SpxTracker
    raise AttributeError(name)
