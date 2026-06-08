# Common tasks for the Võro MCP server. Run `make help` for the list.
.DEFAULT_GOAL := help
SHELL := /bin/bash

# Release tags. Keep in sync with the VRO_DATA_TAG / VRO_GIELLA_TAG defaults in
# scripts/fetch_data.sh and scripts/fetch_giella.sh. Override on the command
# line, e.g. `make release-data DATA_TAG=data-v2`.
DATA_TAG ?= data-v1
DATA_ASSET := vro-data.tar.xz
GIELLA_TAG ?= giella-v1
GIELLA_ASSET := giella-share.tar.xz

.PHONY: help install data giella giella-build setup test run local-url \
        package-data release-data package-giella release-giella deploy \
        deploy-new-secret deploy-local-secret deploy-release deploy-release-force \
        deploy-local deploy-local-force deploy-none undeploy

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) \
	  | awk -F':.*## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create .venv and install the package
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e .

data: ## Download the SQLite datasets into data/
	scripts/fetch_data.sh

giella: ## Download the prebuilt GiellaLT artifacts into data/giella-share/
	scripts/fetch_giella.sh

giella-build: ## Build the GiellaLT artifacts from source (heavy toolchain)
	scripts/install_giella_artifacts.sh

setup: ## One-command local setup (Debian/Ubuntu)
	scripts/run_local_ubuntu.sh

test: ## Run the smoke tests
	python -m unittest discover -s tests

run: ## Run the MCP server (blocks on stdio; clients normally launch it themselves)
	.venv/bin/vro-mcp-server

local-url: ## Print local MCP path plus Claude, Codex, and JSON client config
	@bin="$(CURDIR)/.venv/bin/vro-mcp-server"; \
	 [[ -x "$$bin" ]] || echo "(not built yet, run 'make install' first)"; \
	 echo "Local MCP server binary:"; \
	 echo "  $$bin"; \
	 echo; \
	 echo "Claude Code:"; \
	 echo "  claude mcp add vro -- $$bin"; \
	 echo; \
	 echo "Codex CLI:"; \
	 echo "  codex mcp add vro -- $$bin"; \
	 echo; \
	 echo "Generic JSON MCP client config:"; \
	 printf '%s\n' \
	   "  {" \
	   "    \"mcpServers\": {" \
	   "      \"vro\": {" \
	   "        \"command\": \"$$bin\"," \
	   "        \"cwd\": \"$(CURDIR)\"" \
	   "      }" \
	   "    }" \
	   "  }"

package-data: ## Build the dataset release archive from data/
	tar cJf $(DATA_ASSET) -C data \
	  vro_dictionary.sqlite vro_corpus.sqlite vro_word_bag.sqlite LICENSE NOTICE

release-data: package-data ## Publish the dataset as a GitHub release (DATA_TAG=...)
	gh release create $(DATA_TAG) $(DATA_ASSET) \
	  --title "Võro dataset ($(DATA_TAG))" \
	  --notes $$'Võro datasets for the MCP server.\n\n`vro-data.tar.xz`: dictionary, corpus, and word-bag SQLite DBs + LICENSE/NOTICE.\n\nFetch with `scripts/fetch_data.sh`. CC-BY-SA-4.0. Sources and attribution in the bundled NOTICE.'
	rm -f $(DATA_ASSET)

package-giella: ## Build the giella-share release archive from data/giella-share/
	test -f data/giella-share/LICENSE || { echo "data/giella-share/LICENSE missing; build with 'make giella-build' first"; exit 1; }
	tar cJf $(GIELLA_ASSET) -C data/giella-share .

release-giella: package-giella ## Publish the GiellaLT artifacts as a GitHub release (GIELLA_TAG=...)
	gh release create $(GIELLA_TAG) $(GIELLA_ASSET) \
	  --title "GiellaLT artifacts ($(GIELLA_TAG))" \
	  --notes $$'Prebuilt GiellaLT runtime artifacts for the Võro MCP server.\n\n`giella-share.tar.xz`: compiled FSTs, CG grammars, and spellers + LICENSE/NOTICE.\n\nFetch with `scripts/fetch_giella.sh`. GPL-3.0. Sources and corresponding-source commits in the bundled NOTICE.'
	rm -f $(GIELLA_ASSET)

deploy: ## Deploy to Modal using the secret + settings from .env
	scripts/deploy_modal.sh

deploy-new-secret: ## Generate a fresh secret URL, save it to .env, then deploy
	NEW_SECRET=1 scripts/deploy_modal.sh

deploy-local-secret: ## Push the MCP_PATH secret defined in .env to Modal, then deploy
	LOCAL_SECRET=1 scripts/deploy_modal.sh

deploy-release: ## Deploy using GitHub release data, skipping existing files
	DATA_SOURCE=release scripts/deploy_modal.sh

deploy-release-force: ## Deploy and overwrite Modal data from GitHub releases
	DATA_SOURCE=release FORCE_DATA=1 scripts/deploy_modal.sh

deploy-local: ## Deploy and upload data from DATA_DIR, defaulting to ./data
	DATA_SOURCE=local DATA_DIR="$(DATA_DIR)" scripts/deploy_modal.sh

deploy-local-force: ## Deploy and overwrite Modal data from DATA_DIR
	DATA_SOURCE=local FORCE_DATA=1 DATA_DIR="$(DATA_DIR)" scripts/deploy_modal.sh

deploy-none: ## Deploy code only; never inspect or change Modal data
	DATA_SOURCE=none scripts/deploy_modal.sh

undeploy: ## Remove Modal app, volume, and secret
	scripts/remove_modal.sh
