# Groth16 benchmark artifact releases

These are disposable testbed artifacts, not a production trusted setup. Each synthetic
public-input count has its own R1CS, fresh gnark Groth16 setup, proof and Solidity verifier.
Proving keys and setup randomness are never serialized. Regeneration changes the keys;
reproducibility means independently re-running the checks and calibration, not identical bytes.

## Generate candidates

Use Go from `prover/go.mod`, Foundry **v1.7.1**, Python 3, and Git. The scripts pin their
Solidity compilers and compiler settings. Do not substitute a newer toolchain silently.

```sh
make sweep TARGET=236285 LABEL=236k
make sweep TARGET=300000 LABEL=300k
make sweep TARGET=500000 LABEL=500k
python3 scripts/soispoke.py --output artifacts/sweep-soispoke
python3 scripts/package-sweeps.py --component synthetic
python3 scripts/package-sweeps.py --component soispoke
```

Each output directory contains `verifier.hex` (runtime, not creation bytecode),
`calldata-invalid.hex`, and `gas.txt` (verifier child-call execution gas from the Foundry trace),
plus source and evidence. Valid controls must pass. Invalid synthetic calls use uncompressed
`verifyProof` and negate A's y coordinate while retaining a valid curve point; they must revert
with `ProofInvalid()` after one successful, false four-pair check costing 181,000 gas. The
soispoke proof flips public `input[9]` and must return false after pairing. Its coordinate-alias
and infinity controls must fail before any precompile call.

The sweep ceilings and old expectations were rechecked at Nethermind devnet7 commit
`a4d4306106170c9009e405d1b2819b5a6681e5b9`: 236,285 / 300,000 / 500,000 and
234,190 / 299,256 / 494,586 respectively; soispoke's expectation is 248,437. The existing
harness allows 2% drift and separately checks pairing gas against 181,000 ± 3,000.
If regenerated execution gas exceeds that tolerance, update the harness expectations in a
reviewed follow-up before dispatch. Never relax the pairing check to accommodate malformed points.

## One version, four sweeps

`Build Groth16 candidates` is manually dispatched independently with `component=synthetic`
and `component=soispoke`. Both runs must use the **same source commit** that will be tagged.
They can run concurrently and upload separate candidate artifacts with a 30-day retention.
They do not tag or publish a release. A reviewer must inspect those exact artifacts before
publication; a green workflow is not cryptographic sign-off.

After both builds succeed, prepare the review bundle locally with authenticated `gh`:

```sh
python3 scripts/prepare-release.py --version v1.0.0 --commit <full-sha> \
  --synthetic-run <run-id> --soispoke-run <run-id> --output /tmp/groth16-review
```

The new output directory contains four `sweep-*.tar.gz` assets, `SHA256SUMS`, and
`SIGNOFF-REQUIRED.txt`. A **named human maintainer with crypto/circuit context** reviews:

- Circuit constraints, witness controls, per-circuit setups and absence of serialized private keys.
- Valid/invalid Foundry traces, pairing completion at the expected price, empirical calibration,
  runtime bytecode and exact calldata, and the comparison with Nethermind's 2% tolerance.
- The deliberately pinned upstream commit, independently committed hashes, secondary manifest
  agreement, mutation and gas reconciliation.
- GPL-3.0 verifier attribution, unchanged source and equivalent source access in the same asset.

The reviewer then posts the **exact contents** of `SIGNOFF-REQUIRED.txt` as a PR/issue comment
in `NethermindEth/frame-verify-gas`. The publication script verifies the comment author's
GitHub association is OWNER, MEMBER or COLLABORATOR, that it is a human account, and that the
comment binds the version, source commit and SHA256 of the complete checksum manifest. This
checks provenance; maintainers still must choose a reviewer competent to make that assessment.

Dispatch `Publish reviewed Groth16 release` at the same commit with the version, both run IDs,
and the numeric comment ID. Only then does it create the tag and a draft release, upload all
four archives and the manifest, and publish it as a regular release. Existing tags are rejected.
An interrupted publication can leave a draft: investigate it and use a fresh version, rather
than replacing reviewed assets in place. Publication is restricted to the upstream repository.

## Licensing

The upstream repository's Apache-2.0 license does **not** replace the verifier's GPL-3.0
header. The soispoke archive keeps the verifier under GPL-3.0 and bundles its unchanged source,
license text, attribution, build configuration and generation script. This implements source
availability alongside object code as described in [GPLv3 §6(d)](https://www.gnu.org/licenses/gpl.en.html#section6).
Named maintainer review of that distribution is required before the first publication; this
document and automated checks do not constitute that sign-off.

## Downstream acceptance gate

Do not switch Nethermind dispatches to a nonexistent release. After a reviewed upstream release
exists, implement and smoke-test the versioned download in `run-frame-tx-measurements.yml`,
preserving the `both|mempool|flood` gate, rejecting draft/prerelease/invalid versions, explicitly
setting `GH_TOKEN`, checking SHA256s and verifier plausibility, and using storage outside the
checkout. Note that `RUNNER_TEMP` survives checkout but GitHub runner job cleanup may clear it;
cross-job reuse needs an explicit cache or a persistent runner directory.

Acceptance requires an actual `harness=mempool` dispatch with that release version and
`raise_verify_gas_const=500000`, with all four named Groth16 rows present. Local generator
and harness runs are prerequisites, not substitutes for that dispatch.
