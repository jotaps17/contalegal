.PHONY: build run run-d stop logs dev install clean shell

build:
	docker compose build

run:
	docker compose up

run-d:
	docker compose up -d
	@echo "ContaLegal disponível em http://localhost:8501"

stop:
	docker compose down

logs:
	docker compose logs -f

# Execução local sem Docker (requer pip install -r calculolegal/requirements.txt)
dev:
	streamlit run app.py

install:
	pip install -r calculolegal/requirements.txt

# Remove container, imagem local e volumes anônimos
clean:
	docker compose down --rmi local --volumes

shell:
	docker compose exec contalegal bash
