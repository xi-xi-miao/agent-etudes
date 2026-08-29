# agent-etudes — run these from the repository root.
#
# Which étude a target applies to is set with CHALLENGE, e.g.
#     make demo CHALLENGE=c001

CHALLENGE ?= c001

.DEFAULT_GOAL := help

.PHONY: help sync lint test stats collect retro demo check-words check-challenge

help:
	@echo "agent-etudes targets (CHALLENGE=$(CHALLENGE)):"
	@echo ""
	@echo "  make sync              install every dependency group with uv"
	@echo "  make lint              lint all annotations.md (+ their session.yaml)"
	@echo "  make test              run the test suite"
	@echo "  make stats             move/glyph/motif distributions and phase timelines"
	@echo "  make collect           copy attempt branches into results/ (maintainer)"
	@echo "  make retro             collect + stats + gallery into retros/$(CHALLENGE)"
	@echo "  make demo              round trip for challenges/$(CHALLENGE)"
	@echo "  make check-words       vocabulary check over the repository"
	@echo "  make check-challenge   contract check for challenges/$(CHALLENGE)"
	@echo ""
	@echo "  set the étude with CHALLENGE=cXXX (default: c001)"

sync:
	uv sync --all-groups

lint:
	uv run python scripts/lint_annotations.py --session

test:
	uv run pytest

stats:
	uv run python scripts/stats.py results

collect:
	uv run python scripts/collect_results.py

retro:
	@if [ ! -d challenges/$(CHALLENGE) ]; then \
	  echo "make retro: challenges/$(CHALLENGE) does not exist." >&2; \
	  echo "Set CHALLENGE to an étude from the index in challenges/README.md." >&2; \
	  exit 1; \
	fi
	uv run python scripts/retro.py --challenge $(CHALLENGE)

demo:
	@if [ ! -f challenges/$(CHALLENGE)/demo.sh ]; then \
	  echo "make demo: challenges/$(CHALLENGE)/demo.sh not found." >&2; \
	  echo "Set CHALLENGE to an étude that ships a demo, e.g. make demo CHALLENGE=c001;" >&2; \
	  echo "the index of études is in challenges/README.md." >&2; \
	  exit 1; \
	fi
	bash challenges/$(CHALLENGE)/demo.sh

check-words:
	bash scripts/check_words.sh

check-challenge:
	uv run python scripts/check_challenge.py challenges/$(CHALLENGE)
