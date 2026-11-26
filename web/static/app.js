/* novel-lab Web 控制台前端（纯手写，无任何外部依赖） */
'use strict';

const POLL_MS = 3000;
const PREF_PREFIX = 'novel-lab:';

const state = {
  projects: [],
  current: null,
  pinnedProject: null,
  manifests: {},
  manifest: null,
  manifestError: '',
  view: 'projects',
  chapter: 1,
  chapterSeq: 0,
  chapterData: null,
  chapterError: '',
  logLines: [],
  logPaused: false,
  loading: { projects: false, manifest: false, chapter: false, logs: false },
  polling: false,
  lastRefresh: { projects: 0, manifest: 0, chapter: 0, logs: 0 },
  lastError: {},
  modalProject: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

/* ------------------------------------------------------------------ 基础工具 */

function el(tag, props, ...children) {
  const node = document.createElement(tag);
  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key === 'dataset') Object.assign(node.dataset, value);
      else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
      else if (key.startsWith('on') && typeof value === 'function') {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (value === true) node.setAttribute(key, '');
      else node.setAttribute(key, String(value));
    }
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function numOrNull(value) {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function fmtInt(value) {
  const number = numOrNull(value);
  return number === null ? '—' : Math.round(number).toLocaleString('zh-CN');
}

function fmtNum(value, digits) {
  const number = numOrNull(value);
  if (number === null) return '—';
  return number.toFixed(digits === undefined ? 1 : digits);
}

function fmtDuration(seconds) {
  const value = numOrNull(seconds);
  if (value === null || value < 0) return '—';
  const total = Math.round(value);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return `${hours} 小时 ${minutes} 分`;
  if (minutes > 0) return `${minutes} 分 ${secs} 秒`;
  return `${secs} 秒`;
}

function fmtClock(timestamp) {
  const value = numOrNull(timestamp);
  if (value === null) return '—';
  try {
    return new Date(value).toLocaleTimeString('zh-CN', { hour12: false });
  } catch (err) {
    return '—';
  }
}

function scoreClass(score) {
  const number = numOrNull(score);
  if (number === null) return 'score-na';
  if (number >= 75) return 'score-good';
  if (number >= 60) return 'score-mid';
  return 'score-bad';
}

function fmtMetric(value, ratio) {
  const number = numOrNull(value);
  if (number === null) return '—';
  if (ratio) return `${(number * 100).toFixed(1)}%`;
  if (Math.abs(number) >= 100) return fmtInt(number);
  return String(Math.round(number * 100) / 100);
}

function formatIssues(issues) {
  if (!Array.isArray(issues) || issues.length === 0) return '';
  return issues
    .map((item) => {
      if (item === null || item === undefined) return '';
      if (typeof item === 'string') return item;
      if (typeof item === 'object') {
        const label = item.label || item.name || item.rule || item.metric || '';
        const value = item.value !== undefined ? item.value : item.v;
        if (label) return value === undefined || value === '' ? String(label) : `${label} ${value}`;
        try {
          return JSON.stringify(item);
        } catch (err) {
          return String(item);
        }
      }
      return String(item);
    })
    .filter(Boolean)
    .join('；');
}

function savePref(key, value) {
  try {
    window.localStorage.setItem(PREF_PREFIX + key, String(value));
  } catch (err) {
    /* 隐私模式等情况下忽略 */
  }
}

function loadPref(key) {
  try {
    return window.localStorage.getItem(PREF_PREFIX + key);
  } catch (err) {
    return null;
  }
}

/* ------------------------------------------------------------------ 网络 */

async function apiFetch(path, options) {
  let response;
  try {
    response = await fetch(path, Object.assign({ cache: 'no-store' }, options || {}));
  } catch (err) {
    throw new Error(`网络请求失败：${(err && err.message) || err}`);
  }
  let text = '';
  try {
    text = await response.text();
  } catch (err) {
    text = '';
  }
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (err) {
      if (response.ok) throw new Error(`服务返回的不是合法 JSON（HTTP ${response.status}）`);
      data = null;
    }
  }
  if (!response.ok) {
    const message = (data && (data.error || data.message)) || `HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  if (data === null) throw new Error(`服务返回空响应（HTTP ${response.status}）`);
  return data;
}

function postJSON(path, body) {
  return apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify(body),
  });
}

/* ------------------------------------------------------------------ 错误提示 */

function toast(message, kind, ttl) {
  const box = $('#toasts');
  if (!box) return;
  const item = el('div', { class: `toast toast-${kind || 'error'}` });
  item.append(el('span', { class: 'toast-msg', text: String(message) }));
  item.append(
    el('button', {
      class: 'toast-close',
      type: 'button',
      'aria-label': '关闭',
      text: '×',
      onclick: () => item.remove(),
    })
  );
  box.append(item);
  while (box.children.length > 5) box.firstElementChild.remove();
  window.setTimeout(() => item.remove(), ttl || 7000);
}

function reportError(err, key, silentToast) {
  const message = (err && err.message) || String(err);
  if (key) {
    if (state.lastError[key] === message) return; // 轮询失败只提示一次
    state.lastError[key] = message;
  }
  if (!silentToast) toast(message, 'error');
}

function clearError(key) {
  if (key) delete state.lastError[key];
}

function setInlineError(node, message) {
  if (!node) return;
  if (!message) {
    node.hidden = true;
    node.textContent = '';
    return;
  }
  node.hidden = false;
  node.textContent = message;
}

/* ------------------------------------------------------------------ 数据辅助 */

function currentProject() {
  if (!state.current) return null;
  return state.projects.find((project) => project.name === state.current) || null;
}

function projectTotal() {
  const project = currentProject();
  if (state.manifest) {
    const total = numOrNull(state.manifest.total);
    if (total !== null) return total;
  }
  if (project) {
    const total = numOrNull(project.total);
    if (total !== null) return total;
    return numOrNull(project.chapters);
  }
  return null;
}

function manifestChapters() {
  const chapters = state.manifest && state.manifest.chapters;
  return Array.isArray(chapters) ? chapters.filter((item) => item && typeof item === 'object') : [];
}

function chapterInfo(number) {
  const wanted = numOrNull(number);
  if (wanted === null) return null;
  return manifestChapters().find((item) => numOrNull(item.no) === wanted) || null;
}

/* ------------------------------------------------------------------ 刷新数据 */

async function refreshProjects() {
  if (state.loading.projects) return;
  state.loading.projects = true;
  try {
    const data = await apiFetch('/api/projects');
    const list = Array.isArray(data.projects) ? data.projects : [];
    state.projects = list;
    clearError('projects');
    setInlineError($('#projectsError'), '');
    syncProjectSelect();
    if (!state.current && list.length > 0) {
      const saved = loadPref('current');
      const preferred = list.find((project) => project.name === saved) || list[0];
      state.current = preferred.name;
    }
    if (state.current && !list.some((project) => project.name === state.current) && !state.pinnedProject) {
      state.current = list.length > 0 ? list[0].name : null;
      state.manifest = null;
      state.manifestError = '';
    }
    if (state.current && state.manifests[state.current]) {
      state.manifest = state.manifests[state.current];
    }
    renderProjects();
    updateStatusPill();
    updateFooter();
    // 运行中的项目补拉 manifest，用于显示 ETA / 停止按钮（当前项目由轮询单独刷新）
    const running = list.filter((project) => project.running && project.name !== state.current);
    if (running.length > 0) {
      await Promise.all(running.map((project) => fetchManifest(project.name)));
      renderProjects();
    }
    state.lastRefresh.projects = Date.now();
  } catch (err) {
    reportError(err, 'projects');
    setInlineError($('#projectsError'), `项目列表加载失败：${(err && err.message) || err}`);
    renderProjects();
  } finally {
    state.loading.projects = false;
  }
}

async function fetchManifest(project) {
  try {
    const data = await apiFetch(`/api/manifest/${encodeURIComponent(project)}`);
    state.manifests[project] = data;
    if (project === state.current) {
      state.manifest = data;
      state.manifestError = '';
    }
    clearError(`manifest:${project}`);
    return data;
  } catch (err) {
    delete state.manifests[project];
    if (project === state.current) {
      state.manifest = null;
      state.manifestError = (err && err.message) || String(err);
    }
    // 404 = 流水线还没开始，属于正常状态，不弹错误
    if (err.status !== 404) reportError(err, `manifest:${project}`);
    return null;
  }
}

async function refreshManifest(project, options) {
  if (!project) {
    state.manifest = null;
    state.manifestError = '';
    return null;
  }
  if (state.loading.manifest) return state.manifest;
  state.loading.manifest = true;
  try {
    const data = await fetchManifest(project);
    state.lastRefresh.manifest = Date.now();
    if (!options || !options.silent) renderForCurrentView();
    else if (project === state.current) {
      // 后台轮询也要把进度画出来
      if (state.view === 'projects') renderProjects();
      else if (state.view === 'reader') renderReader();
      else if (state.view === 'quality') renderQuality();
      updateStatusPill();
      updateFooter();
    }
    return data;
  } finally {
    state.loading.manifest = false;
  }
}

async function loadChapter(number) {
  if (!state.current) {
    state.chapterData = null;
    state.chapterError = '';
    renderReader();
    return;
  }
  let wanted = Number(number);
  if (!Number.isFinite(wanted) || wanted < 1) wanted = 1;
  wanted = Math.trunc(wanted);
  const total = projectTotal();
  if (total !== null && wanted > total) wanted = total;
  state.chapter = wanted;
  savePref('chapter', wanted);
  const seq = ++state.chapterSeq;
  state.loading.chapter = true;
  try {
    const data = await apiFetch(
      `/api/chapter/${encodeURIComponent(state.current)}/${encodeURIComponent(wanted)}`
    );
    if (seq !== state.chapterSeq) return; // 丢弃过期响应
    state.chapterData = {
      no: numOrNull(data.no) !== null ? numOrNull(data.no) : wanted,
      text: typeof data.text === 'string' ? data.text : '',
    };
    state.chapterError = '';
    clearError('chapter');
  } catch (err) {
    if (seq !== state.chapterSeq) return;
    state.chapterData = null;
    if (err.status === 404) {
      state.chapterError = `第 ${wanted} 章还没有正文（${(err && err.message) || '章节不存在'}）`;
    } else {
      state.chapterError = `章节加载失败：${(err && err.message) || err}`;
      reportError(err, 'chapter');
    }
  } finally {
    if (seq === state.chapterSeq) {
      state.loading.chapter = false;
      state.lastRefresh.chapter = Date.now();
      renderReader();
    }
  }
}

async function refreshLogs() {
  if (!state.current) {
    state.logLines = [];
    renderLogs();
    return;
  }
  if (state.loading.logs) return;
  state.loading.logs = true;
  const tailSelect = $('#logTail');
  const tail = numOrNull(tailSelect && tailSelect.value) || 300;
  try {
    const data = await apiFetch(
      `/api/log/${encodeURIComponent(state.current)}?tail=${encodeURIComponent(Math.trunc(tail))}`
    );
    state.logLines = Array.isArray(data.lines) ? data.lines : [];
    clearError('logs');
    setInlineError($('#logsError'), '');
    state.lastRefresh.logs = Date.now();
  } catch (err) {
    reportError(err, 'logs');
    setInlineError($('#logsError'), `日志加载失败：${(err && err.message) || err}`);
  } finally {
    state.loading.logs = false;
    renderLogs();
  }
}

/* ------------------------------------------------------------------ 项目选择 */

function syncProjectSelect() {
  const select = $('#projectSelect');
  if (!select) return;
  // 允许通过 ?project=xxx 直接打开一个只有 out/ 产物、没有 toml 的项目
  const extras =
    state.current && !state.projects.some((project) => project.name === state.current)
      ? [state.current]
      : [];
  const signature =
    state.projects.map((project) => project.name).join('\u0000') + '\u0001' + extras.join('\u0000');
  if (select.dataset.sig !== signature) {
    select.replaceChildren();
    if (state.projects.length === 0 && extras.length === 0) {
      select.append(el('option', { value: '', text: '（无项目）' }));
    } else {
      for (const project of state.projects) {
        select.append(
          el('option', {
            value: project.name,
            text: `${project.title || project.name} (${project.name})`,
          })
        );
      }
      for (const name of extras) {
        select.append(el('option', { value: name, text: `${name}（仅 out/）` }));
      }
    }
    select.dataset.sig = signature;
  }
  select.disabled = state.projects.length === 0 && extras.length === 0;
  if (
    state.current &&
    (state.projects.some((project) => project.name === state.current) || extras.includes(state.current))
  ) {
    select.value = state.current;
  } else if (state.projects.length === 0) {
    select.value = '';
  }
}

async function selectProject(name) {
  state.pinnedProject = null;
  state.current = name || null;
  savePref('current', state.current || '');
  syncProjectSelect();
  state.manifest = name ? state.manifests[name] || null : null;
  state.manifestError = '';
  state.chapterData = null;
  state.chapterError = '';
  state.chapter = 1;
  state.chapterSeq += 1;
  state.logLines = [];
  if (name) await refreshManifest(name, { silent: true });
  updateStatusPill();
  updateFooter();
}

async function onProjectChange(event) {
  await selectProject(event.target.value || null);
  renderForCurrentView();
  if (state.view === 'reader' && state.current) await loadChapter(1);
  else if (state.view === 'logs') await refreshLogs();
}

/* ------------------------------------------------------------------ 运行 / 停止 */

function openRunModal(projectName) {
  const project =
    state.projects.find((item) => item.name === projectName) ||
    (state.current === projectName ? currentProject() : null);
  if (!project) {
    toast(`找不到项目：${projectName}`, 'error');
    return;
  }
  state.modalProject = project.name;
  const total = numOrNull(project.total) !== null ? numOrNull(project.total) : numOrNull(project.chapters);
  const written = numOrNull(project.written) || 0;
  const from = Math.max(1, written + 1);
  const to = total !== null ? Math.min(total, from + 49) : from + 49;
  $('#runFrom').value = String(from);
  $('#runTo').value = String(to);
  $('#runModalHint').textContent =
    `${project.title || project.name}（${project.name}）· 总章数 ${total === null ? '未知' : fmtInt(total)} · 已写 ${fmtInt(written)}`;
  updateRunPreview();
  setInlineError($('#runModalError'), '');
  const modal = $('#runModal');
  modal.hidden = false;
  window.setTimeout(() => {
    const input = $('#runFrom');
    if (input) input.focus();
  }, 30);
}

function closeRunModal() {
  $('#runModal').hidden = true;
  state.modalProject = null;
}

function updateRunPreview() {
  const project = state.modalProject || '…';
  const from = $('#runFrom').value || '…';
  const to = $('#runTo').value || '…';
  $('#runCmdPreview').textContent = `python src/runner.py --project ${project} --from ${from} --to ${to}`;
}

async function confirmRun() {
  const project = state.modalProject;
  if (!project) return;
  const from = Number($('#runFrom').value);
  const to = Number($('#runTo').value);
  if (!Number.isInteger(from) || from < 1) {
    setInlineError($('#runModalError'), '「从第几章」必须是正整数');
    return;
  }
  if (!Number.isInteger(to) || to < from) {
    setInlineError($('#runModalError'), '「到第几章」必须是 >= 起始章的正整数');
    return;
  }
  setInlineError($('#runModalError'), '');
  const button = $('#btnRunConfirm');
  button.disabled = true;
  try {
    const data = await postJSON('/api/run', { project, from, to });
    closeRunModal();
    toast(`已启动 ${project} 第 ${from}–${to} 章，pid=${data.pid}`, 'ok');
    await selectProject(project);
    await refreshProjects();
    renderForCurrentView();
  } catch (err) {
    const message = `启动失败：${(err && err.message) || err}`;
    setInlineError($('#runModalError'), message);
    toast(message, 'error');
  } finally {
    button.disabled = false;
  }
}

async function stopProject(project) {
  if (!project) return;
  const confirmed = window.confirm(`确定停止「${project}」的写作进程？未落盘的章节可能丢失。`);
  if (!confirmed) return;
  try {
    const data = await postJSON('/api/stop', { project });
    toast(`已停止 ${project}${data.pid ? `（pid=${data.pid}）` : ''}`, 'ok');
  } catch (err) {
    if (err.status === 404) toast(`「${project}」当前没有正在运行的进程`, 'error');
    else toast(`停止失败：${(err && err.message) || err}`, 'error');
  }
  await refreshProjects();
  if (project === state.current) await refreshManifest(project, { silent: true });
  renderForCurrentView();
}

function openChapter(number) {
  const wanted = numOrNull(number) !== null ? numOrNull(number) : state.chapter;
  applyView('reader');
  loadChapter(wanted);
}

/* ------------------------------------------------------------------ 渲染：项目 */

function projectCard(project) {
  const total = numOrNull(project.total) !== null ? numOrNull(project.total) : numOrNull(project.chapters);
  const written = numOrNull(project.written) || 0;
  const percent = total && total > 0 ? Math.max(0, Math.min(100, (written / total) * 100)) : 0;
  const manifest = state.manifests[project.name] || null;
  const running =
    manifest && manifest.running && typeof manifest.running === 'object' ? manifest.running : null;
  const isRunning = Boolean(running) || Boolean(project.running);

  const card = el('article', {
    class: `card${project.name === state.current ? ' card-current' : ''}`,
    dataset: { project: project.name },
  });

  const sub = el('div', { class: 'card-sub' }, el('span', { class: 'mono', text: project.name }));
  if (project.genre) sub.append(el('span', { class: 'badge', text: project.genre }));
  if (project.style) sub.append(el('span', { class: 'badge badge-muted', text: project.style }));
  if (isRunning) sub.append(el('span', { class: 'badge badge-run', text: '运行中' }));
  if (project.error) sub.append(el('span', { class: 'badge badge-bad', text: 'TOML 有误' }));
  card.append(
    el(
      'div',
      { class: 'card-head' },
      el(
        'div',
        { class: 'card-title-wrap' },
        el('h3', { class: 'card-title', text: project.title || project.name }),
        sub
      )
    )
  );

  if (project.logline) card.append(el('p', { class: 'card-logline', text: project.logline }));

  const metrics = el('div', { class: 'card-metrics' });
  const addMetric = (label, value) => {
    metrics.append(
      el(
        'div',
        { class: 'metric' },
        el('span', { class: 'metric-k', text: label }),
        el('span', { class: 'metric-v mono', title: String(value), text: String(value) })
      )
    );
  };
  addMetric('章数', total === null ? '—' : fmtInt(total));
  addMetric('每章字数', numOrNull(project.words_per_chapter) === null ? '—' : fmtInt(project.words_per_chapter));
  addMetric('模型', project.model || '—');
  card.append(metrics);

  const progress = el('div', { class: 'progress-block' });
  progress.append(
    el(
      'div',
      { class: 'progress-label' },
      el('span', { text: '已写' }),
      el('span', {
        class: 'mono',
        text: `${fmtInt(written)}${total === null ? '' : ` / ${fmtInt(total)}`} · ${percent.toFixed(1)}%`,
      })
    )
  );
  const bar = el('div', { class: 'progress' });
  bar.append(el('div', { class: 'progress-fill', style: { width: `${percent.toFixed(2)}%` } }));
  progress.append(bar);
  card.append(progress);

  if (running) {
    const done = numOrNull(running.done) || 0;
    const todo = numOrNull(running.todo) || 0;
    const runTotal = done + todo;
    const runPercent = runTotal > 0 ? Math.max(0, Math.min(100, (done / runTotal) * 100)) : 0;
    const runBox = el('div', { class: 'card-run' });
    const runLine = el('div', { class: 'run-line' });
    runLine.append(el('span', { class: 'badge badge-run', text: '运行中' }));
    runLine.append(el('span', { class: 'mono', text: `pid ${numOrNull(running.pid) === null ? '?' : numOrNull(running.pid)}` }));
    runLine.append(
      el('span', {
        text: `第 ${numOrNull(running.from) === null ? '?' : numOrNull(running.from)}–${
          numOrNull(running.to) === null ? '?' : numOrNull(running.to)
        } 章`,
      })
    );
    runLine.append(el('span', { class: 'muted', text: `阶段 ${running.phase || '—'}` }));
    runBox.append(runLine);
    const runBar = el('div', { class: 'progress progress-run' });
    runBar.append(el('div', { class: 'progress-fill', style: { width: `${runPercent.toFixed(2)}%` } }));
    runBox.append(runBar);
    runBox.append(
      el(
        'div',
        { class: 'run-meta mono' },
        el('span', { text: `完成 ${fmtInt(done)} / ${fmtInt(runTotal)}` }),
        el('span', { text: `剩余 ${fmtDuration(running.eta_sec)}` }),
        el('span', { text: runTotal > 0 ? `${runPercent.toFixed(1)}%` : '—' })
      )
    );
    card.append(runBox);
  }

  const actions = el('div', { class: 'card-actions' });
  const btnRun = el('button', {
    class: 'btn btn-primary',
    type: 'button',
    text: '开始写作',
    title: isRunning ? '该项目已有 runner 在跑（409）' : '选择章节区间后启动 runner',
    disabled: isRunning,
    onclick: () => openRunModal(project.name),
  });
  actions.append(btnRun);
  if (isRunning) {
    actions.append(
      el('button', {
        class: 'btn btn-danger',
        type: 'button',
        text: '停止',
        onclick: () => stopProject(project.name),
      })
    );
  }
  actions.append(
    el('button', {
      class: 'btn btn-ghost',
      type: 'button',
      text: '阅读最新章节',
      onclick: async () => {
        await selectProject(project.name);
        const latest = Math.max(1, numOrNull(project.written) || 1);
        applyView('reader');
        loadChapter(latest);
      },
    })
  );
  actions.append(
    el('button', {
      class: 'btn btn-ghost',
      type: 'button',
      text: '文体质量',
      onclick: async () => {
        await selectProject(project.name);
        applyView('quality');
      },
    })
  );
  card.append(actions);
  return card;
}

function renderProjects() {
  const grid = $('#projectGrid');
  if (!grid) return;
  grid.replaceChildren();
  const empty = $('#projectsEmpty');
  if (state.projects.length === 0) {
    if (empty) {
      empty.hidden = false;
      empty.textContent = '暂无数据 —— projects/ 目录不存在或还没有 *.toml 项目配置。流水线产物 out/<project>/ 不会自动出现在这里。';
    }
    return;
  }
  if (empty) empty.hidden = true;
  for (const project of state.projects) grid.append(projectCard(project));
}

/* ------------------------------------------------------------------ 渲染：正文 */

function chip(text, className) {
  return el('span', { class: `chip${className ? ` ${className}` : ''}`, text: text });
}

function renderReader() {
  const input = $('#chapterInput');
  if (input && document.activeElement !== input) input.value = String(state.chapter || 1);
  const meta = $('#readerMeta');
  const body = $('#readerBody');
  const empty = $('#readerEmpty');
  if (!meta || !body || !empty) return;
  meta.replaceChildren();

  if (!state.current) {
    body.textContent = '';
    body.hidden = true;
    empty.hidden = false;
    empty.textContent = '暂无数据 —— 请先在「项目」视图选择一个项目';
    setInlineError($('#readerError'), '');
    return;
  }

  const project = currentProject();
  const info = chapterInfo(state.chapter);
  const text = state.chapterData && state.chapterData.no === state.chapter ? state.chapterData.text : null;

  meta.append(chip(`第 ${state.chapter} 章`));
  if (project) meta.append(chip(project.title || project.name, 'chip-muted'));

  const manifestChars = info ? numOrNull(info.chars) : null;
  const chars = manifestChars !== null ? manifestChars : text === null ? null : Array.from(text).length;
  if (chars !== null) {
    meta.append(chip(`字数 ${fmtInt(chars)}${manifestChars !== null ? '（manifest）' : ''}`));
  }
  const score = info ? numOrNull(info.score) : null;
  if (score !== null) meta.append(el('span', { class: `chip score ${scoreClass(score)}`, text: `评分 ${fmtNum(score, 1)}` }));
  else meta.append(chip('评分 —', 'chip-muted'));
  const retries = info ? numOrNull(info.retries) : null;
  if (retries !== null && retries > 0) meta.append(chip(`重试 ${fmtInt(retries)}`, 'chip-warn'));
  onMissingIssueChip(info, meta);

  setInlineError($('#readerError'), state.chapterError || '');
  if (text !== null && text.trim() !== '') {
    body.hidden = false;
    empty.hidden = true;
    body.textContent = text;
  } else {
    body.hidden = true;
    empty.hidden = false;
    if (state.loading.chapter) empty.textContent = '加载中…';
    else empty.textContent = '暂无数据 —— 该章还没有正文';
  }
}

function onMissingIssueChip(info, meta) {
  if (!info) return;
  const issues = info.issues;
  if (!Array.isArray(issues) || issues.length === 0) return;
  const text = formatIssues(issues);
  meta.append(
    el('span', {
      class: 'chip chip-bad',
      title: text,
      text: `问题 ${issues.length} 项`,
    })
  );
}

/* ------------------------------------------------------------------ 渲染：文体质量 */

const LINT_LABELS = {
  avg_sent: '平均句长（字）',
  short6: '短句占比（≤6 字）',
  g4_dup: '4-gram 重复率',
  para_len: '平均段长（字）',
  dialogue: '对白占比',
  dialogue_ratio: '对白占比',
  cliche: '套话密度（处/千字）',
  emotion: '情绪直说密度（处/千字）',
  parallel: '套式排比密度（处/千字）',
  punct_kinds: '标点种类数',
  ai_score: 'AI 味评分',
};

const RATIO_LINT_KEYS = new Set([
  'short6',
  'g4_dup',
  'dialogue',
  'dialogue_ratio',
  'emotion_ratio',
  'cliche_ratio',
  'ratio',
]);

function looksLikeRatio(key, low, high) {
  if (RATIO_LINT_KEYS.has(key)) return true;
  const numbers = [low, high].filter((value) => numOrNull(value) !== null);
  if (numbers.length === 0) return false;
  if (/sent|len|count|kind|score/i.test(key)) return false;
  return numbers.every((value) => Math.abs(value) <= 1.5);
}

function findCurrentMetric(manifest, key) {
  if (!manifest) return null;
  const containers = [manifest.lint_values, manifest.lint_current, manifest.lint, manifest.metrics];
  for (const container of containers) {
    if (container && typeof container === 'object') {
      const value = numOrNull(container[key]);
      if (value !== null) return value;
    }
  }
  return null;
}

function renderQuality() {
  const manifest = state.manifest;
  setInlineError(
    $('#qualityError'),
    !manifest && state.manifestError && state.current ? `数据加载失败：${state.manifestError}` : ''
  );
  renderQualityTiles(manifest);
  renderLintBars(manifest);
  renderFixTable(manifest);
  const updated = manifest && manifest.updated ? String(manifest.updated) : '';
  const label = $('#qualityUpdated');
  if (label) {
    if (!state.current) label.textContent = '未选择项目';
    else if (updated) label.textContent = `manifest 更新：${updated}`;
    else label.textContent = '暂无 manifest（运行流水线后生成）';
  }
}

function renderQualityTiles(manifest) {
  const box = $('#qualityTiles');
  if (!box) return;
  box.replaceChildren();
  const stats = manifest && typeof manifest.stats === 'object' && manifest.stats ? manifest.stats : {};
  const target = manifest && Array.isArray(manifest.target_words) ? manifest.target_words : null;
  const total = manifest ? numOrNull(manifest.total) : null;
  const written = manifest ? numOrNull(manifest.written) : null;
  const targetHint =
    target && target.length >= 2 && numOrNull(target[0]) !== null && numOrNull(target[1]) !== null
      ? `目标 ${fmtInt(target[0])}~${fmtInt(target[1])} 字`
      : '';

  const tiles = [
    {
      label: '已写 / 总章数',
      value: `${written === null ? '—' : fmtInt(written)} / ${total === null ? '—' : fmtInt(total)}`,
      hint: '',
    },
    {
      label: '平均字数',
      value: numOrNull(stats.avg_chars) === null ? '—' : fmtInt(stats.avg_chars),
      hint: targetHint,
    },
    {
      label: '平均文体评分',
      value: numOrNull(stats.avg_score) === null ? '—' : fmtNum(stats.avg_score, 1),
      hint: '满分 100',
      cls: scoreClass(stats.avg_score),
    },
    {
      label: '低于目标字数',
      value: numOrNull(stats.below_target) === null ? '—' : fmtInt(stats.below_target),
      hint: '章',
      cls: (numOrNull(stats.below_target) || 0) > 0 ? 'text-warn' : '',
    },
    {
      label: '错误数',
      value: numOrNull(stats.errors) === null ? '—' : fmtInt(stats.errors),
      hint: '运行期 errors',
      cls: (numOrNull(stats.errors) || 0) > 0 ? 'text-bad' : '',
    },
  ];

  for (const tile of tiles) {
    const node = el('div', { class: `tile${tile.cls ? ` ${tile.cls}` : ''}` });
    node.append(
      el('div', { class: 'tile-label', text: tile.label }),
      el('div', { class: 'tile-value', text: String(tile.value) }),
      el('div', { class: 'tile-hint muted small', text: tile.hint || '' })
    );
    box.append(node);
  }
}

function renderLintBars(manifest) {
  const box = $('#lintBars');
  const empty = $('#lintEmpty');
  if (!box) return;
  box.replaceChildren();
  const targets =
    manifest && manifest.lint_targets && typeof manifest.lint_targets === 'object'
      ? manifest.lint_targets
      : null;
  const entries = targets ? Object.entries(targets) : [];
  let drawn = 0;

  for (const [key, range] of entries) {
    if (!Array.isArray(range)) continue;
    const low = numOrNull(range[0]);
    const high = numOrNull(range[1]);
    if (low === null && high === null) continue;
    const ratio = looksLikeRatio(key, low, high);
    const scaleMax = high !== null ? high * 1.25 : low * 1.6;
    const max = Math.max(1e-9, scaleMax || 1);
    const left = low !== null ? Math.max(0, Math.min(100, (low / max) * 100)) : 0;
    const right = high !== null ? Math.max(0, Math.min(100, (high / max) * 100)) : 100;
    const width = Math.max(0.5, right - left);
    const current = findCurrentMetric(manifest, key);
    const inRange =
      current !== null && (low === null || current >= low) && (high === null || current <= high);

    const rangeText =
      low !== null && high !== null
        ? `${fmtMetric(low, ratio)} ~ ${fmtMetric(high, ratio)}`
        : low !== null
        ? `≥ ${fmtMetric(low, ratio)}`
        : `≤ ${fmtMetric(high, ratio)}`;

    const label = el(
      'div',
      { class: 'bar-label' },
      el('span', { class: 'bar-name', text: LINT_LABELS[key] || key }),
      el('span', { class: 'bar-range mono', text: `目标 ${rangeText}` })
    );

    const track = el('div', { class: 'bar-track' });
    track.append(el('div', { class: 'bar-band', style: { left: `${left}%`, width: `${width}%` } }));
    if (current !== null) {
      const currentPercent = Math.max(0, Math.min(100, (current / max) * 100));
      track.append(
        el('div', {
          class: `bar-marker ${inRange ? 'is-ok' : 'is-bad'}`,
          style: { left: `${currentPercent}%` },
          title: `当前值 ${fmtMetric(current, ratio)}`,
        })
      );
    }

    const currentCell = el('div', {
      class: `bar-current mono${current === null ? '' : inRange ? ' is-ok' : ' is-bad'}`,
      title: current === null ? 'manifest 未提供当前值（可选字段 lint_values）' : '',
      text: current === null ? '—' : fmtMetric(current, ratio),
    });

    box.append(el('div', { class: 'bar-row' }, label, track, currentCell));
    drawn += 1;
  }

  if (empty) {
    empty.hidden = drawn > 0;
    if (drawn === 0) empty.textContent = '暂无数据 —— manifest.lint_targets 为空或缺失';
  }
}

function renderFixTable(manifest) {
  const tbody = $('#fixTableBody');
  const empty = $('#fixEmpty');
  if (!tbody) return;
  tbody.replaceChildren();
  const chapters = manifest && Array.isArray(manifest.chapters) ? manifest.chapters : [];
  const scored = chapters
    .filter((item) => item && typeof item === 'object' && numOrNull(item.score) !== null)
    .sort((a, b) => numOrNull(a.score) - numOrNull(b.score))
    .slice(0, 20);
  if (scored.length === 0) {
    if (empty) {
      empty.hidden = false;
      empty.textContent =
        chapters.length > 0
          ? '暂无数据 —— 章节还没有文体评分（score 字段）'
          : '暂无数据 —— manifest.chapters 为空';
    }
    return;
  }
  if (empty) empty.hidden = true;
  const targetMin =
    manifest && Array.isArray(manifest.target_words) ? numOrNull(manifest.target_words[0]) : null;

  for (const chapter of scored) {
    const number = numOrNull(chapter.no);
    const chars = numOrNull(chapter.chars);
    const score = numOrNull(chapter.score);
    const retries = numOrNull(chapter.retries);
    const issuesText = formatIssues(chapter.issues);
    const row = el('tr');
    row.append(
      el('td', { class: 'mono', text: number === null ? '—' : String(Math.trunc(number)) }),
      el('td', {
        class: `mono${targetMin !== null && chars !== null && chars < targetMin ? ' text-warn' : ''}`,
        text: chars === null ? '—' : fmtInt(chars),
      }),
      el('td', {}, el('span', { class: `score ${scoreClass(score)}`, text: score === null ? '—' : fmtNum(score, 1) })),
      el('td', { class: 'mono muted', text: retries === null ? '—' : fmtInt(retries) }),
      el('td', { class: 'issues' }, el('span', { title: issuesText, text: issuesText || '—' })),
      el(
        'td',
        { class: 'col-act' },
        el('button', {
          class: 'btn btn-xs',
          type: 'button',
          text: '阅读',
          onclick: () => openChapter(number),
        })
      )
    );
    tbody.append(row);
  }
}

/* ------------------------------------------------------------------ 渲染：日志 */

function renderLogs() {
  const pre = $('#logBody');
  const empty = $('#logsEmpty');
  const meta = $('#logsMeta');
  if (!pre) return;
  const lines = Array.isArray(state.logLines) ? state.logLines : [];
  const nearBottom = pre.scrollHeight - pre.clientHeight - pre.scrollTop < 48;
  pre.textContent = lines.join('\n');
  pre.hidden = lines.length === 0;
  if (empty) {
    empty.hidden = lines.length > 0;
    empty.textContent = state.current
      ? `暂无数据 —— 运行开始后日志会追加到 out/${state.current}/run.log`
      : '暂无数据 —— 请先选择一个项目';
  }
  if (meta) {
    meta.textContent = state.current
      ? `项目 ${state.current} · 末尾 ${lines.length} 行 · 刷新于 ${fmtClock(
          state.lastRefresh.logs
        )}${state.logPaused ? ' · 已暂停' : ''}`
      : '未选择项目';
  }
  if (nearBottom) pre.scrollTop = pre.scrollHeight;
}

/* ------------------------------------------------------------------ 顶栏 / 页脚 */

function updateStatusPill() {
  const pill = $('#statusPill');
  if (!pill) return;
  pill.className = 'pill';
  if (!state.current) {
    pill.textContent = '无项目';
    pill.classList.add('pill-idle');
    return;
  }
  const manifest = state.manifest;
  if (manifest && manifest.running && typeof manifest.running === 'object') {
    const running = manifest.running;
    const parts = ['运行中'];
    if (running.phase) parts.push(String(running.phase));
    const pid = numOrNull(running.pid);
    if (pid !== null) parts.push(`pid ${pid}`);
    pill.textContent = parts.join(' · ');
    pill.classList.add('pill-run');
    return;
  }
  const written =
    manifest && numOrNull(manifest.written) !== null
      ? numOrNull(manifest.written)
      : numOrNull(currentProject() && currentProject().written) || 0;
  const total =
    manifest && numOrNull(manifest.total) !== null
      ? numOrNull(manifest.total)
      : projectTotal();
  pill.textContent = `空闲 · 已写 ${fmtInt(written)}${total === null ? '' : ` / ${fmtInt(total)}`}`;
  pill.classList.add('pill-idle');
}

function updateFooter() {
  const node = $('#footerInfo');
  if (!node) return;
  const project = currentProject();
  const parts = [];
  if (project) parts.push(`项目 ${project.title || project.name}（${project.name}）`);
  else if (state.current) parts.push(`项目 ${state.current}（仅 out/ 产物，无 toml）`);
  else parts.push('暂无项目');
  if (state.current) {
    parts.push(
      state.manifest && state.manifest.updated ? `manifest 更新 ${state.manifest.updated}` : '无 manifest'
    );
    parts.push(`out/${state.current}/`);
  }
  node.textContent = parts.join(' · ');
}

function updateClock() {
  const node = $('#metaClock');
  if (!node) return;
  try {
    node.textContent = new Date().toLocaleString('zh-CN', { hour12: false });
  } catch (err) {
    node.textContent = '—';
  }
}

/* ------------------------------------------------------------------ 视图切换 / 轮询 */

function applyView(name) {
  const views = ['projects', 'reader', 'quality', 'logs'];
  const target = views.includes(name) ? name : 'projects';
  state.view = target;
  savePref('view', target);
  try {
    const suffix = `#${target}`;
    if (window.location.hash !== suffix) {
      window.history.replaceState(
        null,
        '',
        `${window.location.pathname}${window.location.search}${suffix}`
      );
    }
  } catch (err) {
    /* file:// 等环境不支持 history 时忽略 */
  }
  $$('.tab').forEach((tab) => tab.classList.toggle('is-active', tab.dataset.view === target));
  $$('.view').forEach((view) => view.classList.toggle('is-active', view.id === `view-${target}`));
  renderForCurrentView();
  if (target === 'logs') refreshLogs();
  else if (target === 'reader' && state.current && !state.chapterData) loadChapter(state.chapter);
  else if (target === 'quality' && state.current && !state.manifest) refreshManifest(state.current, { silent: true });
}

function renderForCurrentView() {
  if (state.view === 'projects') renderProjects();
  else if (state.view === 'reader') renderReader();
  else if (state.view === 'quality') renderQuality();
  else if (state.view === 'logs') renderLogs();
  updateStatusPill();
  updateFooter();
}

async function pollTick() {
  if (document.hidden || state.polling) return;
  state.polling = true;
  try {
    if (state.view === 'projects') {
      await refreshProjects();
    } else if (state.view === 'logs' && !state.logPaused) {
      await refreshLogs();
    }
    if (state.current) await refreshManifest(state.current, { silent: true });
  } catch (err) {
    reportError(err, 'poll');
  } finally {
    state.polling = false;
  }
}

/* ------------------------------------------------------------------ 事件绑定 / 启动 */

function bindUi() {
  $$('.tab').forEach((tab) => tab.addEventListener('click', () => applyView(tab.dataset.view)));
  window.addEventListener('hashchange', () => {
    const view = (window.location.hash || '').replace(/^#/, '');
    if (['projects', 'reader', 'quality', 'logs'].includes(view) && view !== state.view) {
      applyView(view);
    }
  });
  $('#projectSelect').addEventListener('change', onProjectChange);
  $('#btnReloadProjects').addEventListener('click', () => refreshProjects());

  $('#btnPrevChapter').addEventListener('click', () => loadChapter((state.chapter || 1) - 1));
  $('#btnNextChapter').addEventListener('click', () => loadChapter((state.chapter || 1) + 1));
  $('#btnGoChapter').addEventListener('click', () => loadChapter(Number($('#chapterInput').value)));
  $('#chapterInput').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      loadChapter(Number($('#chapterInput').value));
    }
  });
  $('#btnLatestChapter').addEventListener('click', () => {
    const project = currentProject();
    const written = Math.max(1, numOrNull(project && project.written) || 1);
    loadChapter(written);
  });

  $('#logTail').addEventListener('change', () => refreshLogs());
  $('#logPause').addEventListener('change', (event) => {
    state.logPaused = Boolean(event.target.checked);
    if (!state.logPaused) refreshLogs();
    else renderLogs();
  });
  $('#btnReloadLog').addEventListener('click', () => refreshLogs());

  $$('#runModal [data-close]').forEach((node) => node.addEventListener('click', closeRunModal));
  $('#btnRunConfirm').addEventListener('click', confirmRun);
  $('#runFrom').addEventListener('input', updateRunPreview);
  $('#runTo').addEventListener('input', updateRunPreview);
  $('#runFrom').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') confirmRun();
  });
  $('#runTo').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') confirmRun();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !$('#runModal').hidden) closeRunModal();
  });
}

