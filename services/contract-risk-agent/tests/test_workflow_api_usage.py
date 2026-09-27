"""Every `workflow.<name>` the workflows use must exist in the installed
Temporal SDK. A missing one only fails at run time, inside Temporal, where
it retries forever (that's how every renewal workflow broke on
`workflow.sleep`, which temporalio 1.6 doesn't have)."""
import ast
import pathlib

import pytest
from temporalio import workflow

WORKFLOW_DIRS = [pathlib.Path(__file__).resolve().parent.parent / "app" / "workflows"]


def _workflow_attributes():
    for d in WORKFLOW_DIRS:
        for f in d.glob("*.py"):
            for node in ast.walk(ast.parse(f.read_text())):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "workflow":
                    yield f.name, node.attr


@pytest.mark.parametrize("filename,attr", sorted(set(_workflow_attributes())))
def test_workflow_api_exists(filename, attr):
    assert hasattr(workflow, attr), f"{filename} uses workflow.{attr}, not in the installed temporalio"
