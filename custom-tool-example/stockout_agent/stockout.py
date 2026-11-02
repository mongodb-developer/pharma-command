"""Business logic, runnable without Agent Engine, an LLM, or Streamlit."""
import argparse
import json
import math
import os
import re
from datetime import datetime, timezone

# Deliberately disrupted fixture: 45 units / 60 units per day = 18 hours.
SAMPLE_INVENTORY = {
    ("CHI", "DRG-01"): {
        "facility_id": "CHI", "drug_id": "DRG-01", "drug": "Cefazolin 1 g vial",
        "on_hand": 45, "reserved": 0, "quarantined": 0, "daily_demand": 60,
    },
    ("OAK", "DRG-01"): {
        "facility_id": "OAK", "drug_id": "DRG-01", "drug": "Cefazolin 1 g vial",
        "on_hand": 336, "reserved": 0, "quarantined": 0, "daily_demand": 48,
    },
}


def calculate_risk(record, threshold_days):
    """Use deterministic arithmetic; the LLM does not calculate inventory."""
    values = {}
    for key in ("on_hand", "reserved", "quarantined", "daily_demand"):
        value = record.get(key, 0 if key in ("reserved", "quarantined") else None)
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise ValueError(f"Invalid inventory field: {key}")
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid inventory field: {key}")
        values[key] = value
    if values["daily_demand"] <= 0:
        raise ValueError("daily_demand must be positive")
    if values["reserved"] + values["quarantined"] > values["on_hand"]:
        raise ValueError("Reserved plus quarantined stock exceeds on-hand stock")
    usable = values["on_hand"] - values["reserved"] - values["quarantined"]
    days = usable / values["daily_demand"]
    return {
        "available_units": usable,
        "daily_demand_units": values["daily_demand"],
        "days_supply": round(days, 3),
        "hours_supply": round(days * 24, 1),
        "threshold_days": threshold_days,
        "risk_level": "at_risk" if days < threshold_days else "covered",
    }


def check_stockout(facility_id, drug_id, threshold_days=2.0):
    """Return only JSON-native data; choose sample/Atlas explicitly at runtime."""
    if (isinstance(threshold_days, bool) or not isinstance(threshold_days, (int, float))
            or not math.isfinite(threshold_days) or not 0 < threshold_days <= 365):
        return {"status": "error", "code": "INVALID_THRESHOLD", "message": "threshold_days must be >0 and <=365."}
    if not all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9-]{1,64}", value.strip())
               for value in (facility_id, drug_id)):
        return {"status": "error", "code": "INVALID_ID", "message": "Supply facility and drug identifiers such as CHI and DRG-01."}
    facility_id, drug_id = facility_id.strip().upper(), drug_id.strip().upper()
    source = os.environ.get("PHARMA_DATA_SOURCE", "sample").strip().lower()
    if source == "sample":
        record = SAMPLE_INVENTORY.get((facility_id, drug_id))
    elif source == "atlas":
        uri = os.environ.get("PHARMA_ATLAS_URI", "").strip()
        if not uri:
            return {"status": "error", "code": "MISSING_ATLAS_URI", "message": "Configure PHARMA_ATLAS_URI in the tool runtime."}
        try:
            from pymongo import MongoClient
            with MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
                             timeoutMS=8000, appname="PharmaCustomToolExample") as client:
                record = client[os.environ.get("PHARMA_DATABASE", "pharma_stockout_demo")].inventory.find_one(
                    {"facility_id": facility_id, "drug_id": drug_id},
                    {"_id": 0, "facility_id": 1, "drug_id": 1, "drug": 1,
                     "on_hand": 1, "reserved": 1, "quarantined": 1, "daily_demand": 1})
        except ImportError:
            return {"status": "error", "code": "MISSING_DRIVER", "message": "Install the pymongo dependency."}
        except Exception:
            return {"status": "error", "code": "ATLAS_LOOKUP_FAILED", "message": "Inventory lookup failed. Check connection, permissions, and network access."}
    else:
        return {"status": "error", "code": "INVALID_SOURCE", "message": "PHARMA_DATA_SOURCE must be sample or atlas."}
    if record is None:
        return {"status": "not_found", "source": source, "facility_id": facility_id,
                "drug_id": drug_id, "message": "Inventory record not found; stockout risk is unknown."}
    try:
        risk = calculate_risk(record, threshold_days)
    except ValueError as exc:
        return {"status": "error", "code": "INVALID_INVENTORY", "message": str(exc)}
    return {"status": "ok", "source": source, "facility_id": facility_id, "drug_id": drug_id,
            "drug": record.get("drug", drug_id), **risk,
            "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": "Synthetic fixed fixture" if source == "sample" else "Operational inventory snapshot; recheck before acting"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facility", default="CHI")
    parser.add_argument("--drug", default="DRG-01")
    parser.add_argument("--threshold-days", type=float, default=2.0)
    args = parser.parse_args()
    result = check_stockout(args.facility, args.drug, args.threshold_days)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "ok" else 1)