async function init() {
  bindUi();
  updateClock();
  window.setInterval(updateClock, 1000);
  window.setInterval(pollTick, POLL_MS);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) pollTick();
  });

  const params = new URLSearchParams(window.location.search);
  const urlProject = (params.get('project') || '').trim();
  if (/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(urlProject)) {
    state.current = urlProject;
    state.pinnedProject = urlProject;
  }
  const hashView = (window.location.hash || '').replace(/^#/, '');
  if (['projects', 'reader', 'quality', 'logs'].includes(hashView)) {
    state.view = hashView;
  } else {
    const savedView = loadPref('view');
    if (['projects', 'reader', 'quality', 'logs'].includes(savedView)) state.view = savedView;
  }
  const savedChapter = Number(loadPref('chapter'));
  if (Number.isInteger(savedChapter) && savedChapter > 0) state.chapter = savedChapter;

  try {
    await refreshProjects();
  } catch (err) {
    reportError(err, 'init');
  }

  if (state.current) {
    try {
      await refreshManifest(state.current, { silent: true });
    } catch (err) {
      reportError(err, 'init-manifest');
    }
  }

  applyView(state.view);
  renderReader();
  updateStatusPill();
  updateFooter();
}

init().catch((err) => {
  toast(`控制台初始化失败：${(err && err.message) || err}`, 'error', 15000);
});
