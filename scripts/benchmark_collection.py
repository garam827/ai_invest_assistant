"""Offline scheduling benchmark; simulated latency, no credentials or API calls."""
from __future__ import annotations

import json
import time
from unittest.mock import patch

import pandas as pd

from invest_assistant import config
from invest_assistant.data.throttle import YahooGate
from invest_assistant.pipelines import collect


def prices(day):
    return pd.DataFrame({'Date': [pd.Timestamp(day)], 'Open': [100.], 'High': [102.],
                         'Low': [99.], 'Close': [101.], 'Volume': [1000]})


class SimulatedDrive:
    folder_id = 'offline-benchmark'

    def __init__(self, saved=None):
        self.saved = {} if saved is None else saved

    def new_worker(self):
        return SimulatedDrive(self.saved)

    def load_ticker(self, ticker):
        time.sleep(0.04)
        return prices('2026-09-11')

    def save_ticker(self, ticker, data):
        time.sleep(0.04)
        self.saved[ticker] = data.copy()

    def close(self):
        pass


def main():
    outputs = []
    for workers in (1, 3):
        gate = YahooGate()
        db = SimulatedDrive()

        def request():
            time.sleep(0.02)
            return prices('2026-09-14')

        with patch.object(config, 'COLLECTION_WORKERS', workers), \
                patch.object(config, 'COLLECTION_RETRY_ROUNDS', 0), \
                patch.object(config, 'STREAMLIT_PUBLIC_MODE', False), \
                patch.object(config, 'YFINANCE_REQUEST_DELAY_SEC', 0.01), \
                patch.object(collect, 'fetch_ohlcv', side_effect=lambda *a, **kw: gate.call(request)):
            result = collect.run_daily_update(db, [f'TEST{i}' for i in range(12)])
        assert not result['failed'] and len(db.saved) == 12
        outputs.append((result, db.saved))
    for ticker in outputs[0][1]:
        pd.testing.assert_frame_equal(outputs[0][1][ticker], outputs[1][1][ticker])
    print(json.dumps({'simulation_only': True, 'tickers': 12, 'identical_results': True,
                      'sequential_sec': outputs[0][0]['elapsed_sec'],
                      'parallel_sec': outputs[1][0]['elapsed_sec']}, indent=2))


if __name__ == '__main__':
    main()
