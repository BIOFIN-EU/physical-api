"""
Fill in missing case_locations.risk_id values from the Risk Score Framework.

Covers polygon locations created before risk ids existed, and any whose
automatic fetch failed. Point locations are never sent (the framework needs
a polygon). Safe to re-run: only rows that still have no risk_id are
requested, and each id is saved as soon as it is fetched.

Run inside a physical-api or physical-worker container:

    python -m app.scripts.backfill_location_risk_ids --dry-run
    python -m app.scripts.backfill_location_risk_ids
    python -m app.scripts.backfill_location_risk_ids --case-id 80 --case-id 81

Exits with status 1 if any location could not be filled.
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import func, select

from app.models.case_data import Case, CaseLocation
from app.workflows.activities import SessionLocal, fill_missing_location_risk_ids

logger = logging.getLogger("backfill_location_risk_ids")


def _missing_counts(case_ids: list[int] | None) -> dict[int, int]:
    """
    Return {case_id: number of polygon locations without a risk_id}.
    """
    query = (
        select(CaseLocation.case_id, func.count())
        .join(Case, Case.id == CaseLocation.case_id)
        .where(
            CaseLocation.location_type == "polygon",
            CaseLocation.risk_id.is_(None),
            Case.deleted_at.is_(None),
        )
        .group_by(CaseLocation.case_id)
        .order_by(CaseLocation.case_id)
    )

    if case_ids:
        query = query.where(CaseLocation.case_id.in_(case_ids))

    with SessionLocal() as session:
        return dict(session.execute(query).all())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--case-id",
        type=int,
        action="append",
        dest="case_ids",
        help="Only fill this case (repeatable). Default: every case.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be fetched without calling the framework.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    missing = _missing_counts(args.case_ids)
    total = sum(missing.values())

    if not missing:
        logger.info("No polygon locations are missing a risk_id.")
        return 0

    logger.info("%s location(s) missing a risk_id across %s case(s).", total, len(missing))

    if args.dry_run:
        for case_id, count in missing.items():
            logger.info("case %s: %s location(s)", case_id, count)
        return 0

    filled = 0
    failed = 0

    for index, case_id in enumerate(missing, start=1):
        logger.info("[%s/%s] case %s", index, len(missing), case_id)
        attempted, failures = fill_missing_location_risk_ids(case_id, logger)
        filled += attempted - len(failures)
        failed += len(failures)
        logger.info(
            "case %s: filled %s of %s location(s)",
            case_id,
            attempted - len(failures),
            attempted,
        )

    logger.info("Done: filled %s, failed %s.", filled, failed)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
