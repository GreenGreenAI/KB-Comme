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

    def test_a_product_is_said_once_however_many_trades_it_was_judged_on(self) -> None:
        """Every rule runs against every trade, so two trades bring the same
        product back twice — and the sentence cannot say which trade it means.
        The errand behind them is one visit, not two, and the fold's rows used
        the title as a key."""
        two_trades = {
            "support_candidates": [
                {**candidate, "subject_id": f"CASE-{n}", "rule_id": candidate["title"]}
                for n in (1, 2)
                for candidate in self.RESULT["support_candidates"]
            ],
            "next_actions": [
                {
                    "authority": "ksure",
                    "action": "consult_and_apply_for_ksure_product",
                    "product_ids": ["KSURE_FX"],
                    "required_documents": ["청약서", "사업자등록증"],
                }
            ]
            * 2,
        }

        said = narration.support(two_trades)
        rows = narration.detail(two_trades)

        self.assertEqual(2, len(said))
        self.assertEqual(1, len(narration.actions(two_trades)))
        self.assertEqual(len(rows), len({row["title"] for row in rows}))

    def test_it_keeps_the_weaker_claim_when_two_trades_disagree(self) -> None:
        """A product can clear on one trade and be short of a fact on another.
        Neither sentence can name a trade, so 「조건을 충족합니다」 on the
        strength of one of them would be this paragraph deciding something no
        rule decided."""
        disagreeing = {
            "support_candidates": [
                {
                    "rule_id": "KSURE_FX",
                    "title": "K-SURE 환변동보험",
                    "status": "expert_confirmation_required",
                    "checks": [{"description": "수출 거래", "status": "passed"}],
                },
                {
                    "rule_id": "KSURE_FX",
                    "title": "K-SURE 환변동보험",
                    "status": "insufficient_information",
                    "checks": [{"description": "결제일", "status": "uncertain"}],
                },
            ]
        }

        said = narration.support(disagreeing)

        self.assertEqual(1, len(said))
        self.assertIn("아직 판정하지 못했습니다", said[0])


class GroundedTests(unittest.TestCase):
    """A claim and the evidence for it, built in one pass.

    They used to be built by two functions in two different orders — sentences
    settled-first, rows in rule order — so the screen could only put all the
    sentences in a paragraph and all the rows in a fold underneath. The
    evidence was present and unusable, which is worse than absent: the product
    looks like it is showing its work while making the work unreadable.
    """

    RESULT = {
        "support_candidates": [
            {
                "rule_id": "KSURE_POSTSHIP",
                "title": "K-SURE 단기수출보험(선적후·개별)",
                "status": "insufficient_information",
                "checks": [
                    {"field": "trade.direction", "description": "수출 거래", "status": "passed"},
                    {
                        "field": "company.ksure_exporter_grade",
                        "description": "K-SURE 수출자 신용등급 F급 이상",
                        "status": "uncertain",
                    },
                    {
                        "field": "counterparty.country_restricted",
                        "description": "국별인수방침 인수제한국 소재가 아님",
                        "status": "uncertain",
                    },
                ],
            },
            {
                "rule_id": "KSURE_FX",
                "title": "K-SURE 환변동보험",
                "status": "expert_confirmation_required",
                "checks": [
                    {"field": "company.size", "description": "중소·중견기업", "status": "passed"},
                ],
            },
        ]
    }

    def test_a_claim_carries_its_own_grounds(self) -> None:
        blocks = narration.grounded(self.RESULT)

        settled = next(b for b in blocks if b["settled"])
        self.assertIn("중소·중견기업", settled["met"])
        self.assertNotIn("국별인수방침 인수제한국 소재가 아님", settled["met"])

    def test_what_is_decided_comes_before_what_is_not(self) -> None:
        """The question was 「받을 수 있나요」. An answer that opens with what
        is still unknown answers a different one — and the rulepack's order is
        not the reader's."""
        self.assertEqual(
            [True, False], [block["settled"] for block in narration.grounded(self.RESULT)]
        )

    def test_it_does_not_ask_for_what_it_refuses_to_ask_for(self) -> None:
        """`asking.ASKABLE` leaves 국별인수방침 out on purpose — a company's
        answer about whether its buyer's country is restricted is evidence of
        nothing. The sentence went on demanding it anyway, so the reader was
        left waiting on a question that never arrives."""
        open_one = next(b for b in narration.grounded(self.RESULT) if not b["settled"])

        self.assertEqual(["K-SURE 수출자 신용등급 F급 이상"], open_one["wanted"])
        self.assertEqual(["국별인수방침 인수제한국 소재가 아님"], open_one["ours"])
        self.assertIn("알려주시면", open_one["claim"])
        self.assertIn("저희가 확인할 항목", open_one["claim"])

    def test_a_condition_nobody_will_be_asked_about_is_still_named(self) -> None:
        """Silence about it reads as the rule having passed."""
        open_one = next(b for b in narration.grounded(self.RESULT) if not b["settled"])

        self.assertIn("국별인수방침", open_one["claim"])

    def test_the_claim_is_word_for_word_the_summary_sentence(self) -> None:
        """The block under a claim and the summary above it are the same
        assertion. A reader who finds them differently worded has to work out
        whether they are also differently meant."""
        claims = [b["claim"] for b in narration.grounded(self.RESULT) if b["kind"] == "support"]

        self.assertEqual(sorted(narration.support(self.RESULT)), sorted(claims))


