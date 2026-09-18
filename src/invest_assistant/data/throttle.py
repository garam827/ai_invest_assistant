"""One Yahoo request at a time, with a cooldown shared across all workers."""
from __future__ import annotations

import logging
import time
from threading import Lock

from yfinance.exceptions import YFRateLimitError

from invest_assistant import config

logger = logging.getLogger(__name__)


class YahooGate:
    def __init__(self):
        self.lock = Lock()
        self.next_allowed = 0.0
        self.rate_limit_streak = 0

    def call(self, request):
        with self.lock:
            delay = max(0.0, self.next_allowed - time.monotonic())
            if delay:
                logger.info('Yahoo shared wait: %.1fs', delay)
                time.sleep(delay)
            try:
                result = request()
            except YFRateLimitError:
                self.rate_limit_streak += 1
                cooldown = max(0, config.YFINANCE_RATE_LIMIT_COOLDOWN_SEC) * 2 ** min(self.rate_limit_streak - 1, 3)
                self.next_allowed = time.monotonic() + max(cooldown, config.YFINANCE_REQUEST_DELAY_SEC)
                logger.warning('Yahoo rate limit: all workers pause for %.1fs', cooldown)
                raise
            except Exception:
                self.next_allowed = time.monotonic() + max(0, config.YFINANCE_REQUEST_DELAY_SEC)
                raise
            else:
                self.rate_limit_streak = 0
                self.next_allowed = time.monotonic() + max(0, config.YFINANCE_REQUEST_DELAY_SEC)
                return result


yahoo_gate = YahooGate()
