from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime
from pydantic import BaseModel
from app.database import Base


# --- SQLAlchemy Model ---
# This defines the actual database table structure.
class EmissionRecord(Base):
    __tablename__ = "emission_records"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, nullable=False)
    grid_region = Column(String, nullable=False)
    kwh = Column(Float, nullable=False)
    emissions_factor_kg_per_kwh = Column(Float, nullable=False)
    co2e_kg = Column(Float, nullable=False)       # The calculated result
    co2e_lbs = Column(Float, nullable=False)      # Convenience conversion
    created_at = Column(DateTime, default=datetime.utcnow)


# --- Pydantic Schemas ---
# These control what data looks like going INTO and coming OUT OF the API.
# Keeping them separate from the DB model is a FastAPI best practice —
# it means you can change your DB schema without breaking your API contract.

class EmissionRecordOut(BaseModel):
    id: int
    timestamp: datetime
    grid_region: str
    kwh: float
    emissions_factor_kg_per_kwh: float
    co2e_kg: float
    co2e_lbs: float

    class Config:
        from_attributes = True  # Allows Pydantic to read SQLAlchemy model objects


class ProcessingSummary(BaseModel):
    records_processed: int
    total_kwh: float
    total_co2e_kg: float
    total_co2e_lbs: float
    avg_emissions_factor: float
