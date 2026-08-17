.PHONY: prove measure test clean

prove:
	cd prover && go run . ..

measure:
	forge test -vv --match-test test_MeasureVerifyGas

test:
	forge test -vv

clean:
	rm -rf out cache
