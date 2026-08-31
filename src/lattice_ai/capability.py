from lattice_ai.models import Template, Tool


_RULES = [
    ("recon", ("dns", "subdomain", "port", "http", "probe", "crawl", "fingerprint", "enumerate", "recon", "nmap", "naabu")),
    ("vuln", ("nuclei", "sqlmap", "dalfox", "exploit", "cve", "injection", "xss", "vuln", "scan")),
    ("fuzz", ("fuzz", "ffuf", "brute", "wordlist", "directory")),
]

_CAPABILITY_STAGE = {
    "recon": ("liveness", "subdomain", "ports", "web", "normalize"),
    "vuln": ("discover", "verify"),
    "fuzz": ("web", "discover"),
}


def capability_of(tool: Tool) -> str:
    text = f"{tool.name} {tool.description}".lower()
    for kind, keywords in _RULES:
        if any(word in text for word in keywords):
            return kind
    return "other"


def suggest_stage(template: Template, capability: str) -> str | None:
    preferred = _CAPABILITY_STAGE.get(capability, [])
    stage_ids = {stage.id for stage in template.stages}
    for stage_id in preferred:
        if stage_id in stage_ids:
            return stage_id
    return template.stages[0].id if template.stages else None
