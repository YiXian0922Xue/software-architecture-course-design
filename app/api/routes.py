import asyncio
import logging
import mimetypes
import shutil
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.config import ROOT, get_settings
from app.domain.models import ChatRequest, ChatResponse, Project, ProjectCreate, ReportRequest, Resource
from app.logging_config import get_logger
from app.repositories.sqlite_repository import SQLiteRepository
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import DeepSeekService
from app.services.ocr_service import OCRService
from app.services.orchestrator import ReportAgent
from app.services.rag_service import RAGService
from app.services.report_service import ReportService


settings = get_settings()
repo = SQLiteRepository(settings.database_path)
documents = DocumentService()
embeddings = EmbeddingService(settings.ollama_base_url, settings.ollama_embed_model)
rag = RAGService(repo, embeddings)
ocr = OCRService(settings.baidu_app_id, settings.baidu_api_key, settings.baidu_secret_key, ROOT / "BaiduAi")
llm = DeepSeekService(settings.deepseek_api_key, settings.deepseek_base_url, settings.deepseek_model)
agent = ReportAgent(repo, rag, llm, ReportService(), settings.output_dir)
router = APIRouter(prefix="/api")
logger = get_logger("api")
report_jobs: dict[str, dict] = {}
report_tasks: set[asyncio.Task] = set()


def _validate_report_project(project_id: str) -> dict:
    project = repo.get_project(project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    if not any(item["kind"] in {"material", "image"} for item in project["resources"]):
        raise HTTPException(400, "请先上传实验材料或图片")
    return project


async def _run_report_job(job_id: str, project: dict, payload: ReportRequest):
    job = report_jobs[job_id]

    def progress(stage: str, message: str):
        job.update(status="running", stage=stage, message=message)

    try:
        logger.info("生成任务启动 | job=%s project=%s title=%s", job_id[:8], project["id"][:8], project["title"])
        report = await agent.generate(
            project,
            payload.instructions,
            payload.image_instructions,
            payload.custom_prompt,
            progress=progress,
        )
        job.update(status="completed", stage="completed", message="报告生成完成", report=report.model_dump())
        logger.info("生成任务完成 | job=%s report=%s", job_id[:8], report.id[:8])
    except Exception as exc:
        job.update(status="failed", stage="failed", message=str(exc))
        logger.exception("生成任务失败 | job=%s error=%s", job_id[:8], exc)


@router.get("/health")
async def health():
    ollama = False
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(f"{settings.ollama_base_url}/api/tags")
            if response.is_success:
                names = [item.get("name", "") for item in response.json().get("models", [])]
                ollama = any(name == settings.ollama_embed_model or name.startswith(settings.ollama_embed_model + ":") for name in names)
    except httpx.HTTPError:
        pass
    return {"status": "ok", "deepseek_configured": bool(settings.deepseek_api_key), "deepseek_model": settings.deepseek_model, "baidu_configured": bool(settings.baidu_api_key and settings.baidu_secret_key), "ollama_available": ollama, "embedding_provider": embeddings.provider}


@router.post("/projects", status_code=201)
def create_project(payload: ProjectCreate):
    return repo.add_project(Project(**payload.model_dump()))


@router.get("/projects")
def list_projects():
    return repo.list_projects()


@router.get("/projects/{project_id}")
def get_project(project_id: str):
    project = repo.get_project(project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    return project


@router.post("/projects/{project_id}/resources", status_code=201)
async def upload_resources(project_id: str, kind: str = Query("material", pattern="^(material|template)$"), files: list[UploadFile] = File(...)):
    if not repo.get_project(project_id):
        raise HTTPException(404, "项目不存在")
    results = []
    project_dir = settings.upload_dir / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    for upload in files:
        safe_name = Path(upload.filename or "upload.bin").name
        destination = project_dir / f"{Resource(project_id=project_id, name=safe_name, kind='material', path='').id}_{safe_name}"
        size = 0
        with destination.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_mb * 1024 * 1024:
                    target.close()
                    destination.unlink(missing_ok=True)
                    raise HTTPException(413, f"{safe_name} 超过 {settings.max_upload_mb}MB")
                target.write(chunk)
        is_image = (upload.content_type or "").startswith("image/") or destination.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
        resource_kind = "image" if is_image else kind
        text, error = "", ""
        try:
            logger.info("解析资源 | project=%s kind=%s file=%s bytes=%s", project_id[:8], resource_kind, safe_name, size)
            text = ocr.recognize(destination) if is_image else documents.extract(destination)
        except Exception as exc:
            error = str(exc)
            logger.exception("资源解析失败 | project=%s file=%s error=%s", project_id[:8], safe_name, exc)
        resource = Resource(project_id=project_id, name=safe_name, kind=resource_kind, media_type=upload.content_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream", path=str(destination), extracted_text=text, error=error)
        repo.add_resource(resource)
        if text and resource_kind != "template":
            await rag.index(project_id, resource.id, safe_name, text)
        logger.info("资源处理完成 | project=%s file=%s extracted_chars=%s error=%s", project_id[:8], safe_name, len(text), bool(error))
        results.append(resource)
    return results


@router.post("/projects/{project_id}/chat", response_model=ChatResponse)
async def chat(project_id: str, payload: ChatRequest):
    if not repo.get_project(project_id):
        raise HTTPException(404, "项目不存在")
    repo.add_message(project_id, "user", payload.message)
    try:
        answer, citations = await agent.answer(project_id, payload.message)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    repo.add_message(project_id, "assistant", answer)
    return ChatResponse(answer=answer, citations=citations)


@router.post("/projects/{project_id}/reports", status_code=201)
async def generate_report(project_id: str, payload: ReportRequest):
    project = _validate_report_project(project_id)
    try:
        return await agent.generate(project, payload.instructions, payload.image_instructions, payload.custom_prompt)
    except Exception as exc:
        logger.exception("同步生成失败 | project=%s error=%s", project_id[:8], exc)
        raise HTTPException(502, str(exc)) from exc


@router.post("/projects/{project_id}/report-jobs", status_code=202)
async def create_report_job(project_id: str, payload: ReportRequest):
    project = _validate_report_project(project_id)
    job_id = uuid4().hex
    report_jobs[job_id] = {
        "job_id": job_id,
        "project_id": project_id,
        "status": "queued",
        "stage": "queued",
        "message": "任务已创建，正在准备材料",
        "report": None,
    }
    task = asyncio.create_task(_run_report_job(job_id, project, payload))
    report_tasks.add(task)
    task.add_done_callback(report_tasks.discard)
    # Bound memory use for a long-running classroom demo server.
    if len(report_jobs) > 100:
        finished = [key for key, value in report_jobs.items() if value["status"] in {"completed", "failed"}]
        for key in finished[: len(report_jobs) - 100]:
            report_jobs.pop(key, None)
    return report_jobs[job_id]


@router.get("/report-jobs/{job_id}")
async def get_report_job(job_id: str):
    job = report_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "生成任务不存在或服务已重启")
    return job


@router.get("/reports/{report_id}/download")
def download_report(report_id: str):
    report = repo.get_report(report_id)
    if not report or not Path(report["path"]).exists():
        raise HTTPException(404, "报告不存在")
    return FileResponse(report["path"], filename=Path(report["path"]).name)
