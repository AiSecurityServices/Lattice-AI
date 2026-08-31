import json

from lattice_ai import grounding


_CONDITION_OPS = (
    "truthy: {\"op\":\"truthy\",\"key\":\"<fact path>\"}  "
    "equals: {\"op\":\"equals\",\"key\":\"<fact path>\",\"value\":<value>}  "
    "in: {\"op\":\"in\",\"key\":\"<fact path>\",\"values\":[<values>]}  "
    "not / and / or: {\"op\":\"not\",\"condition\":{...}} / {\"op\":\"and\",\"conditions\":[...]} / {\"op\":\"or\",\"conditions\":[...]}"
)


def _collect_facts(template: dict) -> list[str]:
    facts = []
    for stage in template.get("stages", []):
        for b in stage.get("tools", []) or []:
            facts.append(b.get("key") or b.get("tool"))
    return facts


def translate_condition(provider, description: str, facts: list[str]) -> dict | None:
    prompt = (
        "Translate the following natural-language trigger condition into a JSON condition object for a workflow engine.\n"
        f"Operators:\n{_CONDITION_OPS}\n\n"
        f"Available fact paths: {json.dumps(facts)}\n"
        f"Condition (natural language): {description}\n\n"
        "Return ONLY the JSON object. If it cannot be expressed deterministically, return {\"op\":\"truthy\",\"key\":\"" + (facts[0] if facts else "") + "\"}."
    )
    response = provider.chat([{"role": "user", "content": prompt}], [])
    content = response.get("content") or ""
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(content[start : end + 1])
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def understand_workflow(provider, template: dict) -> tuple[dict, list[dict]]:
    facts = _collect_facts(template)
    updated = json.loads(json.dumps(template))
    updated["summary"] = generate_summary(provider, updated)
    issues = review_workflow(provider, updated)
    return updated, issues


def generate_summary(provider, template: dict) -> str:
    prompt = (
        "Generate a fixed-format description of this workflow. Use EXACTLY this Markdown structure:\n\n"
        "## 执行流程\n"
        "<numbered list: each stage in order, with the tools it calls>\n\n"
        "## 阶段间联系\n"
        "<for each stage: 'stage id depends_on [dependency ids], condition: <stage condition or 无条件>'>\n\n"
        "## 工具调用\n"
        "<each stage's tools: name and what it does>\n\n"
        "Return ONLY the description. Template JSON:\n"
        + json.dumps(template, ensure_ascii=False)
    )
    response = provider.chat([{"role": "user", "content": prompt}], [])
    return (response.get("content") or "").strip()


def generate_report_stream(provider, facts: dict, template, on_delta=None) -> str:
    """Stream a Markdown report. Calls on_delta(content_chunk) as text arrives."""
    name = template.get("name") if isinstance(template, dict) else getattr(template, "name", "")
    prompt = (
        "Write a concise penetration test report in Markdown based on the workflow run below.\n"
        "请使用简体中文撰写报告。\n"
        "Use these sections: ## 目标, ## 发现, ## 结论与建议。\n\n"
        f"Template: {name}\n"
        f"Facts:\n{json.dumps(facts, ensure_ascii=False, default=str)}"
    )
    parts = []
    for event in provider.stream_chat([{"role": "user", "content": prompt}], []):
        if event["type"] == "delta":
            parts.append(event["content"])
            if on_delta:
                on_delta(event["content"])
    return "".join(parts).strip()


_PROMPT = """You are reviewing a security workflow template. The JSON is below.
Check for these problems and report them:
1. A stage that has no tools bound (it will do nothing).
2. A stage whose tool output (fact) is not consumed by any later stage or by a dependency/gate condition.
3. A stage whose depends_on references a missing stage, or a dependency cycle that would never terminate.
4. A gate whose check references a fact path that no tool produces.
5. A tool binding that references a tool name not present in the template's tool list.

Return ONLY a JSON array of issues. Each issue is:
{"severity": "error" or "warning", "where": stage id or "整体", "message": "..."}
Return ONLY the JSON array, no other text."""


