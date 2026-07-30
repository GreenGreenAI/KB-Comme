"""Record, approve and apply a governed hedge-model promotion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradeflow.knowledge.hedge_model_promotion import (
    HedgeModelPromotionStore,
    REQUIRED_APPROVALS,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "governance" / "hedge_models.db"
DEFAULT_REGISTRY = PROJECT_ROOT / "knowledge" / "hedge_model_registry.json"


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    root.add_argument("--db", type=Path, default=DEFAULT_DB)
    commands = root.add_subparsers(dest="command", required=True)

    record = commands.add_parser("record")
    record.add_argument("--report", type=Path, required=True)

    request = commands.add_parser("request")
    request.add_argument("--run-id", required=True)
    request.add_argument("--challenger", required=True)

    approve = commands.add_parser("approve")
    approve.add_argument("--request-id", required=True)
    approve.add_argument("--role", choices=REQUIRED_APPROVALS, required=True)
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--organization")

    status = commands.add_parser("status")
    status.add_argument("--request-id", required=True)

    promote = commands.add_parser("promote")
    promote.add_argument("--request-id", required=True)
    promote.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    return root


def main() -> int:
    args = parser().parse_args()
    store = HedgeModelPromotionStore(args.db)
    if args.command == "record":
        result = store.record_validation(
            json.loads(args.report.read_text(encoding="utf-8"))
        )
    elif args.command == "request":
        result = store.request_promotion(args.challenger, args.run_id)
    elif args.command == "approve":
        result = store.approve(
            args.request_id,
            role=args.role,
            reviewer=args.reviewer,
            organization=args.organization,
        )
    elif args.command == "status":
        result = store.status(args.request_id)
    else:
        result = store.promote(args.request_id, args.registry)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
