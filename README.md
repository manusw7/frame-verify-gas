# frame-verify-gas

A reproducible measurement of the EVM gas cost of verifying one Groth16 proof on BN254,
the workload an EIP-8141 frame `VERIFY` prefix runs when a transaction carries a proof.

The point is a single citable number with a run behind it: a real Groth16 verify on BN254,
executed through the EVM, costs about **194k gas**, against an effective validation budget of
about **79k gas** (`MAX_VERIFY_GAS` minus the intrinsic and nonce deductions). That is roughly
**2x over budget**, which is why in-clear proof verification cannot ride the public mempool and
why aggregation is the path being explored in EIP-8288, rather than raising the budget.

## Result

```
groth16_bn254_verify_gas: 194396   // pure verifyProof execution
                          216112    // including the external call and calldata
```

## What is measured

A minimal Groth16 circuit (`x^3 + x + 5 == y`, `y` public) is proven with
[gnark](https://github.com/Consensys/gnark). gnark exports a Solidity verifier that checks the
proof through the BN254 precompiles (`ecAdd 0x06`, `ecMul 0x07`, `ecPairing 0x08`), which is the
exact arithmetic a frame `VERIFY` prefix performs. The verifier is then run on the EVM under
Foundry and the gas is read off `gasleft()`.

The proof and verifying key are checked in under `fixture/` and `src/Verifier.sol`, so the number
is deterministic without re-running the prover.

## Reproduce

Measure the gas from the checked-in fixture (needs only [Foundry](https://getfoundry.sh)):

```
make measure
```

Regenerate the proof, verifying key and Solidity verifier from scratch (needs Go 1.24+):

```
make prove
make measure
```

## Layout

- `prover/` — gnark program that builds the circuit, proves it, and exports `src/Verifier.sol` and `fixture/proof.json`.
- `src/Verifier.sol` — gnark-exported BN254 Groth16 verifier.
- `fixture/proof.json` — the proof words and public input the test consumes.
- `test/VerifyGas.t.sol` — asserts the proof verifies and measures the verification gas.

## Notes

- The circuit is intentionally trivial; the verification cost of a Groth16 proof is fixed by the
  proof system and curve, not by the circuit size, so a three-constraint circuit measures the same
  verify cost as a large one.
- BN254 offers about 100-bit security after Kim-Barbulescu. BLS12-381 (EIP-2537) is the stronger
  choice for a new primitive; its four-pair check is `37_700 + 32_600 * 4 = 168_100` gas for the
  pairing alone, still over budget.
