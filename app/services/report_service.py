import re
import shutil
from pathlib import Path

from app.domain.models import GeneratedReport


class ReportService:
    """Render a validated report plan into a XeLaTeX document."""

    def analyze_template(self, template: Path | None) -> dict:
        if not template or not template.exists():
            return {"has_template": False, "has_placeholder": False, "sections": [], "uses_report_macros": False}
        source = template.read_text(encoding="utf-8", errors="ignore")
        body = self._document_body(source)
        sections = re.findall(r"\\ReportSection\s*\{([^{}]+)\}", body)
        if not sections:
            sections = re.findall(r"\\(?:section|subsection)\*?\s*\{([^{}]+)\}", body)
        unique_sections = []
        for section in sections:
            cleaned = re.sub(r"\\[A-Za-z]+", "", section).strip()
            if cleaned and cleaned not in unique_sections:
                unique_sections.append(cleaned)
        return {
            "has_template": True,
            "has_placeholder": "{{REPORT_CONTENT}}" in source,
            "sections": unique_sections,
            "uses_report_macros": "\\newcommand{\\ReportSection}" in source,
        }

    def export(
        self,
        title: str,
        report: GeneratedReport,
        output_path: Path,
        images: list[dict],
        template: Path | None = None,
    ):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        copied = self._copy_images(output_path, images)
        profile = self.analyze_template(template)
        body = self._report_to_latex(report, copied, profile["uses_report_macros"])

        if template and template.suffix.lower() in {".tex", ".latex"}:
            template_source = template.read_text(encoding="utf-8", errors="ignore")
            if profile["has_placeholder"]:
                source = template_source.replace("{{TITLE}}", self._escape_latex(title)).replace("{{REPORT_CONTENT}}", body)
            else:
                source = self._replace_template_body(template_source, title, body)
        else:
            source = self._default_document(title, body)

        source = self._ensure_xelatex(source)
        output_path.write_text(source, encoding="utf-8")

    def _copy_images(self, output_path: Path, images: list[dict]) -> dict[str, dict]:
        # Report filenames may contain Chinese text. Keep the referenced asset
        # directory ASCII-only for maximum XeLaTeX portability on Windows, but
        # preserve each original image basename so the LaTeX path visibly
        # matches the image manifest and OCR evidence.
        stable_prefix = re.sub(r"[^A-Za-z0-9_-]", "_", output_path.stem[:32]) or "report"
        assets = output_path.with_name(f"{stable_prefix}_assets")
        assets.mkdir(exist_ok=True)
        copied: dict[str, dict] = {}
        used_names: set[str] = set()
        for image in images:
            image_id = str(image["image_id"])
            source = Path(image["path"])
            extension = source.suffix.lower() if source.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"} else ".png"
            original_name = Path(str(image["name"])).name
            # Uploaded files already have legal Windows names. This extra
            # cleanup also protects reports created through the Python API.
            preserved_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", original_name).strip(" .")
            if not preserved_name:
                preserved_name = f"{image_id.lower()}{extension}"
            if Path(preserved_name).suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
                preserved_name += extension
            key = preserved_name.casefold()
            if key in used_names:
                preserved_name = f"{image_id.lower()}_{preserved_name}"
                key = preserved_name.casefold()
            used_names.add(key)
            destination = assets / preserved_name
            shutil.copy2(source, destination)
            copied[image_id] = {
                "relative_path": f"{assets.name}/{destination.name}",
                "original_name": original_name,
                "ocr_text": str(image.get("ocr_text", "")),
            }
        return copied

    def _report_to_latex(self, report: GeneratedReport, copied: dict[str, dict], uses_report_macros: bool) -> str:
        result: list[str] = []
        used_images: set[str] = set()
        for section in report.sections:
            title = self._escape_latex(section.title)
            result.append(f"\\ReportSection{{{title}}}" if uses_report_macros else f"\\section{{{title}}}")
            result.append(self._markdown_to_latex(section.content_markdown, heading_offset=1))
            for figure in section.figures:
                if figure.image_id in copied and figure.image_id not in used_images:
                    result.append(self._figure(figure.image_id, figure.caption, copied[figure.image_id]))
                    used_images.add(figure.image_id)

        unused = [image_id for image_id in copied if image_id not in used_images]
        if unused:
            result.append("\\ReportSection{Screenshots}" if uses_report_macros else "\\section{补充实验图片}")
            result.append("以下图片未被模型分配到特定章节，系统为避免材料遗漏而统一附后。")
            for image_id in unused:
                result.append(self._figure(image_id, f"实验图片：{copied[image_id]['original_name']}", copied[image_id]))
        return "\n\n".join(item for item in result if item.strip())

    def _figure(self, image_id: str, caption: str, image: dict) -> str:
        original = image["original_name"].replace("\n", " ")
        return (
            f"% Source image {image_id}: {original}\n"
            "\\begin{figure}[H]\n"
            "\\centering\n"
            f"\\includegraphics[width=0.88\\textwidth,height=0.68\\textheight,keepaspectratio]{{\\detokenize{{{image['relative_path']}}}}}\n"
            f"\\caption{{{self._escape_latex(caption)}}}\n"
            f"\\label{{fig:{image_id.lower()}}}\n"
            "\\end{figure}"
        )

    def _replace_template_body(self, source: str, title: str, body: str) -> str:
        begin = source.find("\\begin{document}")
        end = source.rfind("\\end{document}")
        if begin < 0 or end < begin:
            return self._default_document(title, body)
        preamble = source[:begin]
        preamble = self._ensure_package(preamble, "graphicx")
        preamble = self._ensure_package(preamble, "float")
        cover: list[str] = []
        if "\\newcommand{\\ReportTitle}" in preamble:
            cover.extend(["\\setcounter{page}{0}", "\\thispagestyle{empty}", "\\vspace*{0.48in}", f"\\ReportTitle{{{self._escape_latex(title)}}}"])
            if "\\newcommand{\\StudentInfo}" in preamble:
                cover.extend(["\\vspace{0.72in}", "\\StudentInfo"])
        else:
            cover.extend([f"\\title{{{self._escape_latex(title)}}}", "\\author{}", "\\date{\\today}", "\\maketitle"])
        return preamble + "\\begin{document}\n" + "\n".join(cover) + "\n\n" + body + "\n\\end{document}\n"

    def _default_document(self, title: str, body: str) -> str:
        return (
            "\\documentclass[12pt,a4paper]{ctexart}\n"
            "\\usepackage{graphicx}\n\\usepackage{float}\n\\usepackage{geometry}\n\\usepackage{booktabs}\n"
            "\\geometry{margin=2.5cm}\n"
            f"\\title{{{self._escape_latex(title)}}}\n\\author{{}}\n\\date{{\\today}}\n"
            "\\begin{document}\n\\maketitle\n" + body + "\n\\end{document}\n"
        )

    @staticmethod
    def _document_body(source: str) -> str:
        match = re.search(r"\\begin\{document\}(.*)\\end\{document\}", source, flags=re.S)
        return match.group(1) if match else source

    @staticmethod
    def _ensure_package(preamble: str, package: str) -> str:
        if re.search(rf"\\usepackage(?:\[[^]]*\])?\{{{re.escape(package)}\}}", preamble):
            return preamble
        document_class = re.search(r"\\documentclass(?:\[[^]]*\])?\{[^}]+\}", preamble)
        document_class_end = document_class.end() if document_class else 0
        insertion = f"\n\\usepackage{{{package}}}"
        return preamble[:document_class_end] + insertion + preamble[document_class_end:]

    @staticmethod
    def _ensure_xelatex(source: str) -> str:
        directive = "%!TEX program = xelatex\n"
        return source if source.lstrip().startswith("%!TEX program = xelatex") else directive + source

    def _markdown_to_latex(self, markdown: str, heading_offset: int = 0) -> str:
        result: list[str] = []
        list_mode: str | None = None
        lines = markdown.splitlines()
        index = 0

        def close_list():
            nonlocal list_mode
            if list_mode:
                result.append(f"\\end{{{list_mode}}}")
                list_mode = None

        while index < len(lines):
            line = lines[index].strip()
            if line.startswith("|") and index + 1 < len(lines) and re.match(r"^\|?\s*:?-+", lines[index + 1].strip()):
                close_list()
                rows = []
                while index < len(lines) and lines[index].strip().startswith("|"):
                    cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                    if not all(re.fullmatch(r":?-+:?", cell) for cell in cells):
                        rows.append(cells)
                    index += 1
                result.extend(self._table(rows))
                continue
            if re.match(r"^#{1,6}\s+", line):
                close_list()
                level = min(3, len(line) - len(line.lstrip("#")) + heading_offset)
                command = {1: "section", 2: "subsection", 3: "subsubsection"}[level]
                result.append(f"\\{command}{{{self._escape_latex(line.lstrip('#').strip())}}}")
            elif re.match(r"^[-*]\s+", line):
                if list_mode != "itemize":
                    close_list(); result.append("\\begin{itemize}"); list_mode = "itemize"
                result.append("\\item " + self._escape_latex(self._plain(re.sub(r"^[-*]\s+", "", line))))
            elif re.match(r"^\d+[.)]\s+", line):
                if list_mode != "enumerate":
                    close_list(); result.append("\\begin{enumerate}"); list_mode = "enumerate"
                result.append("\\item " + self._escape_latex(self._plain(re.sub(r"^\d+[.)]\s+", "", line))))
            elif line:
                close_list(); result.append(self._escape_latex(self._plain(line)) + "\n")
            index += 1
        close_list()
        return "\n".join(result)

    def _table(self, rows: list[list[str]]) -> list[str]:
        if not rows:
            return []
        columns = max(len(row) for row in rows)
        output = ["\\begin{table}[H]", "\\centering", "\\small", "\\resizebox{\\textwidth}{!}{%", "\\begin{tabular}{|" + "l|" * columns + "}", "\\hline"]
        for row_index, row in enumerate(rows):
            cells = row + [""] * (columns - len(row))
            rendered = [self._escape_latex(self._plain(cell)) for cell in cells]
            if row_index == 0:
                rendered = [f"\\textbf{{{cell}}}" for cell in rendered]
            output.append(" & ".join(rendered) + " \\\\ \\hline")
        output.extend(["\\end{tabular}%", "}", "\\end{table}"])
        return output

    @staticmethod
    def _plain(text: str) -> str:
        return re.sub(r"[*_`]+", "", text)

    @staticmethod
    def _escape_latex(text: str) -> str:
        replacements = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
        return "".join(replacements.get(char, char) for char in text)
