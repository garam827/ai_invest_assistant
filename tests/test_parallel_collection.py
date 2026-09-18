"""Concurrency and failure boundaries; all market/Drive calls are simulated."""
import copy
import logging
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
from yfinance.exceptions import YFRateLimitError

from apps.streamlit.components.log_viewer import _StreamlitLogHandler
from invest_assistant import config
from invest_assistant.data.quality import validate_ohlcv
from invest_assistant.data.throttle import YahooGate
from invest_assistant.pipelines import collect
from invest_assistant.storage import runtime
from invest_assistant.storage.drive import DriveDB
from invest_assistant.storage.drive import _SerializedCredentials as WorkerCredentials


def frame(day='2026-09-14'):
    return pd.DataFrame({'Date': [pd.Timestamp(day)], 'Open': [100.], 'High': [102.],
                         'Low': [99.], 'Close': [101.], 'Volume': [1000]})


class ParallelCollectionTests(unittest.TestCase):
    def setUp(self):
        for name, value in [('COLLECTION_WORKERS', 3), ('COLLECTION_RETRY_ROUNDS', 0),
                            ('COLLECTION_RETRY_DELAY_SEC', 0), ('STREAMLIT_PUBLIC_MODE', False)]:
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_independent_transports_can_overlap(self):
        rendezvous = threading.Barrier(2)
        clients = []
        for _ in range(2):
            db = object.__new__(DriveDB)
            db.folder_id = 'test-folder'
            db.service = Mock()
            def execute():
                rendezvous.wait(timeout=3)
                return {'files': []}
            db.service.files.return_value.list.return_value.execute.side_effect = execute
            clients.append(db)
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(lambda db: db.list_tickers(), clients)), [[], []])

    def test_automatic_worker_credential_refreshes_are_serialized_and_persisted(self):
        from google.oauth2.credentials import Credentials
        active = 0
        peak = 0
        def refresh(credentials, request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            time.sleep(0.02)
            credentials.token = 'refreshed-test-token'
            active -= 1
        clients = [WorkerCredentials(token='test-token') for _ in range(2)]
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(config, 'GOOGLE_OAUTH_TOKEN_PATH', str(Path(directory) / 'token.json')), \
                patch.object(Credentials, 'refresh', refresh), ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda credentials: credentials.refresh(None), clients))
            self.assertIn('refreshed-test-token', (Path(directory) / 'token.json').read_text())
        self.assertEqual(peak, 1)

    def test_transport_refresh_does_not_wait_for_paper_transaction_lock(self):
        from google.oauth2.credentials import Credentials
        credentials = WorkerCredentials(token='test-token')
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(config, 'GOOGLE_OAUTH_TOKEN_PATH', str(Path(directory) / 'token.json')), \
                patch.object(Credentials, 'refresh'), ThreadPoolExecutor(max_workers=1) as pool:
            @runtime.serialized
            def paper_transaction():
                pool.submit(credentials.refresh, None).result(timeout=3)
            paper_transaction()

    def test_workers_overlap_deduplicate_preserve_history_and_finish_saves(self):
        rendezvous = threading.Barrier(3)
        stored = {t: frame('2026-09-11') for t in ['A', 'B', 'C']}
        clients = []
        class DB:
            folder_id = 'parallel-test'
            def __init__(self):
                self.owner = threading.get_ident()
                self.closed = False
                self.reads = 0
            def load_ticker(self, ticker):
                assert self.owner == threading.get_ident()
                self.reads += 1
                rendezvous.wait(timeout=3)
                return stored[ticker].copy()
            def save_ticker(self, ticker, data):
                assert self.owner == threading.get_ident()
                time.sleep(0.02)
                stored[ticker] = data.copy()
            def close(self):
                self.closed = True
        def factory():
            db = DB()
            clients.append(db)
            return db
        parent = Mock()
        parent.new_worker.side_effect = factory
        with patch.object(collect, 'fetch_ohlcv', side_effect=lambda *a, **kw: frame()) as fetch:
            report = collect.run_daily_update(parent, ['A', 'A', 'B', 'C'], end='2026-09-15')
        self.assertEqual(report['failed'], [])
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(len(clients), 3)
        self.assertTrue(all(c.closed and c.reads == 1 for c in clients))
        for data in stored.values():
            self.assertEqual(data['Date'].tolist(), [pd.Timestamp('2026-09-11'), pd.Timestamp('2026-09-14')])
        self.assertEqual(fetch.call_args.kwargs['end'], '2026-09-15')

    def test_only_failures_are_retried_and_single_worker_uses_existing_client(self):
        parent = Mock()
        calls = []
        def update(db, ticker, end=None):
            self.assertIs(db, parent)
            calls.append(ticker)
            if ticker == 'B' and calls.count('B') == 1:
                raise OSError('temporary upload failure')
            return {}
        with patch.object(config, 'COLLECTION_WORKERS', 1), \
                patch.object(config, 'COLLECTION_RETRY_ROUNDS', 1), \
                patch.object(collect, '_update_one_ticker', side_effect=update), self.assertLogs(collect.logger):
            report = collect.run_daily_update(parent, ['A', 'B'])
        self.assertEqual(calls, ['A', 'B', 'B'])
        self.assertEqual(report['failed'], [])
        parent.new_worker.assert_not_called()

    def test_persistent_failure_blocks_assets_after_other_saves_finish(self):
        finished = threading.Event()
        def update(db, ticker, end=None):
            if ticker == 'BAD':
                raise ValueError('bad prices')
            time.sleep(0.03)
            finished.set()
        with patch.object(collect, 'ASSET_CLASS_TICKERS', {'BAD': {}, 'GOOD': {}}), \
                patch.object(collect, '_update_one_ticker', side_effect=update), self.assertLogs(collect.logger):
            with self.assertRaisesRegex(RuntimeError, 'BAD'):
                collect.run_asset_class_update(Mock())
        self.assertTrue(finished.is_set())

    def test_empty_response_is_failure_and_does_not_save(self):
        db = Mock()
        db.load_ticker.return_value = frame('2026-09-11')
        with patch.object(collect, 'fetch_ohlcv', return_value=pd.DataFrame()):
            with self.assertRaises(ValueError):
                collect._update_one_ticker(db, 'EMPTY')
        db.save_ticker.assert_not_called()

    def test_same_ticker_updates_on_two_clients_preserve_both_writes(self):
        shared = {'data': frame('2026-09-10')}
        guard = threading.Lock()
        active = 0
        peak = 0
        class DB:
            folder_id = 'transaction-test'
            def load_ticker(self, ticker):
                nonlocal active, peak
                with guard:
                    active += 1
                    peak = max(peak, active)
                time.sleep(0.02)
                return copy.deepcopy(shared['data'])
            def save_ticker(self, ticker, data):
                nonlocal active
                shared['data'] = data
                with guard:
                    active -= 1
        with patch.object(collect, 'fetch_ohlcv', side_effect=lambda t, **kw: frame(kw['end'])), \
                ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(collect._update_one_ticker, DB(), 'SAME', day)
                       for day in ['2026-09-11', '2026-09-14']]
            for f in futures:
                f.result()
        self.assertEqual(peak, 1)
        self.assertEqual(len(shared['data']), 3)

    def test_yahoo_requests_never_overlap(self):
        gate = YahooGate()
        active = 0
        peak = 0
        def request():
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            time.sleep(0.02)
            active -= 1
        with patch.object(config, 'YFINANCE_REQUEST_DELAY_SEC', 0), ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda _: gate.call(request), range(6)))
        self.assertEqual(peak, 1)

    def test_rate_limit_cooldown_is_shared_and_grows(self):
        gate = YahooGate()
        clock = [100.0]
        waits = []
        def sleep(seconds):
            waits.append(seconds)
            clock[0] += seconds
        with patch('invest_assistant.data.throttle.time.monotonic', side_effect=lambda: clock[0]), \
                patch('invest_assistant.data.throttle.time.sleep', side_effect=sleep), \
                patch.object(config, 'YFINANCE_RATE_LIMIT_COOLDOWN_SEC', 10), \
                patch.object(config, 'YFINANCE_REQUEST_DELAY_SEC', 0.5), self.assertLogs('invest_assistant.data.throttle'):
            for _ in range(2):
                with self.assertRaises(YFRateLimitError):
                    gate.call(Mock(side_effect=YFRateLimitError()))
            self.assertEqual(gate.call(lambda: 'next worker'), 'next worker')
            gate.call(lambda: 'following request')
        self.assertEqual(waits, [10.0, 20.0, 0.5])

    def test_diagnostics_name_bad_field_and_value(self):
        bad = frame()
        bad.loc[0, 'Close'] = float('nan')
        with self.assertRaisesRegex(ValueError, "invalid_fields=.*Close.*nan"):
            validate_ohlcv(bad)

    def test_streamlit_handler_only_renders_on_owner_thread(self):
        placeholder = Mock()
        handler = _StreamlitLogHandler(placeholder, flush_every=1)
        record = logging.LogRecord('test', logging.INFO, '', 0, 'worker log', (), None)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(handler.handle, record).result()
        placeholder.code.assert_not_called()
        handler._flush()
        placeholder.code.assert_called_once_with('worker log')


if __name__ == '__main__':
    unittest.main()
