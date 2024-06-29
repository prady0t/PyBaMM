import pytest
import numpy as np


def pytest_addoption(parser):
    parser.addoption(
        "--scripts", action="store_true", default=False, help="run examples tests"
    )
    parser.addoption(
        "--unit", action="store_true", default=False, help="run unit tests"
    )
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="run integration tests",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "scripts: mark test as an example")
    config.addinivalue_line("markers", "unit: mark test as a unit test")
    config.addinivalue_line("markers", "integration: mark test as an integration test")


def pytest_collection_modifyitems(config, items):
    options = {
        "unit": "unit",
        "scripts": "examples",
        "integration": "integration",
    }
    selected_markers = [
        marker for option, marker in options.items() if config.getoption(option)
    ]

    for item in items:
        if "unit" in item.nodeid:
            item.add_marker(pytest.mark.unit)
        elif "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)

    if "scripts" not in selected_markers:
        skip_example = pytest.mark.skip(
            reason="Skipping example tests since --scripts option is not provided"
        )
        for item in items:
            if "scripts" in item.keywords:
                item.add_marker(skip_example)


@pytest.fixture(autouse=True)
# Set the random seed to 42 for all tests
def set_random_seed():
    np.random.seed(42)