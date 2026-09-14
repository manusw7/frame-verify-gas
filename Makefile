.PHONY: prove measure test clean

prove:
	cd prover && go run . ..

measure:
	forge test -vv --match-test test_MeasureVerifyGas

test:
	forge test -vv

clean:
	rm -rf out cache

# Current sweep ceilings verified on nethermind eip8141-frame-txs-devnet7:
# a4d4306106170c9009e405d1b2819b5a6681e5b9 (2026-09-14).
.PHONY: sweep synthetic-sweeps
sweep:
	python3 scripts/synthetic-sweep.py --target $(TARGET) --label $(or $(LABEL),$(TARGET)) --output $(or $(OUTPUT),artifacts) $(if $(ALLOW_DIRTY),--allow-dirty)

synthetic-sweeps:
	$(MAKE) sweep TARGET=236285 LABEL=236k
	$(MAKE) sweep TARGET=300000 LABEL=300k
	$(MAKE) sweep TARGET=500000 LABEL=500k
