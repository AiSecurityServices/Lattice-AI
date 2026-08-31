import pytest

from lattice_ai.graph import GraphError, evaluate, validate_template
from lattice_ai.models import Stage, Template


def test_evaluate_predicates():
    facts = {"a": {"b": 3}}
    assert evaluate({"op": "truthy", "key": "a.b"}, facts) is True
    assert evaluate({"op": "equals", "key": "a.b", "value": 3}, facts) is True
    assert (
        evaluate(
            {"op": "and", "conditions": [{"op": "truthy", "key": "a.b"}, {"op": "equals", "key": "a.b", "value": 2}]},
            facts,
        )
        is False
    )


def test_valid_template():
    t = Template(
        id="t",
        name="n",
        start="a",
        stages=[Stage(id="a", name="a"), Stage(id="b", name="b", depends_on=["a"])],
    )
    validate_template(t)


def test_duplicate_stage_id_raises():
    t = Template(id="t", name="n", start="a", stages=[Stage(id="a", name="a"), Stage(id="a", name="b")])
    with pytest.raises(GraphError):
        validate_template(t)


def test_cycle_rejected():
    t = Template(
        id="t",
        name="n",
        start="a",
        stages=[Stage(id="a", name="a", depends_on=["b"]), Stage(id="b", name="b", depends_on=["a"])],
    )
    with pytest.raises(GraphError):
        validate_template(t)


def test_missing_dependency_rejected():
    t = Template(id="t", name="n", start="a", stages=[Stage(id="a", name="a", depends_on=["x"])])
    with pytest.raises(GraphError):
        validate_template(t)
