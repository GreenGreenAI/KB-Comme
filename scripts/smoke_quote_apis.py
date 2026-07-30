"""Run credentialed live smoke checks without printing secrets or raw payloads."""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal

from tradeflow.integration.currencycloud import (
    CurrencycloudDemoForwardQuoteAdapter,
)
from tradeflow.integration.krx_futures import KrxUsdFuturesAdapter


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="provider", required=True)

    krx = subparsers.add_parser("krx")
    krx.add_argument("--date", type=date.fromisoformat, required=True)

    currencycloud = subparsers.add_parser("currencycloud")
    currencycloud.add_argument("--tenant-id", required=True)
    currencycloud.add_argument("--company-id", required=True)
    currencycloud.add_argument("--case-id", required=True)
    currencycloud.add_argument("--buy", required=True)
    currencycloud.add_argument("--sell", required=True)
    currencycloud.add_argument("--amount", type=Decimal, required=True)
    currencycloud.add_argument("--fixed-side", choices=("buy", "sell"), required=True)
    currencycloud.add_argument(
        "--conversion-date",
        type=date.fromisoformat,
        required=True,
    )
    args = parser.parse_args()

    if args.provider == "krx":
        payload = KrxUsdFuturesAdapter().fetch(args.date)
        print(
            "KRX live contract verified: "
            f"{len(payload['records'])} USD futures records for {args.date}"
        )
        return 0

    payload = CurrencycloudDemoForwardQuoteAdapter(
        tenant_id=args.tenant_id,
        company_id=args.company_id,
    ).fetch(
        buy_currency=args.buy,
        sell_currency=args.sell,
        amount=args.amount,
        fixed_side=args.fixed_side,
        conversion_date=args.conversion_date,
        case_ids=(args.case_id,),
    )
    record = payload["records"][0]
    print(
        "Currencycloud Demo contract verified: "
        f"{record['buy_currency']}/{record['sell_currency']} "
        f"conversion_date={record['conversion_date']} "
        "booking_required=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
