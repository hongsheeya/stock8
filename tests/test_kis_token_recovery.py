"""Network-free broker authentication recovery regressions."""
import time
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock, patch
from test_kis_api_buying_power import kis_api, _StructStub


class TokenRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.api = kis_api.KisApi(_StructStub())
        self.api._assert_safe_request = Mock()
        self.api._rate_limit_wait = Mock()
        self.api._session = Mock()
        self.key, self.expiry = self.api.token_config_keys
        self.api._set_config(self.key, 'old-test-token')
        self.api._set_config(self.expiry, str(time.time() + 3600))
        self.rejected = self.response({'rt_cd': '1', 'msg_cd': 'EGW00123', 'msg1': 'expired token'})
        self.success = self.response({'rt_cd': '0'})
        self.oauth = self.response({'access_token': 'new-test-token', 'expires_in': 86400})
        self.oauth.status_code = 200

    def response(self, data):
        return Mock(headers={}, json=Mock(return_value=data))

    def test_zero_transport_retries_still_recovers_read(self):
        self.api._session.get.side_effect = [self.rejected, self.success]
        with patch.object(kis_api.requests, 'post', return_value=self.oauth) as issue:
            result = self.api._request('GET', '/test/read', 'TEST', retries=0, tr_cont='N')
        self.assertEqual(result['rt_cd'], '0')
        self.assertEqual(issue.call_count, 1)
        self.assertEqual(self.api._session.get.call_count, 2)
        self.assertEqual(self.api._get_config(self.key), 'new-test-token')
        self.assertEqual(self.api._session.get.call_args.kwargs['headers']['tr_cont'], 'N')

    def test_second_rejection_is_returned_not_silently_none(self):
        self.api._session.get.return_value = self.rejected
        with patch.object(kis_api.requests, 'post', return_value=self.oauth) as issue:
            result = self.api._request('GET', '/test/read-again', 'TEST', retries=2)
        self.assertEqual(result['msg_cd'], 'EGW00123')
        self.assertEqual(self.api._session.get.call_count, 2)
        self.assertEqual(issue.call_count, 1)

    def test_rejected_write_is_never_replayed(self):
        self.api._session.post.return_value = self.rejected
        with patch.object(kis_api.requests, 'post') as issue:
            result = self.api._request('POST', '/trading/test-order', 'TEST', retries=2)
        self.assertEqual(result['rt_cd'], '1')
        self.assertEqual(self.api._session.post.call_count, 1)
        issue.assert_not_called()

    def test_newer_cached_token_from_other_reader_is_preserved(self):
        self.api._set_config(self.key, 'newer-test-token')
        with patch.object(kis_api.requests, 'post') as issue:
            token = self.api._issue_token(rejected_token='old-test-token')
        self.assertEqual(token, 'newer-test-token')
        issue.assert_not_called()

    def test_failed_refresh_does_not_leave_rejected_token_valid(self):
        with patch.object(kis_api.requests, 'post', side_effect=kis_api.requests.exceptions.Timeout('test')):
            with self.assertRaises(kis_api.requests.exceptions.Timeout):
                self.api._issue_token(rejected_token='old-test-token')
        self.assertEqual(float(self.api._get_config(self.expiry)), 0)
        self.assertFalse(self.api.has_valid_cached_token())

    def test_order_timeout_is_not_retried(self):
        self.api._session.post.side_effect = kis_api.requests.exceptions.Timeout('test')
        with self.assertRaises(Exception):
            self.api._request('POST', '/trading/test-order', 'TEST', retries=2)
        self.assertEqual(self.api._session.post.call_count, 1)

    def test_concurrent_rejected_readers_issue_only_one_token(self):
        with patch.object(kis_api.requests, 'post', return_value=self.oauth) as issue:
            with ThreadPoolExecutor(max_workers=8) as pool:
                tokens = list(pool.map(lambda _: self.api._issue_token(rejected_token='old-test-token'), range(24)))
        self.assertEqual(tokens, ['new-test-token'] * 24)
        self.assertEqual(issue.call_count, 1)

    def test_expiry_across_three_virtual_days_reissues_once_per_day(self):
        start = time.time()
        self.api._set_config(self.expiry, '0')
        with patch.object(kis_api.requests, 'post', return_value=self.oauth) as issue:
            for day in range(3):
                with patch.object(kis_api.time, 'time', return_value=start + day * 86401):
                    self.assertEqual(self.api._issue_token(), 'new-test-token')
                    self.assertEqual(self.api._issue_token(), 'new-test-token')
        self.assertEqual(issue.call_count, 3)
