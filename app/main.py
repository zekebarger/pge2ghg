from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
import os

from app.database import engine, get_db, Base
from app.models import EmissionRecord, EmissionRecordOut, ProcessingSummary
from app.calculations import load_csv, calculate_emissions, build_summary

# Create all tables on startup if they don't already exist.
# In production you'd use a migration tool like Alembic instead,
# but this is fine for learning.
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="GHG Emissions Tracker",
    description="Reads hourly electricity usage from CSV and calculates CO₂e emissions.",
    version="1.0.0",
)

CSV_PATH = os.getenv("CSV_PATH", "/data/sample_usage.csv")


@app.get("/health")
def health_check():
    """Simple liveness check — useful for Docker health checks and load balancers."""
    return {"status": "ok"}


@app.post("/process", response_model=ProcessingSummary)
def process_csv(db: Session = Depends(get_db)):
    """
    Reads the CSV at CSV_PATH, calculates hourly CO₂e emissions,
    and writes each row as a record in Postgres.

    Note the `db: Session = Depends(get_db)` pattern — this is FastAPI's
    dependency injection system. FastAPI calls get_db() for you, passes
    the session in, and closes it when the request is done.
    """
    try:
        df = load_csv(CSV_PATH)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    df = calculate_emissions(df)

    # Convert each DataFrame row into a SQLAlchemy model instance and save it
    records = [
        EmissionRecord(
            timestamp=row["timestamp"],
            grid_region=row["grid_region"],
            kwh=row["kwh"],
            emissions_factor_kg_per_kwh=row["emissions_factor_kg_per_kwh"],
            co2e_kg=row["co2e_kg"],
            co2e_lbs=row["co2e_lbs"],
        )
        for _, row in df.iterrows()
    ]

    db.add_all(records)
    db.commit()

    return build_summary(df)


@app.get("/emissions", response_model=List[EmissionRecordOut])
def get_emissions(
    region: str | None = Query(default=None, description="Filter by grid region"),
    limit: int = Query(default=100, le=1000),
    db: Session = Depends(get_db),
):
    """
    Retrieve stored emission records, optionally filtered by grid region.
    The `limit` parameter prevents accidentally returning thousands of rows.
    """
    query = db.query(EmissionRecord)
    if region:
        query = query.filter(EmissionRecord.grid_region == region)
    return query.order_by(EmissionRecord.timestamp).limit(limit).all()


@app.get("/emissions/summary")
def get_summary(db: Session = Depends(get_db)):
    """Return aggregate stats across all stored records."""
    records = db.query(EmissionRecord).all()
    if not records:
        raise HTTPException(status_code=404, detail="No records found. Run POST /process first.")

    total_kwh = sum(r.kwh for r in records)
    total_co2e_kg = sum(r.co2e_kg for r in records)

    return {
        "total_records": len(records),
        "total_kwh": round(total_kwh, 4),
        "total_co2e_kg": round(total_co2e_kg, 4),
        "total_co2e_lbs": round(total_co2e_kg * 2.20462, 4),
        "avg_emissions_factor": round(
            sum(r.emissions_factor_kg_per_kwh for r in records) / len(records), 6
        ),
    }
