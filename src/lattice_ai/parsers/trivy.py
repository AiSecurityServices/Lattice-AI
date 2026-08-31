"""Trivy filesystem scanner parser (M2-A T0): json L1.

trivy fs --format json emits one document whose ``Results[]`` entries carry
per-target ``Vulnerabilities[]``. Items follow the shared facts contract:
``{"type": "finding", "value": <vulnerability id>, "severity", "cve", "pkg", ...}``
so the repo-audit template's gates and the asset/finding pipeline can consume
the same shape as the nuclei/dalfox parsers.
"""


def trivy_rows(rows):
    items = []
    severity_count: dict[str, int] = {}
    for row in rows:
        for result in row.get("Results") or []:
            if not isinstance(result, dict):
                continue
            target = str(result.get("Target") or "")
            for vuln in result.get("Vulnerabilities") or []:
                if not isinstance(vuln, dict):
                    continue
                vid = str(vuln.get("VulnerabilityID") or "").strip()
                if not vid:
                    continue
                severity = str(vuln.get("Severity") or "unknown").lower()
                severity_count[severity] = severity_count.get(severity, 0) + 1
                items.append({
                    "type": "finding",
                    "value": vid,
                    "severity": severity,
                    "cve": [vid] if vid.upper().startswith("CVE-") else [],
                    "pkg": vuln.get("PkgName") or "",
                    "installed_version": vuln.get("InstalledVersion") or "",
                    "fixed_version": vuln.get("FixedVersion") or "",
                    "target": target,
                    "title": vuln.get("Title") or "",
                })
    parts = [f"{k}:{v}" for k, v in sorted(severity_count.items())]
    summary = f"{len(items)} 条依赖漏洞" + (f"（{' / '.join(parts)}）" if parts else "")
    return items, summary
