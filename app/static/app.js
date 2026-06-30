const $ = (selector) => document.querySelector(selector);
const state = { projects: [], current: null };

const api = async (path, options = {}) => {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try { detail = (await response.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
};

const escapeHtml = (value = "") => value.replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
const toast = (message, error = false) => {
  const node = $('#toast'); node.textContent = message; node.className = `toast show${error ? ' error' : ''}`;
  clearTimeout(node.timer); node.timer = setTimeout(() => node.className = 'toast', 2800);
};

async function loadHealth() {
  try {
    const h = await api('/health');
    const model = h.deepseek_model === 'deepseek-v4-pro' ? 'V4-Pro' : h.deepseek_model;
    $('#serviceStatus').innerHTML = `DeepSeek ${h.deepseek_configured ? model : '未配置'} · OCR ${h.baidu_configured ? '已配置' : '未配置'}<br>嵌入 ${h.ollama_available ? 'Ollama 模型就绪' : '本地降级（模型未就绪）'}`;
  } catch { $('#serviceStatus').textContent = 'API 暂不可用'; }
}

async function loadProjects(selectId) {
  state.projects = await api('/projects');
  $('#projectList').innerHTML = state.projects.map(p => `<button class="project-item ${p.id === state.current?.id ? 'active' : ''}" data-id="${p.id}">◫　${escapeHtml(p.title)}</button>`).join('');
  if (selectId) await selectProject(selectId);
}

async function selectProject(id) {
  state.current = await api(`/projects/${id}`);
  $('#projectTitle').textContent = state.current.title;
  $('#emptyState').classList.add('hidden'); $('#workspace').classList.remove('hidden');
  $('#uploadBtn').disabled = false; $('#openGenerateBtn').disabled = false;
  renderProject();
  [...document.querySelectorAll('.project-item')].forEach(x => x.classList.toggle('active', x.dataset.id === id));
}

function renderProject() {
  const resources = state.current.resources || [];
  $('#resourceChips').innerHTML = resources.slice(0, 5).map(r => `<span class="chip">${r.kind === 'image' ? '▧' : r.kind === 'template' ? '◇' : '▤'} ${escapeHtml(r.name)}</span>`).join('');
  $('#resourceList').innerHTML = resources.length ? resources.map(r => `
    <div class="resource-item"><span class="file-icon">${r.kind === 'image' ? 'IMG' : r.kind === 'template' ? 'TPL' : 'DOC'}</span><div>
      <b title="${escapeHtml(r.name)}">${escapeHtml(r.name)}</b><small>${r.extracted_text ? `${r.extracted_text.length} 字已索引` : '未提取文本'}</small>
      ${r.error ? `<small class="error" title="${escapeHtml(r.error)}">${escapeHtml(r.error.slice(0, 40))}</small>` : ''}
    </div></div>`).join('') : '<p class="muted">还没有材料</p>';
  const base = `<article class="message assistant"><div class="avatar">L</div><div class="bubble"><b>材料工作台已就绪</b><p>上传实验指导书、数据文件、报告模板和截图。随后你可以先问我核对材料，再生成报告。</p></div></article>`;
  const messages = (state.current.messages || []).map(m => messageHtml(m.role, m.content)).join('');
  const reports = (state.current.reports || []).map(r => messageHtml('assistant', `报告已生成：<a href="/api/reports/${r.id}/download">下载 ${r.format.toUpperCase()} 文件</a>`, true)).join('');
  $('#conversation').innerHTML = base + messages + reports;
  scrollConversation();
}

function messageHtml(role, content, raw = false, citations = []) {
  const safe = raw ? content : escapeHtml(content).replace(/\n/g, '<br>');
  const sources = citations.length ? `<div class="citations">${citations.map((c,i) => `<div class="citation">[${i+1}] <b>${escapeHtml(c.resource)}</b> · 相似度 ${c.score}<br>${escapeHtml(c.excerpt)}</div>`).join('')}</div>` : '';
  return `<article class="message ${role}"><div class="avatar">${role === 'user' ? '你' : 'L'}</div><div class="bubble">${safe}${sources}</div></article>`;
}
const scrollConversation = () => { const box = $('#conversation'); requestAnimationFrame(() => box.scrollTop = box.scrollHeight); };

async function upload(files, kind) {
  if (!files.length || !state.current) return;
  const data = new FormData(); [...files].forEach(file => data.append('files', file));
  toast(`正在处理 ${files.length} 个文件…`);
  try {
    const results = await api(`/projects/${state.current.id}/resources?kind=${kind}`, {method:'POST', body:data});
    const failed = results.filter(x => x.error).length;
    await selectProject(state.current.id); $('#inspector').classList.remove('hidden');
    toast(failed ? `上传完成，${failed} 个文件需检查` : '材料已解析并建立索引', failed > 0);
  } catch (error) { toast(error.message, true); }
}

function openProjectDialog(){ $('#projectDialog').showModal(); setTimeout(() => $('#newTitle').focus(), 50); }
$('#newProjectBtn').onclick = openProjectDialog; $('#emptyCreateBtn').onclick = openProjectDialog;
document.addEventListener('click', event => {
  const project = event.target.closest('.project-item'); if (project) selectProject(project.dataset.id);
  const closer = event.target.closest('[data-close]'); if (closer) document.getElementById(closer.dataset.close).close();
});
$('#projectForm').onsubmit = async event => {
  event.preventDefault();
  try {
    const project = await api('/projects', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title:$('#newTitle').value.trim(), description:$('#newDescription').value.trim()})});
    $('#projectDialog').close(); event.target.reset(); await loadProjects(project.id); toast('项目已创建');
  } catch (error) { toast(error.message, true); }
};

