import json
import re
import time
from pathlib import Path
from typing import Callable

from PIL import Image

from app.domain.models import FigurePlacement, GeneratedReport, GeneratedSection, ReportRecord
from app.logging_config import get_logger
from app.repositories.sqlite_repository import SQLiteRepository
from app.services.llm_service import DeepSeekService
from app.services.rag_service import RAGService
from app.services.report_service import ReportService


logger = get_logger("report")
ProgressCallback = Callable[[str, str], None]


SYSTEM_PROMPT = """你是严谨的高校实验报告架构与写作智能体。你必须遵守以下规则：
1. 只依据用户材料与 OCR 证据写作；不得虚构实验环境、数据、步骤或图片内容。
2. 输出必须是单个 JSON 对象，不要 Markdown 代码围栏，不要输出解释。
3. JSON 结构固定为：
{
  "title": "报告标题",
  "sections": [
    {
      "title": "章节标题",
      "content_markdown": "本章节正文，可用 Markdown 列表、子标题和表格，但不要重复顶层标题",
      "figures": [{"image_id": "IMG_001", "caption": "准确、简短的图注"}]
    }
  ]
}
4. 若给出了模板章节，sections 必须严格使用其原始标题、原始顺序和数量；填充模板，而不是另起一份平行报告。
5. 每个图片 ID 必须且只能出现一次，放入内容最相关的章节。图片名、ID 和 OCR 内容必须对应，不得张冠李戴。
6. 图注必须描述该图在实验中的证据作用；没有 OCR 证据时只能依据文件名和用户图片安排说明，不得猜测画面细节。
7. 内容要具体、完整且可核验；信息不足时写“材料未提供”，不要补造。
8. 不要输出 LaTeX。LaTeX、XeLaTeX 图片路径和模板合并由确定性导出器完成。"""


