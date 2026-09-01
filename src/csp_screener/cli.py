from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from .benchmark import run_benchmark


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Benchmark Alpaca stock and option data")
    command.add_argument("--stocks", default="SPY,QQQ,AAPL,MSFT,NVDA")
    command.add_argument("--underlying", default="SPY")
    command.add_argument("--runs", type=int, default=5)
    command.add_argument("--warmups", type=int, default=1)
    command.add_argument("--dte-min", type=int, default=7)
    command.add_argument("--dte-max", type=int, default=45)
    command.add_argument("--strike-low", type=float)
    command.add_argument("--strike-high", type=float)
    command.add_argument("--output", type=Path, default=Path("results/benchmarks.jsonl"))
    return command


def main() -> None:
    args = parser().parse_args()
    load_dotenv()
    api_key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret_key = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
    if not api_key or not secret_key:
        sys.exit("Missing Alpaca credentials. Copy .env.example to .env and fill in both values.")
    if args.runs < 1 or args.warmups < 0 or args.dte_min < 0 or args.dte_max < args.dte_min:
        sys.exit("Invalid run, warmup, or DTE arguments.")
    report = run_benchmark(
        api_key,
        secret_key,
        stocks=[item.strip().upper() for item in args.stocks.split(",") if item.strip()],
        underlying=args.underlying.upper(),
        runs=args.runs,
        warmups=args.warmups,
        dte_min=args.dte_min,
        dte_max=args.dte_max,
        strike_low=args.strike_low,
        strike_high=args.strike_high,
    )
    report["measured_at"] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(report, default=str) + "\n")
    print(json.dumps(report, indent=2, default=str))
    print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()

