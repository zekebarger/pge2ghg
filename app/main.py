import logging

from fastapi import FastAPI, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session
from typing import List
import pandas as pd

from app.database import engine, get_db, Base
from app.models import WattTimeRecord, WattTimeRecordOut, ProcessingResult, GasProcessingResult
from app.calculations import (
    parse_pge_csv,
    join_usage_with_intensity,
    calculate_emissions,
    build_result,
    parse_pge_gas_csv,
    calculate_gas_emissions,
    build_gas_result,
)
from app import watttime

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Create all tables on startup if they don't already exist.
# In production you'd use a migration tool like Alembic instead,
# but this is fine for learning.
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="GHG Emissions Tracker",
    description="Upload a PG&E CSV and calculate CO₂e emissions using live WattTime marginal intensity data.",
    version="2.0.0",
)


@app.get("/health")
def health_check():
    """Simple liveness check — useful for Docker health checks and load balancers."""
    return {"status": "ok"}


@app.post("/process", response_model=ProcessingResult)
async def process_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload a PG&E Green Button CSV to calculate CO₂e emissions.

    Flow:
    1. Parse the uploaded PG&E CSV into 15-min (timestamp, kWh) intervals.
    2. Determine the date range and fetch WattTime marginal intensity for it
       (only hits the API for ranges not already cached in the DB).
    3. Join usage with intensity data and compute emissions on the fly.
    4. Return aggregate summary — nothing is stored except the WattTime cache.
    """
    file_bytes = await file.read()
    logger.info("Received file: %s (%d bytes)", file.filename, len(file_bytes))

    try:
        df_usage = parse_pge_csv(file_bytes)
    except ValueError as e:
        logger.error("Failed to parse PG&E CSV: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

    logger.info(
        "Parsed %d usage rows; date range %s to %s",
        len(df_usage),
        df_usage["timestamp"].min(),
        df_usage["timestamp"].max(),
    )

    # Determine the date range covered by the uploaded data
    start_dt = df_usage["timestamp"].min().to_pydatetime()
    end_dt = df_usage["timestamp"].max().to_pydatetime()

    # Fetch and cache WattTime intensity for this range (no-ops for cached intervals)
    logger.info("Fetching WattTime intensity for %s to %s", start_dt, end_dt)
    try:
        watttime.fetch_and_store_intensity(db, start_dt, end_dt)
    except Exception as e:
        logger.error("WattTime API error: %s", e)
        raise HTTPException(status_code=502, detail=f"WattTime API error: {e}")

    # Load matching intensity records from the DB
    intensity_rows = (
        db.query(WattTimeRecord)
        .filter(
            WattTimeRecord.point_time >= start_dt,
            WattTimeRecord.point_time <= end_dt,
        )
        .order_by(WattTimeRecord.point_time)
        .all()
    )
    if not intensity_rows:
        logger.error("No intensity data in DB for range %s to %s", start_dt, end_dt)
        raise HTTPException(
            status_code=502,
            detail="No intensity data available for the uploaded date range.",
        )

    logger.info("Loaded %d intensity records from DB", len(intensity_rows))

    df_intensity = pd.DataFrame(
        [{"timestamp": r.point_time, "value_lbs_per_mwh": r.value_lbs_per_mwh} for r in intensity_rows]
    )

    try:
        df_joined = join_usage_with_intensity(df_usage, df_intensity)
    except ValueError as e:
        logger.error("Failed to join usage with intensity: %s", e)
        raise HTTPException(status_code=422, detail=str(e))

    logger.info("Joined DataFrame has %d rows", len(df_joined))

    df_result = calculate_emissions(df_joined)
    result = build_result(df_result)

    logger.info(
        "Processing complete: %d records, %.4f kWh, %.4f kg CO2e, %.4f lbs CO2e",
        result["records_processed"],
        result["total_kwh"],
        result["total_co2e_kg"],
        result["total_co2e_lbs"],
    )

    return result


@app.post("/process_gas", response_model=GasProcessingResult)
async def process_gas_csv(file: UploadFile = File(...)):
    """Upload a PG&E natural gas CSV to calculate CO₂ emissions using the EPA fixed factor."""
    file_bytes = await file.read()
    logger.info("Received gas file: %s (%d bytes)", file.filename, len(file_bytes))
    try:
        df_usage = parse_pge_gas_csv(file_bytes)
    except ValueError as e:
        logger.error("Failed to parse PG&E gas CSV: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    logger.info("Parsed %d gas usage rows; %s to %s",
                len(df_usage), df_usage["date"].min(), df_usage["date"].max())
    df_result = calculate_gas_emissions(df_usage)
    result = build_gas_result(df_result)
    logger.info("Gas processing complete: %d records, %.4f therms, %.4f kg CO2",
                result["records_processed"], result["total_therms"], result["total_co2_kg"])
    return result


@app.get("/intensity", response_model=List[WattTimeRecordOut])
def get_intensity(
    limit: int = Query(default=100, le=1000),
    db: Session = Depends(get_db),
):
    """
    Retrieve cached WattTime marginal intensity records.
    These are populated automatically when you POST /process.
    """
    return db.query(WattTimeRecord).order_by(WattTimeRecord.point_time).limit(limit).all()


@app.get("/intensity/summary")
def get_intensity_summary(db: Session = Depends(get_db)):
    """Return coverage stats for cached WattTime intensity data."""
    from sqlalchemy import func

    row = db.query(
        func.count(WattTimeRecord.id),
        func.min(WattTimeRecord.point_time),
        func.max(WattTimeRecord.point_time),
    ).one()

    count, earliest, latest = row
    if not count:
        raise HTTPException(
            status_code=404,
            detail="No intensity records found. Upload a PG&E CSV via POST /process first.",
        )

    return {
        "total_records": count,
        "earliest_point_time": earliest,
        "latest_point_time": latest,
    }
