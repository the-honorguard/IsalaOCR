from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_training_image_pins_shapely_two_in_a_small_post_dependency_layer() -> None:
    dockerfile = (ROOT / "infrastructure" / "docker" / "Dockerfile.training").read_text(encoding="utf-8")
    heavy = dockerfile.index('python3 -m pip install --upgrade "${PADDLE_PACKAGE}"')
    shapely_layer = dockerfile.index('ARG SHAPELY_VERSION=2.1.2')
    source_checkout = dockerfile.index('ARG PADDLEOCR_SOURCE_COMMIT=b03f464')
    assert heavy < shapely_layer < source_checkout
    assert 'python3 -m pip install --upgrade "shapely==${SHAPELY_VERSION}"' in dockerfile
    assert 'from shapely import intersection' in dockerfile
    assert 'Shapely PaddleOCR compatibility:' in dockerfile


def test_training_runtime_fails_fast_on_legacy_shapely() -> None:
    runner = (ROOT / "automation" / "training_runtime" / "paddlex_runner.py").read_text(encoding="utf-8")
    assert "def _verify_shapely_runtime" in runner
    assert "from shapely import intersection" in runner
    assert "Run menu option 1 to build training image revision 3.8.4" in runner
    train_block = runner.split("def train(args: argparse.Namespace) -> int:", 1)[1].split("def evaluate", 1)[0]
    assert "_verify_shapely_runtime()" in train_block


def test_launcher_self_unblocks_powershell_scripts() -> None:
    launcher = (ROOT / "automation" / "powershell" / "launcher.ps1").read_text(encoding="utf-8")
    assert "Unblock-File -ErrorAction SilentlyContinue" in launcher


def test_menu_argument_dispatch_does_not_call_containskey_on_nullable_definition() -> None:
    menu = (ROOT / "automation" / "powershell" / "training-menu.ps1").read_text(encoding="utf-8")
    assert '.ContainsKey("Arguments")' not in menu
    assert '$defaultArguments = $definition["Arguments"]' in menu
    assert 'IsalaOCR local pipeline v{0}' in menu
