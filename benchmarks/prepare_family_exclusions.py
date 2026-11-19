"""Prepare the exact packed SHA-256 family exclusion archive."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

PINNED_CORPUS_SHA256 = (
    "2faa003d65827bebdcc4cb7f7c2fac9958b905e5db8143c708466d58bd26c958"
)
EXPECTED_ROWS = 100_000
EXPECTED_FAMILIES = 54_649


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a deterministic packed archive of full family SHA-256 hashes."
    )
    parser.add_argument("prior_corpus", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/data/prior_family_hashes.bin.gz"),
    )
    args = parser.parse_args()

    corpus_sha256 = sha256_file(args.prior_corpus)
    if corpus_sha256 != PINNED_CORPUS_SHA256:
        raise ValueError("prior corpus SHA-256 does not match the pinned v3 artifact")

    families: set[str] = set()
    row_count = 0
    with gzip.open(args.prior_corpus, "rt", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            family = row.get("program_family_hash")
            if not isinstance(family, str) or len(family) != 64:
                raise ValueError("prior corpus row lacks a SHA-256 family hash")
            families.add(family)
            row_count += 1

    if row_count != EXPECTED_ROWS or len(families) != EXPECTED_FAMILIES:
        raise ValueError(
            f"prior dimensions mismatch: rows={row_count}, "
            f"unique families={len(families)}"
        )

    packed_hashes = b"".join(bytes.fromhex(family) for family in sorted(families))
    if len(packed_hashes) != EXPECTED_FAMILIES * 32:
        raise AssertionError("packed archive must contain full 256-bit hashes")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = gzip.compress(
        packed_hashes,
        compresslevel=9,
        mtime=0,
    )
    args.output.write_bytes(payload)

    print(
        json.dumps(
            {
                "prior_corpus_sha256": corpus_sha256,
                "rows": row_count,
                "unique_families": len(families),
                "hash_width_bits": 256,
                "packed_payload_bytes": len(packed_hashes),
                "archive_bytes": len(payload),
                "output": str(args.output),
                "archive_sha256": hashlib.sha256(payload).hexdigest(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
