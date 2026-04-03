from __future__ import annotations

import json
from pathlib import Path


def test_base_donor_bank_is_balanced() -> None:
    manifest_path = Path("assets/driver-face-donors/manifest.json")
    payload = json.loads(manifest_path.read_text())
    donors = payload["donors"]
    base_rows = [row for row in donors if row.get("role") == "base"]

    assert len(base_rows) >= 7

    presentations = {row["presentation"] for row in base_rows}
    tone_bands = {row["tone_band"] for row in base_rows}

    assert presentations == {"masc", "fem"}
    assert tone_bands == {"light", "medium", "dark"}

    fem_rows = [row for row in base_rows if row["presentation"] == "fem"]
    masc_rows = [row for row in base_rows if row["presentation"] == "masc"]

    assert {row["age_band"] for row in fem_rows} == {"younger"}
    assert {row["age_band"] for row in masc_rows} == {"younger", "older"}

    fem_combos = {(row["tone_band"], row["presentation"]) for row in fem_rows}
    masc_combos = {
        (row["tone_band"], row["presentation"], row["age_band"])
        for row in masc_rows
    }
    assert fem_combos == {
        ("light", "fem"),
        ("medium", "fem"),
    }
    assert len(masc_combos) == 6


def test_active_bank_excludes_older_female_donors() -> None:
    manifest_path = Path("assets/driver-face-donors/manifest.json")
    payload = json.loads(manifest_path.read_text())
    donors = payload["donors"]

    assert not any(
        row.get("presentation") == "fem" and row.get("age_band") == "older" and row.get("role") == "base"
        for row in donors
    )


def test_glasses_variants_cover_masculine_tone_bands() -> None:
    manifest_path = Path("assets/driver-face-donors/manifest.json")
    payload = json.loads(manifest_path.read_text())
    donors = payload["donors"]
    glasses_rows = [row for row in donors if row.get("glasses") == "yes"]

    assert len(glasses_rows) >= 3

    combos = {
        (row.get("tone_band"), row.get("presentation"))
        for row in glasses_rows
        if row.get("tone_band") and row.get("presentation")
    }
    assert combos.issuperset(
        {
            ("light", "masc"),
            ("medium", "masc"),
            ("dark", "masc"),
        }
    )


def test_active_bank_excludes_older_or_glasses_female_variants() -> None:
    manifest_path = Path("assets/driver-face-donors/manifest.json")
    payload = json.loads(manifest_path.read_text())
    donors = payload["donors"]

    assert not any(
        row.get("presentation") == "fem"
        and (row.get("age_band") == "older" or row.get("glasses") == "yes")
        for row in donors
    )


def test_active_bank_excludes_dark_female_base_donors() -> None:
    manifest_path = Path("assets/driver-face-donors/manifest.json")
    payload = json.loads(manifest_path.read_text())
    donors = payload["donors"]

    assert not any(
        row.get("presentation") == "fem"
        and row.get("role") == "base"
        and row.get("tone_band") == "dark"
        for row in donors
    )
