# Newsfeed CLI — install / uninstall via uv tool
# Override: make install UV=uvx

.PHONY: help install uninstall reinstall

UV ?= uv

help:
	@echo "Targets:"
	@echo "  install    Install the newsfeed CLI into the uv tool environment (uv tool install .)"
	@echo "  uninstall  Remove the installed tool (uv tool uninstall newsfeed)"
	@echo "  reinstall  Uninstall then install again from this directory"

install:
	$(UV) tool install .

uninstall:
	$(UV) tool uninstall newsfeed

reinstall:
	-$(UV) tool uninstall newsfeed
	$(UV) tool install .
