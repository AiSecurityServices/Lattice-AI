"""Default template matrix (M2-A T1): ten built-in templates organized by
target type x depth, following the Osmedeus library's taxonomy (structure
only — every stage, command and wording here is original).

Rules that make the matrix meaningful (handoff §3 T1 "三重区分"):
- stage structure: lite <= 4 stages and no verify stage; standard/extensive
  end with verify (evidence_complete block gate) -> report; extensive adds
  parallel DAG branches;
- skills: lite binds none; standard binds web-enumeration/verification;
  api-assessment additionally binds finding-format + api-auth-testing;
- gates: every template carries at least one distinctive gate.

Tool bindings never pin a tier (demo environments have no real tools); the
M1 tier mechanism resolves real/sim automatically. Registry-backed tools are
NOT redeclared in template.tools — ``install_builtins`` injects the registry
entries, so only builtin-only sims are declared here for UI visibility.
"""


def _gate(name, key, on_fail="warn"):
    return {"name": name, "check": {"op": "truthy", "key": key}, "on_fail": on_fail}


def _or_gate(name, keys, on_fail="warn"):
    return {
        "name": name,
        "check": {"op": "or", "conditions": [{"op": "truthy", "key": k} for k in keys]},
        "on_fail": on_fail,
    }


def _binding(tool, key=None, **extra):
    binding = {"tool": tool}
    if key:
        binding["key"] = key
    binding.update(extra)
    return binding


def _stage(id_, name, goal, depends_on=None, tools=None, gates=None, skills=None, condition=None):
    stage = {"id": id_, "name": name, "goal": goal, "depends_on": depends_on or []}
    if tools:
        stage["tools"] = tools
    if gates:
        stage["gates"] = gates
    if skills:
        stage["skills"] = [{"skill": s} for s in skills]
    if condition:
        stage["condition"] = condition
    return stage


_EVIDENCE_SKILL = "evidence-collection"

# verify + evidence gate, copied from the 18-stage builtin template's pattern
def _verify_stage(depends_on):
    return _stage(
        "verify", "验证复测", "证明漏洞真实存在并固化证据", depends_on,
        tools=[
            _binding("record_finding", "record_verify",
                     defaults={"title": "漏洞验证", "severity": "medium", "status": "confirmed"}),
            _binding("record_loot", "record_loot"),
        ],
        gates=[_gate("evidence_complete", "record_verify.recorded", on_fail="block")],
        skills=["verification", _EVIDENCE_SKILL],
    )


def _triage_stage(depends_on):
    return _stage(
        "triage", "去重与定级", "去重、CWE/CVSS 与证据关联", depends_on,
        gates=[_gate("findings_with_evidence", "record_loot.recorded")],
        skills=["claim-grounding", _EVIDENCE_SKILL],
    )


def _report_stage(depends_on):
    return _stage("report", "报告产出", "生成交付报告", depends_on, skills=["report-format"])


def _injection_stage(depends_on, *, with_record=True):
    tools = [
        _binding("nuclei", "nuclei"),
        _binding("sqlmap", "sqlmap"),
        _binding("dalfox", "dalfox"),
    ]
    if with_record:
        tools.append(_binding("record_finding", "record_injection",
                              defaults={"title": "注入类漏洞", "severity": "high", "status": "confirmed",
                                        "cwe": "CWE-89"}))
    return _stage("injection", "注入类漏洞", "SQLi/XSS 等注入类测试", depends_on,
                  tools=tools, skills=["finding-format", _EVIDENCE_SKILL])


# builtin-only sims (registry-backed tools come from the toolchain registry)
_DECLARED_BUILTIN_TOOLS = [
    {"name": "whatweb", "description": "内置轻量近似：响应头/页面技术特征识别", "runner": "builtin"},
    {"name": "js_extract", "description": "内置 JS 端点/参数提取", "runner": "builtin"},
    {"name": "value_fuzz", "description": "内置值池联动 fuzz", "runner": "builtin"},
    {"name": "fingerprint_cve", "description": "内置依赖版本→CVE 匹配", "runner": "builtin"},
    {"name": "jwt_analyze", "description": "内置 JWT 攻击检测", "runner": "builtin"},
    {"name": "record_finding", "description": "记录结构化发现", "runner": "builtin"},
    {"name": "record_loot", "description": "记录战利品数据", "runner": "builtin"},
]


