from __future__ import annotations

from core import driver_face_auto_select


def test_select_representative_frame_indices_prefers_high_face_prob_without_holds() -> None:
    track = {
        "frames": [
            {"face_prob": 0.91, "held_without_detection": 0, "padded_box": {"x": 0}},
            {"face_prob": 0.97, "held_without_detection": 1, "padded_box": {"x": 0}},
            {"face_prob": 0.95, "held_without_detection": 0, "padded_box": {"x": 0}},
            {"face_prob": 0.93, "held_without_detection": 0, "padded_box": None},
            {"face_prob": 0.92, "held_without_detection": 0, "padded_box": {"x": 0}},
            {"face_prob": 0.89, "held_without_detection": 0, "padded_box": {"x": 0}},
        ]
    }

    assert driver_face_auto_select.select_representative_frame_indices(track, count=3) == [0, 2, 4]


def test_presentation_compatibility_is_strict_for_known_source() -> None:
    assert driver_face_auto_select._presentation_is_compatible("masc", "masc")
    assert not driver_face_auto_select._presentation_is_compatible("masc", "fem")
    assert not driver_face_auto_select._presentation_is_compatible("fem", "uncertain")


def test_presentation_compatibility_prefers_uncertain_only_for_uncertain_source() -> None:
    assert driver_face_auto_select._presentation_is_compatible("uncertain", "uncertain")
    assert not driver_face_auto_select._presentation_is_compatible("uncertain", "masc")


def test_tone_distance_downweights_lightness_only_differences() -> None:
    lightness_only = driver_face_auto_select._tone_distance_lab([60.0, 140.0, 140.0], [120.0, 140.0, 140.0])
    chroma_shift = driver_face_auto_select._tone_distance_lab([90.0, 140.0, 140.0], [90.0, 160.0, 160.0])

    assert lightness_only < chroma_shift


def test_prefilter_prefers_clean_shaven_extreme_when_source_has_beard() -> None:
    donors = [
        {
            "donor_id": "same-beard-a",
            "presentation": "masc",
            "facial_hair": "full_beard",
            "glasses": "no",
            "tone_lab": [130.0, 130.0, 130.0],
        },
        {
            "donor_id": "same-beard-b",
            "presentation": "masc",
            "facial_hair": "full_beard",
            "glasses": "no",
            "tone_lab": [131.0, 130.0, 130.0],
        },
        {
            "donor_id": "clean-shaven",
            "presentation": "masc",
            "facial_hair": "none",
            "glasses": "no",
            "tone_lab": [132.0, 130.0, 130.0],
        },
    ]

    selected, summary = driver_face_auto_select._select_prefiltered_candidates(
        donors,
        source_lab=[130.5, 130.0, 130.0],
        source_presentation="masc",
        source_facial_hair="full_beard",
        source_glasses="no",
        top_k=2,
        tone_margin_lab=12.0,
    )

    assert summary["compatible_count"] == 3
    assert summary["hair_strategy"] == "prefer_clean_shaven_extreme"
    assert {row["donor_id"] for row in selected} == {"clean-shaven"}


def test_prefilter_prefers_most_facial_hair_extreme_when_source_is_clean_shaven() -> None:
    donors = [
        {
            "donor_id": "stubble",
            "presentation": "masc",
            "facial_hair": "stubble",
            "glasses": "no",
            "tone_lab": [130.0, 130.0, 130.0],
        },
        {
            "donor_id": "short-beard",
            "presentation": "masc",
            "facial_hair": "short_beard",
            "glasses": "no",
            "tone_lab": [130.5, 130.0, 130.0],
        },
        {
            "donor_id": "full-beard",
            "presentation": "masc",
            "facial_hair": "full_beard",
            "glasses": "no",
            "tone_lab": [131.0, 130.0, 130.0],
        },
    ]

    selected, summary = driver_face_auto_select._select_prefiltered_candidates(
        donors,
        source_lab=[130.2, 130.0, 130.0],
        source_presentation="masc",
        source_facial_hair="none",
        source_glasses="no",
        top_k=3,
        tone_margin_lab=12.0,
    )

    assert summary["hair_strategy"] == "prefer_most_facial_hair_extreme"
    assert {row["donor_id"] for row in selected} == {"full-beard"}


