.PHONY: help install run web test clean skills

help:
	@echo "Nano-Hermes"
	@echo ""
	@echo "  make install   full install (venv + deps + 'nano' command)"
	@echo "  make run       start the CLI"
	@echo "  make web       start the web panel"
	@echo "  make test      run the health check"
	@echo "  make skills    list learned skills"
	@echo "  make clean     remove caches"

install:
	bash install.sh

run:
	.venv/bin/python nano

web:
	.venv/bin/python nano_hermes.py

test:
	.venv/bin/python -m py_compile nano nano_hermes.py skills.py webtools.py
	@echo "ok - code is valid"

skills:
	.venv/bin/python skills.py list

clean:
	rm -rf .cache __pycache__ *.pyc
