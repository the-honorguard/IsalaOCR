from isala_ocr.training.metrics import compute_metrics


def test_raw_exact_match_and_character_error_metrics():
    metrics = compute_metrics(
        [
            {"expected": "120.7 ml", "observed": "120.7 ml", "field_key": "edv"},
            {"expected": "51.2 %", "observed": "51.2 %", "field_key": "ef"},
            {"expected": "80 ml", "observed": "8O mI", "field_key": "esv"},
        ]
    )
    assert metrics["samples"] == 3
    assert metrics["exact_matches"] == 2
    assert metrics["exact_match_accuracy"] == 2 / 3
    assert metrics["character_error_rate"] > 0
    pairs = {item["pair"] for item in metrics["confusion_pairs"]}
    assert "'0'→'O'" in pairs
    assert "'l'→'I'" in pairs
