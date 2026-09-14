#!/usr/bin/env python3
"""Extract the reviewed disposable soispoke fixture; never use a floating ref.

Pin chosen from upstream HEAD on 2026-09-14: EIP-8250 first-use state gas
update. The verifier/setup/fixture remain the hardened August testbed circuit.
Changing PIN or HASHES requires source, circuit and licensing review together.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

PIN = "44a826c8de3493bd955aaac995a9a453ee924727"
UPSTREAM = "https://github.com/soispoke/minimal-shielded-pool.git"
HASHES = {
    "build/spend.r1cs": "8b07031680a6d86e9261f64291e398ad9031abb09dcdf3f1d7ca86735847d15e",
    "build/spend_final.zkey": "3a2bcbedd704e05cdbabfcc027c3f27a647380da84c83e506c3fdec5913b877a",
    "build/spend_js/spend.wasm": "4935c11e3be2309af2b6bf6fa9821eaaaf41ffd481716483d0f28b73ed363a2b",
    "circuits/spend.circom": "3d100fbf47852a50ee7fc5bf4fa2e8735e072f2c96533b9cb028168ccb6a78ea",
    "contracts/src/Groth16Verifier.sol": "9667eab74b1efdd0a6cc5c419e6dbe4b7cb78ad29b5ed8ecf3b3d40886b286ac",
    "wallet/smoke_fixture.json": "9b030500c356aeb63956f7cc6a7e4a7ada8013381151cac261054bdbd5c5ef42",
    "contracts/test/VerifierCanonical.t.sol": "a6e14e1baf8642a9bab9f126603db8ba4fb78641e1f7d8ac2560e32a34a5d1a4",
    "tooling/patch_verifier.py": "8359d3364ad219c98d1c81b40cfef90501363d746375a1cc091f6f9cfc938fa7",
    "contracts/foundry.toml": "af279592ce45b3be466ff10f0d20c4b3107ba47776259a738176fc789d59b817",
    "activation_manifest.testbed.json": "5e7e91b8ab465cce6fa60a1bbad89914561c014ecbd4b2aa078b68c08b4b6acc",
    "LICENSE": "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
}
CONFIG = '''[profile.default]
src = "src"
test = "test"
libs = []
solc_version = "0.8.30"
optimizer = true
optimizer_runs = 5000
via_ir = true
evm_version = "prague"
'''


def run(*args, cwd=None):
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"command failed: {args!r}\n{result.stdout}")
    return result.stdout


def verify_source(source):
    if run("git", "rev-parse", "HEAD", cwd=source).strip() != PIN:
        raise ValueError("upstream checkout is not the reviewed commit")
    for name, expected in HASHES.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"independently pinned SHA256 mismatch: {name}")
    manifest = json.loads((source / "activation_manifest.testbed.json").read_text())
    # Secondary only: expected hashes above remain the primary trust anchor.
    for name in list(HASHES)[:5]:
        if manifest["artifacts"].get(name) != HASHES[name]:
            raise ValueError(f"upstream manifest disagrees with our pin: {name}")
    return manifest


def calldata(source):
    transfer = json.loads((source / "wallet/smoke_fixture.json").read_text())["transfer"]
    proof = transfer["proof"]
    words = proof["pA"] + proof["pB"][0] + proof["pB"][1] + proof["pC"]
    words += [transfer[k] for k in ("nf1", "nf2", "out_cm1", "out_cm2", "root", "domain", "public_amount", "fee", "recipient", "authorizer")]
    values = [int(x, 0) if x.startswith("0x") else int(x) for x in words]
    variants = {"valid": values.copy(), "authorizer": values.copy(), "alias": values.copy(), "infinity": values.copy()}
    # Only this upstream mutation reaches pairing and returns false. Coordinate
    # alias/infinity are included to prove they are unsuitable early exits.
    variants["authorizer"][8 + 9] ^= 1
    variants["alias"][1] += 21888242871839275222246405745257275088696311157297823662689037894645226208583
    variants["infinity"][:2] = [0, 0]
    return {k: "f3bb70f6" + "".join(f"{v:064x}" for v in w) for k, w in variants.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/sweep-soispoke"))
    parser.add_argument("--upstream", type=Path, help="optional existing checkout (still SHA/hash checked)")
    args = parser.parse_args()
    forge = os.environ.get("FORGE", "forge")
    version = run(forge, "--version")
    if "1.7.1" not in version.splitlines()[0]:
        raise ValueError("Foundry v1.7.1 is required for reproducible traces")
    if args.output.exists():
        raise ValueError("output already exists; choose a fresh output directory")
    with tempfile.TemporaryDirectory(prefix="soispoke-") as tmp:
        tmp = Path(tmp)
        source = args.upstream.resolve() if args.upstream else tmp / "upstream"
        if not args.upstream:
            run("git", "init", str(source))
            run("git", "fetch", "--depth=1", UPSTREAM, PIN, cwd=source)
            run("git", "checkout", "--detach", "FETCH_HEAD", cwd=source)
        manifest = verify_source(source)
        project = tmp / "project"
        (project / "src").mkdir(parents=True)
        (project / "test").mkdir()
        shutil.copyfile(source / "contracts/src/Groth16Verifier.sol", project / "src/Groth16Verifier.sol")
        (project / "foundry.toml").write_text(CONFIG)
        calls = calldata(source)
        test = '// SPDX-License-Identifier: MIT\npragma solidity ^0.8.30;\nimport {Groth16Verifier} from "../src/Groth16Verifier.sol";\ncontract FixtureTest {\nevent GasBracket(uint256 used);\nGroth16Verifier verifier;\nfunction setUp() public { verifier = new Groth16Verifier(); }\n'
        for name, data in calls.items():
            expected = "true" if name == "valid" else "false"
            test += f'function test_{name}() public {{ bytes memory data = hex"{data}"; uint256 beforeGas = gasleft(); (bool ok, bytes memory result) = address(verifier).staticcall(data); uint256 used = beforeGas - gasleft(); emit GasBracket(used); require(ok && result.length == 32 && abi.decode(result, (bool)) == {expected}, "unexpected verification result"); }}\n'
        test += "}\n"
        (project / "test/Fixture.t.sol").write_text(test)
        trace = run(forge, "test", "--root", str(project), "-vvvv", "--color", "never")
        measurements = {}
        for name in calls:
            block = trace.split(f"FixtureTest::test_{name}()", 1)[1].split("[PASS]", 1)[0]
            match = re.search(r"\[(\d+)\] Groth16Verifier::verifyProof", block)
            if not match:
                raise ValueError(f"missing verifier execution trace for {name}")
            pairings = len(re.findall(r"PRECOMPILES::ecpairing", block, re.IGNORECASE))
            expected_pairings = int(name in ("valid", "authorizer"))
            if pairings != expected_pairings:
                raise ValueError(f"{name}: expected {expected_pairings} pairing calls, got {pairings}")
            if expected_pairings and not re.search(r"\[181000\] PRECOMPILES::ecpairing", block, re.IGNORECASE):
                raise ValueError("four-pair BN254 pairing did not consume 181000 gas")
            bracket = re.search(r"GasBracket\(used: (\d+)", block)
            # Includes the cold verifier-address SLOAD, cold account access,
            # STATICCALL and Solidity returndata bookkeeping, unlike child gas.
            if not bracket or not int(match[1]) <= int(bracket[1]) < int(match[1]) + 6000:
                raise ValueError("gasleft cross-check disagrees with child execution trace")
            measurements[name] = {"gas": int(match[1]), "pairing_calls": pairings, "gasleft_bracket": int(bracket[1])}
        if measurements["valid"]["gas"] != measurements["authorizer"]["gas"]:
            raise ValueError("valid and bit-flipped proof execution gas differ; investigate")
        runtime = run(forge, "inspect", "--root", str(project), "Groth16Verifier", "deployedBytecode").strip()
        artifact = json.loads((project / "out/Groth16Verifier.sol/Groth16Verifier.json").read_text())
        if runtime.removeprefix("0x") != artifact["deployedBytecode"]["object"].removeprefix("0x"):
            raise ValueError("runtime bytecode extraction cross-check failed")
        output = args.output
        output.mkdir(parents=True)
        (output / "verifier.hex").write_text(runtime + "\n")
        (output / "calldata-invalid.hex").write_text("0x" + calls["authorizer"] + "\n")
        (output / "gas.txt").write_text(str(measurements["authorizer"]["gas"]) + "\n")
        (output / "trace.txt").write_text(trace)
        provenance = {"upstream": UPSTREAM, "commit": PIN, "input_sha256": HASHES, "foundry": version.strip(), "compiler": "0.8.30", "optimizer_runs": 5000, "via_ir": True, "evm_version": "prague", "mutation": "input[9] ^= 1", "ceremony": manifest["ceremony"], "measurements": measurements, "historical_full_pool_verify_frame_gas": 294401, "historical_isolated_nethermind_gas": 248437}
        (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        corresponding = output / "source"
        shutil.copytree(project / "src", corresponding / "src")
        shutil.copytree(project / "test", corresponding / "test")
        shutil.copyfile(project / "foundry.toml", corresponding / "foundry.toml")
        shutil.copyfile(Path(__file__).parent / "licenses/GPL-3.0.txt", corresponding / "COPYING")
        shutil.copyfile(source / "LICENSE", corresponding / "LICENSE.upstream-Apache-2.0")
        (corresponding / "scripts/licenses").mkdir(parents=True)
        shutil.copyfile(Path(__file__), corresponding / "scripts/soispoke.py")
        shutil.copyfile(Path(__file__).parent / "licenses/GPL-3.0.txt", corresponding / "scripts/licenses/GPL-3.0.txt")
        pipeline_root = Path(__file__).parent.parent
        pipeline_license = pipeline_root / "LICENSE"
        if not pipeline_license.exists():
            pipeline_license = pipeline_root / "LICENSE.pipeline-MIT"
        shutil.copyfile(pipeline_license, corresponding / "LICENSE.pipeline-MIT")
        (corresponding / "README.md").write_text(f"# Corresponding verifier source\n\nUpstream: {UPSTREAM} at `{PIN}`.\n\n`src/Groth16Verifier.sol` is unmodified, Copyright 2021 0KIMS association,\nSPDX GPL-3.0 (its notice permits version 3 or later); see COPYING.\nThe repository-wide Apache-2.0 license does not replace this file's GPL terms.\n\nRebuild runtime with Foundry v1.7.1: `forge inspect Groth16Verifier deployedBytecode`.\nReproduce gas and all four mutations: `forge test -vvvv`.\nSolc and compiler flags are pinned in foundry.toml.\nNo external Solidity dependencies are needed. Source and bytecode must be\ndistributed together, including these notices and COPYING.\nThis fixture uses upstream's single-party disposable testbed setup.\n")
        print(json.dumps(measurements, indent=2))


if __name__ == "__main__":
    main()
