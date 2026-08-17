package main

import (
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"path/filepath"

	"github.com/consensys/gnark-crypto/ecc"
	fr "github.com/consensys/gnark-crypto/ecc/bn254/fr"
	"github.com/consensys/gnark/backend/groth16"
	"github.com/consensys/gnark/frontend"
	"github.com/consensys/gnark/frontend/cs/r1cs"
)

// Cubic is the canonical minimal Groth16 circuit: prove knowledge of X such that
// X**3 + X + 5 == Y, with Y the single public input. It uses only field arithmetic,
// so gnark emits a plain verifier that verifies through the BN254 precompiles
// (ecAdd 0x06, ecMul 0x07, ecPairing 0x08) - exactly what a frame VERIFY prefix runs.
type Cubic struct {
	X frontend.Variable `gnark:",secret"`
	Y frontend.Variable `gnark:",public"`
}

func (c *Cubic) Define(api frontend.API) error {
	x3 := api.Mul(c.X, c.X, c.X)
	api.AssertIsEqual(c.Y, api.Add(x3, c.X, 5))
	return nil
}

func must(err error) {
	if err != nil {
		panic(err)
	}
}

func hexWord(b *big.Int) string { return fmt.Sprintf("0x%064x", b) }

func main() {
	outDir := "."
	if len(os.Args) > 1 {
		outDir = os.Args[1]
	}
	contractDir := filepath.Join(outDir, "src")
	fixtureDir := filepath.Join(outDir, "fixture")
	must(os.MkdirAll(contractDir, 0o755))
	must(os.MkdirAll(fixtureDir, 0o755))

	var circuit Cubic
	ccs, err := frontend.Compile(ecc.BN254.ScalarField(), r1cs.NewBuilder, &circuit)
	must(err)

	pk, vk, err := groth16.Setup(ccs)
	must(err)

	// X = 3 -> Y = 27 + 3 + 5 = 35
	assignment := Cubic{X: 3, Y: 35}
	witness, err := frontend.NewWitness(&assignment, ecc.BN254.ScalarField())
	must(err)
	publicWitness, err := witness.Public()
	must(err)

	proof, err := groth16.Prove(ccs, pk, witness)
	must(err)

	// Native verify: fail loudly if the proof is not valid before we measure anything.
	must(groth16.Verify(proof, vk, publicWitness))

	// Solidity verifier.
	sol, err := os.Create(filepath.Join(contractDir, "Verifier.sol"))
	must(err)
	must(vk.ExportSolidity(sol))
	must(sol.Close())

	// Proof words for Solidity (8 uint256 for a commitment-free circuit).
	ms, ok := proof.(interface{ MarshalSolidity() []byte })
	if !ok {
		panic("proof does not expose MarshalSolidity")
	}
	raw := ms.MarshalSolidity()
	proofWords := make([]string, 0, len(raw)/32)
	for i := 0; i+32 <= len(raw); i += 32 {
		proofWords = append(proofWords, "0x"+fmt.Sprintf("%064x", new(big.Int).SetBytes(raw[i:i+32])))
	}

	// Public input words.
	pubVec, ok := publicWitness.Vector().(fr.Vector)
	if !ok {
		panic("unexpected public witness vector type")
	}
	inputWords := make([]string, 0, len(pubVec))
	for i := range pubVec {
		var bi big.Int
		pubVec[i].BigInt(&bi)
		inputWords = append(inputWords, hexWord(&bi))
	}

	fixture := map[string]any{
		"circuit":     "x^3 + x + 5 == y (bn254, groth16, gnark v0.11)",
		"public_y":    "35",
		"proof_words": proofWords,
		"input_words": inputWords,
		"proof_len":   len(raw),
	}
	f, err := os.Create(filepath.Join(fixtureDir, "proof.json"))
	must(err)
	enc := json.NewEncoder(f)
	enc.SetIndent("", "  ")
	must(enc.Encode(fixture))
	must(f.Close())

	fmt.Printf("OK: %d proof words, %d input words, proof_len=%d bytes\n", len(proofWords), len(inputWords), len(raw))
}
