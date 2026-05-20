#!/usr/bin/env python3
"""
BEarn CLI — Command-line client for the BEarn Live Earning System
"""

import os
import sys
import json
import hashlib
import argparse
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import (
    init_db, register_user, get_user_by_id, get_user_balance,
    get_user_earnings_history, get_traffic_summary, get_daily_earnings,
    request_payout, get_payout_history
)


def cmd_register(args):
    """Register a new user."""
    uid = register_user(
        username=args.username,
        token_hash=hashlib.sha256(args.token.encode()).hexdigest(),
        earning_rate=args.rate,
        referral_code=args.referral_code
    )
    if uid:
        print(f"[OK] User registered with ID {uid}")
        print(f"[!] Save your token: {args.token}")
        if args.referral_code:
            print(f"[!] Referral code: {args.referral_code}")
    else:
        print("[FAIL] Username already exists or error occurred")


def cmd_balance(args):
    """Check user balance."""
    balance = get_user_balance(args.user_id)
    print(f"User ID {args.user_id} balance: ${balance:.6f}")


def cmd_history(args):
    """Show earnings history."""
    entries = get_user_earnings_history(args.user_id, args.limit)
    if not entries:
        print("No earnings yet.")
        return
    print(f"{'ID':<6} {'Amount':<12} {'Rate':<10} {'Source':<12} {'Date'}")
    print("-" * 60)
    for e in entries:
        print(f"{e['id']:<6} ${e['amount']:<9.6f} {e['rate_used']:<10} {e['source']:<12} {e['created_at']}")


def cmd_summary(args):
    """Show traffic summary."""
    summary = get_traffic_summary(args.user_id)
    total_mb = summary["total_bytes"] / (1024 * 1024)
    print(f"Requests:      {summary['requests']}")
    print(f"Total Traffic: {total_mb:.2f} MB")
    print(f"Avg Duration:  {summary['avg_duration']:.1f} ms")


def cmd_daily(args):
    """Show daily earnings."""
    days = args.days or 7
    daily = get_daily_earnings(args.user_id, days)
    if not daily:
        print(f"No earnings in the last {days} days.")
        return
    print(f"{'Date':<14} {'Earnings':<12}")
    print("-" * 30)
    total = 0
    for d in daily:
        print(f"{d['day']:<14} ${d['total']:<9.6f}")
        total += d["total"]
    print("-" * 30)
    print(f"{'TOTAL':<14} ${total:.6f}")


def cmd_payout(args):
    """Request a payout."""
    success, msg = request_payout(args.user_id, args.amount, args.method)
    print(f"[{'OK' if success else 'FAIL'}] {msg}")


def cmd_payouts(args):
    """List payouts."""
    payouts = get_payout_history(args.user_id)
    if not payouts:
        print("No payouts yet.")
        return
    print(f"{'ID':<6} {'Amount':<10} {'Method':<10} {'Status':<12} {'Date'}")
    print("-" * 50)
    for p in payouts:
        print(f"{p['id']:<6} ${p['amount']:<7.2f} {p['method']:<10} {p['status']:<12} {p['created_at']}")


def cmd_run(args):
    """Run the proxy server from CLI."""
    from src.proxy_server import run_proxy
    run_proxy()


def main():
    parser = argparse.ArgumentParser(
        description="BEarn — Live Earning System CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  bearn register --username alice --token my-secret-token
  bearn balance --user 1
  bearn history --user 1 --limit 20
  bearn daily --user 1 --days 7
  bearn payout --user 1 --amount 5.00
  bearn run
        """
    )
    sub = parser.add_subparsers(dest="command")

    # register
    p = sub.add_parser("register", help="Register a new user")
    p.add_argument("--username", required=True)
    p.add_argument("--token", required=True)
    p.add_argument("--rate", type=float, default=0.001)
    p.add_argument("--referral-code")

    # balance
   # history
    p = sub.add_parser("history", help="Show earnings history")
    p.add_argument("--user", dest="user_id", type=int, required=True)
    p.add_argument("--limit", type=int, default=50)

    # summary
    p = sub.add_parser("summary", help="Show traffic summary")
    p.add_argument("--user", dest="user_id", type=int, required=True)

    # daily
    p = sub.add_parser("daily", help="Show daily earnings")
    p.add_argument("--user", dest="user_id", type=int, required=True)
    p.add_argument("--days", type=int, default=7)

    # payout
    p = sub.add_parser("payout", help="Request a payout")
    p.add_argument("--user", dest="user_id", type=int, required=True)
    p.add_argument("--amount", type=float, required=True)
    p.add_argument("--method", default="stripe", choices=["stripe", "paypal", "bkash"])

    # payouts list
    p = sub.add_parser("payouts", help="List payout history")
    p.add_argument("--user", dest="user_id", type=int, required=True)

    # run proxy
    p = sub.add_parser("run", help="Start the BEarn proxy server")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Init DB before any command
    init_db()

    cmds = {
        "register": cmd_register,
        "balance": cmd_balance,
        "history": cmd_history,
        "summary": cmd_summary,
        "daily": cmd_daily,
        "payout": cmd_payout,
        "payouts": cmd_payouts,
        "run": cmd_run,
    }

    cmds[args.command](args)


if __name__ == "__main__":
    main()
