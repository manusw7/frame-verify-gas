# Pinned soispoke fixture

Run `python3 scripts/soispoke.py --output artifacts/sweep-soispoke` with Foundry
v1.7.1 available as `forge` (or set `FORGE`). Python 3 and Git are the only other
dependencies. An optional `--upstream /path/to/checkout` avoids fetching; its HEAD
and every consumed upstream input are still checked. Existing output paths are
rejected to avoid mixing releases.

The deliberately selected upstream commit is
`44a826c8de3493bd955aaac995a9a453ee924727`, the September 14, 2026 HEAD inspected
during implementation. It updates EIP-8250 first-use state gas; its verifier and
setup artifacts are unchanged from the August hardened testbed. Pin updates need
a human review of source and hashes together. The script's SHA256 values are the
primary checks; the upstream activation manifest is only a secondary agreement
check. The smoke fixture, canonical mutation tests, patcher, compiler settings,
manifest itself, and upstream license are pinned alongside the five circuit
artifacts. This is a single-party disposable testbed setup, never a production
trusted setup.

## Gas reconciliation and measured evidence

Actual Foundry v1.7.1, solc 0.8.30, optimizer 5000, via-IR, Prague execution:

| Call | Verifier execution gas | Pairing calls | `gasleft()` bracket |
| --- | ---: | ---: | ---: |
| Valid fixture | 248,437 | 1 | 253,386 |
| Authorizer `input[9] ^= 1` | 248,437 | 1 | 253,386 |
| Coordinate alias `a[1] += Q` | 441 | 0 | 5,390 |
| Infinity `a = [0, 0]` | 763 | 0 | 5,712 |

The pairing call costs 181,000 gas and is checked explicitly in the trace.
The bracket consistently adds 4,949 gas for loading the stored verifier address,
cold account access, calling, and return-data bookkeeping. `gas.txt` records the
verifier child execution gas, matching the Nethermind harness measurement scope.
Both valid and invalid return values are asserted. The extracted runtime is
cross-checked between `forge inspect deployedBytecode` and the compiler artifact.

The plan's wrong-mutation hypothesis is disproved: neither early-exit mutation
comes close to 294,401 gas. More decisively, upstream's
[hardened-pool live-run record](https://github.com/soispoke/minimal-shielded-pool/blob/44a826c8de3493bd955aaac995a9a453ee924727/devnet/vectors/2026-08-14-hardened-pool.md)
identifies 294,401 as the **successful full pool VERIFY frame** on live ethrex,
transaction `0x3318f589b59d52825285a71b5cfd0dcbfd99ebee19aefa1a18c9b0d057657301`.
The [tight-profile record](https://github.com/soispoke/minimal-shielded-pool/blob/44a826c8de3493bd955aaac995a9a453ee924727/devnet/vectors/2026-08-14-tight-gas-profile.md)
retains this historical maximum; subsequent live transfer/withdrawal frames used
294,374. Git history locates the original manifest figure in commit
`38b39376b30f8b42529164789a5e75c5ee195ccf`.

The [dispatcher source](https://github.com/soispoke/minimal-shielded-pool/blob/44a826c8de3493bd955aaac995a9a453ee924727/devnet/ShieldedPoolDispatcher.yul)
loads frame data and enforces pool/domain/canonicality checks around the verifier.
The 45,964-gas numerical difference compares different execution scopes and
clients; we do not claim an opcode-by-opcode replay of that historical ethrex
transaction. The release ships the freshly reproduced isolated 248,437, which
exactly matches the campaign's isolated Nethermind number, rather than the
manifest's historical whole-frame maximum.

## Source distribution and licensing review

`contracts/src/Groth16Verifier.sol` is snarkJS 0.7.5 output, patched by upstream
`tooling/patch_verifier.py`, redistributed without further modification. It is
labelled GPL-3.0 by its SPDX tag and header notice (Copyright 2021 0KIMS
association); upstream's NOTICE says the same. The upstream repository's
Apache-2.0 license does not replace that label. The archive includes the verifier,
the canonical GPL-3.0 text (hash-checked), upstream LICENSE and NOTICE, the patcher,
its dependency-free build configuration, generated tests and extraction script
under `sweep-soispoke/source/`.
That source can rebuild the published runtime with `forge inspect
Groth16Verifier deployedBytecode` from its directory. The build requires no
external Solidity library or proving key. The extraction script is MIT;
upstream notices remain intact.

This packaging implements same-place source access described in
[GPLv3 section 6(d)](https://www.gnu.org/licenses/gpl.en.html).
Keep source and object code in the same release archive, at no additional charge,
and do not relabel the verifier as MIT or Apache-2.0. The archive's generated test
fixture contains only public proof/input data, without copying the upstream wallet
private-key fields.

**Licensing decision pending.** Options: ship bytecode with corresponding source
(current), regenerate the verifier with a permissively licensed generator, ask
iden3 for terms covering generated verifiers, or exclude the soispoke bytecode.

**Release remains gated on named human crypto/circuit and licensing sign-off.**
Implementation and source review by an automated agent do not supply that named
approval. The PR/release checklist must identify the reviewer and exact artifact
manifest they approved, including this GPL packaging and the disposable ceremony.
