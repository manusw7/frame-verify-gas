package main

import (
	"fmt"
	"testing"

	"github.com/consensys/gnark-crypto/ecc"
	"github.com/consensys/gnark/frontend"
	"github.com/consensys/gnark/frontend/cs/r1cs"
)

// Every public input must be constrained, including the last element in a slice.
func TestEveryPublicInputIsBound(t *testing.T) {
	for _, n := range []int{1, 3, 48} {
		t.Run(fmt.Sprint(n), func(t *testing.T) {
			c := Cubic{X: make([]frontend.Variable, n), Y: make([]frontend.Variable, n)}
			ccs, err := frontend.Compile(ecc.BN254.ScalarField(), r1cs.NewBuilder, &c)
			if err != nil {
				t.Fatal(err)
			}
			a := Cubic{X: make([]frontend.Variable, n), Y: make([]frontend.Variable, n)}
			for i := range a.X {
				x := int64(i + 3)
				a.X[i], a.Y[i] = x, x*x*x+x+5
			}
			check := func(wantValid bool) {
				t.Helper()
				w, err := frontend.NewWitness(&a, ecc.BN254.ScalarField())
				if err != nil {
					t.Fatal(err)
				}
				_, err = ccs.Solve(w)
				if (err == nil) != wantValid {
					t.Fatalf("valid=%v: %v", wantValid, err)
				}
			}
			check(true)
			for i := range a.Y {
				old := a.Y[i]
				a.Y[i] = 0
				check(false)
				a.Y[i] = old
			}
		})
	}
}
