# ============================================================
# Makefile — ERP Accounting Engine
# ============================================================

.DEFAULT_GOAL := help
.PHONY: help install install-dev check run run-prod lint fmt type-check \
        security-scan arch-check test test-unit test-integration test-e2e \
        test-compliance test-performance test-all coverage migrate \
        migrate-rollback seed db-reset docker-build docker-up docker-down \
        clean pre-commit docs

PYTHON     := python3
PIP        := pip3
UVICORN    := uvicorn
APP_MODULE := asgi:app
ENV_FILE   := .env

# ── Warna terminal ───────────────────────────────────────────
RESET  := \033[0m
BOLD   := \033[1m
GREEN  := \033[32m
YELLOW := \033[33m
CYAN   := \033[36m
RED    := \033[31m

# ═══════════════════════════════════════════════════════════════
# HELP
# ═══════════════════════════════════════════════════════════════
help:
	@echo ""
	@echo "$(BOLD)$(CYAN)ERP Accounting Engine — Makefile$(RESET)"
	@echo "$(CYAN)════════════════════════════════════════$(RESET)"
	@echo ""
	@echo "$(BOLD)Setup$(RESET)"
	@echo "  make install         Install production dependencies"
	@echo "  make install-dev     Install dev + test dependencies"
	@echo "  make pre-commit      Install pre-commit hooks"
	@echo ""
	@echo "$(BOLD)Development$(RESET)"
	@echo "  make run             Jalankan server development (reload)"
	@echo "  make run-prod        Jalankan server production (4 workers)"
	@echo "  make check           Cek health sistem (import, env, struktur)"
	@echo ""
	@echo "$(BOLD)Code Quality$(RESET)"
	@echo "  make lint            Ruff + flake8 linting"
	@echo "  make fmt             Format kode (black + isort)"
	@echo "  make fmt-check       Cek format tanpa ubah file"
	@echo "  make type-check      mypy type checking"
	@echo "  make security-scan   Bandit + safety + pip-audit"
	@echo "  make arch-check      Import-linter architecture enforcement"
	@echo ""
	@echo "$(BOLD)Testing$(RESET)"
	@echo "  make test            Jalankan semua test"
	@echo "  make test-unit       Unit test saja"
	@echo "  make test-integration  Integration test (butuh DB, Redis)"
	@echo "  make test-e2e        End-to-end test"
	@echo "  make test-compliance PSAK + IFRS + Coretax compliance test"
	@echo "  make test-performance  Performance + load test"
	@echo "  make coverage        Test + laporan coverage HTML"
	@echo ""
	@echo "$(BOLD)Database$(RESET)"
	@echo "  make migrate         Jalankan migrasi Alembic (upgrade head)"
	@echo "  make migrate-rollback  Rollback 1 langkah (downgrade -1)"
	@echo "  make migrate-status  Status migrasi saat ini"
	@echo "  make migrate-new m=<nama>  Buat file migrasi baru"
	@echo "  make seed            Seed data awal (CoA PSAK, tax rates)"
	@echo "  make db-reset        DROP + CREATE + migrate + seed (DEV ONLY)"
	@echo ""
	@echo "$(BOLD)Docker$(RESET)"
	@echo "  make docker-build    Build Docker image"
	@echo "  make docker-up       docker-compose up (semua service)"
	@echo "  make docker-down     docker-compose down"
	@echo "  make docker-logs     Tail log semua container"
	@echo ""
	@echo "$(BOLD)Utilitas$(RESET)"
	@echo "  make clean           Hapus cache, .pyc, artifact test"
	@echo "  make docs            Build dokumentasi MkDocs"
	@echo ""

# ═══════════════════════════════════════════════════════════════
# SETUP
# ═══════════════════════════════════════════════════════════════
install:
	@echo "$(GREEN)▶ Installing production dependencies...$(RESET)"
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

install-dev:
	@echo "$(GREEN)▶ Installing dev dependencies...$(RESET)"
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements_dev.txt

pre-commit:
	@echo "$(GREEN)▶ Installing pre-commit hooks...$(RESET)"
	pre-commit install
	pre-commit install --hook-type commit-msg

# ═══════════════════════════════════════════════════════════════
# DEVELOPMENT
# ═══════════════════════════════════════════════════════════════
run:
	@echo "$(GREEN)▶ Starting development server (auto-reload)...$(RESET)"
	$(PYTHON) main.py --reload --host 127.0.0.1 --port 8000 --log-level debug

run-prod:
	@echo "$(GREEN)▶ Starting production server (4 workers)...$(RESET)"
	$(PYTHON) main.py --host 0.0.0.0 --port 8000 --workers 4 --log-level info

check:
	@echo "$(GREEN)▶ Running system health check...$(RESET)"
	$(PYTHON) main.py --check --verbose

check-fast:
	@echo "$(GREEN)▶ Running fast health check (skip import scan)...$(RESET)"
	$(PYTHON) main.py --check --skip-import

# ═══════════════════════════════════════════════════════════════
# CODE QUALITY
# ═══════════════════════════════════════════════════════════════
lint:
	@echo "$(YELLOW)▶ Linting dengan ruff...$(RESET)"
	ruff check . --fix
	@echo "$(YELLOW)▶ Linting dengan flake8...$(RESET)"
	flake8 constitution axioms bootstrap config kernel domain \
	       policy_engine compliance application ports adapters \
	       event_gateway transformers infrastructure audit \
	       projections reports main.py asgi.py

fmt:
	@echo "$(YELLOW)▶ Formatting dengan black...$(RESET)"
	black . --line-length 100
	@echo "$(YELLOW)▶ Sorting imports dengan isort...$(RESET)"
	isort . --profile black

fmt-check:
	@echo "$(YELLOW)▶ Cek format (tidak mengubah file)...$(RESET)"
	black . --check --line-length 100
	isort . --check-only --profile black

type-check:
	@echo "$(YELLOW)▶ Type checking dengan mypy...$(RESET)"
	mypy constitution axioms bootstrap config kernel domain \
	     policy_engine compliance application ports adapters \
	     event_gateway transformers infrastructure audit \
	     projections reports main.py asgi.py \
	     --config-file pyproject.toml

security-scan:
	@echo "$(RED)▶ Security scan dengan bandit...$(RESET)"
	bandit -r constitution axioms bootstrap config kernel domain \
	         policy_engine compliance application ports adapters \
	         infrastructure audit -c pyproject.toml
	@echo "$(RED)▶ Cek known vulnerabilities dengan safety...$(RESET)"
	safety check -r requirements.txt
	@echo "$(RED)▶ Audit pip dependencies...$(RESET)"
	pip-audit -r requirements.txt

arch-check:
	@echo "$(YELLOW)▶ Architecture enforcement dengan import-linter...$(RESET)"
	lint-imports --config .importlinter

# ═══════════════════════════════════════════════════════════════
# TESTING
# ═══════════════════════════════════════════════════════════════
test:
	@echo "$(GREEN)▶ Running all tests...$(RESET)"
	pytest tests/ -v --tb=short

test-unit:
	@echo "$(GREEN)▶ Running unit tests...$(RESET)"
	pytest tests/unit/ -v --tb=short -m unit

test-integration:
	@echo "$(GREEN)▶ Running integration tests (butuh DB & Redis)...$(RESET)"
	pytest tests/integration/ -v --tb=short -m integration

test-e2e:
	@echo "$(GREEN)▶ Running end-to-end tests...$(RESET)"
	pytest tests/e2e/ -v --tb=long -m e2e

test-compliance:
	@echo "$(GREEN)▶ Running compliance tests (PSAK, IFRS, Coretax)...$(RESET)"
	pytest tests/compliance/ -v --tb=short -m compliance

test-performance:
	@echo "$(GREEN)▶ Running performance tests...$(RESET)"
	pytest tests/performance/ -v --tb=short -m performance

test-arch:
	@echo "$(GREEN)▶ Running architecture tests...$(RESET)"
	pytest tests/architecture/ -v --tb=short -m architecture

coverage:
	@echo "$(GREEN)▶ Running tests with coverage...$(RESET)"
	pytest tests/unit/ tests/integration/ \
	       --cov=. \
	       --cov-report=html:htmlcov \
	       --cov-report=term-missing \
	       --cov-report=xml:coverage.xml \
	       --cov-config=pyproject.toml \
	       --tb=short
	@echo "$(GREEN)Coverage report: htmlcov/index.html$(RESET)"

# ═══════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════
migrate:
	@echo "$(GREEN)▶ Running Alembic migrations (upgrade head)...$(RESET)"
	alembic -c migrations/alembic.ini upgrade head

migrate-rollback:
	@echo "$(YELLOW)▶ Rolling back 1 migration step...$(RESET)"
	alembic -c migrations/alembic.ini downgrade -1

migrate-status:
	@echo "$(CYAN)▶ Migration status...$(RESET)"
	alembic -c migrations/alembic.ini current
	alembic -c migrations/alembic.ini history --verbose

migrate-new:
	@if [ -z "$(m)" ]; then echo "$(RED)Usage: make migrate-new m=<nama_migrasi>$(RESET)"; exit 1; fi
	@echo "$(GREEN)▶ Creating new migration: $(m)...$(RESET)"
	alembic -c migrations/alembic.ini revision --autogenerate -m "$(m)"

seed:
	@echo "$(GREEN)▶ Seeding initial data (CoA PSAK + Tax Rates)...$(RESET)"
	$(PYTHON) deployment/scripts/seed_data.sh

db-reset:
	@echo "$(RED)⚠️  WARNING: Ini akan menghapus seluruh database!$(RESET)"
	@echo "$(RED)Hanya untuk environment DEVELOPMENT.$(RESET)"
	@read -p "Ketik 'yes' untuk konfirmasi: " confirm; \
	if [ "$$confirm" = "yes" ]; then \
	    $(PYTHON) -c "import asyncio, asyncpg, os; \
	        asyncio.run(asyncpg.connect(os.environ['DATABASE_URL']))"; \
	    alembic -c migrations/alembic.ini downgrade base; \
	    alembic -c migrations/alembic.ini upgrade head; \
	    echo "$(GREEN)Database reset selesai.$(RESET)"; \
	else \
	    echo "$(YELLOW)Dibatalkan.$(RESET)"; \
	fi

# ═══════════════════════════════════════════════════════════════
# DOCKER
# ═══════════════════════════════════════════════════════════════
docker-build:
	@echo "$(GREEN)▶ Building Docker image...$(RESET)"
	docker build -f deployment/docker/Dockerfile \
	             -t erp-accounting-engine:latest \
	             -t erp-accounting-engine:2.0.0 .

docker-up:
	@echo "$(GREEN)▶ Starting all services via docker-compose...$(RESET)"
	docker-compose -f deployment/docker/docker-compose.yaml up -d
	@echo "$(GREEN)Services running. API: http://localhost:8000$(RESET)"

docker-down:
	@echo "$(YELLOW)▶ Stopping all docker services...$(RESET)"
	docker-compose -f deployment/docker/docker-compose.yaml down

docker-logs:
	docker-compose -f deployment/docker/docker-compose.yaml logs -f

docker-ps:
	docker-compose -f deployment/docker/docker-compose.yaml ps

# ═══════════════════════════════════════════════════════════════
# OPERATIONAL SCRIPTS
# ═══════════════════════════════════════════════════════════════
period-close-monthly:
	@echo "$(GREEN)▶ Running monthly period close...$(RESET)"
	$(PYTHON) deployment/scripts/monthly_period_close.py

period-close-yearly:
	@echo "$(GREEN)▶ Running year-end closing...$(RESET)"
	$(PYTHON) deployment/scripts/annual_year_end_close.py

depreciation-run:
	@echo "$(GREEN)▶ Running monthly depreciation...$(RESET)"
	$(PYTHON) deployment/scripts/run_depreciation_all_assets.py

bank-recon:
	@echo "$(GREEN)▶ Running bank reconciliation...$(RESET)"
	$(PYTHON) deployment/scripts/run_bank_reconciliation_auto.py

payroll-run:
	@echo "$(GREEN)▶ Running monthly payroll...$(RESET)"
	$(PYTHON) deployment/scripts/run_payroll_all_employees.py

tax-submit:
	@echo "$(GREEN)▶ Submitting SPT to Coretax DJP...$(RESET)"
	$(PYTHON) deployment/scripts/run_coretax_submit_spt_masa.py

integrity-check:
	@echo "$(GREEN)▶ Running full hash chain integrity check...$(RESET)"
	$(PYTHON) deployment/scripts/run_integrity_check_full_hash_chain.py

rebuild-projections:
	@echo "$(YELLOW)▶ Rebuilding all CQRS projections...$(RESET)"
	$(PYTHON) deployment/scripts/rebuild_all_cqrs_projections.py

emergency-freeze:
	@echo "$(RED)⚠️  EMERGENCY: Membekukan semua mutasi akuntansi...$(RESET)"
	$(PYTHON) deployment/scripts/emergency_freeze_all_mutations.py

emergency-unfreeze:
	@echo "$(YELLOW)▶ Mencairkan sistem (butuh dual control)...$(RESET)"
	$(PYTHON) deployment/scripts/emergency_unfreeze_dual_control.py

dr-replay:
	@echo "$(GREEN)▶ Disaster recovery replay from snapshot...$(RESET)"
	$(PYTHON) deployment/scripts/disaster_recovery_replay_from_snapshot.py

# ═══════════════════════════════════════════════════════════════
# UTILITAS
# ═══════════════════════════════════════════════════════════════
clean:
	@echo "$(YELLOW)▶ Cleaning build artifacts...$(RESET)"
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "coverage.xml" -delete 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
	@echo "$(GREEN)Clean selesai.$(RESET)"

docs:
	@echo "$(GREEN)▶ Building MkDocs documentation...$(RESET)"
	mkdocs build --clean

docs-serve:
	@echo "$(GREEN)▶ Serving docs at http://localhost:8001...$(RESET)"
	mkdocs serve --dev-addr 127.0.0.1:8001

ci: fmt-check lint type-check security-scan arch-check test-unit
	@echo "$(GREEN)✅ CI checks passed.$(RESET)"
