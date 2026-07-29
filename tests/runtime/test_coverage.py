import unittest

from tradeflow.runtime import coverage


class HeldTests(unittest.TestCase):
    """Derived from the rulepacks, so it cannot drift from them."""

    def test_support_holds_only_ksure_today(self) -> None:
        self.assertEqual(
            coverage.held("support"),
            frozenset({"ksure", "ksure_and_financial_institution"}),
        )

    def test_compliance_holds_the_three_filing_authorities(self) -> None:
        self.assertEqual(
            coverage.held("compliance"),
            frozenset(
                {
                    "bank_of_korea",
                    "foreign_exchange_bank",
                    "designated_foreign_exchange_bank",
                }
            ),
        )


class StatementTests(unittest.TestCase):
    def test_it_names_what_is_missing(self) -> None:
        said = coverage.statement("support")
        self.assertIn("한국무역보험공사 제도만 판정합니다", said)
        for absent in ("한국수출입은행", "신용보증기금", "기술보증기금", "중소벤처기업진흥공단"):
            self.assertIn(absent, said)

    def test_a_body_is_named_once(self) -> None:
        """`ksure` and `ksure_and_financial_institution` are the same body —
        the second is K-SURE's product delivered through a bank. Listing both
        read as "한국무역보험공사 · 한국무역보험공사·금융기관"."""
        self.assertEqual(1, coverage.statement("support").count("한국무역보험공사"))

    def test_complete_coverage_says_nothing(self) -> None:
        """A product that recites its limits every turn teaches the reader to
        skip the line, and then it is not there on the turn that needed it."""
        self.assertEqual("", coverage.statement("compliance"))

    def test_a_subject_with_no_declared_scope_says_nothing(self) -> None:
        self.assertEqual("", coverage.statement("market_scenario"))

    def test_the_particle_follows_the_last_name(self) -> None:
        """`은(는)` is what a template writes when it does not know the word it
        is joining, and that word changes as rules are added."""
        self.assertEqual("은", coverage._particle("중소벤처기업진흥공단"))
        self.assertEqual("는", coverage._particle("신용보증기금나"))

    def test_it_would_go_quiet_if_the_rules_arrived(self) -> None:
        """The held side is read from the rulepacks, so landing a 수출입은행
        rulepack changes this sentence with nobody editing it."""
        original = coverage.held
        coverage.held = lambda section: frozenset(coverage.INTENDED[section])
        try:
            self.assertEqual("", coverage.statement("support"))
        finally:
            coverage.held = original


class FinancingTests(unittest.TestCase):
    def test_it_names_the_product_that_covers_that_money(self) -> None:
        """"지원제도는 한국무역보험공사 제도만 판정합니다" is true and reads as
        having nothing, when the rulepack holds a rule aimed at exactly the
        money the company just described."""
        self.assertEqual(
            "필요하신 자금은 K-SURE 수출신용보증(선적전)으로 판정합니다.",
            coverage.for_financing("trade_finance"),
        )

    def test_the_particle_follows_the_last_syllable_not_the_last_character(
        self,
    ) -> None:
        """Rule titles end in brackets — "수출신용보증(선적전)" — and 로/으로
        is decided by 전, which the closing bracket hides."""
        self.assertEqual("으로", coverage._instrumental("수출신용보증(선적전)"))
        self.assertEqual("으로", coverage._instrumental("환변동보험"))
        self.assertEqual("로", coverage._instrumental("수출신용보증(선적전)이"))
        self.assertEqual("로", coverage._instrumental("수출신용보증(선적후)"))

    def test_no_purpose_says_nothing(self) -> None:
        self.assertEqual("", coverage.for_financing(None))

    def test_an_uncovered_purpose_says_nothing(self) -> None:
        """Silence rather than an empty promise — the limits line below it
        already says what is not covered."""
        self.assertEqual("", coverage.for_financing("other"))


if __name__ == "__main__":
    unittest.main()
