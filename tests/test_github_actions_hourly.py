from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
MODELS_SRC_DIR = SRC_DIR / "models"
for source_dir in (SRC_DIR, MODELS_SRC_DIR):
    if str(source_dir) not in sys.path:
        sys.path.insert(0, str(source_dir))

from live.github_actions_hourly import has_current_hour_observations  # noqa: E402


class GitHubActionsHourlyTests(unittest.TestCase):
    def test_current_hour_observation_gate_requires_enough_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "hourly_observations.csv"
            frame = pd.DataFrame(
                [
                    {
                        "timestamp": "2026-07-03 10:00:00",
                        "location_key": "location_a",
                    },
                    {
                        "timestamp": "2026-07-03 10:00:00",
                        "location_key": "location_b",
                    },
                    {
                        "timestamp": "2026-07-03 09:00:00",
                        "location_key": "location_c",
                    },
                ]
            )
            frame.to_csv(output, index=False, encoding="utf-8-sig")

            current = pd.Timestamp("2026-07-03 10:00:00")

            self.assertTrue(has_current_hour_observations(output, current, 2))
            self.assertFalse(has_current_hour_observations(output, current, 3))


if __name__ == "__main__":
    unittest.main()