def test_prefilter_preserves_glasses_state_when_known() -> None:
    donors = [
        {
            "donor_id": "no-glasses",
            "presentation": "masc",
            "facial_hair": "none",
            "glasses": "no",
            "tone_lab": [130.0, 130.0, 130.0],
        },
        {
            "donor_id": "glasses",
            "presentation": "masc",
            "facial_hair": "none",
            "glasses": "yes",
            "tone_lab": [129.8, 130.0, 130.0],
        },
    ]

    selected, summary = driver_face_auto_select._select_prefiltered_candidates(
        donors,
        source_lab=[130.1, 130.0, 130.0],
        source_presentation="masc",
        source_facial_hair="none",
        source_glasses="no",
        top_k=2,
        tone_margin_lab=12.0,
    )

    assert {row["donor_id"] for row in selected} == {"no-glasses"}
    assert any(row["reason"] == "glasses_mismatch" for row in summary["excluded"])


def test_prefilter_prefers_no_glasses_when_source_glasses_are_uncertain() -> None:
    donors = [
        {
            "donor_id": "no-glasses",
            "presentation": "fem",
            "facial_hair": "none",
            "glasses": "no",
            "tone_lab": [130.0, 130.0, 130.0],
        },
        {
            "donor_id": "glasses",
            "presentation": "fem",
            "facial_hair": "none",
            "glasses": "yes",
            "tone_lab": [129.8, 130.0, 130.0],
        },
    ]

    selected, summary = driver_face_auto_select._select_prefiltered_candidates(
        donors,
        source_lab=[130.1, 130.0, 130.0],
        source_presentation="fem",
        source_facial_hair="none",
        source_glasses="uncertain",
        top_k=2,
        tone_margin_lab=12.0,
    )

    assert summary["glasses_strategy"] == "prefer_no_glasses"
    assert {row["donor_id"] for row in selected} == {"no-glasses"}
    assert any(row["reason"] == "prefer_no_glasses" for row in summary["excluded"])


def test_score_candidate_prefers_clean_shaven_same_tone_for_bearded_source_when_metrics_close() -> None:
    beard_score, _ = driver_face_auto_select._score_candidate(
        source_presentation="masc",
        source_facial_hair="full_beard",
        source_glasses="no",
        donor_presentation="masc",
        donor_facial_hair="full_beard",
        donor_glasses="no",
        donor_tone_distance_lab=8.0,
        swap_tone_distance_lab=7.5,
        original_vs_swapped_cosine=0.10,
        donor_vs_swapped_cosine=0.70,
        swap_detector_score=0.85,
    )
    clean_score, _ = driver_face_auto_select._score_candidate(
        source_presentation="masc",
        source_facial_hair="full_beard",
        source_glasses="no",
        donor_presentation="masc",
        donor_facial_hair="none",
        donor_glasses="no",
        donor_tone_distance_lab=8.0,
        swap_tone_distance_lab=7.5,
        original_vs_swapped_cosine=0.10,
        donor_vs_swapped_cosine=0.70,
        swap_detector_score=0.85,
    )

    assert clean_score > beard_score


