#!/usr/bin/env python3
"""Calibrate a circuit-specific Groth16 setup against measured verifier execution gas.

Temporary proving keys are never serialized. This is a disposable benchmark setup,
not a production ceremony. Every candidate N receives its own fresh Setup and proof.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOLC = "0.8.24"
MAX_INPUTS = 128
# Nethermind's harness asserts frame gas available >= ceiling - 3000.
CAP_MARGIN = 3000
PROOF_INVALID = 0x7fcdd1f4
WARNING = "Benchmark-only disposable setup - never use to secure value."


def run(*args, cwd=None):
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError(f"Command failed: {' '.join(map(str, args))}\n{result.stdout}")
    return result.stdout


def generate_test(fixture, cap):
    n = len(fixture["input_words"])
    words = lambda key: ",".join(f"uint256({x})" for x in fixture[key])
    return f'''// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import {{Verifier}} from "../src/Verifier.sol";
contract SyntheticTest {{
    Verifier verifier;
    event log_named_uint(string key, uint256 val);
    function setUp() public {{ verifier = new Verifier(); }}
    function test_Valid() public view {{
        uint256[8] memory proof = [{words("proof_words")}];
        uint256[{n}] memory input = [{words("input_words")}];
        verifier.verifyProof(proof, input);
    }}
    function test_Invalid() public {{
        uint256[8] memory proof = [{words("invalid_proof_words")}];
        uint256[{n}] memory input = [{words("input_words")}];
        bytes memory payload = abi.encodeCall(Verifier.verifyProof, (proof, input));
        address target = address(verifier);
        bytes memory result = new bytes(4);
        bool ok;
        uint256 size;
        uint256 beforeGas = gasleft();
        assembly {{
            ok := staticcall({cap}, target, add(payload, 32), mload(payload), add(result, 32), 4)
            size := returndatasize()
        }}
        uint256 consumed = beforeGas - gasleft();
        emit log_named_uint("call_gas_with_overhead", consumed);
        emit log_named_uint("revert_selector", !ok && size == 4 ? uint256(uint32(bytes4(result))) : 0);
    }}
}}
'''


def measure(binary, base, n, cap):
    project = base / str(n)
    run(str(binary), "-inputs", str(n), str(project))
    (project / "test").mkdir()
    (project / "foundry.toml").write_text(f'''[profile.default]
solc_version = "{SOLC}"
evm_version = "cancun"
optimizer = true
optimizer_runs = 200
''')
    fixture = json.loads((project / "fixture/proof.json").read_text())
    (project / "test/Synthetic.t.sol").write_text(generate_test(fixture, cap))
    valid_trace = run("forge", "test", "--match-test", "test_Valid", "-vvvv", cwd=project)
    trace = run("forge", "test", "--match-test", "test_Invalid", "-vvvv", cwd=project)
    (project / "trace-valid.txt").write_text(valid_trace)
    (project / "trace-invalid.txt").write_text(trace)
    # Foundry's child-call trace is execution gas, excluding the caller's ABI/CALL
    # overhead. Independently cross-check the gasleft bracket below.
    matches = re.findall(r"\[(\d+)\] Verifier::verifyProof\(", trace)
    if len(matches) != 1:
        raise RuntimeError(f"Expected one verifier call\n{trace}")
    gas = int(matches[0])
    pairings = re.findall(r"\[(\d+)\] PRECOMPILES::ecpairing\(", trace, re.IGNORECASE)
    selector = re.search(r"revert_selector(?:\", val:|:)\s*(\d+)", trace)
    # Under the cap, the full 4-pair check must run and return false, then revert.
    fits = (pairings == ["181000"] and selector is not None and int(selector[1]) == PROOF_INVALID
            and re.search(r"\[181000\] PRECOMPILES::ecpairing\([^\n]*\n[^\n]*\[Return\] false\n"
                          r"[^\n]*\[Revert\] ProofInvalid\(\)", trace, re.IGNORECASE) is not None)
    print(f"calibration N={n}: verifier={gas}, pairing={pairings}, fits cap {cap}={fits}", flush=True)
    sample = {"n": n, "gas": gas, "fits": fits, "project": project}
    if not fits:
        return sample
    bracket = re.search(r"call_gas_with_overhead(?:\", val:|:)\s*(\d+)", trace)
    if bracket is None or not gas <= int(bracket[1]) <= gas + 6000:
        raise RuntimeError(f"Trace gas disagrees with independent gasleft measurement\n{trace}")
    runtime = run("forge", "inspect", "src/Verifier.sol:Verifier", "deployedBytecode", cwd=project).strip()
    if not re.fullmatch(r"0x[0-9a-fA-F]+", runtime):
        raise RuntimeError("Unexpected runtime bytecode")
    signature = f"verifyProof(uint256[8],uint256[{n}])"
    selector = run("cast", "sig", signature).strip()
    calldata = selector + "".join(x.removeprefix("0x").zfill(64)
                                  for x in fixture["invalid_proof_words"] + fixture["input_words"])
    return {**sample, "runtime": runtime, "calldata": calldata}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts")
    parser.add_argument("--allow-dirty", action="store_true", help="permit an uncommitted source tree")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9-]+", args.label) or not CAP_MARGIN < args.target <= 1000000:
        parser.error(f"label must be alphanumeric/hyphens and target in {CAP_MARGIN + 1}..1000000")
    if run("forge", "--version").splitlines()[0].strip() != "forge Version: 1.7.1":
        raise ValueError("Foundry v1.7.1 is required for reproducible traces")
    output = args.output / f"sweep-{args.label}"
    if output.exists():
        raise ValueError(f"{output} already exists; choose a fresh output directory")
    dirty = bool(run("git", "status", "--porcelain", cwd=ROOT).strip())
    if dirty and not args.allow_dirty:
        raise ValueError("source tree is dirty; commit first or pass --allow-dirty")
    cap = args.target - CAP_MARGIN
    with tempfile.TemporaryDirectory(prefix="groth16-sweep-") as temp:
        base = Path(temp)
        binary = base / "prover"
        run("go", "build", "-o", str(binary), ".", cwd=ROOT / "prover")
        samples = {}

        def fits(n):
            if n not in samples:
                samples[n] = measure(binary, base, n, cap)
            return samples[n]["fits"]

        if not fits(1):
            raise RuntimeError("Even the one-input verifier cannot complete pairing under the cap")
        low, high = 1, 2
        while high <= MAX_INPUTS and fits(high):
            low, high = high, min(high * 2, MAX_INPUTS + 1)
        while high - low > 1:
            mid = (low + high) // 2
            if fits(mid):
                low = mid
            else:
                high = mid
        ordered = sorted(samples)
        qualifying = [n for n in ordered if samples[n]["fits"]]
        if qualifying != ordered[:len(qualifying)] or any(
                samples[a]["gas"] >= samples[b]["gas"] for a, b in zip(qualifying, qualifying[1:])):
            raise RuntimeError("Non-monotonic calibration: investigate instead of selecting a circuit")
        chosen = samples[low]
        output.mkdir(parents=True, exist_ok=False)
        (output / "verifier.hex").write_text(chosen["runtime"] + "\n")
        (output / "calldata-invalid.hex").write_text(chosen["calldata"] + "\n")
        (output / "gas.txt").write_text(str(chosen["gas"]) + "\n")
        (output / "README.txt").write_text(f"WARNING: {WARNING}\nSingle-party Groth16 setup generated for gas "
                                           "benchmarking; anyone may hold its toxic waste.\n")
        # Keep enough evidence to audit both the valid control and failing pairing.
        for name in ("trace-valid.txt", "trace-invalid.txt"):
            shutil.copyfile(chosen["project"] / name, output / name)
        shutil.copyfile(chosen["project"] / "src/Verifier.sol", output / "Verifier.sol")
        shutil.copyfile(chosen["project"] / "fixture/proof.json", output / "proof.json")
        metadata = {
            "WARNING": WARNING,
            "target_gas": args.target, "public_inputs": low,
            "measured_execution_gas": chosen["gas"], "pairing_gas": 181000,
            "invalid_call_gas_cap": cap, "cap_headroom_gas": cap - chosen["gas"],
            "mutation": "A.y = BN254_BASE_FIELD - A.y; uncompressed verifyProof",
            "setup": "fresh circuit-specific, single-party disposable benchmark setup",
            "solc": SOLC, "evm_version": "cancun", "optimizer_runs": 200,
            "forge": run("forge", "--version").strip(),
            "go": run("go", "version").strip(),
            "source_commit": run("git", "rev-parse", "HEAD", cwd=ROOT).strip(),
            "source_tree_dirty": dirty,
            "source_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                              for path in ("prover/main.go", "prover/go.mod", "prover/go.sum",
                                           "scripts/synthetic-sweep.py")},
            "calibration": [{"public_inputs": n, "gas": samples[n]["gas"], "pairing_completes_under_cap": samples[n]["fits"]}
                            for n in ordered],
        }
        (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(f"Selected N={low}, {chosen['gas']} gas, pairing completes under cap {cap}; artifacts: {output}")


if __name__ == "__main__":
    main()
