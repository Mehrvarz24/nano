.PHONY: help install run web test clean skills

help:
	@echo "⚡ Nano-Hermes"
	@echo ""
	@echo "  make install   نصب کامل (venv + deps + دستور nano)"
	@echo "  make run       اجرای CLI"
	@echo "  make web       اجرای پنل وب"
	@echo "  make test      تست سلامت کد"
	@echo "  make skills    لیست مهارت‌ها"
	@echo "  make clean     پاک کردن کش"

install:
	bash install.sh

run:
	.venv/bin/python nano

web:
	.venv/bin/python nano_hermes.py

test:
	.venv/bin/python -m py_compile nano nano_hermes.py skills.py webtools.py
	@echo "✓ کد سالم"

skills:
	.venv/bin/python skills.py list

clean:
	rm -rf .cache __pycache__ *.pyc
