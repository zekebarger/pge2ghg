from datetime import datetime, timezone
from typing import List
from sqlalchemy import Column, Integer, Float, DateTime
from pydantic import BaseModel
from app.database import Base


# --- SQLAlchemy Model ---
# Caches raw WattTime marginal intensity data so we don't re-fetch the same
# date ranges from the API on subsequent uploads.
class WattTimeRecord(Base):
    __tablename__ = "watttime_records"

    id = Column(Integer, primary_key=True, index=True)
    point_time = Column(DateTime(timezone=True), nullable=False, unique=True)
    value_lbs_per_mwh = Column(Float, nullable=False)
    fetched_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# --- Pydantic Schemas ---
class WattTimeRecordOut(BaseModel):
    id: int
    point_time: datetime
    value_lbs_per_mwh: float
    fetched_at: datetime

    class Config:
        from_attributes = True


class EmissionsRecord(BaseModel):
    timestamp: datetime
    kwh: float
    emissions_factor_kg_per_kwh: float
    co2e_kg: float
    co2e_lbs: float


class ProcessingResult(BaseModel):
    records_processed: int
    total_kwh: float
    total_co2e_kg: float
    total_co2e_lbs: float
    avg_emissions_factor: float
    records: List[EmissionsRecord]
