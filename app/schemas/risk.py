from pydantic import BaseModel


# Input for Risk Framework to return ID for database
class LocationRiskInput(BaseModel):
    country_code: str
    wkt_polygon: str
    sri_logic_type: str = "fuzzy"
    sri_correction_method: str = "HFI"
    risk_model: str = "EddamiriEtAl2026"
    risk_type: str = "Full"
