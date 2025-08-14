# Global (system / user site) installation helpers (no virtualenv)

.PHONY: install run upgrade clean

install:
	pip install --upgrade pip
	pip install -r requirements.txt

upgrade:
	pip install --upgrade -r requirements.txt

run:
	python3 src/main.py

clean:
	find . -type f -name '*.pyc' -delete
	find . -type d -name '__pycache__' -exec rm -rf {} +