class ReadBackTests(unittest.TestCase):
    HEARD = {
        "direction": "수출",
        "amount": "100000",
        "currency": "USD",
        "expected_shipment_date": "2026-09-12",
        "expected_payment_date": "2026-10-24",
        "country": "VN",
    }

    def test_it_says_back_everything_it_read(self) -> None:
        """The older line carried three of six fields. The shipment date is
        what settles 「결제기간 2년 이내」 and the country is what 국별인수방침
        is read against — a company that mentioned them and saw them left out
        cannot tell whether they were ignored or merely unsaid."""
        said = narration.read_back(self.HEARD)

        self.assertIn("수출 100,000 USD", said)
        self.assertIn("베트남", said)
        self.assertIn("9월 12일 선적", said)
        self.assertIn("10월 24일 결제", said)

    def test_it_says_the_term_it_worked_out(self) -> None:
        """Not a seventh thing that was heard — the first thing the product
        worked out, and the difference between a form that echoes and a tool
        that read."""
        self.assertIn("사이는 42일입니다", narration.read_back(self.HEARD))

    def test_a_sentence_that_read_nothing_says_nothing(self) -> None:
        """A turn that answered 「왜?」 read no trade out of it. 「로
        읽었습니다」 with nothing before it is the product talking to itself."""
        self.assertIsNone(narration.read_back({}))
        self.assertIsNone(narration.read_back(None))

    def test_one_date_alone_states_no_term(self) -> None:
        """A term is the gap between two days. With one of them missing there
        is no gap to state, and a zero would read as same-day settlement."""
        said = narration.read_back(
            {k: v for k, v in self.HEARD.items() if k != "expected_shipment_date"}
        )

        self.assertIn("10월 24일 결제", said)
        self.assertNotIn("사이는", said)

    def test_an_unlisted_country_is_left_out_rather_than_guessed(self) -> None:
        said = narration.read_back({**self.HEARD, "country": "ZZ"})

        self.assertNotIn("ZZ", said)
        self.assertIn("수출 100,000 USD", said)


