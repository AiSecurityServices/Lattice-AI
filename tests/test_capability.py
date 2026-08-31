from lattice_ai.capability import capability_of, suggest_stage
from lattice_ai.models import Stage, Template, Tool


def test_capability_of_maps_tools():
    assert capability_of(Tool(name="nmap", description="port scan")) == "recon"
    assert capability_of(Tool(name="nuclei", description="vulnerability scan")) == "vuln"
    assert capability_of(Tool(name="ffuf", description="directory fuzz")) == "fuzz"
    assert capability_of(Tool(name="unknown")) == "other"


def test_suggest_stage_prefers_matching_stage():
    template = Template(
        id="t",
        name="t",
        start="start",
        stages=[
            Stage(id="normalize", name="normalize"),
            Stage(id="ports", name="ports"),
        ],
    )
    assert suggest_stage(template, "recon") == "ports"
    assert suggest_stage(template, "other") == "normalize"
