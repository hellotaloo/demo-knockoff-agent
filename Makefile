.PHONY: help lint format check dev test clean

help:
	@echo "Taloo Backend - Development Commands"
	@echo ""
	@echo "Usage:"
	@echo "  make lint     - Run ruff linter to check code quality"
	@echo "  make format   - Auto-format code with ruff"
	@echo "  make check    - Run both lint and format (without fixing)"
	@echo "  make dev      - Start development server with auto-reload"
	@echo "  make test     - Run tests (if configured)"
	@echo "  make clean    - Remove cache files and artifacts"
	@echo ""

lint:
	@echo "Running ruff linter..."
	@ruff check src/ app.py

format:
	@echo "Formatting code with ruff..."
	@ruff format src/ app.py
	@ruff check --fix src/ app.py

check:
	@echo "Checking code quality..."
	@ruff check src/ app.py
	@ruff format --check src/ app.py

dev:
	@echo "Starting development server..."
	@uvicorn app:app --reload --host 0.0.0.0 --port 8080

test:
	@echo "Running tests..."
	@pytest tests/ -v

clean:
	@echo "Cleaning cache files..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Done!"
