#!/usr/bin/env python3
"""Combine successful candidate runs without regenerating their reviewed artifacts."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tarfile

spec = importlib.util.spec_from_file_location("package", Path(__file__).with_name("package-sweeps.py"))
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True)


def api(path):
    return json.loads(gh("api", path))


def prepare(args):
    if not re.fullmatch(r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", args.version):
        raise ValueError("expected version vMAJOR.MINOR.PATCH without prerelease suffix")
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        raise ValueError("expected full candidate commit SHA")
    args.output.mkdir(parents=True, exist_ok=False)
    for component, run_id in (("synthetic", args.synthetic_run), ("soispoke", args.soispoke_run)):
        run = api(f"repos/{args.repo}/actions/runs/{run_id}")
        if (run["conclusion"] != "success" or run["event"] != "workflow_dispatch"
                or run["head_sha"] != args.commit or run["head_repository"]["full_name"] != args.repo
                or run["path"] != ".github/workflows/build-groth16-candidates.yml"):
            raise ValueError(f"{component} run must be a successful candidate build of {args.repo}@{args.commit}")
        gh("run", "download", str(run_id), "--repo", args.repo,
           "--name", f"{component}-candidate", "--dir", str(args.output))
    expected = {f"sweep-{label}.tar.gz" for label in package.LABELS}
    if {p.name for p in args.output.iterdir()} != expected:
        raise ValueError("candidate assets must contain exactly four sweep archives")
    for label in package.LABELS:
        with tarfile.open(args.output / f"sweep-{label}.tar.gz") as archive:
            names = set()
            total = 0
            for member in archive:
                name = Path(member.name)
                total += member.size
                if (not member.isfile() or name.is_absolute() or str(name) != member.name or ".." in name.parts
                        or name.parts[0] != f"sweep-{label}" or member.name in names
                        or total > 32 * 1024 * 1024):
                    raise ValueError(f"unsafe archive member: {member.name}")
                names.add(member.name)
            required_files = ["verifier.hex", "calldata-invalid.hex", "gas.txt"]
            if label == "soispoke":
                required_files += ["provenance.json", "trace.txt", "source/src/Groth16Verifier.sol",
                                   "source/COPYING", "source/LICENSE.upstream-Apache-2.0",
                                   "source/README.md", "source/foundry.toml", "source/scripts/soispoke.py", "source/scripts/licenses/GPL-3.0.txt", "source/LICENSE.pipeline-MIT"]
            else:
                required_files += ["Verifier.sol", "proof.json", "metadata.json",
                                   "trace-valid.txt", "trace-invalid.txt"]
            for required in required_files:
                if f"sweep-{label}/{required}" not in names:
                    raise ValueError(f"missing {required} in {label}")
    digest = package.manifest(args.output)
    with tarfile.open(args.output / "sweep-soispoke.tar.gz") as archive:
        provenance = json.load(archive.extractfile("sweep-soispoke/provenance.json"))
    upstream_commit = provenance["commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", upstream_commit):
        raise ValueError("missing pinned soispoke commit")
    attestation = (f"Groth16 release sign-off\nversion: {args.version}\ncommit: {args.commit}\n"
                   f"SHA256SUMS-sha256: {digest}\n"
                   "I reviewed the circuits, fresh per-circuit setups, valid and invalid pairing traces, "
                   "gas calibration, upstream pin and hashes, and GPL-3.0 corresponding source and attribution. "
                   "These disposable testbed artifacts are approved for benchmark publication.")
    (args.output / "SIGNOFF-REQUIRED.txt").write_text(attestation + "\n")
    print(attestation)
    if args.signoff_comment:
        comment = api(f"repos/{args.repo}/issues/comments/{args.signoff_comment}")
        if (comment["user"]["type"] != "User"
                or comment["author_association"] not in ("OWNER", "MEMBER", "COLLABORATOR")
                or comment["body"].strip() != attestation):
            raise ValueError("named maintainer sign-off does not match these exact assets and version")
        notes = (f"Benchmark-only disposable Groth16 setups; never use for production funds.\n\n"
                 f"Source commit: {args.commit}\n"
                 f"Pinned soispoke source: https://github.com/soispoke/minimal-shielded-pool/tree/{upstream_commit}\n"
                 f"Synthetic build: https://github.com/{args.repo}/actions/runs/{args.synthetic_run}\n"
                 f"Soispoke build: https://github.com/{args.repo}/actions/runs/{args.soispoke_run}\n"
                 f"Named crypto and licensing reviewer: @{comment['user']['login']}\n"
                 f"Sign-off: {comment['html_url']}\n\n"
                 f"SHA256SUMS SHA256: `{digest}`\n\n"
                 "The soispoke archive includes the pinned upstream commit, GPL-3.0 verifier source, "
                 "license, attribution, build settings and measured gas reconciliation.\n")
        (args.output / "RELEASE-NOTES.md").write_text(notes)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="NethermindEth/frame-verify-gas")
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--synthetic-run", required=True, type=int)
    parser.add_argument("--soispoke-run", required=True, type=int)
    parser.add_argument("--signoff-comment", type=int)
    parser.add_argument("--output", type=Path, required=True)
    prepare(parser.parse_args())
