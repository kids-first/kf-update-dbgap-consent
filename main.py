#!/usr/bin/env python
import argparse
from argparse import RawTextHelpFormatter
from pprint import pprint

from kf_utils.dataservice.patch import send_patches
from sample_status import ConsentProcessor

SERVER_DEFAULT = "http://localhost:5000"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        formatter_class=RawTextHelpFormatter, allow_abbrev=False
    )
    parser.add_argument(
        "study", help="Which study to target\n - e.g. SD_1234567"
    )
    parser.add_argument(
        "--server",
        default=SERVER_DEFAULT,
        help=(
            "Which dataservice server to target\n"
            f" - Defaults to {SERVER_DEFAULT}"
        ),
    )
    parser.add_argument(
        "--db_url",
        help=(
            "Optional DB connection URL for direct access.\n"
            " - e.g. postgres://{USER_NAME}:{PASSWORD}@kf-dataservice-api-prd-20q19-9-11.c3siovbugjym.us-east-1.rds.amazonaws.com:5432/kfpostgresprd"  # noqa E501
        ),
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        default=False,
        help="Collect patches but don't apply them",
    )
    parser.add_argument(
        "--match_aliquot",
        action="store_true",
        default=False,
        help=(
            "Match dbGaP `SAMPLE_ID` to `external_aliquot_id` in the dataservice.\n"  # noqa E501
            " - Defaults to match on `external_sample_id`"
        ),
    )
    args = parser.parse_args()
    print(f"Args: {args.__dict__}")

    patches, alerts = ConsentProcessor(
        args.server, args.db_url
    ).get_patches_for_study(args.study, match_aliquot=args.match_aliquot)

    all_patches = {}
    for endpoint_patches in patches.values():
        all_patches.update(endpoint_patches)

    if args.dry_run:
        pprint(all_patches)
    else:
        send_patches(args.server, all_patches)
