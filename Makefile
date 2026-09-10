.PHONY: test collect collect-transition up down

test:
	python3 -m unittest discover -s tests -v

collect:
	sh ./collector.sh

collect-transition:
	sudo -iu octra sh ./transition_collector.sh

up:
	OCTRA_STATUS_DIR=./runtime docker compose up -d --build

down:
	docker compose down
