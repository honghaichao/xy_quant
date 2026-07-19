"""令牌桶限频工具。"""
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic, sleep


@dataclass
class TokenBucketRateLimiter:
    """Simple token bucket rate limiter."""

    capacity: int
    refill_rate: float
    tokens: float = field(init=False)
    last_refill: float = field(init=False)
    _lock: Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize limiter state."""
        if self.capacity <= 0:
            raise ValueError("capacity must be positive")
        if self.refill_rate <= 0:
            raise ValueError("refill_rate must be positive")
        self.tokens = float(self.capacity)
        self.last_refill = monotonic()
        self._lock = Lock()

    def consume(self, tokens: int = 1) -> bool:
        """Consume tokens if available."""
        if tokens <= 0:
            raise ValueError("tokens must be positive")
        with self._lock:
            self._refill()
            if self.tokens < tokens:
                return False
            self.tokens -= tokens
            return True

    def acquire(self, tokens: int = 1) -> bool:
        """Block until the requested tokens are available and consume them."""
        if tokens <= 0:
            raise ValueError("tokens must be positive")
        while True:
            with self._lock:
                self._refill()
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True
                wait_seconds = self._wait_seconds(tokens)
            sleep(wait_seconds)

    def available_tokens(self) -> float:
        """Return currently available tokens."""
        with self._lock:
            self._refill()
            return self.tokens

    def _wait_seconds(self, tokens: int = 1) -> float:
        deficit = max(tokens - self.tokens, 0.0)
        return deficit / self.refill_rate if deficit > 0 else 0.0

    def _refill(self) -> None:
        """Refill tokens based on elapsed monotonic time."""
        now = monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
