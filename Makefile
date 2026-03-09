# Run commands (Python’s common “scripts” alternative to npm run)
# Usage: make dev | make start | make install | make setup

.PHONY: dev start install data setup

VENV := .venv
UVICORN := $(VENV)/bin/uvicorn
PIP := $(VENV)/bin/pip
PYTHON := $(VENV)/bin/python

dev:
	$(UVICORN) app.main:app --reload --host 0.0.0.0 --port 8000

start:
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000

install:
	$(PIP) install -e .

data:
	mkdir -p data

setup: install data
	@echo "Done. Run 'make dev' to start the server."
