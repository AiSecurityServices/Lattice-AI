import pytest

from lattice_ai.graph import GraphError, validate_template
from lattice_ai.models import Stage, Template


def test_cycle_is_rejected():
    t = Template(id="t", name="T", start="a", stages=[
        Stage(id="a", name="A", depends_on=["b"]),
        Stage(id="b", name="B", depends_on=["a"]),
    ])
    with pytest.raises(GraphError):
        validate_template(t)


def test_missing_dependency_rejected():
    t = Template(id="t", name="T", start="a", stages=[Stage(id="a", name="A", depends_on=["x"])])
    with pytest.raises(GraphError):
        validate_template(t)


def test_valid_dag_passes():
    t = Template(id="t", name="T", start="a", stages=[
        Stage(id="a", name="A"),
        Stage(id="b", name="B", depends_on=["a"]),
    ])
    validate_template(t)
