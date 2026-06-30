"""Convert the maintained Markdown architecture report into submission-ready LaTeX."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "软件体系结构课程设计报告.md"
OUTPUT = ROOT / "docs" / "软件体系结构课程设计报告.tex"

VIEW_IMAGES = {
    "逻辑视图": "diagrams/01_逻辑视图.png",
    "开发视图": "diagrams/02_开发视图.png",
    "进程视图": "diagrams/03_进程视图.png",
    "物理视图": "diagrams/04_物理视图.png",
    "场景视图": "diagrams/05_场景视图.png",
}

PREAMBLE = r"""\documentclass[12pt,a4paper]{ctexart}
\usepackage{geometry}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{tabularx}
\usepackage{float}
\usepackage{xcolor}
\usepackage{hyperref}
\usepackage{enumitem}
\usepackage{fancyhdr}
\usepackage{amsmath}
\geometry{top=2.5cm,bottom=2.4cm,left=2.7cm,right=2.7cm}
\definecolor{LabGreen}{HTML}{174B36}
\definecolor{LabSoft}{HTML}{EEF5EE}
\hypersetup{colorlinks=true,linkcolor=LabGreen,urlcolor=LabGreen}
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{LabScribe Agent}
\fancyhead[R]{软件体系结构课程设计}
\fancyfoot[C]{\thepage}
\setlength{\parindent}{2em}
\setlength{\parskip}{0.35em}
\setlist{nosep,leftmargin=2.5em}
\begin{document}
\begin{titlepage}
\centering
\vspace*{2.2cm}
{\Large\bfseries 软件体系结构课程大作业\par}
\vspace{2.2cm}
{\color{LabGreen}\Huge\bfseries LabScribe Agent\par}
\vspace{0.6cm}
{\LARGE 实验报告编写助手\par}
\vspace{0.4cm}
{\LARGE 体系结构设计文档\par}
\vfill
\renewcommand{\arraystretch}{1.8}
\begin{tabular}{rl}
姓名：& \underline{\hspace{6cm}}\\
学号：& \underline{\hspace{6cm}}\\
日期：& 2026 年 6 月\\
\end{tabular}
\vspace{2cm}
\end{titlepage}
\tableofcontents
\clearpage
"""


def escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def inline(text: str) -> str:
    parts = re.split(r"(`[^`]*`|\*\*[^*]+\*\*)", text)
    result = []
    for part in parts:
        if part.startswith("`") and part.endswith("`"):
            result.append(r"\texttt{" + escape(part[1:-1]) + "}")
        elif part.startswith("**") and part.endswith("**"):
            result.append(r"\textbf{" + escape(part[2:-2]) + "}")
        else:
            result.append(escape(part))
    return "".join(result)


def clean_heading(text: str) -> str:
    return re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", text).strip()


def table_to_latex(rows: list[list[str]]) -> str:
    columns = max(len(row) for row in rows)
    spec = "|" + "|".join("X" for _ in range(columns)) + "|"
    out = [r"\begin{table}[H]", r"\centering\small", rf"\begin{{tabularx}}{{\textwidth}}{{{spec}}}", r"\hline"]
    for index, row in enumerate(rows):
        cells = row + [""] * (columns - len(row))
        rendered = [inline(cell) for cell in cells]
        if index == 0:
            rendered = [r"\textbf{" + cell + "}" for cell in rendered]
        out.append(" & ".join(rendered) + r" \\ \hline")
    out.extend([r"\end{tabularx}", r"\end{table}"])
    return "\n".join(out)


def convert(markdown: str) -> str:
    lines = markdown.splitlines()[1:]
    output: list[str] = [PREAMBLE]
    current_heading = ""
    in_code = False
    code_language = ""
    code_lines: list[str] = []
    list_mode: str | None = None
    i = 0

    def close_list():
        nonlocal list_mode
        if list_mode:
            output.append(r"\end{" + list_mode + "}")
            list_mode = None

    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("```"):
            if not in_code:
                close_list()
                in_code = True
                code_language = line[3:].strip()
                code_lines = []
            else:
                if code_language == "mermaid":
                    image = next((path for key, path in VIEW_IMAGES.items() if key in current_heading), None)
                    if image:
                        output.extend([
                            r"\begin{figure}[H]", r"\centering",
                            rf"\includegraphics[width=\textwidth]{{{image}}}",
                            rf"\caption{{{inline(clean_heading(current_heading))}}}", r"\end{figure}",
                        ])
                    else:
                        output.append(r"\begin{quote}\small 本结构图的可渲染 Mermaid 源码见配套 Markdown 文档。\end{quote}")
                else:
                    output.extend([r"\begin{verbatim}", *code_lines, r"\end{verbatim}"])
                in_code = False
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue

        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-+", lines[i + 1]):
            close_list()
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [cell.strip() for cell in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", cell) for cell in cells):
                    rows.append(cells)
                i += 1
            output.append(table_to_latex(rows))
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            close_list()
            level = len(heading.group(1))
            current_heading = heading.group(2)
            title = clean_heading(current_heading)
            if title.startswith("附录 A"):
                output.append(r"\appendix")
                title = "个人/团队分工表（尾页）"
            command = {1: "section", 2: "section", 3: "subsection"}[level]
            output.append(rf"\{command}{{{inline(title)}}}")
            i += 1
            continue

        if line.strip().startswith("$$") and line.strip().endswith("$$"):
            close_list()
            output.append(r"\[" + line.strip()[2:-2] + r"\]")
            i += 1
            continue

        bullet = re.match(r"^[-*]\s+(.+)$", line)
        numbered = re.match(r"^\d+\.\s+(.+)$", line)
        if bullet or numbered:
            wanted = "itemize" if bullet else "enumerate"
            if list_mode != wanted:
                close_list()
                list_mode = wanted
                output.append(r"\begin{" + wanted + "}")
            output.append(r"\item " + inline((bullet or numbered).group(1)))
            i += 1
            continue

        close_list()
        if line.startswith(">"):
            output.append(r"\begin{quote}\small " + inline(line.lstrip("> ")) + r"\end{quote}")
        elif line.strip():
            output.append(inline(line.strip()) + "\n")
        i += 1

    close_list()
    output.append(r"\end{document}")
    return "\n".join(output) + "\n"


def main():
    OUTPUT.write_text(convert(SOURCE.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Built: {OUTPUT}")


if __name__ == "__main__":
    main()
