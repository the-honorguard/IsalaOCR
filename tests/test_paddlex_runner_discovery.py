from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_runner():
    runner_path = Path(__file__).resolve().parents[1] / "automation" / "training_runtime" / "paddlex_runner.py"
    spec = importlib.util.spec_from_file_location("isala_paddlex_runner", runner_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_discover_sorts_path_objects_without_len_type_error(tmp_path, monkeypatch):
    runner = _load_runner()

    shallow = tmp_path / "runtime"
    deep = tmp_path / "nested" / "runtime"
    for root in (shallow, deep):
        config_dir = root / "paddlex" / "configs" / "modules" / "text_recognition"
        config_dir.mkdir(parents=True)
        (config_dir / "PP-OCRv6_medium_rec.yml").write_text("Global: {}\n", encoding="utf-8")
        (root / "main.py").write_text("# test entry point\n", encoding="utf-8")

    monkeypatch.setattr(runner, "_candidate_roots", lambda: [deep, shallow])

    main, config = runner._discover("PP-OCRv6_medium_rec")

    assert main == (shallow / "main.py").resolve()
    assert config == (
        shallow
        / "paddlex"
        / "configs"
        / "modules"
        / "text_recognition"
        / "PP-OCRv6_medium_rec.yml"
    ).resolve()


def test_build_paddlex_command_repeats_override_flag_for_every_value(tmp_path):
    runner = _load_runner()
    main = tmp_path / "main.py"
    config = tmp_path / "model.yaml"

    command = runner._build_paddlex_command(
        main,
        config,
        "PP-OCRv6_medium_rec",
        [
            "Global.mode=check_dataset",
            "Global.dataset_dir=/training/workspace/datasets/example",
            "Global.output=/training/workspace/runs/check-example",
        ],
    )

    bootstrap = Path(runner.__file__).resolve().with_name("paddlex_bootstrap.py")
    assert command == [
        runner.sys.executable,
        str(bootstrap),
        "--main",
        str(main),
        "--model",
        "PP-OCRv6_medium_rec",
        "--source-root",
        str(main.parent),
        "-c",
        str(config),
        "-o",
        "Global.mode=check_dataset",
        "-o",
        "Global.dataset_dir=/training/workspace/datasets/example",
        "-o",
        "Global.output=/training/workspace/runs/check-example",
    ]


def test_run_paddlex_passes_all_overrides_to_bootstrap(tmp_path, monkeypatch):
    runner = _load_runner()
    main = tmp_path / "main.py"
    config = tmp_path / "model.yaml"
    config.write_text("Global: {}\n", encoding="utf-8")
    main.write_text("# test main\n", encoding="utf-8")

    captured = {}

    def fake_run(command, check, env=None):
        captured["command"] = command
        captured["check"] = check
        captured["env"] = env

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    overrides = [
        "Global.mode=check_dataset",
        "Global.dataset_dir=/training/workspace/datasets/example",
        "Global.output=/training/workspace/runs/check-example",
    ]
    runner._run_paddlex(main, config, "PP-OCRv6_medium_rec", overrides)

    assert captured["check"] is True
    assert str(runner.Path(runner.__file__).resolve().parent) in captured["env"]["PYTHONPATH"]
    assert captured["command"][-6:] == [
        "-o",
        overrides[0],
        "-o",
        overrides[1],
        "-o",
        overrides[2],
    ]


def _make_official_dictionary_fixture(tmp_path, model="PP-OCRv6_medium_rec"):
    source = tmp_path / "paddlex-source"
    high_config = source / "paddlex" / "configs" / "modules" / "text_recognition" / f"{model}.yaml"
    high_config.parent.mkdir(parents=True)
    high_config.write_text("Global:\n  model: PP-OCRv6_medium_rec\n", encoding="utf-8")

    low_config = source / "paddlex" / "repo_apis" / "PaddleOCR_api" / "configs" / f"{model}.yaml"
    low_config.parent.mkdir(parents=True)
    low_config.write_text(
        "Global:\n"
        "  character_dict_path: ppocr/utils/dict/ppocrv6_dict.txt\n"
        "  use_space_char: true\n",
        encoding="utf-8",
    )
    dictionary = source / "PaddleOCR" / "ppocr" / "utils" / "dict" / "ppocrv6_dict.txt"
    dictionary.parent.mkdir(parents=True)
    dictionary.write_text("0\n1\n2\n3\n4\n5\n6\n7\n8\n9\n.\n,\n%\nm\nl\n/\n²\n", encoding="utf-8")
    return source, high_config, low_config, dictionary


def test_synchronize_dataset_dictionary_uses_official_model_vocabulary(tmp_path, monkeypatch):
    runner = _load_runner()
    source, high_config, low_config, official_dictionary = _make_official_dictionary_fixture(tmp_path)
    monkeypatch.setattr(runner, "_candidate_roots", lambda: [source])

    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "train.txt").write_text("images/a.png\t51.2 %\n", encoding="utf-8")
    (dataset / "val.txt").write_text("images/b.png\t82,6 ml/m²\n", encoding="utf-8")

    result = runner._synchronize_dataset_dictionary(
        dataset, high_config, "PP-OCRv6_medium_rec"
    )

    assert result["changed"] is True
    assert result["use_space_char"] is True
    assert Path(result["model_config"]) == low_config.resolve()
    assert (dataset / "dict.txt").read_bytes() == official_dictionary.read_bytes()
    assert (dataset / "dictionary_manifest.json").is_file()