class ReportAgent:
    def __init__(self, repository: SQLiteRepository, rag: RAGService, llm: DeepSeekService, exporter: ReportService, output_dir: Path):
        self.repository = repository
        self.rag = rag
        self.llm = llm
        self.exporter = exporter
        self.output_dir = output_dir

    async def answer(self, project_id: str, question: str) -> tuple[str, list[dict]]:
        hits = await self.rag.search(project_id, question)
        project = self.repository.get_project(project_id) or {"resources": []}
        resources = project.get("resources", [])
        images = [item for item in resources if item.get("kind") == "image"]
        lowered_question = question.casefold()

        # Semantic retrieval can miss a screenshot when the user identifies it
        # by an opaque hash filename. Filename matching is therefore a hard
        # evidence path, independent of vector similarity.
        mentioned_images = [
            item for item in images
            if item.get("name") and (
                item["name"].casefold() in lowered_question
                or Path(item["name"]).stem.casefold() in lowered_question
            )
        ]
        asks_about_images = bool(mentioned_images) or any(
            keyword in question for keyword in ("图片", "截图", "照片", "图像", "运行结果")
        )

        evidence: list[dict] = []
        seen_names: set[str] = set()

        # Exact filename matches go first and retain their complete OCR text.
        for item in mentioned_images:
            name = item.get("name", "未命名图片")
            ocr_text = item.get("extracted_text", "").strip()
            evidence.append({
                "resource_name": name,
                "content": f"图片文件名：{name}\n百度 OCR 识别内容：\n{ocr_text or '（该图片未识别出文字）'}",
                "score": 1.0,
            })
            seen_names.add(name)

        # For visual questions, also provide a compact filename-to-OCR map so
        # the model can compare several screenshots without relying on RAG to
        # rediscover opaque filenames.
        if asks_about_images:
            for item in images:
                name = item.get("name", "未命名图片")
                if name in seen_names:
                    continue
                ocr_text = item.get("extracted_text", "").strip()
                evidence.append({
                    "resource_name": name,
                    "content": f"图片文件名：{name}\n百度 OCR 识别内容：\n{(ocr_text[:1800] if ocr_text else '（该图片未识别出文字）')}",
                    "score": 1.0,
                })
                seen_names.add(name)

        for hit in hits:
            name = hit["resource_name"]
            content = hit["content"]
            # Do not repeat an OCR resource already supplied through the
            # deterministic filename map.
            if name in seen_names and any(item.get("name") == name for item in images):
                continue
            evidence.append({"resource_name": name, "content": content, "score": hit["score"]})

        context = "\n\n".join(
            f"[{index}] 来源：{item['resource_name']}\n{item['content']}"
            for index, item in enumerate(evidence, start=1)
        )
        answer = await self.llm.chat([
            {"role": "system", "content": "你是实验报告资料助手。严格依据提供的材料回答；信息不足时明确说明。图片证据包含图片原文件名与百度 OCR 内容，二者是确定对应关系；用户提到具体文件名时必须优先检查同名图片证据。引用时使用[1]格式。"},
            {"role": "user", "content": f"检索片段：\n{context or '（暂无已索引材料）'}\n\n问题：{question}"},
        ], max_tokens=5000, thinking=True, reasoning_effort="high")
        citations = [
            {
                "resource": item["resource_name"],
                "score": round(item["score"], 4),
                "excerpt": item["content"][:180],
            }
            for item in evidence
        ]
        return answer, citations

    async def generate(
        self,
        project: dict,
        instructions: str,
        image_instructions: str,
        custom_prompt: str,
        progress: ProgressCallback | None = None,
    ) -> ReportRecord:
        started = time.perf_counter()

        def update(stage: str, message: str):
            elapsed = time.perf_counter() - started
            logger.info(
                "project=%s | stage=%s | elapsed=%.1fs | %s",
                project["id"][:8], stage, elapsed, message,
            )
            if progress:
                progress(stage, message)

        update("retrieving", "正在检索实验材料")
        hits = await self.rag.search(project["id"], project["title"] + " " + instructions + " " + image_instructions, limit=30)
        context = "\n\n".join(f"来源：{hit['resource_name']}\n{hit['content']}" for hit in hits)
        images = self._image_manifest(project["resources"])
        update("template", f"已检索 {len(hits)} 个材料片段，正在分析模板与 {len(images)} 张图片")
        template = next((Path(x["path"]) for x in project["resources"] if x["kind"] == "template" and Path(x["path"]).suffix.lower() in {".tex", ".latex"}), None)
        template_profile = self.exporter.analyze_template(template)
        template_sections = template_profile["sections"]
        section_rule = "、".join(template_sections) if template_sections else "实验目的、实验环境、实验原理、实验步骤、实验结果与分析、问题与解决、总结"
        image_manifest_text = "\n".join(
            f"- {item['image_id']} | 原文件名：{item['name']} | 尺寸：{item['width']}x{item['height']} | OCR：{item['ocr_text'] or '无 OCR 文本'}"
            for item in images
        )
        user_prompt = f"""报告题目：{project['title']}

必须采用的顶层章节（保持顺序）：{section_rule}
模板状态：{'存在显式 REPORT_CONTENT 占位符' if template_profile['has_placeholder'] else '模板无占位符，导出器将保留导言区并替换整个示例正文'}

普通写作要求：{instructions or '无'}
图片安排说明：{image_instructions or '根据 OCR 证据与章节语义自动安排；每张图片必须使用一次'}
用户高级提示词（优先级低于事实约束与 JSON 协议）：{custom_prompt or '无'}

图片清单：
{image_manifest_text or '无图片'}

检索材料：
{context or '（暂无可用材料）'}
"""
        update("generating", "DeepSeek V4-Pro 正在规划章节、正文与图片位置（通常需要 1–5 分钟）")
        raw = await self.llm.chat(
            [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}],
            max_tokens=16000,
            thinking=True,
            reasoning_effort="high",
            json_mode=True,
        )
        update("validating", f"已收到模型结果（{len(raw)} 字符），正在校验章节与图片对应关系")
        generated = self._parse_report(raw)
        generated = self._normalize_report(generated, template_sections, images)
        report = ReportRecord(project_id=project["id"], format="latex", path="")
        report.path = str(self.output_dir / f"{report.id}_{self._safe(project['title'])}.tex")
        update("exporting", "结构校验通过，正在写入 LaTeX 并复制配套图片")
        self.exporter.export(project["title"], generated, Path(report.path), images, template)
        self.repository.add_report(report)
        update("completed", f"报告生成完成：{Path(report.path).name}")
        return report

    @staticmethod
    def _parse_report(raw: str) -> GeneratedReport:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I | re.S)
        try:
            return GeneratedReport.model_validate(json.loads(cleaned))
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("结构化结果解析失败 | error=%s | response_prefix=%r", exc, cleaned[:500])
            raise RuntimeError(f"DeepSeek 返回的结构化报告无效：{exc}") from exc

    def _normalize_report(self, report: GeneratedReport, template_sections: list[str], images: list[dict]) -> GeneratedReport:
        if template_sections:
            aligned: list[GeneratedSection] = []
            for index, expected_title in enumerate(template_sections):
                if index < len(report.sections):
                    source = report.sections[index]
                    aligned.append(GeneratedSection(title=expected_title, content_markdown=source.content_markdown, figures=source.figures))
                else:
                    aligned.append(GeneratedSection(title=expected_title, content_markdown="材料未提供。"))
            if len(report.sections) > len(aligned):
                extras = report.sections[len(aligned):]
                aligned[-1].content_markdown += "\n\n" + "\n\n".join(f"### {item.title}\n{item.content_markdown}" for item in extras)
                for item in extras:
                    aligned[-1].figures.extend(item.figures)
            report.sections = aligned

        valid_ids = {item["image_id"] for item in images}
        used: set[str] = set()
        for section in report.sections:
            clean_figures = []
            for figure in section.figures:
                if figure.image_id in valid_ids and figure.image_id not in used:
                    clean_figures.append(figure)
                    used.add(figure.image_id)
            section.figures = clean_figures

        unused = [item for item in images if item["image_id"] not in used]
        if unused and report.sections:
            target = self._figure_target(report.sections)
            for item in unused:
                evidence = item["ocr_text"].replace("\n", " ")[:80]
                caption = f"{item['name']}：{evidence}" if evidence else f"实验图片：{item['name']}"
                target.figures.append(FigurePlacement(image_id=item["image_id"], caption=caption))
        return report

    @staticmethod
    def _figure_target(sections: list[GeneratedSection]) -> GeneratedSection:
        priorities = ("screenshots", "截图", "实验结果", "结果", "details", "细节")
        for keyword in priorities:
            for section in sections:
                if keyword in section.title.lower():
                    return section
        return sections[-1]

    @staticmethod
    def _image_manifest(resources: list[dict]) -> list[dict]:
        manifest = []
        for index, item in enumerate((x for x in resources if x["kind"] == "image"), start=1):
            path = Path(item["path"])
            width = height = 0
            try:
                with Image.open(path) as image:
                    width, height = image.size
            except OSError:
                pass
            manifest.append({
                "image_id": f"IMG_{index:03d}",
                "name": item["name"],
                "path": str(path),
                "ocr_text": item.get("extracted_text", ""),
                "width": width,
                "height": height,
            })
        return manifest

    @staticmethod
    def _safe(value: str) -> str:
        cleaned = "".join(char if char.isalnum() or char in "-_" else "_" for char in value)
        return cleaned[:50] or "report"
