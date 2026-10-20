"""Versioned scenario contract. Hydrology, hydraulics and rendering stay separate."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Outlet(StrictModel):
    station_id: str | None
    lat: float = Field(ge=23, le=38)
    lon: float = Field(ge=60, le=80)
    crs: Literal["EPSG:4326"]


class Domain(StrictModel):
    radius_km: float = Field(ge=1, le=50)
    mesh_m: float = Field(ge=10, le=1000)
    model_crs: Literal["EPSG:32642", "EPSG:32643"]
    dem_source: Literal["FABDEM"]
    dem_sha256: str | None = Field(pattern=r"^[a-f0-9]{64}$")


class Time(StrictModel):
    start: datetime
    end: datetime
    output_interval_minutes: int = Field(ge=1, le=1440)

    @model_validator(mode="after")
    def ordered(self):
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Model times require an explicit timezone (UTC recommended).")
        days = (self.end - self.start).total_seconds() / 86400
        if not 0 < days <= 93:
            raise ValueError("The model time window must be increasing and at most 93 days.")
        return self


class Forcing(StrictModel):
    mode: Literal["inflow_hydrograph", "rain_on_grid"]
    rainfall_product: Literal["GPM IMERG", "CHIRPS", "PMD gauges", "design storm"]
    rainfall_multiplier: float = Field(gt=0, le=5)
    design_storm_mm: float | None = Field(default=None, gt=0, le=3000)
    return_period_years: int | None = Field(default=None, ge=1, le=10000)
    bias_correction: str
    soil_moisture: Literal["dry", "normal", "saturated", "SMAP"]
    infiltration: Literal["Green-Ampt", "SCS-CN"]
    inflow_asset: str | None
    upstream_station_ids: list[str]
    ffd_class: Literal["low", "medium", "high", "veryHigh", "exceptional"] | None


class Structure(StrictModel):
    type: Literal["barrage", "levee", "reservoir", "breach"]
    name: str
    specification: str


class Hydraulics(StrictModel):
    engine: Literal["HEC-RAS 2D", "LISFLOOD-FP"]
    equations: Literal["full SWE", "local inertial"]
    manning_source: Literal["ESA WorldCover", "Dynamic World"]
    structures: list[Structure]

    @model_validator(mode="after")
    def engine_equations(self):
        expected = "full SWE" if self.engine == "HEC-RAS 2D" else "local inertial"
        if self.equations != expected:
            raise ValueError(f"{self.engine} requires {expected} in this workflow.")
        return self


class Validation(StrictModel):
    gauge_ids: list[str]
    extent_source: Literal["Sentinel-1", "UNOSAT"]
    target_nse: float = Field(ge=-10, le=1)
    target_kge: float = Field(ge=-10, le=1)
    target_csi: float = Field(ge=0, le=1)


class Provenance(StrictModel):
    created_at: datetime
    purpose: str
    notes: str
    sources: list[str]


class Scenario(StrictModel):
    schema_version: Literal[1]
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=160)
    kind: Literal["historical", "ffd_class", "design_storm", "soil_state", "reservoir_release", "breach", "land_cover", "climate"]
    outlet: Outlet
    domain: Domain
    time: Time
    forcing: Forcing
    hydraulics: Hydraulics
    validation: Validation
    provenance: Provenance

    @model_validator(mode="after")
    def preset_requirements(self):
        if self.kind == "design_storm" and self.forcing.design_storm_mm is None:
            raise ValueError("Design storms require a rainfall depth; IDF provenance is checked at preflight.")
        if self.kind == "ffd_class" and self.forcing.ffd_class is None:
            raise ValueError("Select an FFD flood class.")
        return self
