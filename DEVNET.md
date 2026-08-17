# Cross-client devnet confirmation

The gas number in this repo is measured through revm under Foundry. To show it is
a consensus fact and not a property of one EVM, the same Groth16 proof was run
through an EIP-8141 frame transaction on a two-client devnet (Nethermind and
ethrex, the public `frames-devnet-0` peer).

## Result

| Check | Nethermind | ethrex |
|---|---|---|
| Verifier deployed at `0xF01ecC1dF1868C3B15f0edC4768812b9c435BBfb` | code present | code present |
| `verifyProof` `eth_call` on the fixture | valid | valid |
| Groth16 verify as an execution frame, block | `10393` | same block |
| Block hash | `0xba89c8b92a40fabe8717e7a3d43bf08377d1171cf86656bd97090557af8d8cbd` | identical |
| State root | `0x88d497b87a121200b1893e18fc4ca089445c556a533eca762c0f18241d4d4905` | identical |
| Frame transaction `gasUsed` | `215581` | `215581` |

Both clients import the same block and charge the same gas for a frame
transaction whose execution frame verifies the proof. The gas is client
independent.

## The verification does not fit the validation prefix

The verify costs about 194k gas, above the 100k `MAX_VERIFY_GAS` that bounds a
frame's validation prefix. On the same devnet, a prefix budget of 200k is
rejected by ethrex at ingress:

```
-32000 Invalid params: Frame transaction prefix gas budget (frames + sig cost) exceeds MAX_VERIFY_GAS
```

Nethermind admits the same transaction only because the run raises the bound with
`--TxPool.FrameTxMaxVerifyGas=500000`. So a real Groth16 verify cannot ride the
public-mempool validation prefix under the spec default. That is the case for
aggregation, not for a higher budget: raising the budget reopens the
mempool denial-of-service the prefix bound exists to prevent.

## Reproducing

The devnet run uses a Kurtosis `ethereum-package` enclave with a Nethermind and
an ethrex execution client on the frame-transaction branches. The submitter and
evidence scripts are bench tooling, not part of this repo; the numbers above are
recorded from `eth_getBlockByNumber`, `eth_getTransactionReceipt` and
`eth_sendRawTransaction` on both clients.
