#!/usr/bin/env python3
"""Merge certifi CA bundle + optional enterprise .cer (DER or PEM) into bpe_sg_merged.pem.

Run from repo root after placing SFSRootCAG2.cer (or pass path as first arg):

  python scripts/build_shotgrid_ca_bundle.py
  python scripts/build_shotgrid_ca_bundle.py <path-to-SFSRootCAG2.cer>

Output: src/bpe/resources/shotgrid/bpe_sg_merged.pem
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import certifi


def _der_or_pem_to_pem_blocks(data: bytes) -> bytes:
    """Return PEM bytes (one or more CERTIFICATE blocks)."""
    stripped = data.strip()
    if stripped.startswith(b"-----BEGIN"):
        return data
    b64 = base64.encodebytes(data).decode("ascii").replace("\n", "")
    lines = "\n".join(b64[i : i + 64] for i in range(0, len(b64), 64))
    pem = "-----BEGIN CERTIFICATE-----\n" + lines + "\n-----END CERTIFICATE-----\n"
    return pem.encode("utf-8")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    out_dir = root / "src" / "bpe" / "resources" / "shotgrid"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "bpe_sg_merged.pem"

    extra_path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    if extra_path is None:
        default = Path(r"W:\team\_Pipeline\upload\shotgun_upload_patch\SFSRootCAG2.cer")
        extra_path = default if default.is_file() else None

    certifi_path = Path(certifi.where())
    base_pem = certifi_path.read_bytes()

    parts: list[bytes] = [base_pem]
    if extra_path is not None and extra_path.is_file():
        raw = extra_path.read_bytes()
        parts.append(b"\n")
        parts.append(_der_or_pem_to_pem_blocks(raw))
    else:
        print("warning: no extra .cer path; writing certifi-only bundle", file=sys.stderr)

    merged = b"".join(parts)
    out_path.write_bytes(merged)
    print(f"Wrote {out_path} ({len(merged)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
