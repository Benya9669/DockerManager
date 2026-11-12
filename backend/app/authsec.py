"""Login throttling, one-time websocket tickets and request context (client IP)."""
import secrets
import threading
import time
from collections import defaultdict, deque
from contextvars import ContextVar

client_ip: ContextVar[str] = ContextVar("client_ip", default="")


class LoginThrottle:
    """Block an IP / username after too many failed logins in a sliding window."""

    def __init__(self, window: int = 900, max_per_ip: int = 10, max_per_user: int = 20, block: int = 900):
        self.window, self.max_ip, self.max_user, self.block = window, max_per_ip, max_per_user, block
        self.fails: dict[str, deque] = defaultdict(deque)
        self.blocked_until: dict[str, float] = {}
        self.lock = threading.Lock()

    def _keys(self, ip: str, username: str) -> list[tuple[str, int]]:
        return [(f"ip:{ip}", self.max_ip), (f"user:{username.lower()}", self.max_user)]

    def retry_after(self, ip: str, username: str) -> int:
        now = time.time()
        with self.lock:
            until = max((self.blocked_until.get(k, 0) for k, _ in self._keys(ip, username)), default=0)
        return max(0, int(until - now))

    def fail(self, ip: str, username: str) -> None:
        now = time.time()
        with self.lock:
            for key, limit in self._keys(ip, username):
                q = self.fails[key]
                q.append(now)
                while q and q[0] < now - self.window:
                    q.popleft()
                if len(q) >= limit:
                    self.blocked_until[key] = now + self.block
                    q.clear()

    def success(self, ip: str, username: str) -> None:
        with self.lock:
            for key, _ in self._keys(ip, username):
                self.fails.pop(key, None)
                self.blocked_until.pop(key, None)


throttle = LoginThrottle()


class WsTickets:
    """Short-lived single-use tickets so session tokens never appear in websocket URLs / proxy logs."""

    TTL = 30

    def __init__(self) -> None:
        self.items: dict[str, tuple[int, float]] = {}
        self.lock = threading.Lock()

    def issue(self, user_id: int) -> str:
        t = secrets.token_urlsafe(32)
        now = time.time()
        with self.lock:
            for k in [k for k, (_, exp) in self.items.items() if exp < now]:
                del self.items[k]
            self.items[t] = (user_id, now + self.TTL)
        return t

    def consume(self, ticket: str | None) -> int | None:
        if not ticket:
            return None
        with self.lock:
            item = self.items.pop(ticket, None)
        if not item or item[1] < time.time():
            return None
        return item[0]


ws_tickets = WsTickets()
