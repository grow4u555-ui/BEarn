#!/usr/bin/env python3
"""
Tests for BEarn Database Layer
"""

import os
import sys
import tempfile
import hashlib
import unittest

# Override DB path to use temp file for testing
os.environ["BEARN_DB_PATH"] = os.path.join(tempfile.gettempdir(), "bearn_test.db")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import (
    init_db, register_user, get_user_by_token, get_user_by_id,
    get_user_balance, get_user_earnings_history, insert_earning,
    insert_proxy_log, request_payout, get_payout_history,
    get_traffic_summary, get_daily_earnings, update_earning_rate,
    calculate_earnings, close_db, DB_PATH
)


class TestDatabase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Initialize DB once for all tests."""
        init_db()

    @classmethod
    def tearDownClass(cls):
        """Clean up temp DB."""
        close_db()
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)

    def setUp(self):
        """Clean earnings/proxy_logs before each test, keep users."""
        from src.database import get_connection
        conn = get_connection()
        conn.execute("DELETE FROM earnings")
        conn.execute("DELETE FROM proxy_logs")
        conn.execute("DELETE FROM payouts")
        conn.commit()

    # ── User Tests ─────────────────────────────────────────────────

    def test_register_user(self):
        uid = register_user("testuser", "abc123hash", 0.001)
        self.assertIsNotNone(uid)
        self.assertGreater(uid, 0)

    def test_register_duplicate_user(self):
        register_user("dupuser", "hash1", 0.001)
        uid = register_user("dupuser", "hash2", 0.001)
        self.assertIsNone(uid)

    def test_get_user_by_token(self):
        register_user("tokenuser", "mytokenhash", 0.002, referral_code="REF123")
        user = get_user_by_token("mytokenhash")
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "tokenuser")
        self.assertEqual(user["earning_rate"], 0.002)
        self.assertEqual(user["referral_code"], "REF123")
        self.assertEqual(user["is_active"], 1)

   def test_get_user_by_token_invalid(self):
        user = get_user_by_token("nonexistent")
        self.assertIsNone(user)

    def test_get_user_by_id(self):
        uid = register_user("id_user", "hash_id", 0.001)
        user = get_user_by_id(uid)
        self.assertEqual(user["id"], uid)

    def test_update_earning_rate(self):
        uid = register_user("rate_user", "hash_rate", 0.001)
        update_earning_rate(uid, 0.005)
        user = get_user_by_id(uid)
        self.assertEqual(user["earning_rate"], 0.005)

    # ── Proxy Log Tests ────────────────────────────────────────────

    def test_insert_proxy_log(self):
        uid = register_user("log_user", "hash_log", 0.001)
        insert_proxy_log(uid, "GET", "example.com", "/", 200, 1024, 512, 45, "1.2.3.4", "curl/7.0")
        summary = get_traffic_summary(uid)
        self.assertEqual(summary["requests"], 1)

    def test_batch_insert_proxy_logs(self):
        uid = register_user("batch_user", "hash_batch", 0.001)
        logs = [
            {"user_id": uid, "method": "GET", "host": "a.com", "path": "/1",
             "status_code": 200, "bytes_sent": 100, "bytes_recv": 50,
             "duration_ms": 10, "ip_address": "1.1.1.1", "user_agent": "test"},
            {"user_id": uid, "method": "POST", "host": "b.com", "path": "/2",
             "status_code": 201, "bytes_sent": 200, "bytes_recv": 100,
             "duration_ms": 20, "ip_address": "2.2.2.2", "user_agent": "test"},
        ]
        batch_insert_proxy_logs(logs)
        summary = get_traffic_summary(uid)
        self.assertEqual(summary["requests"], 2)
        self.assertEqual(summary["total_bytes"], 450)

    # ── Earnings Tests ─────────────────────────────────────────────

    def test_calculate_earnings(self):
        # 1 MB at $0.001/MB = $0.001
        amount = calculate_earnings(1024 * 1024, 0, 0.001)
        self.assertAlmostEqual(amount, 0.001, places=6)

        # 10 MB at $0.0005/MB = $0.005
        amount = calculate_earnings(5 * 1024 * 1024, 5 * 1024 * 1024, 0.0005)
        self.assertAlmostEqual(amount, 0.005, places=6)

    def test_insert_earning(self):
        uid = register_user("earn_user", "hash_earn", 0.001)
        insert_earning(uid, 0.005, 0.001, "proxy")
        balance = get_user_balance(uid)
        self.assertAlmostEqual(balance, 0.005, places=6)

    def test_batch_insert_earnings(self):
        uid = register_user("batch_earn", "hash_batch_e", 0.001)
        earnings = [
            {"user_id": uid, "amount": 0.001, "rate_used": 0.001, "source": "proxy", "ref_id": None},
            {"user_id": uid, "amount": 0.002, "rate_used": 0.001, "source": "proxy", "ref_id": None},
        ]
        batch_insert_earnings(earnings)
        balance = get_user_balance(uid)
        self.assertAlmostEqual(balance, 0.003, places=6)

    def test_earnings_history(self):
        uid = register_user("history_user", "hash_hist", 0.001)
        insert_earning(uid, 0.01, 0.001, "proxy")
        insert_earning(uid, 0.02, 0.001, "referral")
        history = get_user_earnings_history(uid)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["source"], "referral")  # newest first

    def test_daily_earnings(self):
        uid = register_user("daily_user", "hash_daily", 0.001)
        insert_earning(uid, 0.01, 0.001, "proxy")
        daily = get_daily_earnings(uid, 7)
        self.assertEqual(len(daily), 1)
        self.assertAlmostEqual(daily[0]["total"], 0.01, places=6)

    # ── Payout Tests ──────────────────────────────────────────────

    def test_payout_below_minimum(self):
        uid = register_user("payout_user", "hash_pay", 0.001)
        insert_earning(uid, 1.0, 0.001, "proxy")
        success, msg = request_payout(uid, 1.0)
        self.assertFalse(success)
        self.assertIn("Minimum", msg)

    def test_payout_insufficient_balance(self):
        uid = register_user("poor_user", "hash_poor", 0.001)
        insert_earning(uid, 2.0, 0.001, "proxy")
        success, msg = request_payout(uid, 10.0)
        self.assertFalse(success)
        self.assertIn("Insufficient", msg)

    def test_payout_success(self):
        uid = register_user("rich_user", "hash_rich", 0.001)
        insert_earning(uid, 10.0, 0.001, "proxy")
        success, msg = request_payout(uid, 5.0, "stripe")
        self.assertTrue(success)
        self.assertEqual(msg, "Payout requested")

    def test_payout_history(self):
        uid = register_user("pay_hist", "hash_ph", 0.001)
        insert_earning(uid, 10.0, 0.001, "proxy")
        request_payout(uid, 5.0, "paypal")
        history = get_payout_history(uid)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["method"], "paypal")
        self.assertEqual(history[0]["status"], "pending")

    # ── Traffic Summary Tests ──────────────────────────────────────

    def test_traffic_summary_empty(self):
        uid = register_user("empty_user", "hash_empty", 0.001)
        summary = get_traffic_summary(uid)
        self.assertEqual(summary["requests"], 0)
        self.assertEqual(summary["total_bytes"], 0)

    def test_traffic_summary_with_data(self):
        uid = register_user("traffic_user", "hash_traf", 0.001)
        insert_proxy_log(uid, "GET", "x.com", "/a", 200, 500, 300, 15, "1.1.1.1", "ua")
        insert_proxy_log(uid, "POST", "y.com", "/b", 201, 1000, 200, 30, "2.2.2.2", "ua")
        summary = get_traffic_summary(uid)
        self.assertEqual(summary["requests"], 2)
        self.assertEqual(summary["total_bytes"], 2000)
        self.assertAlmostEqual(summary["avg_duration"], 22.5, places=1)

    # ── Batch Worker Tests ─────────────────────────────────────────

    def test_enqueue_and_flush(self):
        uid = register_user("queue_user", "hash_queue", 0.001)
        start_batch_worker()

        enqueue_log(uid, "GET", "test.com", "/path", 200, 100, 50, 5, "1.1.1.1", "curl")
        enqueue_earn(uid, 0.001, 0.001, "proxy")

        # Give batch worker time to flush
        import time
        time.sleep(12)

        summary = get_traffic_summary(uid)
        self.assertGreaterEqual(summary["requests"], 1)

        balance = get_user_balance(uid)
        self.assertGreaterEqual(balance, 0.001)


if __name__ == "__main__":
    unittest.main()
