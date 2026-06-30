# LabScribe Agent — 实验报告编写助手

LabScribe Agent 是一个面向高校实验课程的智能体 Web 应用。它读取 Word/LaTeX/PDF 等实验材料、LaTeX 模板和多张实验截图，通过百度 OCR、Ollama 向量嵌入、轻量 SQLite RAG 与 DeepSeek V4-Pro，生成带图片引用、可继续编译的 LaTeX 源码。

## 架构

- 表示层：原生 HTML/CSS/JavaScript，ChatGPT 风格单页界面。
- 业务层：FastAPI API、报告智能体编排、RAG、OCR、LLM、导出服务。
- 数据层：SQLite 元数据与向量、工作区文件存储。

外部能力均经适配器封装。Ollama 不可用时使用确定性的本地哈希嵌入，便于离线演示；DeepSeek 或百度 OCR 不可用时接口返回清晰错误，不会悄悄伪造识别结果。

报告生成使用结构化 JSON 计划：模板章节先被提取，图片以稳定 ID 绑定原文件名、尺寸和 OCR 内容，V4-Pro 只负责章节内容、图片归属与图注；导出器负责模板正文替换、XeLaTeX 路径与 `figure` 语法。即使模型漏分配图片，系统也会自动补入结果/截图章节，确保每张图恰好出现一次。

## 安装、启动与关闭

首次安装：

```powershell
conda env create -p .conda\env -f environment.yml
ollama pull nomic-embed-text
```

以后每次启动和关闭：

```powershell
.\start.ps1   # 后台启动，访问 http://127.0.0.1:8000
.\stop.ps1    # 安全关闭并释放 8000 端口
```

后台模式查看实时生成日志：

```powershell
Get-Content .\data\server.out.log -Wait
```

也可以前台运行 `.\.conda\env\python.exe run.py`，RAG、模板分析、DeepSeek 请求耗时、结构校验和导出状态会直接打印在当前控制台，此时按 `Ctrl+C` 关闭。不要同时使用两种启动方式，否则会出现端口 8000 已占用。

报告生成采用后台任务，页面每 3 秒查询一次进度并显示累计耗时；刷新或关闭下载窗口不会中断服务端已开始的生成。DeepSeek 调用使用 V4-Pro 的 `high` 推理强度，在保留模板和图片约束的同时避免 `max` 模式带来的过长等待。

项目根目录已经提供本地 `.env`；它被 `.gitignore` 排除。若代码要公开，请立即轮换其中的 API 密钥。

## 推荐演示流程

1. 新建项目并填写实验名称。
2. 上传 `.docx/.tex/.pdf/.txt/.md` 实验材料和多张 `.png/.jpg` 截图。
3. 把一个 `.tex` 文件标记为“报告模板”。
4. 在对话框询问材料中的问题，展示 RAG 引用。
5. 填写写作要求、图片安排和可选高级提示词，再生成 LaTeX。
6. 从历史记录下载 `.tex`；同目录会生成 `_assets` 配套图片目录。

## API 摘要

- `GET /api/health`：依赖状态。
- `POST /api/projects`、`GET /api/projects`：项目管理。
- `POST /api/projects/{id}/resources?kind=material|template`：多文件上传与索引。
- `POST /api/projects/{id}/chat`：RAG 问答。
- `POST /api/projects/{id}/report-jobs`：创建后台生成任务。
- `GET /api/report-jobs/{job_id}`：查询生成阶段、消息和结果。
- `POST /api/projects/{id}/reports`：兼容用的同步生成接口。
- `GET /api/reports/{id}/download`：下载生成物。

更完整的需求、模式论证和 4+1 视图见 [课程设计报告](docs/软件体系结构课程设计报告.md)。
