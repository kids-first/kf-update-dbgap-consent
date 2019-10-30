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
        "--dry_run",
        action="store_true",
        default=False,
        help="Collect patches but don't apply them",
    )
    args = parser.parse_args()
    print(f"Args: {args.__dict__}")

    patches, alerts = ConsentProcessor(args.server).get_patches_for_study(
        args.study
    )

    all_patches = {}
    for endpoint_patches in patches.values():
        all_patches.update(endpoint_patches)

    if args.dry_run:
        pprint(all_patches)
    else:
        send_patches(args.server, all_patches)
