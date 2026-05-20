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
