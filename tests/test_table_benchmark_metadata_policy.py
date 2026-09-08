from isala_ocr.training.table_benchmark_metadata_policy import normalize_table_benchmark_metadata


def test_trained_table_region_metadata_without_runs_is_safe():
    source = {
        "enabled": True,
        "mode": "trained_table_regions",
        "region_count": 2,
        "cell_count": 17,
    }

    normalized = normalize_table_benchmark_metadata(source)

    assert normalized["runs"] == []
    assert normalized["selected_variant"] == "trained_region_model"
    assert normalized["selected_scope"] == "detected_regions"
    assert "runs" not in source


def test_existing_preprocessing_benchmark_runs_are_preserved():
    runs = [{"variant": "original", "scope": "full", "table_count": 1}]

    normalized = normalize_table_benchmark_metadata({"runs": runs})

    assert normalized["runs"] == runs


def test_none_runs_is_normalized_to_empty_list():
    normalized = normalize_table_benchmark_metadata({"runs": None})

    assert normalized["runs"] == []
