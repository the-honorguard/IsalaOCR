from pathlib import Path

import yaml


def test_paddlex_runtime_services_have_writable_model_cache():
    compose = yaml.safe_load(Path("infrastructure/docker/compose.yaml").read_text(encoding="utf-8"))
    for service_name in ("ocr", "training-collector", "evaluator", "trainer-cpu", "trainer-gpu"):
        service = compose["services"][service_name]
        model_mounts = [str(item) for item in service.get("volumes", []) if "/models" in str(item)]
        assert model_mounts, service_name
        assert all(not item.endswith(":ro") for item in model_mounts), (service_name, model_mounts)
        assert service.get("environment", {}).get("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK") == "True"
