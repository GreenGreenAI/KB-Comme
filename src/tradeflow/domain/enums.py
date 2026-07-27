from enum import StrEnum


class TradeDirection(StrEnum):
    EXPORT = "export"
    IMPORT = "import"


class PaymentMethod(StrEnum):
    TT = "tt"
    LC = "lc"
    DP = "dp"
    DA = "da"


class DecisionStatus(StrEnum):
    ELIGIBLE_CANDIDATE = "eligible_candidate"
    CONDITIONALLY_ELIGIBLE = "conditionally_eligible"
    NOT_ELIGIBLE = "not_eligible"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    EXPERT_CONFIRMATION_REQUIRED = "expert_confirmation_required"
    SOURCE_EXPIRED = "source_expired"


class DecisionCategory(StrEnum):
    CANDIDATE = "candidate"
    EXCLUDED = "excluded"
    MISSING_INFORMATION = "missing_information"
    EXPERT_REVIEW = "expert_review"
    SOURCE_UNUSABLE = "source_unusable"
    URGENT_ACTION = "urgent_action"


class RuleType(StrEnum):
    ELIGIBILITY = "eligibility"
    REQUIREMENT = "requirement"
    RESTRICTION = "restriction"
    EXCEPTION = "exception"
    PROCEDURE = "procedure"
    DEADLINE = "deadline"


class EvidenceRole(StrEnum):
    USER_TRADE = "user_trade"
    CALCULATION = "calculation"
    SUPPORT_ELIGIBILITY = "support_eligibility"
    COMPLIANCE = "compliance"
    PROCEDURE = "procedure"
    MARKET_DATA = "market_data"


class SourceStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    FUTURE = "future"
    UNVERIFIED = "unverified"
    FRESHNESS_UNKNOWN = "freshness_unknown"
    STALE = "stale"


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"


class HedgeMeasureCategory(StrEnum):
    """A contracted product and a way of restructuring trade behave differently.

    A financial instrument has a counterparty, a contracted rate and a cost. A
    strategy has none of these, so the payoff formula does not apply to it.
    """

    FINANCIAL_INSTRUMENT = "financial_instrument"
    STRATEGY = "strategy"


class FinancialInstrumentKind(StrEnum):
    FORWARD = "forward"
    KSURE_FX_INSURANCE = "ksure_fx"


class HedgeStrategyKind(StrEnum):
    NATURAL = "natural"
    TERMS_ADJUSTMENT = "terms"


class AvailabilityStatus(StrEnum):
    """Whether a company may use a hedging measure.

    Mirrors `DecisionStatus`: not knowing whether a measure is usable is a
    distinct answer from knowing it is not, and collapsing the two into a
    boolean would let missing information read as a settled refusal.
    """

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    CONDITIONAL = "conditional"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    EXPERT_CONFIRMATION_REQUIRED = "expert_confirmation_required"

