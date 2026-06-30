import asyncio
from pathlib import Path

import pytest

from app.domain.models import FigurePlacement, GeneratedReport, GeneratedSection
from app.services.embedding_service import EmbeddingService
from app.services.orchestrator import ReportAgent
from app.services.rag_service import RAGService
from app.services.report_service import ReportService


def test_split_has_overlap_and_preserves_text():
    text = "第一段。" * 200
    chunks = RAGService.split(text, size=120, overlap=20)
    assert len(chunks) > 2
    assert all(len(chunk) <= 121 for chunk in chunks)
    assert chunks[0][-20:] in chunks[1]


def test_hash_embedding_is_deterministic_and_normalized():
    left = EmbeddingService._hash_embedding("采样频率 44100 Hz")
    right = EmbeddingService._hash_embedding("采样频率 44100 Hz")
    assert left == right
    assert sum(x*x for x in left) == pytest.approx(1.0)


def test_hash_embedding_handles_chinese_without_spaces():
    query = EmbeddingService._hash_embedding("吞吐量峰值")
    related = EmbeddingService._hash_embedding("并发五十时吞吐量达到峰值")
    unrelated = EmbeddingService._hash_embedding("本实验使用蓝色试剂")
    assert RAGService._cosine(query, related) > RAGService._cosine(query, unrelated)


def test_latex_export_copies_image(tmp_path: Path):
    image = tmp_path / "result.png"
    image.write_bytes(b"not-a-real-image-but-copy-is-enough")
    output = tmp_path / "report.tex"
    report = GeneratedReport(title="测试报告", sections=[GeneratedSection(
        title="实验结果",
        content_markdown="结果如下。",
        figures=[FigurePlacement(image_id="IMG_001", caption="程序运行结果")],
    )])
    images = [{"image_id": "IMG_001", "name": "运行 结果.png", "path": str(image), "ocr_text": "success"}]
    ReportService().export("测试报告", report, output, images)
    source = output.read_text(encoding="utf-8")
    assert "\\section{实验结果}" in source
    assert "report_assets/运行 结果.png" in source
    assert "Source image IMG_001: 运行 结果.png" in source
    assert (tmp_path / "report_assets" / "运行 结果.png").exists()


def test_latex_export_converts_tables_lists_and_percent(tmp_path: Path):
    output = tmp_path / "report.tex"
    markdown = """## 结果
| 并发 | 吞吐量 |
|---|---|
| 50 | 672 req/s |

1. **运行测试**
2. 计算提升 45.8%
"""
    service = ReportService()
    source = service._markdown_to_latex(markdown)
    assert "\\begin{tabular}" in source
    assert "\\begin{enumerate}" in source
    assert "45.8\\%" in source
    assert "45.8\\\\%" not in source
    assert "**" not in source


def test_template_body_is_replaced_instead_of_appended(tmp_path: Path):
    template = tmp_path / "template.tex"
    template.write_text(r"""\documentclass{article}
\newcommand{\ReportTitle}[1]{\begin{center}#1\end{center}}
\newcommand{\StudentInfo}{Student: ____}
\newcommand{\ReportSection}[1]{\section*{#1}}
\begin{document}
\ReportTitle{Report Name: ****}
\ReportSection{Introduction}
PLACEHOLDER TEXT MUST DISAPPEAR
\ReportSection{Screenshots}
\end{document}
""", encoding="utf-8")
    report = GeneratedReport(title="新报告", sections=[
        GeneratedSection(title="Introduction", content_markdown="真实实验简介。"),
        GeneratedSection(title="Screenshots", content_markdown="截图说明。"),
    ])
    output = tmp_path / "output.tex"
    ReportService().export("新报告", report, output, [], template)
    source = output.read_text(encoding="utf-8")
    assert "PLACEHOLDER TEXT MUST DISAPPEAR" not in source
    assert "Report Name: ****" not in source
    assert "\\ReportTitle{新报告}" in source
    assert source.count("\\begin{document}") == 1
    assert source.count("\\end{document}") == 1


def test_report_plan_aligns_template_and_uses_each_image_once():
    report = GeneratedReport(title="测试", sections=[GeneratedSection(
        title="错误标题",
        content_markdown="正文",
        figures=[FigurePlacement(image_id="IMG_001", caption="图一"), FigurePlacement(image_id="IMG_001", caption="重复")],
    )])
    images = [
        {"image_id": "IMG_001", "name": "one.png", "path": "one.png", "ocr_text": "结果一"},
        {"image_id": "IMG_002", "name": "two.png", "path": "two.png", "ocr_text": "结果二"},
    ]
    agent = object.__new__(ReportAgent)
    normalized = agent._normalize_report(report, ["Introduction", "Screenshots"], images)
    assert [section.title for section in normalized.sections] == ["Introduction", "Screenshots"]
    assigned = [figure.image_id for section in normalized.sections for figure in section.figures]
    assert sorted(assigned) == ["IMG_001", "IMG_002"]


def test_generation_reports_progress_stages(tmp_path: Path):
    class FakeRag:
        async def search(self, *_args, **_kwargs):
            return [{"resource_name": "实验过程.docx", "content": "完成部署并记录结果。"}]

    class FakeLlm:
        async def chat(self, *_args, **_kwargs):
            return '{"title":"测试报告","sections":[{"title":"实验过程","content_markdown":"部署完成。","figures":[]}]}'

    class FakeRepository:
        def __init__(self):
            self.report = None

        def add_report(self, report):
            self.report = report

    repository = FakeRepository()
    agent = ReportAgent(repository, FakeRag(), FakeLlm(), ReportService(), tmp_path)
    stages = []
    project = {
        "id": "test-project-id",
        "title": "测试实验",
        "resources": [{"kind": "material", "name": "实验过程.docx", "path": "unused"}],
    }
    report = asyncio.run(agent.generate(project, "", "", "", progress=lambda stage, message: stages.append((stage, message))))
    assert [stage for stage, _ in stages] == [
        "retrieving", "template", "generating", "validating", "exporting", "completed"
    ]
    assert Path(report.path).exists()
    assert repository.report is report
