#!/usr/bin/env python3
"""Create one *new* empty MinIO bucket for an isolated restore/drill target."""

from __future__ import annotations

import argparse
import sys

from minio import Minio


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--access-key", required=True)
    parser.add_argument("--secret-key", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--secure", choices=("true", "false"), required=True)
    args = parser.parse_args(argv)
    client = Minio(
        args.endpoint,
        access_key=args.access_key,
        secret_key=args.secret_key,
        secure=args.secure == "true",
    )
    try:
        if client.bucket_exists(args.bucket):
            print(
                f"[isolated-minio-bucket] ERROR: bucket already exists: {args.bucket}",
                file=sys.stderr,
            )
            return 1
        client.make_bucket(args.bucket)
    except Exception as exc:  # MinIO error types vary by transport/version.
        print(
            f"[isolated-minio-bucket] ERROR: cannot create isolated bucket: {exc}",
            file=sys.stderr,
        )
        return 1
    print(f"[isolated-minio-bucket] created new bucket {args.bucket}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
