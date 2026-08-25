run:
	./run.sh

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

reset:
	docker compose down -v
	./install.sh

test:
	./scripts/test-service.sh all

e2e:
	./tests/e2e/run.sh
