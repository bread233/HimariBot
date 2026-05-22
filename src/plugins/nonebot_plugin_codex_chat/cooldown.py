import time

class UserCooldown:
    def __init__(self, seconds: int) -> None:
        self.seconds = max(int(seconds), 0)
        self._next_allowed: dict[int, float] = {}

    def remaining(self, user_id: int) -> int:
        now = time.time()
        next_ts = self._next_allowed.get(user_id, 0.0)
        remain = int(next_ts - now)
        return remain if remain > 0 else 0

    def hit(self, user_id: int) -> None:
        self._next_allowed[user_id] = time.time() + self.seconds