def _template(id_, name, summary, start, stages, *, tools=None, tags, depth, target_type, en, en_name):
    return {
        "id": id_,
        "name": name,
        "name_i18n": {"zh": name, "en": en_name},
        "summary": summary,
        "start": start,
        "stages": stages,
        "tools": tools or [],
        "skills": [],
        "tags": tags,
        "depth": depth,
        "target_type": target_type,
        "author": "lattice-builtin",
        "description_i18n": {"zh": summary, "en": en},
    }


MATRIX_TEMPLATES = [
    # 1 ------------------------------------------------------------------
    _template(
        "matrix-triage-quick", "快速体检",
        "探活、常见端口与技术指纹的三步快筛，30 秒了解目标轮廓。",
        "probe",
        [
            _stage("probe", "存活探测", "确认目标 Web 服务可达", tools=[_binding("httpx", "httpx")]),
            _stage("ports", "常见端口", "扫描常见端口", ["probe"],
                   tools=[_binding("naabu", "naabu")],
                   gates=[_gate("has_open_ports", "naabu.open_ports")]),
            _stage("fingerprint", "技术指纹", "识别 Web 技术栈", ["ports"],
                   tools=[_binding("whatweb", "whatweb")]),
        ],
        tools=[_DECLARED_BUILTIN_TOOLS[0]],
        tags=["triage", "quick"], depth="lite", target_type="web",
        en="Three-step triage: liveness, common ports and web fingerprint in seconds.", en_name="Quick Health Check",
    ),
    # 2 ------------------------------------------------------------------
    _template(
        "matrix-web-lite", "Web 快筛",
        "指纹→目录→漏扫的三阶段轻量 Web 评估。",
        "fingerprint",
        [
            _stage("fingerprint", "技术指纹", "识别 Web 技术栈", tools=[_binding("whatweb", "whatweb")]),
            _stage("dirs", "目录发现", "固定路径目录探测", ["fingerprint"],
                   tools=[_binding("ffuf", "ffuf")],
                   gates=[_gate("fuzz_surface", "ffuf.paths")]),
            _stage("vuln_scan", "漏洞扫描", "nuclei 低误报漏扫", ["dirs"],
                   tools=[_binding("nuclei", "nuclei")]),
        ],
        tools=[_DECLARED_BUILTIN_TOOLS[0]],
        tags=["web", "quick"], depth="lite", target_type="web",
        en="Lightweight web assessment: fingerprint, directory probe, then vulnerability scan.", en_name="Web Quick Sweep",
    ),
    # 3 ------------------------------------------------------------------
    _template(
        "matrix-web-standard", "Web 标准评估",
        "侦察→端口→指纹→注入→验证→报告的标准 Web 评估流水线。",
        "normalize",
        [
            _stage("normalize", "目标规范化", "确认目标格式和 scope", skills=["recon-playbook"]),
            _stage("liveness", "存活发现", "DNS 与 HTTP 探活", ["normalize"],
                   tools=[_binding("dnsx", "dnsx-live"), _binding("httpx", "httpx-live")],
                   skills=["recon-playbook", _EVIDENCE_SKILL]),
            _stage("subdomain", "子域发现", "扩大攻击面", ["liveness"],
                   tools=[_binding("subfinder", "subfinder")],
                   gates=[_gate("has_subdomains", "subfinder.subdomains")],
                   skills=["recon-playbook", _EVIDENCE_SKILL]),
            _stage("ports", "端口与服务", "识别开放端口", ["subdomain"],
                   tools=[_binding("naabu", "naabu")],
                   skills=["recon-playbook", _EVIDENCE_SKILL]),
            _stage("web_fingerprint", "Web 指纹与端点", "技术栈、目录与端点", ["ports"],
                   tools=[_binding("whatweb", "whatweb"), _binding("ffuf", "ffuf"), _binding("katana", "katana")],
                   skills=["web-enumeration", _EVIDENCE_SKILL]),
            _injection_stage(["web_fingerprint"]),
            _verify_stage(["injection"]),
            _triage_stage(["verify"]),
            _report_stage(["triage"]),
        ],
        tools=_DECLARED_BUILTIN_TOOLS[:1] + _DECLARED_BUILTIN_TOOLS[5:7],
        tags=["web", "standard"], depth="standard", target_type="web",
        en="Standard web pipeline: recon, ports, fingerprint, injection, verify and report.", en_name="Web Standard Assessment",
    ),
    # 4 ------------------------------------------------------------------
    _template(
        "matrix-web-extensive", "Web 深度评估",
        "标准评估之上叠加全量目录与参数 fuzz 并行分支、双路漏扫。",
        "normalize",
        [
            _stage("normalize", "目标规范化", "确认目标格式和 scope", skills=["recon-playbook"]),
            _stage("liveness", "存活发现", "DNS 与 HTTP 探活", ["normalize"],
                   tools=[_binding("dnsx", "dnsx-live"), _binding("httpx", "httpx-live")],
                   skills=["recon-playbook", _EVIDENCE_SKILL]),
            _stage("subdomain", "子域发现", "扩大攻击面", ["liveness"],
                   tools=[_binding("subfinder", "subfinder")],
                   gates=[_gate("has_subdomains", "subfinder.subdomains")],
                   skills=["recon-playbook", _EVIDENCE_SKILL]),
            _stage("ports", "端口与服务", "端口与服务版本", ["subdomain"],
                   tools=[_binding("naabu", "naabu"), _binding("nmap", "nmap")],
                   skills=["recon-playbook", _EVIDENCE_SKILL]),
            _stage("web_fingerprint", "Web 指纹与端点", "技术栈、目录与端点", ["ports"],
                   tools=[_binding("whatweb", "whatweb"), _binding("ffuf", "ffuf"), _binding("katana", "katana")],
                   skills=["web-enumeration", _EVIDENCE_SKILL]),
            _stage("dir_full", "全量目录 fuzz", "扩展词表目录探测", ["web_fingerprint"],
                   tools=[_binding("ffuf", "ffuf-deep")],
                   skills=["web-enumeration"]),
            _stage("param_fuzz", "参数 fuzz", "值池联动的参数探测", ["web_fingerprint"],
                   tools=[_binding("value_fuzz", "value_fuzz", args_from={"endpoints": "katana.links"})],
                   skills=["web-enumeration"]),
            _stage("vuln_scan", "漏洞扫描", "nuclei 漏扫分支", ["dir_full", "param_fuzz"],
                   tools=[_binding("nuclei", "nuclei")],
                   gates=[_or_gate("deep_fuzz_coverage", ["ffuf-deep.paths", "value_fuzz.probes"])],
                   skills=["finding-format", _EVIDENCE_SKILL]),
            _injection_stage(["dir_full", "param_fuzz"]),
            _verify_stage(["vuln_scan", "injection"]),
            _triage_stage(["verify"]),
            _report_stage(["triage"]),
        ],
        tools=_DECLARED_BUILTIN_TOOLS[:1] + _DECLARED_BUILTIN_TOOLS[2:3] + _DECLARED_BUILTIN_TOOLS[5:7],
        tags=["web", "deep", "fuzz"], depth="extensive", target_type="web",
        en="Extensive web assessment: full directory/param fuzz branches and dual scan paths.", en_name="Web Deep Assessment",
    ),
    # 5 ------------------------------------------------------------------
    _template(
        "matrix-api-assessment", "API 专项评估",
        "API 探测→规范发现→认证测试→注入→验证的专项流水线。",
        "probe",
        [
            _stage("probe", "服务探活", "确认 API 服务可达", tools=[_binding("httpx", "httpx")]),
            _stage("spec_discovery", "规范发现", "Swagger/OpenAPI 与 API 端点发现", ["probe"],
                   tools=[_binding("katana", "katana"), _binding("ffuf", "ffuf")],
                   gates=[_or_gate("spec_found", ["ffuf.paths", "katana.links"])],
                   skills=["web-enumeration"]),
            _stage("auth_test", "认证测试", "JWT 弱点与对象级授权探测", ["spec_discovery"],
                   tools=[
                       _binding("jwt_analyze", "jwt_analyze"),
                       _binding("value_fuzz", "value_fuzz", args_from={"endpoints": "katana.links"}),
                   ],
                   gates=[_or_gate("auth_coverage", ["jwt_analyze.vulnerabilities", "value_fuzz.probes"])],
                   skills=["finding-format", "api-auth-testing"]),
            _injection_stage(["auth_test"]),
            _verify_stage(["injection"]),
            _triage_stage(["verify"]),
            _report_stage(["triage"]),
        ],
        tools=_DECLARED_BUILTIN_TOOLS[1:2] + _DECLARED_BUILTIN_TOOLS[2:5] + _DECLARED_BUILTIN_TOOLS[5:7],
        tags=["api", "auth"], depth="standard", target_type="api",
        en="API-focused pipeline: probing, spec discovery, auth testing, injection and verify.", en_name="API Focused Assessment",
    ),
    # 6 ------------------------------------------------------------------
    _template(
        "matrix-recon-domain-lite", "域名侦察-快筛",
        "子域→DNS→探活的三步被动侦察。",
        "subdomain",
        [
            _stage("subdomain", "子域枚举", "被动收集子域", tools=[_binding("subfinder", "subfinder")],
                   gates=[_gate("has_subdomains", "subfinder.subdomains")]),
            _stage("dns", "DNS 解析", "解析 A 记录", ["subdomain"],
                   tools=[_binding("dnsx", "dnsx")]),
            _stage("liveness", "存活探测", "确认存活 Web 端点", ["dns"],
                   tools=[_binding("httpx", "httpx")]),
        ],
        tools=[],
        tags=["recon", "domain", "passive"], depth="lite", target_type="domain",
        en="Three-step passive domain recon: subdomains, DNS, liveness.", en_name="Domain Recon (Lite)",
    ),
    # 7 ------------------------------------------------------------------
    _template(
        "matrix-recon-domain-standard", "域名侦察-标准",
        "子域→DNS→探活→指纹→爬虫与历史 URL 并行→漏扫的标准侦察流水线。",
        "subdomain",
        [
            _stage("subdomain", "子域枚举", "被动收集子域", tools=[_binding("subfinder", "subfinder")],
                   gates=[_gate("has_subdomains", "subfinder.subdomains")]),
            _stage("dns", "DNS 解析", "解析 A 记录", ["subdomain"],
                   tools=[_binding("dnsx", "dnsx")]),
            _stage("liveness", "存活探测", "确认存活 Web 端点", ["dns"],
                   tools=[_binding("httpx", "httpx")]),
            _stage("fingerprint", "技术指纹", "识别存活站点技术栈", ["liveness"],
                   tools=[_binding("whatweb", "whatweb")],
                   skills=["web-enumeration", _EVIDENCE_SKILL]),
            _stage("crawl", "主动爬虫", "爬取站点链接", ["fingerprint"],
                   tools=[_binding("katana", "katana")],
                   skills=["web-enumeration"]),
            _stage("historical_urls", "历史 URL", "Wayback/公共档案已知 URL", ["fingerprint"],
                   tools=[_binding("gau", "gau"), _binding("waybackurls", "waybackurls")],
                   skills=["web-enumeration"]),
            _stage("vuln_scan", "漏洞扫描", "对存活端点 nuclei 漏扫", ["crawl", "historical_urls"],
                   tools=[_binding("nuclei", "nuclei")],
                   skills=["finding-format", _EVIDENCE_SKILL]),
            _verify_stage(["vuln_scan"]),
            _report_stage(["verify"]),
        ],
        tools=_DECLARED_BUILTIN_TOOLS[:1] + _DECLARED_BUILTIN_TOOLS[5:7],
        tags=["recon", "domain"], depth="standard", target_type="domain",
        en="Standard domain recon with parallel crawler/history-URL branches and vuln scan.", en_name="Domain Recon (Standard)",
    ),
    # 8 ------------------------------------------------------------------
    _template(
        "matrix-host-network", "主机/网段评估",
        "端口→服务版本→Web 探针→CVE 关联的主机视角评估。",
        "ports",
        [
            _stage("ports", "端口扫描", "常见端口探测", tools=[_binding("naabu", "naabu")],
                   gates=[_gate("open_ports_found", "naabu.open_ports")]),
            _stage("service_scan", "服务识别", "服务与版本识别", ["ports"],
                   tools=[_binding("nmap", "nmap")]),
            _stage("web_probe", "Web 探针", "主机上的 Web 服务指纹", ["ports"],
                   tools=[_binding("httpx", "httpx"), _binding("whatweb", "whatweb")],
                   skills=["web-enumeration"]),
            _stage("vuln_assoc", "CVE 关联", "指纹版本匹配已知 CVE", ["service_scan", "web_probe"],
                   tools=[
                       _binding("fingerprint_cve", "fingerprint_cve",
                                args_from={"fingerprints": "whatweb.technologies"}),
                       _binding("record_finding", "record_cve",
                                defaults={"title": "依赖版本存在已知 CVE", "severity": "high",
                                          "status": "confirmed", "cwe": "CWE-1395"}),
                   ],
                   skills=["finding-format", _EVIDENCE_SKILL]),
            _verify_stage(["vuln_assoc"]),
            _report_stage(["verify"]),
        ],
        tools=_DECLARED_BUILTIN_TOOLS[:1] + _DECLARED_BUILTIN_TOOLS[3:4] + _DECLARED_BUILTIN_TOOLS[5:7],
        tags=["host", "network", "cve"], depth="standard", target_type="host",
        en="Host/network assessment: ports, services, web probe and CVE association.", en_name="Host / Subnet Assessment",
    ),
    # 9 ------------------------------------------------------------------
    _template(
        "matrix-content-discovery", "内容发现专项",
        "目录 fuzz 与端点爬取/参数探测并行推进的内容发现专项。",
        "probe",
        [
            _stage("probe", "服务探活", "确认目标可达", tools=[_binding("httpx", "httpx")]),
            _stage("dir_fuzz", "目录 fuzz", "固定路径目录探测", ["probe"],
                   tools=[_binding("ffuf", "ffuf")],
                   skills=["web-enumeration"]),
            _stage("endpoint_crawl", "端点爬取", "爬取页面端点", ["probe"],
                   tools=[_binding("katana", "katana")],
                   skills=["web-enumeration"]),
            _stage("param_fuzz", "参数 fuzz", "对爬取端点做值池联动探测", ["endpoint_crawl"],
                   tools=[_binding("value_fuzz", "value_fuzz", args_from={"endpoints": "katana.links"})],
                   skills=["web-enumeration"]),
            _stage("summary", "汇总", "汇总目录与参数发现", ["dir_fuzz", "param_fuzz"],
                   gates=[_or_gate("fuzz_coverage", ["ffuf.paths", "value_fuzz.probes"])],
                   skills=["report-format"]),
        ],
        tools=[_DECLARED_BUILTIN_TOOLS[2]],
        tags=["content", "fuzz"], depth="special", target_type="web",
        en="Content discovery: parallel directory fuzz and crawl/param probe branches.", en_name="Content Discovery",
    ),
    # 10 -----------------------------------------------------------------
    _template(
        "matrix-repo-audit", "仓库审计",
        "定位仓库→trivy 依赖扫描→漏洞记录→报告的代码仓库专项。",
        "locate",
        [
            _stage("locate", "定位仓库", "确认目标为本地仓库/目录路径（运行目标即路径）"),
            _stage("dep_scan", "依赖扫描", "trivy 文件系统依赖漏洞扫描", ["locate"],
                   tools=[_binding("trivy", "trivy")],
                   gates=[_gate("dep_scan_done", "trivy.summary")]),
            _stage("triage", "漏洞记录", "把依赖漏洞固化为结构化发现", ["dep_scan"],
                   tools=[_binding("record_finding", "record_deps",
                                   defaults={"title": "依赖组件存在已知漏洞", "severity": "high",
                                             "status": "confirmed", "cwe": "CWE-1395"})],
                   skills=["finding-format", _EVIDENCE_SKILL]),
            _report_stage(["triage"]),
        ],
        tools=[_DECLARED_BUILTIN_TOOLS[5]],
        tags=["repo", "deps", "trivy"], depth="special", target_type="repo",
        en="Repository audit: locate, trivy dependency scan, findings, report.", en_name="Repository Audit",
    ),
]

MATRIX_TEMPLATE_IDS = [t["id"] for t in MATRIX_TEMPLATES]

_STANDARD_IDS = (
    "matrix-web-standard", "matrix-web-extensive", "matrix-api-assessment",
    "matrix-recon-domain-standard", "matrix-host-network",
)


def seed_matrix_templates(store) -> int:
    """Seed the matrix into a TemplateStore, honoring the trash bin: templates
    the user deleted stay deleted, and user-modified copies are never
    overwritten (same contract as the builtin-* seed loop). Copies still
    authored by lattice-builtin are refreshed when they predate a code-side
    schema addition (e.g. name_i18n) so builtin metadata stays current."""
    trashed = {item["name"] for item in store.trash_list()}
    seeded = 0
    for template in MATRIX_TEMPLATES:
        tid = template["id"]
        if tid in trashed:
            continue
        existing = store.get(tid)
        stale = existing is not None and (
            "name_i18n" not in existing or "description_i18n" not in existing
        )
        if existing is None:
            store.save(tid, template)
            seeded += 1
        elif existing.get("author") == "lattice-builtin" and stale:
            store.save(tid, template)
            seeded += 1
    return seeded
