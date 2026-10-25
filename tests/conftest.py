import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")   # boto3 clients built at import time

# The Lambda handlers import boto3 at module load; stub it where it isn't installed.
try:
    import boto3  # noqa: F401
except ImportError:  # pragma: no cover - CI installs boto3
    boto3_stub = types.ModuleType("boto3")
    boto3_stub.client = lambda *a, **k: None
    botocore = types.ModuleType("botocore")
    botocore_config = types.ModuleType("botocore.config")
    botocore_config.Config = lambda **k: None
    sys.modules.update({"boto3": boto3_stub, "botocore": botocore, "botocore.config": botocore_config})


@pytest.fixture(scope="session")
def generated(tmp_path_factory):
    """(Dataset, output dir) for the default seed."""
    from datagen.generate import Generator
    out = tmp_path_factory.mktemp("wkg")
    ds = Generator(seed=42).run()
    ds.write(out)
    return ds, out


@pytest.fixture(scope="session")
def kg(generated):
    """The full knowledge graph in memory: four named graphs, rules applied."""
    from warranty_kg import local
    return local.build(generated[1] / "raw")


@pytest.fixture(scope="session")
def explorer(kg):
    from warranty_kg.explorer import Explorer
    return Explorer(kg)
