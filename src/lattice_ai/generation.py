import json
import os
import threading
import uuid

from lattice_ai.analyzer import ProjectModel, analyze_project
from lattice_ai.extractor import extract_assets
from lattice_ai.generator import generate_template
from lattice_ai.models import to_dict
from lattice_ai.resolver import resolve_source
from lattice_ai.review import review_workflow


class _Job:
    def __init__(self, payload):
        self.payload = payload
        self.events = []
        self.done = False
        self.result = None
        self.error = None


_jobs: dict[str, _Job] = {}
_lock = threading.Lock()


def get_provider():
    # 延迟导入：runtime 依赖当前项目设置，避免模块加载期的循环依赖
    from lattice_ai import runtime
    return runtime._get_provider()


def _emit(job, type_, data):
    with _lock:
        event = {"seq": len(job.events) + 1, "type": type_}
        if isinstance(data, str):
            event["message"] = data
        elif isinstance(data, dict):
            event.update(data)
        job.events.append(event)


def start_generation(payload: dict) -> str:
    job_id = uuid.uuid4().hex
    job = _Job(payload)
    with _lock:
        _jobs[job_id] = job
    threading.Thread(target=_run, args=(job_id, job), daemon=True).start()
    return job_id


def _is_local(source: str) -> bool:
    return os.path.exists(source) or (not source.startswith(("http://", "https://")) and ("\\" in source or "/" in source))


def _model_from_description(provider, description: str) -> ProjectModel:
    prompt = (
        "From this natural-language description of a security workflow, produce a ProjectModel JSON:\n"
        "keys: summary, entrypoints, tools(list of {name,type(cli|http_api|mcp|skill),command,parameters,ref,detail}), "
        "skills(list of {name,description,content,category}), capabilities, dependencies, confidence, gaps.\n"
        "Be honest: mark inferred tools as type=skill or note in gaps. Description:\n" + description
    )
    resp = provider.chat([{"role": "user", "content": prompt}], [])
    text = resp.get("content") or ""
    start, end = text.find("{"), text.rfind("}")
    try:
        data = json.loads(text[start : end + 1])
    except Exception:
        data = {"summary": description[:300], "confidence": "low", "gaps": ["无法解析描述"]}
    return ProjectModel(
        summary=str(data.get("summary", "")),
        entrypoints=list(data.get("entrypoints", [])),
        tools=list(data.get("tools", [])),
        skills=list(data.get("skills", [])),
        capabilities=list(data.get("capabilities", [])),
        dependencies=list(data.get("dependencies", [])),
        confidence=str(data.get("confidence", "low")),
        gaps=list(data.get("gaps", [])),
    )


def _run(job_id, job):
    try:
        provider = get_provider()
        if provider is None:
            raise ValueError("LLM 未配置；请在设置里填写 API Key")
        _emit(job, "progress", "开始处理来源")

        description = (job.payload.get("description") or "").strip()
        source = (job.payload.get("source") or "").strip()
        name = job.payload.get("name") or ""

        if source:
            _emit(job, "progress", "解析来源")
            mode = job.payload.get("mode") or ("path" if _is_local(source) else "url")
            snapshot = resolve_source(source, mode)
            _emit(job, "progress", f"读取文件树（{len(snapshot.files)} 个文件）")
            model = analyze_project(provider, snapshot)
        else:
            _emit(job, "progress", "根据自然语言描述生成理解模型")
            model = _model_from_description(provider, description)

        _emit(job, "progress", "抽取并适配工具 / Skill")
        tools, skills, imports = extract_assets(model)
        _emit(job, "progress", f"生成模板（{len(tools)} 工具 / {len(skills)} Skill）")
        template, report = generate_template(provider, model, tools, skills, name)

        data = to_dict(template)
        report["issues"] = list(report.get("issues", []))
        for iss in review_workflow(provider, data):
            report["issues"].append(iss)
        report["imports"] = {
            "tools": [{"name": t.name, "kind": t.runner if t.runner != "adapter" else t.adapter, "status": "imported", "detail": t.description} for t in tools],
            "skills": [{"name": s.name, "status": "imported", "detail": s.description} for s in skills],
        }
        report["template_preview"] = data
        report["source"] = {"type": "url" if source and not _is_local(source) else ("path" if source else "description"), "depth": "full"}

        _emit(job, "complete", {"template": data, "report": report})
        with _lock:
            job.result = {"template": data, "report": report}
            job.done = True
    except Exception as exc:
        _emit(job, "error", str(exc))
        with _lock:
            job.error = str(exc)
            job.done = True


def list_generation_events(job_id: str) -> list[dict]:
    with _lock:
        job = _jobs.get(job_id)
        return list(job.events) if job else []


def generation_done(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        return bool(job and job.done)


def generation_exists(job_id: str) -> bool:
    with _lock:
        return job_id in _jobs


def generation_result(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
        return job.result if job else None
