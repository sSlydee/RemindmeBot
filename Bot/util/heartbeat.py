import logging
import time
from urllib.parse import urlsplit, urlunsplit

import aiohttp


log = logging.getLogger('Remindme.Heartbeat')


class Heartbeat:
    """push 'up' to an Uptime Kuma push monitor

    Called by the reminder delivery loop after each successful run: when the
    loop stops working (database down, crash, gateway lost), the pushes stop
    and Uptime Kuma raises an alert.

    url: the monitor's push URL (its query string is ignored), None disables it
    """

    def __init__(self, url: str = None, min_interval: float = 30):
        self.url = None
        if url:
            parts = urlsplit(url)
            self.url = urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
            # never log the path: it holds the monitor's secret token
            log.info(f'heartbeat enabled ({parts.netloc})')
        self.min_interval = min_interval
        self._last_push = None
        self._failing = False

    async def push(self, msg: str = 'OK', ping_ms: float = None):
        if not self.url:
            return

        now = time.monotonic()
        if self._last_push is not None and now - self._last_push < self.min_interval:
            return

        params = {'status': 'up', 'msg': msg, 'ping': '' if ping_ms is None else str(int(ping_ms))}
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.url, params=params) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f'HTTP {resp.status}')
        except Exception as e:
            # log once per outage, not on every loop
            if not self._failing:
                log.warning(f'heartbeat push failed: {type(e).__name__}: {e}')
            self._failing = True
            return

        if self._failing:
            log.info('heartbeat push works again')
        self._failing = False
        self._last_push = now
