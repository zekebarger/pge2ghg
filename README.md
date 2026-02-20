# GHG Emissions Tracker

A FastAPI app that calculates CO₂ emissions from PG&E CSV exports. It supports two energy types:

- **Electricity** — accepts a PG&E Green Button CSV, fetches time-varying marginal CO₂ intensity from the [WattTime](https://www.watttime.org/) API, and calculates emissions for each 15-minute interval. WattTime data is cached in PostgreSQL so repeat uploads covering the same date range don't hit the API again.
- **Natural gas** — accepts a PG&E natural gas CSV and calculates daily CO₂ emissions using the EPA fixed factor (5.312 kg CO₂/therm). No API key or database required.

Fully containerized with Docker.

---

## Project Structure

```
pge2ghg/
├── app/
│   ├── __init__.py
│   ├── main.py           # FastAPI routes
│   ├── models.py         # SQLAlchemy table + Pydantic schemas
│   ├── database.py       # DB connection and session management
│   ├── watttime.py       # WattTime API client + DB caching
│   └── calculations.py   # CSV parsing and emissions logic (pure functions)
├── tests/
│   ├── conftest.py            # Shared fixtures
│   ├── test_calculations.py
│   └── test_gas_calculations.py
├── data/                 # Drop PG&E CSV files here (mounted into the container)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt  # Dev dependencies (pytest)
└── .env.example
```

---

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- A [WattTime](https://www.watttime.org/) account (free tier works)

---

## Setup

**1. Copy the example env file and fill in your credentials:**
```bash
cp .env.example .env
```

Edit `.env` with your WattTime username and password. The Postgres values can stay as-is for local development.

**2. Start both containers:**
```bash
docker compose up --build
```

The `--build` flag tells Docker to (re)build the app image before starting. On first run this may take a minute while it downloads base images and installs dependencies.

You should see Postgres start, then the FastAPI app connect to it.

---

## Using the API

**Upload any PG&E CSV (auto-detected):**
```bash
curl -X POST http://localhost:8000/process_auto \
  -F "file=@data/your_pge_export.csv"
```

The file type is detected automatically from the `TYPE` column in the CSV (`Electric usage` or `Natural gas usage`). The response includes a `file_type` field (`"electric"` or `"gas"`) in addition to the normal summary fields.

Example response (electric):
```json
{
  "file_type": "electric",
  "records_processed": 2880,
  "total_kwh": 312.45,
  "total_co2e_kg": 42.18,
  "total_co2e_lbs": 93.01,
  "avg_emissions_factor": 0.000135,
  "records": ["..."]
}
```

Example response (gas):
```json
{
  "file_type": "gas",
  "records_processed": 31,
  "total_therms": 16.77,
  "total_co2_kg": 89.1082,
  "total_co2_lbs": 196.4696,
  "emissions_factor_kg_per_therm": 5.312,
  "records": ["..."]
}
```

The dedicated endpoints are still available if needed:

**Upload a PG&E electricity CSV:**
```bash
curl -X POST http://localhost:8000/process \
  -F "file=@data/your_pge_electric_export.csv"
```

**Upload a PG&E natural gas CSV:**
```bash
curl -X POST http://localhost:8000/process_gas \
  -F "file=@data/your_pge_gas_export.csv"
```

**Inspect the cached WattTime intensity data:**
```bash
# Most recent 100 records (default)
curl http://localhost:8000/intensity

# Up to 1000 records
curl "http://localhost:8000/intensity?limit=1000"

# Coverage summary (count, earliest, latest point_time)
curl http://localhost:8000/intensity/summary
```

**Health check:**
```bash
curl http://localhost:8000/health
```

**Interactive API docs:**

Open http://localhost:8000/docs in your browser. FastAPI auto-generates a Swagger UI where you can call every endpoint interactively — including uploading a file via the browser.

**Stop everything:**
```bash
docker compose down
```

Your Postgres data persists in the `postgres_data` Docker volume. To wipe it too:
```bash
docker compose down -v
```

---

## The Calculations

### Electricity

```
CO₂e (kg) = kWh × emissions_factor (kg CO₂e / kWh)
```

We use a **marginal, time-varying emissions factor** from WattTime's `co2_moer` signal (lbs CO₂/MWh). This changes every 5 minutes to reflect what generation source is actually serving load at that moment — more accurate than a single annual average.

Unit conversion:
```
lbs CO₂/MWh ÷ 2204.62 = kg CO₂/kWh
```

PG&E exports 15-minute intervals. Each interval is matched to the most recent WattTime 5-minute reading at or before its timestamp using an asof merge.

Negative kWh intervals (solar export to the grid) are supported and produce negative CO₂e values, representing an emissions credit.

The region is hardcoded to `CAISO_NORTH` (Northern California, PG&E's territory).

### Natural Gas

```
CO₂ (kg) = therms × 5.312 kg CO₂/therm
```

Uses the EPA fixed emissions factor:
53.12 kg CO₂/MMBtu × 0.1 MMBtu/therm
= **5.312 kg CO₂/therm**.
Only the DATE column from the gas CSV is used.

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

## Streamlit UI

A Streamlit front-end is included (`streamlit_app.py`). It is served as a separate container via `docker-compose.yml`.

Upload one or more PG&E CSVs using the single file uploader — electric and gas files are detected automatically and routed to the correct pipeline. Both types can be uploaded together in one batch. Uploaded files are deduplicated within a session so re-selecting the same file is a no-op.

---

## Next steps

- include sample data
- highlight top 10% of days / hours etc.
- buy and use domain