class ClosedTests(unittest.TestCase):
    """Five questions arrived in a row with no sign that any of them had done
    anything. The rules were closing conditions on every turn and the screen
    reported none of it, so answering read as filling a form that kept
    growing."""

    RESULT = {
        "support_candidates": [
            {
                "rule_id": "KSURE_FX",
                "title": "K-SURE 환변동보험",
                "status": "expert_confirmation_required",
                "checks": [
                    {"field": "company.size", "description": "중소·중견기업", "status": "passed"},
                    {"field": "trade.direction", "description": "수출 거래", "status": "passed"},
                ],
            },
            {
                "rule_id": "KSURE_GUARANTEE",
                "title": "K-SURE 수출신용보증(선적전)",
                "status": "insufficient_information",
                "checks": [
                    {"field": "company.size", "description": "중소·중견기업", "status": "passed"},
                    {
                        "field": "financing.has_bank_consultation",
                        "description": "취급 금융기관 사전 상담",
                        "status": "uncertain",
                    },
                ],
            },
        ]
    }

    def test_it_names_the_condition_and_where_it_was(self) -> None:
        said = narration.closed(self.RESULT, ["company_size"])

        self.assertIn("「중소·중견기업」", said)
        self.assertIn("제도 2건", said)

    def test_somebody_checked_it_rather_than_it_having_gone_past(self) -> None:
        """「지나갔습니다」 described a state transition. A condition does not
        go past anyone — the person on this side checked it, and 확인 is the
        word already labelling passed conditions in the block below."""
        said = narration.closed(self.RESULT, ["company_size"])

        self.assertIn("확인했습니다", said)
        self.assertNotIn("지나갔", said)
        # 충족 belongs to the product's verdict. Spending it on one condition
        # makes a single check read as the whole judgement.
        self.assertNotIn("충족", said)

    def test_one_product_is_named_rather_than_counted(self) -> None:
        """「제도 1건」 withholds the one thing it could have said."""
        said = narration.closed(
            {"support_candidates": [self.RESULT["support_candidates"][1]]}, ["company_size"]
        )

        self.assertIn("K-SURE 수출신용보증(선적전)", said)
        self.assertNotIn("1건", said)

    def test_a_request_field_reaches_the_fact_a_rule_reads(self) -> None:
        """The screen sends what it set; a check names the fact a rule wanted.
        Nobody is asked for a payment term — they are asked when they ship."""
        derived = {
            "support_candidates": [
                {
                    "rule_id": "KSURE_POSTSHIP",
                    "title": "K-SURE 단기수출보험(선적후·개별)",
                    "status": "insufficient_information",
                    "checks": [
                        {
                            "field": "trade.payment_term_days",
                            "description": "개별보험 결제기간 2년 이내",
                            "status": "passed",
                        }
                    ],
                }
            ]
        }

        self.assertIn(
            "개별보험 결제기간 2년 이내",
            narration.closed(derived, ["expected_shipment_date"]),
        )

    def test_a_condition_still_open_is_not_reported_as_closed(self) -> None:
        """Answering does not make a rule pass, and this line must never be the
        reason somebody believes it did."""
        said = narration.closed(self.RESULT, ["financing.has_bank_consultation"])

        self.assertIsNone(said)

    def test_nothing_answered_says_nothing(self) -> None:
        """A typed sentence answers no question. 「방금 답해 주신 것으로」 after
        a sentence nobody was asked for is the product mishearing the turn."""
        self.assertIsNone(narration.closed(self.RESULT, []))
        self.assertIsNone(narration.closed(self.RESULT, None))

    def test_a_condition_is_said_once_however_many_trades_it_ran_against(self) -> None:
        two_trades = {
            "support_candidates": [
                {**candidate, "subject_id": f"CASE-{n}"}
                for n in (1, 2)
                for candidate in self.RESULT["support_candidates"]
            ]
        }

        said = narration.closed(two_trades, ["company_size"])

        self.assertEqual(1, said.count("중소·중견기업"))
        self.assertIn("제도 2건", said)


class BasisTests(unittest.TestCase):
    RESULT = {
        "cashflow_analysis": {"net_exposure": [{"currency": "USD", "amount": "100000"}]},
        "market_scenario": {
            "spot_rate": "1441.1",
            "adverse_rate": "1339.22",
            "confidence_level": 0.9,
            "observed_from": "2026-05-04",
            "observed_to": "2026-07-31",
            "observation_days": 60,
        },
    }

    def test_the_largest_number_can_say_where_it_came_from(self) -> None:
        """Every rule judgement could at least be opened. The figure most
        likely to be repeated to a bank was the one claim on the screen with
        nothing underneath it."""
        said = narration.basis(self.RESULT)

        self.assertIn("거래 순노출 100,000 USD", said)
        self.assertIn("Σ수취 − Σ지급", said)
        self.assertIn("1,339.22원", said)
        self.assertIn("신뢰수준 90%", said)
        self.assertIn("2026-05-04 ~ 2026-07-31", said)

    def test_no_scenario_says_nothing(self) -> None:
        """§5.2 refuses to produce a bound it cannot date, and a basis line for
        a figure that was never computed would be a citation for nothing."""
        self.assertIsNone(narration.basis({"cashflow_analysis": {}}))


