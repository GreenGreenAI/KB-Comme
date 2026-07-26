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


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"

