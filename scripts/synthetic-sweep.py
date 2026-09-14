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


def run(*args, cwd=None):
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError(f"Command failed: {' '.join(map(str, args))}\n{result.stdout}")
    return result.stdout


def generate_test(fixture):
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
            ok := staticcall(gas(), target, add(payload, 32), mload(payload), add(result, 32), 4)
            size := returndatasize()
        }}
        uint256 consumed = beforeGas - gasleft();
        require(!ok && size == 4 && bytes4(result) == Verifier.ProofInvalid.selector,
                "expected pairing failure");
        emit log_named_uint("call_gas_with_overhead", consumed);
    }}
}}
'''


def measure(binary, base, n):
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
    (project / "test/Synthetic.t.sol").write_text(generate_test(fixture))
    valid_trace = run("forge", "test", "--match-test", "test_Valid", "-vvvv", cwd=project)
    trace = run("forge", "test", "--match-test", "test_Invalid", "-vvvv", cwd=project)
    (project / "trace-valid.txt").write_text(valid_trace)
    (project / "trace-invalid.txt").write_text(trace)
    # Foundry's child-call trace is execution gas, excluding the caller's ABI/CALL
    # overhead. Independently cross-check the gasleft bracket below.
    matches = re.findall(r"\[(\d+)\] Verifier::verifyProof\(", trace)
    pairings = re.findall(r"\[(\d+)\] (?:PRECOMPILES::ecpairing|PRECOMPILES::ecPairing|0x0{39}8)\(", trace)
    if len(matches) != 1 or pairings != ["181000"]:
        raise RuntimeError(f"Expected one verifier call and one 4-pair BN254 call (181000 gas)\n{trace}")
    gas = int(matches[0])
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
    print(f"calibration N={n}: verifier={gas}, pairing={pairings[0]}", flush=True)
    return {"n": n, "gas": gas, "runtime": runtime, "calldata": calldata, "project": project}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9-]+", args.label) or not 1 <= args.target <= 1000000:
        parser.error("label must be alphanumeric/hyphens and target in 1..1000000")
    if "1.7.1" not in run("forge", "--version").splitlines()[0]:
        raise ValueError("Foundry v1.7.1 is required for reproducible traces")
    with tempfile.TemporaryDirectory(prefix="groth16-sweep-") as temp:
        base = Path(temp)
        binary = base / "prover"
        run("go", "build", "-o", str(binary), ".", cwd=ROOT / "prover")
        samples = {}

        def sample(n):
            if n not in samples:
                samples[n] = measure(binary, base, n)
            return samples[n]["gas"]

        if sample(1) > args.target:
            raise RuntimeError("Target below the one-input verifier's measured gas")
        low, high = 1, 2
        while sample(high) <= args.target:
            low, high = high, high * 2
            if high > 128:
                raise RuntimeError("Target not bracketed within supported 128 public inputs")
        while high - low > 1:
            mid = (low + high) // 2
            if sample(mid) <= args.target:
                low = mid
            else:
                high = mid
        ordered = sorted(samples)
        if any(samples[a]["gas"] >= samples[b]["gas"] for a, b in zip(ordered, ordered[1:])):
            raise RuntimeError("Non-monotonic calibration: investigate instead of selecting a circuit")
        chosen = samples[low]
        output = args.output / f"sweep-{args.label}"
        output.mkdir(parents=True, exist_ok=False)
        (output / "verifier.hex").write_text(chosen["runtime"] + "\n")
        (output / "calldata-invalid.hex").write_text(chosen["calldata"] + "\n")
        (output / "gas.txt").write_text(str(chosen["gas"]) + "\n")
        # Keep enough evidence to audit both the valid control and failing pairing.
        for name in ("trace-valid.txt", "trace-invalid.txt"):
            shutil.copyfile(chosen["project"] / name, output / name)
        shutil.copyfile(chosen["project"] / "src/Verifier.sol", output / "Verifier.sol")
        shutil.copyfile(chosen["project"] / "fixture/proof.json", output / "proof.json")
        metadata = {
            "target_gas": args.target, "public_inputs": low,
            "measured_execution_gas": chosen["gas"], "pairing_gas": 181000,
            "mutation": "A.y = BN254_BASE_FIELD - A.y; uncompressed verifyProof",
            "setup": "fresh circuit-specific, single-party disposable benchmark setup",
            "solc": SOLC, "evm_version": "cancun", "optimizer_runs": 200,
            "forge": run("forge", "--version").strip(),
            "go": run("go", "version").strip(),
            "source_commit": run("git", "rev-parse", "HEAD", cwd=ROOT).strip(),
            "source_tree_dirty": bool(run("git", "status", "--porcelain", cwd=ROOT).strip()),
            "source_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                              for path in ("prover/main.go", "prover/go.mod", "prover/go.sum",
                                           "scripts/synthetic-sweep.py")},
            "calibration": [{"public_inputs": n, "gas": samples[n]["gas"]} for n in ordered],
        }
        (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(f"Selected N={low}, {chosen['gas']} <= {args.target}; artifacts: {output}")


if __name__ == "__main__":
    main()