$('#uploadBtn').onclick = () => { $('#inspector').classList.remove('hidden'); $('#materialInput').click(); };
$('#dropZone').onclick = () => $('#materialInput').click(); $('#templateBtn').onclick = () => $('#templateInput').click();
$('#closeInspector').onclick = () => $('#inspector').classList.add('hidden');
$('#materialInput').onchange = event => upload(event.target.files, 'material');
$('#templateInput').onchange = event => upload(event.target.files, 'template');
['dragenter','dragover'].forEach(name => $('#dropZone').addEventListener(name, e => {e.preventDefault(); e.currentTarget.classList.add('dragging')}));
['dragleave','drop'].forEach(name => $('#dropZone').addEventListener(name, e => {e.preventDefault(); e.currentTarget.classList.remove('dragging')}));
$('#dropZone').addEventListener('drop', e => upload(e.dataTransfer.files, 'material'));

$('#chatForm').onsubmit = async event => {
  event.preventDefault(); const input = $('#messageInput'); const message = input.value.trim(); if (!message || !state.current) return;
  $('#conversation').insertAdjacentHTML('beforeend', messageHtml('user', message)); input.value = '';
  const typingId = `typing-${Date.now()}`; $('#conversation').insertAdjacentHTML('beforeend', `<article id="${typingId}" class="message assistant"><div class="avatar">L</div><div class="bubble typing"><i></i><i></i><i></i></div></article>`); scrollConversation();
  try {
    const result = await api(`/projects/${state.current.id}/chat`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message})});
    document.getElementById(typingId).outerHTML = messageHtml('assistant', result.answer, false, result.citations); scrollConversation();
  } catch (error) { document.getElementById(typingId).remove(); toast(error.message, true); }
};
$('#messageInput').addEventListener('keydown', e => { if(e.key === 'Enter' && !e.shiftKey){e.preventDefault(); $('#chatForm').requestSubmit();} });
$('#messageInput').addEventListener('input', e => {e.target.style.height='auto'; e.target.style.height=Math.min(e.target.scrollHeight,220)+'px'});

function renderGenerateImages() {
  const images = (state.current?.resources || []).filter(resource => resource.kind === 'image');
  $('#generateImageList').innerHTML = images.length ? images.map((image, index) => `
    <div class="generate-image-item">
      <span>IMG ${String(index + 1).padStart(2, '0')}</span>
      <div><b title="${escapeHtml(image.name)}">${escapeHtml(image.name)}</b><small title="${escapeHtml(image.extracted_text || '无 OCR 文本')}">${escapeHtml(image.extracted_text || '无 OCR 文本')}</small></div>
    </div>`).join('') : '<span class="empty-note">当前项目没有图片</span>';
}

$('#openGenerateBtn').onclick = () => { renderGenerateImages(); $('#generateDialog').showModal(); };
$('#generateForm').onsubmit = async event => {
  event.preventDefault(); const button = $('#generateBtn'); button.disabled = true; button.textContent = '正在创建任务…';
  const progress = $('#generationProgress'); const started = Date.now(); progress.classList.remove('hidden');
  const stageLabels = {queued:'排队中',retrieving:'检索材料',template:'分析模板',generating:'生成正文',validating:'校验结构',exporting:'导出 LaTeX',completed:'生成完成'};
  let timer = setInterval(() => { $('#generationElapsed').textContent = `${Math.floor((Date.now() - started) / 1000)} 秒`; }, 1000);
  try {
    let job = await api(`/projects/${state.current.id}/report-jobs`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
      format:'latex',
      instructions:$('#reportInstructions').value,
      image_instructions:$('#imageInstructions').value,
      custom_prompt:$('#customPrompt').value
    })});
    console.info('[LabScribe] report job created', job.job_id);
    while (!['completed', 'failed'].includes(job.status)) {
      $('#generationStage').textContent = stageLabels[job.stage] || job.stage || '运行中';
      $('#generationMessage').textContent = job.message || '正在生成报告';
      button.textContent = `${job.message || '正在生成'}…`;
      await new Promise(resolve => setTimeout(resolve, 3000));
      job = await api(`/report-jobs/${job.job_id}`);
      console.info('[LabScribe] report progress', job.stage, job.message);
    }
    if (job.status === 'failed') throw new Error(job.message || '报告生成失败');
    const report = job.report;
    $('#generateDialog').close(); await selectProject(state.current.id);
    toast('报告生成完成'); window.location.href = `/api/reports/${report.id}/download`;
  } catch (error) { toast(error.message, true); }
  finally { clearInterval(timer); button.disabled = false; button.textContent = '开始生成'; }
};

Promise.all([loadHealth(), loadProjects()]).catch(error => toast(error.message, true));
