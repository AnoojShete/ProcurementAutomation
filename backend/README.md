# Procurement Workflow Automation Platform

FastAPI backend for procurement vendor management.

## Features

- FastAPI with Swagger docs at `/docs`
- PostgreSQL via SQLAlchemy
- Vendor CRUD APIs
- REST-only procurement agent
- Structured logging in `logs/app.log`
- Dockerized local development

## Setup

1. Create a virtual environment with Python 3.12+.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `backend/.env.example` to `.env` at the repository root and fill in PostgreSQL credentials.
4. Run the app:

```bash
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

## API

- `GET /` returns `{"message":"Procurement API Running"}`
- `POST /vendors`
- `GET /vendors`
- `GET /vendors/{id}`
- `PUT /vendors/{id}`
- `DELETE /vendors/{id}`

Swagger is available at:

- `http://localhost:8000/docs`
- `http://localhost:8000/redoc`

## Seed Test Data

Insert 5 sample vendors:

```bash
python -m backend.app.utils.seed_data
```

## Sample curl Commands

Create a vendor:

```bash
curl -X POST http://localhost:8000/vendors ^
  -H "Content-Type: application/json" ^
  -d "{\"company_name\":\"Acme Supplies\",\"contact_person\":\"John Doe\",\"email\":\"john.doe@acme.example\",\"phone\":\"+1-555-0101\",\"gst_number\":\"GSTACME0001\",\"address\":\"12 Industrial Ave\",\"status\":\"active\"}"
```

List vendors:

```bash
curl http://localhost:8000/vendors
```

Get a vendor by id:

```bash
curl http://localhost:8000/vendors/1
```

Update a vendor:

```bash
curl -X PUT http://localhost:8000/vendors/1 ^
  -H "Content-Type: application/json" ^
  -d "{\"status\":\"verified\"}"
```

Delete a vendor:

```bash
curl -X DELETE http://localhost:8000/vendors/1
```

## Agent

Run the REST-only procurement agent demo:

```bash
python -m backend.app.agents.agent
```

## Docker

Start FastAPI and PostgreSQL:

```bash
docker compose up --build
```
