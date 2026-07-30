import unittest

from tradeflow.runtime import narration


class ParticleTests(unittest.TestCase):
    """`은(는)` is what a template writes when it does not know the word it is
    joining, and every word joined here is a product name or a rule condition
    that changes with the trade."""

    def test_the_last_syllable_decides_not_the_last_character(self) -> None:
        """Product names end in brackets — 「단기수출보험(선적후·개별)」 — and
        reading the bracket gave 는 where 별 wanted 은."""
        self.assertEqual(
            "은", narration._particle("K-SURE 단기수출보험(선적후·개별)", narration.TOPIC)
        )
        self.assertEqual("는", narration._particle("환변동보험(선적후)", narration.TOPIC))

    def test_each_pair_is_chosen_the_same_way(self) -> None:
        self.assertEqual("을", narration._particle("사전 상담", narration.OBJECT))
        self.assertEqual("를", narration._particle("자금 용도", narration.OBJECT))
        self.assertEqual("이", narration._particle("신고예외 확인", narration.SUBJECT))


class SupportTests(unittest.TestCase):
    RESULT = {
        "support_candidates": [
            {
                "title": "K-SURE 환변동보험",
                "status": "expert_confirmation_required",
                "checks": [
                    {"description": "중소·중견기업", "status": "passed"},
                    {"description": "수출 거래", "status": "passed"},
                ],
            },
            {
                "title": "K-SURE 수출신용보증(선적전)",
                "status": "insufficient_information",
                "checks": [
                    {"description": "중소·중견기업", "status": "passed"},
                    {"description": "취급 금융기관 사전 상담", "status": "uncertain"},
                ],
            },
        ]
    }

    def test_a_settled_product_counts_what_was_checked(self) -> None:
        """Five conditions, four requirements and six document titles named
        inline is a record again, in sentence clothing. The full lists are
        carried in `detail`; they are just not in the first thing anyone
        reads."""
        said = narration.support(self.RESULT)

        self.assertIn("K-SURE 환변동보험은 조건을 충족합니다", said[0])
        self.assertIn("확인한 조건은 2가지입니다", said[0])
        self.assertIn("공식 확인을 받으셔야 합니다", said[0])

    def test_the_full_lists_are_carried_not_dropped(self) -> None:
        """§6.1 asks that a judgement be inspectable, and what a rule checked
        is exactly what someone about to apply needs."""
        rows = narration.detail(self.RESULT)

        self.assertEqual("K-SURE 환변동보험", rows[0]["title"])
        self.assertEqual(["중소·중견기업", "수출 거래"], rows[0]["met"])
        self.assertEqual(["취급 금융기관 사전 상담"], rows[1]["wanted"])

    def test_a_long_list_is_named_in_part_and_counted(self) -> None:
        many = {
            "support_candidates": [
                {
                    "title": "K-SURE 단기수출보험",
                    "status": "insufficient_information",
                    "checks": [
                        {"description": f"조건 {n}", "status": "uncertain"}
                        for n in range(1, 5)
                    ],
                }
            ]
        }

        self.assertIn("조건 1 · 조건 2 등 4가지", narration.support(many)[0])

    def test_each_open_product_gets_its_own_sentence(self) -> None:
        """Joined into one paragraph the reader had to hold two lists at once
        to tell which requirement belonged to which product."""
        said = narration.support(self.RESULT)

        self.assertEqual(2, len(said))
        self.assertIn("취급 금융기관 사전 상담 1가지를 알려주시면", said[1])
        self.assertNotIn("K-SURE 환변동보험", said[1])

    def test_it_concludes_nothing_the_rules_did_not(self) -> None:
        """A sentence that could say 「신청하실 수 있습니다」 would be deciding.
        Reporting what a rule reported is not."""
        for line in narration.support(self.RESULT):
            self.assertNotIn("신청하실", line)
            self.assertNotIn("자격이 됩니다", line)

    def test_nothing_judged_says_nothing(self) -> None:
        self.assertEqual([], narration.support({}))


class ComplianceTests(unittest.TestCase):
    def test_it_keeps_not_yet_known_apart_from_not_applicable(self) -> None:
        """§5.5 is explicit that a filing duty is never cleared until the
        company states its structure, so the count of undecided rules must not
        read as a clearance."""
        said = narration.compliance(
            {
                "risk_findings": [
                    {
                        "title": "양자간 상계 외국환은행 보고",
                        "engaged": True,
                        "checks": [{"description": "양자간 상계", "status": "uncertain"}],
                    },
                    {"title": "제3자 지급 신고", "engaged": False, "checks": []},
                ]
            }
        )

        self.assertIn("이 거래에 해당합니다", said[0])
        self.assertIn("신고가 불필요하다는 판정은 아닙니다", said[-1])


if __name__ == "__main__":
    unittest.main()