def test_score_candidate_can_still_keep_beard_when_other_metrics_are_much_better() -> None:
    beard_score, _ = driver_face_auto_select._score_candidate(
        source_presentation="masc",
        source_facial_hair="full_beard",
        source_glasses="no",
        donor_presentation="masc",
        donor_facial_hair="full_beard",
        donor_glasses="no",
        donor_tone_distance_lab=6.0,
        swap_tone_distance_lab=5.0,
        original_vs_swapped_cosine=0.02,
        donor_vs_swapped_cosine=0.82,
        swap_detector_score=0.93,
    )
    clean_score, _ = driver_face_auto_select._score_candidate(
        source_presentation="masc",
        source_facial_hair="full_beard",
        source_glasses="no",
        donor_presentation="masc",
        donor_facial_hair="none",
        donor_glasses="no",
        donor_tone_distance_lab=14.0,
        swap_tone_distance_lab=11.0,
        original_vs_swapped_cosine=0.14,
        donor_vs_swapped_cosine=0.62,
        swap_detector_score=0.75,
    )

    assert beard_score > clean_score


def test_score_candidate_prefers_clean_shaven_over_more_beard_for_stubbly_source_when_metrics_are_close() -> None:
    beardier_score, _ = driver_face_auto_select._score_candidate(
        source_presentation="masc",
        source_facial_hair="stubble",
        source_glasses="no",
        donor_presentation="masc",
        donor_facial_hair="full_beard",
        donor_glasses="no",
        donor_tone_distance_lab=7.0,
        swap_tone_distance_lab=2.2,
        original_vs_swapped_cosine=-0.03,
        donor_vs_swapped_cosine=0.76,
        swap_detector_score=0.85,
    )
    clean_score, _ = driver_face_auto_select._score_candidate(
        source_presentation="masc",
        source_facial_hair="stubble",
        source_glasses="no",
        donor_presentation="masc",
        donor_facial_hair="none",
        donor_glasses="no",
        donor_tone_distance_lab=7.3,
        swap_tone_distance_lab=2.7,
        original_vs_swapped_cosine=-0.08,
        donor_vs_swapped_cosine=0.73,
        swap_detector_score=0.86,
    )

    assert clean_score > beardier_score


def test_score_candidate_penalizes_glasses_mismatch() -> None:
    same_glasses_score, _ = driver_face_auto_select._score_candidate(
        source_presentation="masc",
        source_facial_hair="none",
        source_glasses="no",
        donor_presentation="masc",
        donor_facial_hair="stubble",
        donor_glasses="no",
        donor_tone_distance_lab=7.0,
        swap_tone_distance_lab=2.2,
        original_vs_swapped_cosine=-0.03,
        donor_vs_swapped_cosine=0.76,
        swap_detector_score=0.85,
    )
    mismatch_score, _ = driver_face_auto_select._score_candidate(
        source_presentation="masc",
        source_facial_hair="none",
        source_glasses="no",
        donor_presentation="masc",
        donor_facial_hair="stubble",
        donor_glasses="yes",
        donor_tone_distance_lab=7.0,
        swap_tone_distance_lab=2.2,
        original_vs_swapped_cosine=-0.03,
        donor_vs_swapped_cosine=0.76,
        swap_detector_score=0.85,
    )

    assert same_glasses_score > mismatch_score


def test_score_candidate_penalizes_glasses_when_source_is_uncertain() -> None:
    same_glasses_score, _ = driver_face_auto_select._score_candidate(
        source_presentation="fem",
        source_facial_hair="none",
        source_glasses="uncertain",
        donor_presentation="fem",
        donor_facial_hair="none",
        donor_glasses="no",
        donor_tone_distance_lab=7.0,
        swap_tone_distance_lab=2.2,
        original_vs_swapped_cosine=-0.03,
        donor_vs_swapped_cosine=0.76,
        swap_detector_score=0.85,
    )
    mismatch_score, _ = driver_face_auto_select._score_candidate(
        source_presentation="fem",
        source_facial_hair="none",
        source_glasses="uncertain",
        donor_presentation="fem",
        donor_facial_hair="none",
        donor_glasses="yes",
        donor_tone_distance_lab=7.0,
        swap_tone_distance_lab=2.2,
        original_vs_swapped_cosine=-0.03,
        donor_vs_swapped_cosine=0.76,
        swap_detector_score=0.85,
    )

    assert same_glasses_score > mismatch_score
