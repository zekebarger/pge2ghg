# GHG Emissions Tracker

A FastAPI app that reads hourly electricity usage from a CSV, calculates CO₂e emissions using time-varying grid emissions factors, and stores the results in PostgreSQL. Fully containerized with Docker.

---

## Project Structure

```
ghg-tracker/
├── app/
│   ├── __init__.py
│   ├── main.py           # FastAPI routes
│   ├── models.py         # SQLAlchemy table + Pydantic schemas
│   ├── database.py       # DB connection and session management
│   ├── watttime.py       # collect data from WattTime
│   └── calculations.py   # Emissions logic (pure functions, no DB)
├── data/
│   ├── pge_example.csv   # Realistic input data
│   └── sample_usage.csv  # Initial input data
├── Dockerfile
├── docker-compose.yml
├── secrets.yaml
└── requirements.txt
```

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running

---

## Running the App

**1. Start both containers:**
```bash
docker compose up --build
```
The `--build` flag tells Docker to (re)build the app image before starting.
On first run this may take a minute while it downloads base images and installs dependencies.

You should see Postgres start, then the FastAPI app connect to it.

**2. Trigger CSV processing:**
```bash
curl -X POST http://localhost:8000/process
```
This reads `data/sample_usage.csv`, calculates emissions, and writes to Postgres.

**3. Query the stored results:**
```bash
# All records
curl http://localhost:8000/emissions

# Filter by region
curl "http://localhost:8000/emissions?region=WECC"

# Aggregate summary
curl http://localhost:8000/emissions/summary
```

**4. Explore the interactive API docs:**

Open http://localhost:8000/docs in your browser. FastAPI auto-generates a Swagger UI where you can call every endpoint interactively — no curl needed.

**5. Stop everything:**
```bash
docker compose down
```
Your Postgres data persists in the `postgres_data` Docker volume. To wipe it too:
```bash
docker compose down -v
```

---

## The Calculation

```
CO₂e (kg) = kWh × emissions_factor (kg CO₂e / kWh)
```

The CSV uses a **marginal, time-varying emissions factor** (column: `emissions_factor_kg_per_kwh`). This changes hour-by-hour to reflect what generation source is actually serving load at that moment — more accurate than a single annual average. Real-world data for this comes from sources like [WattTime](https://www.watttime.org/) or [Electricity Maps](https://www.electricitymaps.com/).

---

## Connecting to Postgres Directly

With the containers running, you can connect from your host machine:

- **Host:** `localhost`
- **Port:** `5432`
- **Database:** `ghgdb`
- **User:** `ghguser`
- **Password:** `ghgpassword`

Works with any Postgres client (DBeaver, TablePlus, psql, etc.).

---

## Next Steps

- **Add a real CSV upload endpoint** — swap `POST /process` to accept a file via `UploadFile`
- Create a parser to handle data exported from PG&E's website, like `pge_example.csv`
- Instead of requiring the uploaded CSV to contain hourly intensity
values, collect data from WattTime (CAISO north is free to access)
  - login information is in `secrets.yaml`
  - marginal intensity values can be downloaded 32 days at a time at 5min resolution
- Don't store GHG emission results in the database. Instead, store intensity data
from WattTime so that we can reuse data we've already accessed

## Future goals

- **Add Alembic** for proper database migrations
- **Deploy to the cloud** — this docker-compose setup translates directly to AWS ECS, Google Cloud Run, or Fly.io
- **Swap the emissions factor** for live data from the WattTime or Electricity Maps API
