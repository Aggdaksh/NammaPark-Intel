"""ETL cleaner, validator, enrichment, and optional DB write entrypoint."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from ml.config.settings import load_config
from ml.features.network import compute_blockage_fraction, compute_bpr_delay, severity_factor_for
from ml.features.spatial import OSMSnapResult, snap_to_osm


NULL_TOKENS = {"", "NULL", "NONE", "NAN"}
TEXT_COLUMNS = ["vehicle_type", "violation_type", "police_station", "junction_name"]


@dataclass
class CleaningReport:
    input_rows: int
    duplicate_id_rows: int = 0
    duplicate_spatial_temporal_rows: int = 0
    latitude_coercion_nulls: int = 0
    longitude_coercion_nulls: int = 0
    malformed_violation_type_rows: int = 0
    invalid_action_timestamp_rows: int = 0


@dataclass
class ValidationResult:
    is_valid: bool
    rejection_reason: str | None = None
    vehicle_type: str | None = None


@dataclass
class ETLReport:
    total_read: int
    duplicates_dropped: int
    accepted: int
    rejected: int
    rejection_reasons: dict[str, int]
    data_hash: str
    output_path: str | None = None
    null_coordinate_count: int = 0
    sample_records: list[dict[str, Any]] = field(default_factory=list)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalise_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    text = " ".join(str(value).strip().upper().split())
    return None if text in NULL_TOKENS else text


def safe_parse_violation_types(value: Any) -> tuple[list[str], bool]:
    if value is None:
        return [], False
    raw = str(value).strip()
    if raw.upper() in NULL_TOKENS:
        return [], False
    try:
        parsed = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        label = normalise_text(raw)
        return ([label] if label else []), True
    if isinstance(parsed, str):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return [], True
    labels = [label for label in (normalise_text(item) for item in parsed) if label]
    return labels, False


def clean_raw_df(df: pd.DataFrame) -> pd.DataFrame:
    """Clean raw violation rows before validation.

    The function returns a new DataFrame and attaches a `CleaningReport` to
    `cleaned.attrs["cleaning_report"]` so callers can include it in ETL output
    without changing the task-specified return type.
    """

    cleaned = df.copy()
    report = CleaningReport(input_rows=int(len(cleaned)))

    for column in TEXT_COLUMNS:
        if column in cleaned.columns:
            cleaned[column] = cleaned[column].map(normalise_text)

    if "id" in cleaned.columns:
        before = len(cleaned)
        cleaned = cleaned.drop_duplicates(subset=["id"], keep="first").copy()
        report.duplicate_id_rows = before - len(cleaned)

    for column in ["latitude", "longitude"]:
        if column in cleaned.columns:
            before_nulls = int(cleaned[column].isna().sum())
            cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")
            after_nulls = int(cleaned[column].isna().sum())
            if column == "latitude":
                report.latitude_coercion_nulls = max(after_nulls - before_nulls, 0)
            else:
                report.longitude_coercion_nulls = max(after_nulls - before_nulls, 0)

    if "violation_type" in cleaned.columns:
        parsed = cleaned["violation_type"].map(safe_parse_violation_types)
        cleaned["violation_types"] = parsed.map(lambda item: item[0])
        cleaned["dominant_violation_type"] = cleaned["violation_types"].map(lambda values: values[0] if values else "UNKNOWN")
        report.malformed_violation_type_rows = int(parsed.map(lambda item: item[1]).sum())

    for column in ["created_datetime", "action_taken_timestamp", "closed_datetime"]:
        if column in cleaned.columns:
            cleaned[column] = pd.to_datetime(cleaned[column], utc=True, errors="coerce")

    if {"action_taken_timestamp", "created_datetime"}.issubset(cleaned.columns):
        impossible = cleaned["action_taken_timestamp"].notna() & (
            cleaned["action_taken_timestamp"] < cleaned["created_datetime"]
        )
        report.invalid_action_timestamp_rows = int(impossible.sum())
        cleaned.loc[impossible, "action_taken_timestamp"] = pd.NaT

    if {"latitude", "longitude", "created_datetime"}.issubset(cleaned.columns):
        before = len(cleaned)
        cleaned = cleaned.drop_duplicates(subset=["latitude", "longitude", "created_datetime"], keep="first").copy()
        report.duplicate_spatial_temporal_rows = before - len(cleaned)

    cleaned.attrs["cleaning_report"] = report
    return cleaned


class Validator:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or load_config()
        data_cfg = self.config["data"]
        self.bbox = data_cfg["bengaluru_bbox"]
        self.valid_vehicle_types = set(data_cfg["valid_vehicle_types"])
        self.start_ts = pd.Timestamp(data_cfg["valid_created_datetime"]["start"])
        self.end_ts = pd.Timestamp(data_cfg["valid_created_datetime"]["end"])
        self.null_coordinate_count = 0
        self.rejection_log: list[dict[str, Any]] = []

    def validate_coordinates(self, lat: Any, lon: Any) -> bool:
        if lat is None or lon is None:
            self.null_coordinate_count += 1
            return False
        try:
            if pd.isna(lat) or pd.isna(lon):
                self.null_coordinate_count += 1
                return False
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            self.null_coordinate_count += 1
            return False
        if lat_f == 0.0 and lon_f == 0.0:
            return False
        return (
            self.bbox["min_lat"] <= lat_f <= self.bbox["max_lat"]
            and self.bbox["min_lon"] <= lon_f <= self.bbox["max_lon"]
        )

    def normalise_vehicle_type(self, vehicle_type: Any) -> str:
        text = normalise_text(vehicle_type) or "UNKNOWN"
        return text if text in self.valid_vehicle_types else "UNKNOWN"

    def validate_record(self, row: dict[str, Any] | pd.Series) -> ValidationResult:
        record = row.to_dict() if isinstance(row, pd.Series) else row
        record_id = record.get("id")
        if not self.validate_coordinates(record.get("latitude"), record.get("longitude")):
            reason = "invalid_coordinate"
            self.rejection_log.append({"id": record_id, "reason": reason})
            return ValidationResult(False, reason)

        created = record.get("created_datetime")
        if created is None or pd.isna(created) or not (self.start_ts <= created <= self.end_ts):
            reason = "invalid_created_datetime"
            self.rejection_log.append({"id": record_id, "reason": reason})
            return ValidationResult(False, reason)

        return ValidationResult(True, None, self.normalise_vehicle_type(record.get("vehicle_type")))


def enrich_with_road_features(df: pd.DataFrame, graph: Any = None, config: dict[str, Any] | None = None) -> pd.DataFrame:
    cfg = config or load_config()
    enriched = df.copy()
    snap_results: list[OSMSnapResult] = [
        snap_to_osm(float(row.latitude), float(row.longitude), graph, cfg) for row in enriched.itertuples()
    ]
    for field_name in OSMSnapResult.__dataclass_fields__:
        enriched[field_name] = [getattr(result, field_name) for result in snap_results]

    enriched["severity_factor"] = enriched["violation_types"].map(lambda labels: severity_factor_for(labels, cfg))
    enriched["blockage_fraction"] = [
        compute_blockage_fraction(severity, lanes)
        for severity, lanes in zip(enriched["severity_factor"], enriched["lane_count"])
    ]
    enriched["bpr_delay_min"] = [
        compute_bpr_delay(speed, length, blockage)
        for speed, length, blockage in zip(
            enriched["speed_limit_kph"],
            enriched["segment_length_m"],
            enriched["blockage_fraction"],
        )
    ]
    return enriched


def _serialise_for_sqlite(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, list):
        return json.dumps(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def write_sqlite(df: pd.DataFrame, db_path: Path, table_name: str = "violations_enriched") -> None:
    serialised = df.map(_serialise_for_sqlite)
    with sqlite3.connect(db_path) as conn:
        serialised.to_sql(table_name, conn, if_exists="replace", index=False)


def run_etl(csv_path: str | Path, db_url: str | None = None, graph: Any = None) -> ETLReport:
    path = Path(csv_path)
    raw = pd.read_csv(path, low_memory=False)
    cleaned = clean_raw_df(raw)
    cleaning_report: CleaningReport = cleaned.attrs["cleaning_report"]
    validator = Validator()

    validation_results = cleaned.apply(validator.validate_record, axis=1)
    valid_mask = validation_results.map(lambda result: result.is_valid)
    accepted = cleaned.loc[valid_mask].copy()
    accepted["vehicle_type"] = [result.vehicle_type for result in validation_results.loc[valid_mask]]
    enriched = enrich_with_road_features(accepted, graph)

    rejection_counts = Counter(result.rejection_reason for result in validation_results if not result.is_valid)
    rejection_reasons = {str(key): int(value) for key, value in rejection_counts.items() if key}
    duplicates = cleaning_report.duplicate_id_rows + cleaning_report.duplicate_spatial_temporal_rows

    output_path = None
    if db_url:
        if db_url.startswith("sqlite:///"):
            output_path = db_url.replace("sqlite:///", "", 1)
            write_sqlite(enriched, Path(output_path))
        else:
            try:
                from sqlalchemy import create_engine  # type: ignore[import-not-found]
            except ModuleNotFoundError as exc:
                raise RuntimeError("SQLAlchemy is required for non-sqlite ETL writes; run `uv sync` first") from exc
            engine = create_engine(db_url)
            enriched.to_sql("violations_enriched", engine, if_exists="replace", index=False, method="multi")
            output_path = db_url

    sample_columns = ["id", "latitude", "longitude", "vehicle_type", "bpr_delay_min", "blockage_fraction"]
    sample = enriched[[col for col in sample_columns if col in enriched.columns]].head(5).to_dict(orient="records")
    return ETLReport(
        total_read=int(cleaning_report.input_rows),
        duplicates_dropped=int(duplicates),
        accepted=int(len(enriched)),
        rejected=int((~valid_mask).sum()),
        rejection_reasons=rejection_reasons,
        data_hash=f"sha256:{sha256_file(path)}",
        output_path=output_path,
        null_coordinate_count=int(validator.null_coordinate_count),
        sample_records=sample,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--db-url", default=None)
    args = parser.parse_args()
    report = run_etl(args.csv, args.db_url)
    print(json.dumps(asdict(report), indent=2, default=str))


if __name__ == "__main__":
    main()
