package main

import (
	"encoding/json"
	"flag"
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

// Cubic binds each public Y[i] to a distinct private X[i]. Changing the slice
// length changes the R1CS and requires a fresh circuit-specific Groth16 setup.
type Cubic struct {
	X []frontend.Variable `gnark:",secret"`
	Y []frontend.Variable `gnark:",public"`
}

func (c *Cubic) Define(api frontend.API) error {
	for i := range c.Y {
		x3 := api.Mul(c.X[i], c.X[i], c.X[i])
		api.AssertIsEqual(c.Y[i], api.Add(x3, c.X[i], 5))
	}
	return nil
}

func must(err error) {
	if err != nil {
		panic(err)
	}
}

func hexWord(b *big.Int) string { return fmt.Sprintf("0x%064x", b) }

func main() {
	inputs := flag.Int("inputs", 1, "number of independently constrained public inputs (1..128)")
	flag.Parse()
	if *inputs < 1 || *inputs > 128 {
		panic("inputs must be in 1..128")
	}
	outDir := "."
	if flag.NArg() > 0 {
		outDir = flag.Arg(0)
	}
	contractDir := filepath.Join(outDir, "src")
	fixtureDir := filepath.Join(outDir, "fixture")
	must(os.MkdirAll(contractDir, 0o755))
	must(os.MkdirAll(fixtureDir, 0o755))

	circuit := Cubic{X: make([]frontend.Variable, *inputs), Y: make([]frontend.Variable, *inputs)}
	ccs, err := frontend.Compile(ecc.BN254.ScalarField(), r1cs.NewBuilder, &circuit)
	must(err)

	pk, vk, err := groth16.Setup(ccs)
	must(err)

	// Distinct nonzero public values prevent accidental zero-input shortcuts.
	assignment := Cubic{X: make([]frontend.Variable, *inputs), Y: make([]frontend.Variable, *inputs)}
	for i := range assignment.X {
		x := int64(i + 3)
		assignment.X[i], assignment.Y[i] = x, x*x*x+x+5
	}
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
	if len(raw) != 8*32 {
		panic("expected commitment-free 8-word Groth16 proof")
	}
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

	// Negate A.y within the BN254 base field. A remains on-curve, B/C and all
	// public inputs remain unchanged. The uncompressed entry point reaches the
	// pairing precompile, whose equation now fails (rather than rejecting a point).
	invalidWords := append([]string(nil), proofWords...)
	q, _ := new(big.Int).SetString("21888242871839275222246405745257275088696311157297823662689037894645226208583", 10)
	ay := new(big.Int).SetBytes(raw[32:64])
	invalidWords[1] = hexWord(new(big.Int).Sub(q, ay))
	fixture := map[string]any{
		"circuit":             "x^3 + x + 5 == y (bn254, groth16, gnark v0.11)",
		"public_input_count":  *inputs,
		"proof_words":         proofWords,
		"invalid_proof_words": invalidWords,
		"input_words":         inputWords,
		"proof_len":           len(raw),
	}
	f, err := os.Create(filepath.Join(fixtureDir, "proof.json"))
	must(err)
	enc := json.NewEncoder(f)
	enc.SetIndent("", "  ")
	must(enc.Encode(fixture))
	must(f.Close())

	fmt.Printf("OK: %d proof words, %d input words, proof_len=%d bytes\n", len(proofWords), len(inputWords), len(raw))
}
