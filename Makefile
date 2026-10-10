GO ?= go
PYTHON ?= .venv/bin/python
WEB_PYTHON ?= /mnt/quant/strategies/stocks-quant/web/.venv/bin/python

.PHONY: build init check test test-blog
build:
	$(GO) build -o bin/news-claw ./cmd/news-claw

init:
	python3 scripts/init_db.py

check: build
	bin/news-claw check
	$(PYTHON) -m collectors.news --check --task us-china-export-controls-daily
	$(PYTHON) -m collectors.news --check --task ai-products-attention-daily
	$(PYTHON) -m collectors.news --check --task robotics-physical-ai-space-daily

test: build
	$(GO) test -race ./...
	$(PYTHON) -m unittest discover -s tests -v

test-blog:
	$(WEB_PYTHON) -m unittest discover -s tests_blog -v
