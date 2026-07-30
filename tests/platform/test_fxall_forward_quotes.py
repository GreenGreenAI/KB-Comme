import unittest
import json
from decimal import Decimal
from pathlib import Path

from tradeflow.domain.datasets import parse_observed_forward_quote_payload
from tradeflow.integration.fxall_forward_quotes import (
    FxallQuoteContext,
    FxallQuoteError,
    build_fxall_forward_quote_payload,
    normalize_fxall_forward_quote,
    parse_fix_fields,
)


ORIGIN = {
    "source_id": "ECOS_USD_KRW",
    "version": "2026-07-28",
    "content_hash": "sha256:" + "a" * 64,
}
SELL = (
    "8=FIX.4.4|35=S|131=REQ-1|117=QUOTE-1|55=USD/KRW|"
    "167=FXFWD|54=2|38=100000|15=USD|188=1385.25|189=2.75|"
    "60=20260728-06:30:00.000|62=20260728-06:30:05.000|"
    "64=20260828|10=000|"
)


def context(**changes):
    values = {
        "tenant_id": "TENANT-1",
        "company_id": "COMPANY-1",
        "provider_id": "LSEG-LP-1",
        "case_ids": ("EXP-1",),
        "record_id": "FXALL-QUOTE-1",
        "origin_spot_snapshot": ORIGIN,
        "cost_rate": Decimal("0.0002"),
        "session_verified": True,
    }
    values.update(changes)
    return FxallQuoteContext(**values)


class FxallForwardQuoteTests(unittest.TestCase):
    def test_selected_provider_registry_is_honest_about_connection(self) -> None:
        root = Path(__file__).resolve().parents[2]
        registry = json.loads(
            (
                root / "knowledge/providers/forward_quote_providers.json"
            ).read_text(encoding="utf-8")
        )
        provider = registry["providers"][0]
        self.assertEqual("LSEG_FXALL_CORPORATE", provider["provider_id"])
        self.assertEqual("onboarding_required", provider["connection_state"])
        self.assertFalse(provider["production_eligible"])
        maker = registry["providers"][1]
        self.assertEqual(
            "liquidity_provider_reference_only",
            maker["role"],
        )
        self.assertFalse(maker["production_eligible"])

    def test_sell_quote_maps_bid_side_and_existing_contract(self) -> None:
        record = normalize_fxall_forward_quote(SELL, context=context())
        self.assertEqual("sell", record["side"])
        self.assertEqual("1388.00", record["contract_rate"])
        self.assertEqual("100000", record["notional_min"])
        self.assertEqual("2026-08-28", record["settlement_date"])
        self.assertEqual("LSEG-LP-1", record["provider_id"])
        self.assertNotIn("Account", record)

        payload = build_fxall_forward_quote_payload(
            [SELL],
            dataset_id="fxall-20260728-1",
            contexts=[context()],
        )
        parsed = parse_observed_forward_quote_payload(payload)
        self.assertEqual("TENANT-1", parsed.tenant_id)
        self.assertEqual(Decimal("1388.00"), parsed.records[0].contract_rate)

    def test_buy_quote_maps_offer_side(self) -> None:
        buy = SELL.replace("117=QUOTE-1", "117=QUOTE-2").replace(
            "54=2", "54=1"
        ).replace(
            "188=1385.25|189=2.75",
            "190=1385.75|191=3.25",
        )
        record = normalize_fxall_forward_quote(
            buy,
            context=context(record_id="FXALL-QUOTE-2"),
        )
        self.assertEqual("buy", record["side"])
        self.assertEqual("1389.00", record["contract_rate"])

    def test_unverified_wrong_product_and_ambiguous_fix_fail_closed(self) -> None:
        with self.assertRaisesRegex(FxallQuoteError, "authenticated"):
            normalize_fxall_forward_quote(
                SELL,
                context=context(session_verified=False),
            )
        with self.assertRaisesRegex(FxallQuoteError, "FXFWD"):
            normalize_fxall_forward_quote(
                SELL.replace("167=FXFWD", "167=FXSPOT"),
                context=context(),
            )
        with self.assertRaisesRegex(FxallQuoteError, "duplicate"):
            parse_fix_fields("35=S|35=S|")

    def test_tenant_scope_time_and_base_notional_are_enforced(self) -> None:
        with self.assertRaisesRegex(FxallQuoteError, "tenant"):
            build_fxall_forward_quote_payload(
                [SELL, SELL.replace("117=QUOTE-1", "117=QUOTE-2")],
                dataset_id="mixed",
                contexts=[
                    context(),
                    context(tenant_id="TENANT-2", record_id="R2"),
                ],
            )
        with self.assertRaisesRegex(FxallQuoteError, "base currency"):
            normalize_fxall_forward_quote(
                SELL.replace("15=USD", "15=KRW"),
                context=context(),
            )
        with self.assertRaisesRegex(FxallQuoteError, "cannot precede"):
            normalize_fxall_forward_quote(
                SELL.replace(
                    "62=20260728-06:30:05.000",
                    "62=20260728-06:29:59.000",
                ),
                context=context(),
            )


if __name__ == "__main__":
    unittest.main()
