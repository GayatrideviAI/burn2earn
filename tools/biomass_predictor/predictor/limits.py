"""Simple abuse limits kept in memory (per server process). Enough for a small public tool;
put a proper limiter in front (reverse proxy or a shared store) if it grows."""

import time
from collections import defaultdict, deque


class Limiter:
    def __init__(self, per_ip=10, per_ip_window=3600, daily_total=500, clock=time.time):
        self.per_ip, self.window, self.daily_total, self.clock = per_ip, per_ip_window, daily_total, clock
        self.hits = defaultdict(deque)
        self.day = None
        self.today = 0

    def allow(self, ip):
        """Returns None if allowed (and counts it), else a message to show."""
        now = self.clock()
        day = int(now // 86400)
        if day != self.day:
            self.day, self.today = day, 0
        if self.today >= self.daily_total:
            return "The tool has reached its daily limit. Please try again tomorrow."
        q = self.hits[ip]
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.per_ip:
            return f"Please wait: each person can make {self.per_ip} estimates an hour."
        q.append(now)
        self.today += 1
        if len(self.hits) > 10000:
            for key in [k for k, v in self.hits.items() if not v or v[-1] <= now - self.window]:
                del self.hits[key]
        return None
