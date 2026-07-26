from collections import defaultdict
from decimal import Decimal

from tradeflow.domain.enums import TradeDirection
from tradeflow.domain.models import (
    CashflowPoint,
    CurrencyExposure,
    TradeProgram,
)


def analyze_exposure(program: TradeProgram) -> tuple[CurrencyExposure, ...]:
    """Calculate cashflow and funding gaps by currency and maturity.

    `economic_offset` describes whole-horizon inflow/outflow offset. It is not
    presented as immediately available cash. `peak_funding_gap` independently
    preserves the financing need caused by maturity mismatch.
    """
    cases_by_currency: dict[str, list] = defaultdict(list)
    for case in program.cases:
        cases_by_currency[case.currency].append(case)

    currencies = sorted(set(cases_by_currency) | set(program.opening_balances))
    results: list[CurrencyExposure] = []

    for currency in currencies:
        opening = program.opening_balances.get(currency, Decimal("0"))
        running = opening
        total_inflow = Decimal("0")
        total_outflow = Decimal("0")
        peak_gap = Decimal("0")
        timeline: list[CashflowPoint] = []

        ordered = sorted(
            cases_by_currency.get(currency, []),
            key=lambda case: (case.expected_payment_date, case.case_id),
        )
        for case in ordered:
            inflow = case.amount if case.direction == TradeDirection.EXPORT else Decimal("0")
            outflow = case.amount if case.direction == TradeDirection.IMPORT else Decimal("0")
            total_inflow += inflow
            total_outflow += outflow
            running += inflow - outflow
            gap = max(-running, Decimal("0"))
            peak_gap = max(peak_gap, gap)
            timeline.append(
                CashflowPoint(
                    event_date=case.expected_payment_date,
                    case_id=case.case_id,
                    currency=currency,
                    inflow=inflow,
                    outflow=outflow,
                    running_balance=running,
                    funding_gap=gap,
                )
            )

        results.append(
            CurrencyExposure(
                currency=currency,
                opening_balance=opening,
                total_inflow=total_inflow,
                total_outflow=total_outflow,
                economic_offset=min(total_inflow, total_outflow),
                trade_net_exposure=total_inflow - total_outflow,
                ending_balance=running,
                peak_funding_gap=peak_gap,
                timeline=tuple(timeline),
            )
        )
    return tuple(results)


class DefaultExposureService:
    """Default adapter satisfying the shared ExposureService contract."""

    def analyze(self, program: TradeProgram) -> tuple[CurrencyExposure, ...]:
        return analyze_exposure(program)
