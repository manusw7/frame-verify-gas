// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {Test} from "forge-std/Test.sol";
import {Verifier} from "../src/Verifier.sol";

/// @notice Measures the EVM gas of one real Groth16 (BN254) proof verification, the workload a
/// frame VERIFY prefix runs when a validator carries a proof. The proof and verifying key are the
/// checked-in gnark fixture; the number is deterministic and reproducible with `forge test`.
contract VerifyGasTest is Test {
    Verifier internal verifier;
    uint256[8] internal proof;
    uint256[1] internal input;

    function setUp() public {
        verifier = new Verifier();

        string memory json = vm.readFile("./fixture/proof.json");
        uint256[] memory p = vm.parseJsonUintArray(json, ".proof_words");
        uint256[] memory i = vm.parseJsonUintArray(json, ".input_words");
        require(p.length == 8, "proof must be 8 words");
        require(i.length == 1, "input must be 1 word");
        for (uint256 k = 0; k < 8; k++) proof[k] = p[k];
        input[0] = i[0];
    }

    /// @dev A valid proof must verify; verifyProof reverts otherwise.
    function test_ProofIsValid() public view {
        verifier.verifyProof(proof, input);
    }

    /// @dev Reports the gas the external verify call consumes (execution + calldata), i.e. what a
    /// frame paying to verify a proof through this contract is charged.
    function test_MeasureVerifyGas() public {
        uint256[8] memory p = proof;
        uint256[1] memory i = input;
        uint256 gasBefore = gasleft();
        verifier.verifyProof(p, i);
        uint256 gasAfter = gasleft();
        emit log_named_uint("groth16_bn254_verify_gas", gasBefore - gasAfter);
    }
}
