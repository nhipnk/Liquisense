import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"


def test_source_has_no_trade_clients_or_order_methods():
    forbidden_imports = {
        "Trading", "AsyncTrading", "Stream", "AsyncStream",
        "trading_ws", "async_trading_ws",
    }
    forbidden_methods = {
        "place_limit_order", "place_market_order", "place_order",
        "amend_order", "cancel_order", "batch_new_order",
    }
    for path in SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (set(alias.name for alias in node.names) & forbidden_imports), path
            if isinstance(node, ast.Import):
                assert not any(alias.name.startswith("ssi_sdk.trading") for alias in node.names), path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_methods, path


def test_environment_example_contains_no_order_signing_key():
    example = (ROOT / ".env.example").read_text(encoding="utf-8").upper()
    assert "PRIVATE_KEY" not in example


def test_credentials_are_not_hard_coded_in_source():
    for path in SOURCE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "YOUR_API_KEY" not in text
        assert "YOUR_API_SECRET" not in text