class ComplianceTests(unittest.TestCase):
    RESULT = {
        "risk_findings": [
            {
                "title": "양자간 상계 외국환은행 보고 검토",
                "engaged": True,
                "outcome": {
                    "authority": "foreign_exchange_bank",
                    "action": "report",
                    "timing": "confirm_with_authority",
                },
                "checks": [
                    {"description": "양자간 상계", "status": "uncertain"},
                    {"description": "일방 금액 미화 5천달러 초과", "status": "uncertain"},
                ],
            },
            {
                "title": "다자간 상계 한국은행 신고 검토",
                "engaged": True,
                "outcome": {
                    "authority": "bank_of_korea",
                    "action": "file",
                    "timing": "confirm_before_execution",
                },
                "checks": [{"description": "다자간 상계", "status": "uncertain"}],
            },
            {"title": "제3자 지급 신고", "engaged": False, "checks": []},
        ]
    }

    def test_it_says_what_the_rule_says_not_which_field_is_missing(self) -> None:
        """The rulepack writes every condition as a sentence and names the
        authority, the action and the timing in its outcome. All of it was
        being withheld behind a list of field names, so the answer said less
        than the rules knew — and a general-purpose model answering the same
        question sounded better while asserting a verdict it had no basis for.
        """
        said = " ".join(narration.compliance(self.RESULT))

        self.assertIn("양자간 상계", said)
        self.assertIn("외국환은행에 보고합니다", said)
        self.assertIn("다자간 상계면 한국은행에 신고합니다", said)
        self.assertIn("상계 전에", said)

    def test_it_names_the_discriminator_the_reader_would_get_wrong(self) -> None:
        """The threshold is measured on the offset amount, not the trade. A
        company reading 「미화 5천 달러」 beside a 60,000 USD import will apply
        it to the wrong number unless told."""
        said = " ".join(narration.compliance(self.RESULT))

        self.assertIn("거래금액이 아니라 상계하는 채권과 채무 중 작은 금액", said)

    def test_it_still_refuses_to_conclude(self) -> None:
        """Every branch is conditional. Nothing here says the company must
        file — that is the rules' to say once they have the facts."""
        said = " ".join(narration.compliance(self.RESULT))

        self.assertIn("될 수 있습니다", said)
        self.assertNotIn("신고 대상입니다.", said)

    def test_a_rule_is_said_once_however_many_trades_it_ran_against(self) -> None:
        """§5.5 runs every rule against every trade, so three trades bring the
        same rule back three times. The packet keeps all three — a duty attaches
        to a trade — but this paragraph never names a trade, so it printed
        「다자간 상계면 한국은행에 신고합니다」 three times in a row."""
        three_trades = {
            "risk_findings": [
                {**finding, "subject_id": f"CASE-{n}", "rule_id": finding["title"]}
                for n in (1, 2, 3)
                for finding in self.RESULT["risk_findings"]
            ]
        }

        said = narration.compliance(three_trades)

        self.assertEqual(1, sum("다자간 상계면" in line for line in said))
        self.assertIn("2가지 갈래", said[0])
        self.assertIn("규칙이 1건", said[-1])

    def test_it_keeps_not_yet_known_apart_from_not_applicable(self) -> None:
        """§5.5 is explicit that a filing duty is never cleared until the
        company states its structure, so the count of undecided rules must not
        read as a clearance."""
        said = narration.compliance(self.RESULT)

        self.assertIn("신고가 불필요하다는 판정은 아닙니다", said[-1])


if __name__ == "__main__":
    unittest.main()
