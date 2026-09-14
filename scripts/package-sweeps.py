#!/usr/bin/env python3
"""Package measured sweeps; never publish proving keys or symlinks."""
import argparse
import gzip
import hashlib
import io
from pathlib import Path
import re
import tarfile

LABELS = ("236k", "300k", "500k", "soispoke")


def validate(root):
    for name in ("verifier.hex", "calldata-invalid.hex"):
        value = (root / name).read_text().strip().removeprefix("0x")
        if not re.fullmatch(r"(?:[0-9a-fA-F]{2})+", value):
            raise ValueError(f"{root / name}: expected nonempty, byte-aligned hex")
        if name == "verifier.hex" and not 1000 <= len(value) // 2 <= 24576:
            raise ValueError(f"{root}: implausible verifier size")
    ceiling = {"sweep-236k": 236285, "sweep-300k": 300000,
               "sweep-500k": 500000, "sweep-soispoke": 300000}[root.name]
    if not 150000 < int((root / "gas.txt").read_text().strip()) <= ceiling:
        raise ValueError(f"{root}: implausible measured execution gas")


def package(root, output, labels):
    output.mkdir(parents=True, exist_ok=True)
    for label in labels:
        sweep = root / f"sweep-{label}"
        validate(sweep)
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for path in sorted(sweep.rglob("*")):
                if path.is_symlink():
                    raise ValueError(f"symlink forbidden: {path}")
                if path.is_dir():
                    continue
                if {"out", "cache"}.intersection(path.relative_to(sweep).parts):
                    raise ValueError(f"compiler build output must not be packaged: {path}")
                if path.suffix in (".key", ".zkey", ".r1cs", ".wasm"):
                    raise ValueError(f"setup/build material must not be packaged: {path}")
                data = path.read_bytes()
                info = tarfile.TarInfo(str(path.relative_to(root)))
                info.size, info.mode, info.mtime = len(data), 0o644, 0
                archive.addfile(info, io.BytesIO(data))
        (output / f"sweep-{label}.tar.gz").write_bytes(gzip.compress(buffer.getvalue(), mtime=0))


def manifest(output):
    paths = [output / f"sweep-{label}.tar.gz" for label in LABELS]
    result = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in paths)
    (output / "SHA256SUMS").write_text(result)
    return hashlib.sha256(result.encode()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("artifacts"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--component", choices=("synthetic", "soispoke"), required=True)
    args = parser.parse_args()
    package(args.root, args.output, LABELS[:3] if args.component == "synthetic" else LABELS[3:])
