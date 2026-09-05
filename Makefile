PYTHON := .venv/bin/python
PIP := .venv/bin/pip
export PYTHONPATH := $(CURDIR)

.PHONY: install wallet-setup dev-start pay-once test

install:
	@command -v python3 >/dev/null || (echo "python3 is required"; exit 1)
	@python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
		|| (echo "Python 3.11+ is required (x402-xrpl)"; exit 1)
	@test -d .venv || python3 -m venv .venv
	$(PIP) install -r requirements.txt

wallet-setup:
	$(PYTHON) scripts/wallet_setup.py

dev-start:
	bash scripts/dev-start.sh

pay-once:
	$(PYTHON) scripts/pay_once.py $(ARGS)

test:
	$(PYTHON) -m pytest -q