def review_workflow(provider, template: dict) -> list[dict]:
    messages = [{"role": "user", "content": _PROMPT + "\n\n" + json.dumps(template, ensure_ascii=False)}]
    response = provider.chat(messages, [])
    content = response.get("content") or ""
    start = content.find("[")
    end = content.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(content[start : end + 1])
        return data if isinstance(data, list) else []
    except Exception:
        return []


def generate_report(provider, facts: dict, template) -> str:
    name = template.get("name") if isinstance(template, dict) else getattr(template, "name", "")
    prompt = (
        "Write a concise penetration test report in Markdown based on the workflow run below. 请使用简体中文撰写。\n"
        "Use these sections: ## 目标, ## 发现, ## 结论与建议.\n\n"
        f"Template: {name}\n"
        f"Facts:\n{json.dumps(facts, ensure_ascii=False, default=str)}"
    )
    response = provider.chat([{"role": "user", "content": prompt}], [])
    return (response.get("content") or "").strip()


def generate_findings(provider, facts: dict, template, target: str = "", known_false_positives=None,
                      evidence_map: dict | None = None, grounding_policy: str | None = None) -> list[dict]:
    name = template.get("name") if isinstance(template, dict) else getattr(template, "name", "")
    prompt = (
        "Based on the security workflow run below, output a JSON array of findings.\n"
        "Each finding must be an object with keys: title(string), severity(critical|high|medium|low|info), "
        "status(confirmed|pending|false_positive), cwe(string), cvss(string), confidence(high|medium|low), "
        "summary(string), impact(string), remediation(string), "
        "evidence(array of string): the top-level fact keys from Facts whose output directly supports the "
        "conclusion. Cite at least one fact key per finding; a finding without evidence cannot be verified.\n"
        "所有文本字段（title、summary、impact、remediation）请用简体中文输出。\n"
        "没有证据支撑的结论不要输出，宁可返回 []，也不要编造。\n"
        "Return ONLY the JSON array. If no real finding, return [].\n\n"
        f"Template: {name}\nTarget: {target}\nFacts:\n{json.dumps(facts, ensure_ascii=False, default=str)}"
    )
    if known_false_positives:
        prompt += (
            "\nKnown false positives (dedup keys): " +
            json.dumps(known_false_positives, ensure_ascii=False) +
            "\nSuppress findings that exactly match a key; mark similar ones "
            "confidence='low' and add summary prefix '[possible_duplicate]'."
        )
    response = provider.chat([{"role": "user", "content": prompt}], [])
    text = (response.get("content") or "").strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    if grounding_policy is None:
        grounding_policy = grounding.get_policy()
    if evidence_map is None:
        evidence_map = {key: {"id": key, "result": value} for key, value in (facts or {}).items()}
    findings = []
    for item in data:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        finding = {
            "title": str(item["title"]),
            "severity": str(item.get("severity", "medium")).lower(),
            "status": str(item.get("status", "confirmed")).lower(),
            "cwe": str(item.get("cwe", "")),
            "cvss": str(item.get("cvss", "")),
            "target": target or str(item.get("target", "")),
            "confidence": str(item.get("confidence", "unverified")).lower(),
            "summary": str(item.get("summary", "")),
            "impact": str(item.get("impact", "")),
            "remediation": str(item.get("remediation", "")),
            "evidence_ids": [str(k) for k in (item.get("evidence") or item.get("evidence_ids") or [])],
        }
        if grounding_policy != "off":
            result = grounding.verify_grounding(finding, evidence_map)
            finding["grounding"] = result.to_dict()
            if result.status == "unverified":
                finding["confidence"] = "unverified"
            if grounding_policy == "enforce" and result.status in ("unverified", "missing_evidence"):
                finding["status"] = "rejected"
        findings.append(finding)
    return findings
