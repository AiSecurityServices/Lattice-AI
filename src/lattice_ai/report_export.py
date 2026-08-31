import json
from html import escape


def build_report_data(run: dict, evidence: list[dict], findings: list[dict], template_name: str) -> dict:
    confirmed = []
    pending = []
    for finding in findings:
        if finding.get("status") == "confirmed" and finding.get("evidence_ids"):
            confirmed.append(finding)
        else:
            pending.append(finding)

    grounding = {"verified": 0, "unverified": 0, "missing_evidence": 0}
    for finding in findings:
        status = (finding.get("grounding") or {}).get("status")
        if status in grounding:
            grounding[status] += 1

    return {
        "run_id": run.get("id", ""),
        "template": template_name,
        "target": run.get("target", ""),
        "created_at": run.get("created_at", ""),
        "evidence_count": len(evidence),
        "finding_count": len(confirmed),
        "pending_count": len(pending),
        "grounding": grounding,
        "scope": run.get("scope_policy", {}),
        "findings": confirmed,
        "pending": pending,
        "evidence": evidence,
    }


def _grounding_line(grounding: dict) -> str:
    return (
        f"{grounding.get('verified', 0)} verified / "
        f"{grounding.get('unverified', 0)} unverified / "
        f"{grounding.get('missing_evidence', 0)} missing_evidence"
    )


def render_markdown(data: dict) -> str:
    lines = [
        f"# {data['template']} Pentest Report",
        "",
        f"- Target: {data['target']}",
        f"- Run: {data['run_id']}",
        f"- Evidence: {data['evidence_count']}",
        f"- Findings: {data['finding_count']}",
        f"- Pending: {data['pending_count']}",
    ]
    grounding = data.get("grounding") or {}
    if any(grounding.values()):
        lines.append(f"- Grounding: {_grounding_line(grounding)}")
    lines += [
        "",
        "## Findings",
    ]
    for finding in data["findings"]:
        lines.extend([
            f"### {finding.get('title', 'Untitled')}",
            f"- Severity: {finding.get('severity', 'medium')}",
            f"- Status: {finding.get('status', 'confirmed')}",
            f"- Target: {finding.get('target', '')}",
            f"- CWE: {finding.get('cwe', '')}",
            f"- CVSS: {finding.get('cvss', '')}",
            f"- Evidence: {', '.join(finding.get('evidence_ids', []))}",
            "",
            str(finding.get('summary', '')),
            "",
        ])
    lines.append("## Pending / Unverified")
    if not data["pending"]:
        lines.append("None")
    for finding in data["pending"]:
        lines.append(f"- {finding.get('title', 'Untitled')} ({finding.get('status', 'pending')})")
    lines.append("")
    lines.append("## Evidence Appendix")
    for item in data["evidence"]:
        lines.extend([
            f"### {item.get('tool', '')}",
            f"- ID: {item.get('id', '')}",
            f"- Hash: {item.get('hash', '')}",
            "",
            "```json",
            json.dumps(item.get("result", {}), ensure_ascii=False, default=str),
            "```",
            "",
        ])
    return "\n".join(lines)


def render_html(data: dict) -> str:
    rows = []
    for finding in data["findings"]:
        rows.append(
            f"<tr><td>{escape(finding.get('severity', ''))}</td>"
            f"<td>{escape(finding.get('title', ''))}</td>"
            f"<td>{escape(str(finding.get('evidence_ids', [])))}</td></tr>"
        )
    grounding = data.get("grounding") or {}
    grounding_html = ""
    if any(grounding.values()):
        grounding_html = f"<p>Grounding: {escape(_grounding_line(grounding))}</p>"
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Pentest Report</title></head>
<body>
<h1>{escape(data['template'])} Pentest Report</h1>
<p>Target: {escape(data['target'])}</p>
<p>Run: {escape(data['run_id'])}</p>
{grounding_html}
<h2>Findings</h2>
<table border="1"><tr><th>Severity</th><th>Title</th><th>Evidence</th></tr>{''.join(rows)}</table>
<h2>Pending</h2>
<pre>{escape(json.dumps(data['pending'], ensure_ascii=False, indent=2, default=str))}</pre>
</body>
</html>"""


def export_report(run: dict, evidence: list[dict], findings: list[dict], template_name: str, fmt: str) -> str:
    data = build_report_data(run, evidence, findings, template_name)
    if fmt == "json":
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)
    if fmt == "html":
        return render_html(data)
    if fmt == "md":
        return render_markdown(data)
    raise ValueError(f"unsupported report format: {fmt}")