def test_synchronize_dataset_dictionary_rejects_unsupported_exact_character(tmp_path, monkeypatch):
    runner = _load_runner()
    source, high_config, _, _ = _make_official_dictionary_fixture(tmp_path)
    monkeypatch.setattr(runner, "_candidate_roots", lambda: [source])

    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "train.txt").write_text("images/a.png\t51.2 €\n", encoding="utf-8")
    (dataset / "val.txt").write_text("images/b.png\t82.6 ml\n", encoding="utf-8")

    import pytest

    with pytest.raises(ValueError, match="unsupported by the official"):
        runner._synchronize_dataset_dictionary(
            dataset, high_config, "PP-OCRv6_medium_rec"
        )


def test_synchronize_dataset_dictionary_prefers_bundled_image_resource(tmp_path, monkeypatch):
    runner = _load_runner()
    source, high_config, low_config, source_dictionary = _make_official_dictionary_fixture(tmp_path)
    source_dictionary.unlink()
    bundled = tmp_path / "image-resources" / "ppocrv6_dict.txt"
    bundled.parent.mkdir(parents=True)
    bundled.write_text("0\n1\n2\n3\n4\n5\n6\n7\n8\n9\n.\n,\n%\nm\nl\n/\n²\n", encoding="utf-8")

    monkeypatch.setattr(runner, "_candidate_roots", lambda: [source])
    monkeypatch.setenv(runner.BUNDLED_DICTIONARY_ENV, str(bundled))

    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "train.txt").write_text("images/a.png\t51.2 %\n", encoding="utf-8")
    (dataset / "val.txt").write_text("images/b.png\t82,6 ml/m²\n", encoding="utf-8")

    result = runner._synchronize_dataset_dictionary(
        dataset, high_config, "PP-OCRv6_medium_rec"
    )

    assert Path(result["official_dictionary"]) == bundled.resolve()
    assert Path(result["model_config"]) == low_config.resolve()
    assert result["use_space_char"] is True
    assert (dataset / "dict.txt").read_bytes() == bundled.read_bytes()


def test_missing_dictionary_error_names_deterministic_image_path(tmp_path, monkeypatch):
    runner = _load_runner()
    source, high_config, _, source_dictionary = _make_official_dictionary_fixture(tmp_path)
    source_dictionary.unlink()
    missing = tmp_path / "missing" / "ppocrv6_dict.txt"
    monkeypatch.setattr(runner, "_candidate_roots", lambda: [source])
    monkeypatch.setenv(runner.BUNDLED_DICTIONARY_ENV, str(missing))

    import pytest

    with pytest.raises(FileNotFoundError, match=str(missing).replace("\\", "\\\\")):
        runner._resolve_dictionary(high_config, "PP-OCRv6_medium_rec")
