GO ?= go
PYTHON ?= .venv/bin/python
WEB_PYTHON ?= /mnt/projects/growthyoung/web/.venv/bin/python

.PHONY: build init check test test-blog
build:
	$(GO) build -o bin/news-claw ./cmd/news-claw

init:
	python3 scripts/init_db.py

check: build
	bin/news-claw check
	$(PYTHON) -m collectors.news --check --task company-google-news
	$(PYTHON) -m collectors.news --check --task company-amazon-news
	$(PYTHON) -m collectors.news --check --task company-nvidia-news

test: build
	$(GO) test -race ./...
	$(PYTHON) -m unittest discover -s tests -v

test-blog:
	$(WEB_PYTHON) -m unittest discover -s tests_blog -v
