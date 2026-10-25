import pytest
from onboarding.sandbox import Sandbox


@pytest.fixture(scope="session")
def runtime(tmp_path_factory):
    with Sandbox(tmp_path_factory.mktemp("admission") / "runtime") as stack:
        yield stack


@pytest.fixture
def stack(runtime):
    runtime.reset()
    return runtime
