from __future__ import annotations

import math
import unittest

import pandas as pd

from ml.features.network import compute_blockage_fraction, compute_bpr_delay
from ml.features.spatial import snap_points_to_osm
from ml.pipeline.etl import Validator, clean_raw_df


class Phase1CoreTests(unittest.TestCase):
    def test_clean_raw_df_normalises_and_deduplicates(self) -> None:
        raw = pd.DataFrame(
            [
                {
                    "id": "A",
                    "latitude": "12.9716",
                    "longitude": "77.5946",
                    "vehicle_type": " scooter ",
                    "violation_type": '["no parking"]',
                    "police_station": " cubbon park ",
                    "junction_name": "null",
                    "created_datetime": "2024-01-01 10:00:00+00",
                    "action_taken_timestamp": "2024-01-01 09:00:00+00",
                },
                {
                    "id": "A",
                    "latitude": "12.9716",
                    "longitude": "77.5946",
                    "vehicle_type": "car",
                    "violation_type": '["wrong parking"]',
                    "police_station": "cubbon park",
                    "junction_name": "No Junction",
                    "created_datetime": "2024-01-01 10:00:00+00",
                    "action_taken_timestamp": "2024-01-01 11:00:00+00",
                },
            ]
        )
        cleaned = clean_raw_df(raw)
        self.assertEqual(len(cleaned), 1)
        row = cleaned.iloc[0]
        self.assertEqual(row["vehicle_type"], "SCOOTER")
        self.assertEqual(row["police_station"], "CUBBON PARK")
        self.assertIsNone(row["junction_name"])
        self.assertEqual(row["violation_types"], ["NO PARKING"])
        self.assertTrue(pd.isna(row["action_taken_timestamp"]))
        self.assertEqual(cleaned.attrs["cleaning_report"].duplicate_id_rows, 1)

    def test_validator_coordinate_accept_reject(self) -> None:
        validator = Validator()
        self.assertTrue(validator.validate_coordinates(12.9716, 77.5946))
        self.assertFalse(validator.validate_coordinates(0.0, 0.0))
        self.assertFalse(validator.validate_coordinates(13.5, 77.5946))
        self.assertFalse(validator.validate_coordinates(None, 77.5946))

    def test_bpr_delay_and_blockage_invariants(self) -> None:
        blockage = compute_blockage_fraction(1.0, 2)
        self.assertGreater(blockage, 0)
        self.assertLessEqual(blockage, 1)
        delay = compute_bpr_delay(30.0, 120.0, blockage)
        self.assertGreaterEqual(delay, 0)
        self.assertTrue(math.isfinite(delay))

    def test_osm_batch_snap_falls_back_without_graph(self) -> None:
        results = snap_points_to_osm([12.9716, 12.972], [77.5946, 77.595], graph=None)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.osm_snap_fallback for result in results))
        self.assertTrue(all(result.lane_count >= 1 for result in results))


if __name__ == "__main__":
    unittest.main()
