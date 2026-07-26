from datetime import date
from decimal import Decimal
from pathlib import Path

from tradeflow.domain.enums import PaymentMethod, TradeDirection
from tradeflow.domain.models import CompanyProfile, TradeCase, TradeProgram
from tradeflow.knowledge.repository import KnowledgeRepository
from tradeflow.runtime.pipeline import TradeFlowPipeline


root = Path(__file__).resolve().parents[1]
knowledge = KnowledgeRepository.from_json(
    root / "knowledge" / "source_registry.json",
    root / "knowledge" / "rulepacks" / "demo_trade_support.json",
)
program = TradeProgram(
    program_id="DEMO-001",
    company=CompanyProfile("COMPANY-001", "Demo Exporter", is_sme=True),
    opening_balances={"USD": Decimal("20000")},
    as_of=date(2026, 7, 26),
    cases=(
        TradeCase(
            "IMPORT-001",
            TradeDirection.IMPORT,
            "USD",
            Decimal("60000"),
            date(2026, 8, 25),
            PaymentMethod.TT,
        ),
        TradeCase(
            "EXPORT-001",
            TradeDirection.EXPORT,
            "USD",
            Decimal("100000"),
            date(2026, 10, 24),
            PaymentMethod.TT,
        ),
    ),
)

result = TradeFlowPipeline(knowledge).analyze(program)
usd = result.exposures[0]
print(f"currency={usd.currency}")
print(f"economic_offset={usd.economic_offset}")
print(f"maturity_matched_amount={usd.maturity_matched_amount}")
print(f"peak_funding_gap={usd.peak_funding_gap}")
print(f"ending_balance={usd.ending_balance}")
print(f"review_required={result.review_required}")
print(f"review_reasons={list(result.review_reasons)}")

