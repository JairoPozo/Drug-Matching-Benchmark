# Drug matching benchmark: every target is a thin wrapper around `uv run dmb ...`,
# so on Windows without make you can run the same commands directly (see README).

MATCHER ?= dummy
SPLIT ?= dev
EVAL_ARGS ?=
BUILD_ARGS ?=

.PHONY: setup data build eval test format all notebook

setup:  ## Install dependencies (Python 3.12 + locked packages) with uv
	uv sync

data:  ## Download NDC and RxNorm into data/raw (records version + sha256)
	uv run dmb download

build:  ## Build data/processed: catalog, queries, labels and splits
	uv run dmb build $(BUILD_ARGS)

eval:  ## Run a matcher on a split and write metrics to reports/
	uv run dmb eval --matcher $(MATCHER) --split $(SPLIT) $(EVAL_ARGS)

test:  ## Run pytest and ruff
	uv run pytest
	uv run ruff check .
	uv run ruff format --check .

format:  ## Auto-format and fix lint
	uv run ruff format .
	uv run ruff check --fix .

all: setup data build eval  ## Everything from scratch

notebook:  ## Jupyter for exploration only (official numbers come from `make eval`)
	uv run --group explore jupyter lab
