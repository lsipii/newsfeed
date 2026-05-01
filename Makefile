# Newsfeed CLI — install / uninstall via uv tool
# Override: make install UV=uvx
#
# Two install modes (they are not interchangeable day-to-day):
#
#   • Normal install / reinstall — uv copies a built wheel into ~/.local/share/uv/tools/.
#     You must run ``make reinstall`` after changing code, or you keep running old files.
#
#   • Editable install — the tool’s Python path includes THIS clone, so edits apply on the
#     next ``newsfeed`` run with no Makefile step. Use this for development.
#
# Always pass --force for local installs: a fixed version in pyproject.toml can otherwise
# skip replacing the tool and leave stale wheels.

.PHONY: help install install-editable uninstall reinstall reinstall-editable wipe-tool-dir

UV ?= uv
# e.g. ~/.local/share/uv/tools — where the per-tool venv lives (see ``uv tool dir``).
UV_TOOLS_DIR := $(shell $(UV) tool dir 2>/dev/null)

help:
	@echo "Targets:"
	@echo "  install              Snapshot install (wheel copied under ~/.local/share/uv/tools/)"
	@echo "  reinstall            uninstall + wipe tool dir + install (clean slate)"
	@echo "  install-editable     Dev install: runs code from this repo; no reinstall after edits"
	@echo "  reinstall-editable   uninstall + wipe + install-editable"
	@echo "  uninstall            uv tool uninstall + remove ~/.local/share/uv/tools/newsfeed"
	@echo "  wipe-tool-dir        rm -rf only (after failed uninstall; rarely needed alone)"
	@echo ""
	@echo "Use install-editable while hacking; use reinstall when you want a self-contained copy."

install:
	$(UV) tool install --force .

install-editable:
	$(UV) tool install --force --editable .

# ``uv tool uninstall`` can leave the old environment on disk; remove it so the next
# install is never mixed with a previous tree.
wipe-tool-dir:
	@set -e; t="$(UV_TOOLS_DIR)/newsfeed"; \
	if [ -n "$(UV_TOOLS_DIR)" ] && [ -d "$$t" ]; then \
		echo "Removing $$t"; \
		rm -rf "$$t"; \
	fi

uninstall:
	-$(UV) tool uninstall newsfeed
	@$(MAKE) wipe-tool-dir

reinstall:
	-$(UV) tool uninstall newsfeed
	@$(MAKE) wipe-tool-dir
	$(UV) tool install --force .

reinstall-editable:
	-$(UV) tool uninstall newsfeed
	@$(MAKE) wipe-tool-dir
	$(UV) tool install --force --editable .
