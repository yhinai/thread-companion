const { Plugin, ItemView, PluginSettingTab, Setting, Modal, Notice, requestUrl } = require('obsidian');
const VIEW = 'thread-companion';
const DEFAULTS = { endpoint: 'http://127.0.0.1:47123', token: '', projectId: '' };

class ThreadPlugin extends Plugin {
  async onload() {
    this.settings = Object.assign({}, DEFAULTS, await this.loadData());
    this.registerView(VIEW, leaf => new ThreadView(leaf, this));
    this.addRibbonIcon('git-branch', 'Open Thread', () => this.open());
    for (const [id, name] of [['brief', 'Brief Codex from this note'], ['review', 'Review project work'], ['explore', 'Explore improvements'], ['build', 'Run a task with Codex']]) {
      this.addCommand({ id, name, callback: () => this.launch(id) });
    }
    this.addCommand({ id: 'open', name: 'Open companion', callback: () => this.open() });
    this.addSettingTab(new ThreadSettings(this.app, this));
  }
  async saveSettings() { await this.saveData(this.settings); }
  async api(path, data) {
    const base = new URL(this.settings.endpoint);
    if (base.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(base.hostname)) throw new Error('Use a local coordinator address.');
    const result = await requestUrl({ url: this.settings.endpoint.replace(/\/$/, '') + path,
      method: data === undefined ? 'GET' : 'POST', headers: { Authorization: `Bearer ${this.settings.token}`, 'Content-Type': 'application/json' },
      body: data === undefined ? undefined : JSON.stringify(data), throw: false });
    if (result.status >= 400) throw new Error(result.json?.error || `Coordinator error ${result.status}`);
    return result.json;
  }
  async open() {
    let leaf = this.app.workspace.getLeavesOfType(VIEW)[0];
    if (!leaf) { leaf = this.app.workspace.getRightLeaf(false); await leaf.setViewState({ type: VIEW, active: true }); }
    this.app.workspace.revealLeaf(leaf);
    return leaf.view;
  }
  async launch(mode) {
    if (!this.settings.projectId) { new Notice('Connect a project in Thread first.'); await this.open(); return; }
    const file = this.app.workspace.getActiveFile();
    const note = file?.extension === 'md' ? await this.app.vault.read(file) : '';
    new RunModal(this.app, this, mode, note, file?.path).open();
  }
}

function button(parent, label, action, cls = '') {
  const b = parent.createEl('button', { text: label, cls });
  b.addEventListener('click', async () => {
    b.disabled = true;
    try { await action(); } catch (err) { new Notice(err.message); } finally { b.disabled = false; }
  });
  return b;
}

class ThreadView extends ItemView {
  constructor(leaf, plugin) { super(leaf); this.plugin = plugin; this.busy = false; this.signature = ''; }
  getViewType() { return VIEW; }
  getDisplayText() { return 'Thread'; }
  getIcon() { return 'git-branch'; }
  async onOpen() {
    this.contentEl.addClass('thread-view');
    this.renderShell();
    await this.refresh();
    this.timer = window.setInterval(() => this.refresh(), 2500);
  }
  async onClose() { window.clearInterval(this.timer); }
  renderShell() {
    const el = this.contentEl; el.empty();
    const head = el.createDiv({ cls: 'thread-header' });
    head.createDiv({ text: 'THREAD', cls: 'thread-eyebrow' });
    head.createEl('h2', { text: 'Keep the thread.' });
    head.createEl('p', { text: 'Your intent. Connected to the work.', cls: 'thread-muted' });
    this.connection = el.createDiv({ cls: 'thread-connection', text: 'Connecting…' });
    this.projectBar = el.createDiv({ cls: 'thread-project-bar' });
    const actions = el.createDiv({ cls: 'thread-actions' });
    for (const [mode, name] of [['brief', 'Brief'], ['review', 'Review'], ['explore', 'Explore'], ['build', 'Build']]) button(actions, name, () => this.plugin.launch(mode));
    this.body = el.createDiv();
    const footer = el.createDiv({ cls: 'thread-footer' });
    button(footer, '+ Connect repository', () => new ProjectModal(this.app, this.plugin, () => { this.signature = ''; this.refresh(); }).open());
    button(footer, 'Sync notes', async () => {
      if (!this.plugin.settings.projectId) throw new Error('Connect a project first.');
      const result = await this.plugin.api(`/projects/${this.plugin.settings.projectId}/sync`, {});
      new Notice(`${result.indexed} notes indexed · ${result.changed} updated`); this.signature = ''; await this.refresh();
    });
  }
  async refresh() {
    if (this.busy) return; this.busy = true;
    try {
      const health = await this.plugin.api('/health');
      this.connection.setText(`${health.backend === 'mongodb-atlas' ? 'Atlas connected' : 'Local development store'} · ${health.codex_available ? 'Codex installed' : 'Codex unavailable'}`);
      this.connection.removeClass('thread-error');
      const projects = await this.plugin.api('/projects');
      const id = this.plugin.settings.projectId;
      const project = projects.find(p => p.id === id);
      const state = project ? await this.plugin.api(`/projects/${id}/state`) : null;
      const signature = JSON.stringify([projects, state]);
      // Preserve in-progress question text and focus when nothing has changed.
      if (this.signature === signature) return;
      if (this.body.contains(document.activeElement) && document.activeElement?.tagName === 'TEXTAREA') return;
      this.signature = signature;
      this.projectBar.empty();
      if (projects.length) {
        const select = this.projectBar.createEl('select', { attr: { 'aria-label': 'Project' } });
        select.createEl('option', { text: 'Choose a project', value: '' });
        for (const p of projects) select.createEl('option', { text: p.name, value: p.id });
        select.value = id;
        select.onchange = async () => { this.plugin.settings.projectId = select.value; await this.plugin.saveSettings(); this.signature = ''; this.refresh(); };
      }
      this.body.empty();
      if (!project) {
        const empty = this.body.createDiv({ cls: 'thread-empty' });
        empty.createEl('h3', { text: 'Begin with a project.' });
        empty.createEl('p', { text: 'Connect a repository and the notes that describe what matters. Thread will carry that intent into each agent run.' });
        return;
      }
      const goal = this.body.createDiv({ cls: 'thread-goal' });
      goal.createDiv({ text: 'WORKING TOWARD', cls: 'thread-eyebrow' });
      goal.createEl('p', { text: project.goal });
      this.renderQuestions(state.questions);
      const runs = state.runs.slice().reverse();
      this.body.createEl('h3', { text: 'Activity' });
      if (!runs.length) this.body.createEl('p', { text: 'Ready when you are. Brief prepares context without starting an agent.', cls: 'thread-muted' });
      for (const run of runs.slice(0, 12)) this.renderRun(run);
      this.renderLearning(state);
      const memories = state.memories.filter(m => ['active', 'validated'].includes(m.status));
      const details = this.body.createEl('details', { cls: 'thread-memory' });
      details.createEl('summary', { text: `${memories.length} memories · ${state.edges.filter(e => e.active).length} connections` });
      for (const m of memories) {
        const row = details.createDiv({ cls: 'thread-memory-row' });
        row.createEl('span', { text: m.kind, cls: 'thread-tag' });
        row.createEl('strong', { text: m.title });
        row.createEl('small', { text: `v${m.version} · ${m.source}` });
        row.createEl('p', { text: m.content.slice(0, 500) });
      }
    } catch (error) {
      this.connection.setText(error.message + ' Start the coordinator and check Thread settings.');
      this.connection.addClass('thread-error');
    } finally { this.busy = false; }
  }
  renderLearning(state) {
    const stale = state.memories.filter(m => m.status === 'stale');
    if (stale.length) {
      const card = this.body.createDiv({ cls: 'thread-card' });
      card.createDiv({ text: 'KNOWLEDGE CHANGED', cls: 'thread-eyebrow' });
      card.createEl('p', { text: `${stale.length} outdated procedure${stale.length === 1 ? '' : 's'} excluded from new briefs.` });
      for (const m of stale) {
        const row = card.createDiv({ cls: 'thread-memory-row' });
        row.createEl('strong', { text: m.title });
        row.createEl('small', { text: m.stale_reason || 'Revalidation required' });
        const sources = state.edges.filter(e => e.source === m.id && e.relation === 'learned_from')
          .map(e => state.memories.find(n => n.id === e.target)?.title).filter(Boolean);
        if (sources.length) row.createEl('p', { text: `Based on: ${sources.join(', ')}` });
      }
    }
    for (const evaluation of (state.evaluations || []).slice().reverse().slice(0, 2)) {
      const card = this.body.createDiv({ cls: 'thread-card' });
      card.createDiv({ text: 'TRANSFER EVIDENCE', cls: 'thread-eyebrow' });
      card.createEl('p', { text: `Comparison ${evaluation.status} · ${evaluation.adapter}` });
      card.createEl('small', { text: evaluation.fixture === 'isolated_unimplemented' ? 'Fresh repository · no prior implementation' : 'Shared corrected implementation', cls: 'thread-muted' });
      const table = card.createEl('table', { cls: 'thread-results' });
      const header = table.createEl('thead').createEl('tr');
      for (const label of ['Context', 'Passed', 'Seconds']) header.createEl('th', { text: label });
      const body = table.createEl('tbody');
      for (const [arm, label] of [['no_memory', 'No memory'], ['current_notes', 'Current notes'], ['notes_and_skill', 'Notes + learned skill']]) {
        const trials = evaluation.trials.filter(t => t.arm === arm);
        const row = body.createEl('tr');
        row.createEl('td', { text: label });
        row.createEl('td', { text: `${trials.filter(t => t.success).length}/${trials.length}` });
        row.createEl('td', { text: `${Math.round(trials.reduce((sum, t) => sum + (t.seconds || 0), 0))}` });
      }
      card.createEl('p', { text: 'Compare current notes with notes + skill. Equal results do not demonstrate a learning benefit. Small custom test; time and token use may differ.', cls: 'thread-muted' });
      if (evaluation.error) card.createEl('p', { text: evaluation.error, cls: 'thread-error' });
    }
  }
  renderQuestions(questions) {
    for (const q of questions.filter(q => q.status === 'pending')) {
      const card = this.body.createDiv({ cls: 'thread-card thread-question' });
      card.createDiv({ text: 'YOUR DIRECTION', cls: 'thread-eyebrow' });
      card.createEl('p', { text: q.question });
      card.createEl('small', { text: `Waiting on: ${q.blocks}. Independent work can continue.` });
      const input = card.createEl('textarea', { attr: { placeholder: 'Your answer…', 'aria-label': q.question } });
      button(card, 'Send answer', async () => {
        await this.plugin.api(`/questions/${q.id}/answer`, { answer: input.value });
        this.signature = ''; input.blur(); await this.refresh();
      }, 'mod-cta');
    }
  }
  renderRun(run) {
    const card = this.body.createDiv({ cls: 'thread-card' });
    const top = card.createDiv({ cls: 'thread-card-top' });
    top.createEl('span', { text: run.phase.replaceAll('_', ' '), cls: `thread-status is-${run.status}` });
    top.createEl('small', { text: `${run.continuous ? 'Continuous · ' : ''}Cycle ${run.cycle}` });
    card.createEl('h4', { text: run.task.slice(0, 160) });
    let summary = run.summary;
    if (run.mode === 'brief' && !run.brief) {
      try { const context = JSON.parse(summary); summary = `Prepared a brief from ${context.memories.length} current memories. No coding agent started.`; } catch (_) { /* Older text summaries remain readable. */ }
    }
    card.createEl('p', { text: summary.slice(0, 600), cls: 'thread-run-summary' });
    const actions = card.createDiv({ cls: 'thread-inline-actions' });
    if (run.brief) button(actions, 'Copy brief', async () => { await navigator.clipboard.writeText(run.brief); new Notice('Brief copied.'); });
    if (['queued', 'running', 'stopping'].includes(run.status)) {
      button(actions, 'Stop', () => this.plugin.api(`/runs/${run.id}/stop`, {}));
    } else if (['waiting', 'interrupted', 'failed', 'stopped', 'dead_end'].includes(run.status)) {
      button(actions, 'Resume', () => this.plugin.api(`/runs/${run.id}/resume`, {}));
    }
    button(actions, 'Evidence', async () => {
      const events = await this.plugin.api(`/runs/${run.id}/events`);
      new EvidenceModal(this.app, events).open();
    });
    button(actions, 'Open note', async () => {
      await this.app.workspace.openLinkText(`Thread/Runs/${run.id}`, '', false);
    });
  }
}

class RunModal extends Modal {
  constructor(app, plugin, mode, note, path) { super(app); Object.assign(this, { plugin, mode, note, path }); }
  onOpen() {
    this.titleEl.setText({ brief: 'Prepare a brief', review: 'Review the work', explore: 'Explore improvements', build: 'Give Codex a task' }[this.mode]);
    const task = this.contentEl.createEl('textarea', { cls: 'thread-task-input', attr: { placeholder: 'What should we work toward?', 'aria-label': 'Task' } });
    if (this.path) task.value = `Work toward the intent in ${this.path}.`;
    this.contentEl.createEl('p', { text: this.path ? `Current note: ${this.path}. Project notes are retrieved automatically.` : 'Relevant project knowledge is selected automatically.', cls: 'thread-muted' });
    let continuous = false;
    if (this.mode === 'explore') new Setting(this.contentEl).setName('Keep refining while I’m away').setDesc('Runs until you stop it, no useful improvement remains, or progress is blocked. No session cap.').addToggle(t => t.onChange(value => continuous = value));
    button(this.contentEl, this.mode === 'brief' ? 'Compile context' : 'Start', async () => {
      const runTask = task.value.trim();
      if (!runTask) throw new Error('Describe what you want to achieve.');
      await this.plugin.api(`/projects/${this.plugin.settings.projectId}/runs`, { task: runTask, mode: this.mode, continuous });
      this.close(); await this.plugin.open();
    }, 'mod-cta');
  }
  onClose() { this.contentEl.empty(); }
}

class ProjectModal extends Modal {
  constructor(app, plugin, done) { super(app); this.plugin = plugin; this.done = done; }
  onOpen() {
    this.titleEl.setText('Connect a project');
    const values = { name: '', repo: '', vault: this.app.vault.adapter.getBasePath(), notes_folder: '', goal: '', checks: '' };
    const fields = [['name', 'Project name', 'e.g. Field Notes'], ['repo', 'Repository path', '/absolute/path/to/repository'], ['notes_folder', 'Notes folder', 'Optional folder inside this vault'], ['goal', 'What are you working toward?', 'Describe the outcome and essential constraints'], ['checks', 'Verification commands', 'One JSON argument array per line, e.g. ["python3", "-m", "unittest"]']];
    for (const [key, label, placeholder] of fields) {
      const setting = new Setting(this.contentEl).setName(label);
      if (['goal', 'checks'].includes(key)) setting.addTextArea(t => t.setPlaceholder(placeholder).onChange(v => values[key] = v));
      else setting.addText(t => t.setPlaceholder(placeholder).onChange(v => values[key] = v));
    }
    this.contentEl.createEl('p', { text: 'Use an existing Git repository or the included demo. Execution starts from a clean committed state; verified improvements apply automatically when the working branch is unchanged.', cls: 'thread-muted' });
    button(this.contentEl, 'Connect', async () => {
      const checks = values.checks.split('\n').filter(s => s.trim()).map(s => JSON.parse(s));
      const project = await this.plugin.api('/projects', { ...values, checks });
      this.plugin.settings.projectId = project.id;
      await this.plugin.saveSettings(); this.close(); this.done();
    }, 'mod-cta');
  }
  onClose() { this.contentEl.empty(); }
}

class EvidenceModal extends Modal {
  constructor(app, events) { super(app); this.events = events; }
  onOpen() {
    this.titleEl.setText('Why Thread acted');
    this.modalEl.addClass('thread-evidence-modal');
    for (const event of this.events.filter(e => Array.isArray(e.checks))) {
      for (const check of event.checks) {
        let result;
        try { result = JSON.parse(check.stdout); } catch (_) { result = null; }
        if (result && Number.isInteger(result.passed) && Number.isInteger(result.total)) {
          this.contentEl.createEl('h3', { text: `${result.passed}/${result.total} acceptance checks · ${check.exit_code === 0 ? 'passed' : 'failed'}` });
        }
      }
    }
    for (const event of this.events) {
      if (event.type === 'context.compiled' && event.context) {
        this.contentEl.createEl('p', { text: `${event.context.selected.length} memories selected for this task. Outdated procedures are excluded.` });
        for (const item of event.context.selected) {
          const memory = item.memory;
          const card = this.contentEl.createDiv({ cls: 'thread-memory-row' });
          card.createEl('strong', { text: memory.title });
          card.createEl('small', { text: `${memory.kind} · v${memory.version} · ${memory.source}` });
          card.createEl('p', { text: item.reasons.join(' · ') });
        }
      }
      const section = this.contentEl.createEl('details', { cls: 'thread-evidence' });
      section.createEl('summary', { text: event.message || event.type });
      section.createEl('pre', { text: JSON.stringify(event, null, 2) });
    }
  }
}

class ThreadSettings extends PluginSettingTab {
  constructor(app, plugin) { super(app, plugin); this.plugin = plugin; }
  display() {
    const el = this.containerEl; el.empty(); el.createEl('h2', { text: 'Thread Companion' });
    new Setting(el).setName('Coordinator address').setDesc('Local background service; default port 47123.').addText(t => t.setValue(this.plugin.settings.endpoint).onChange(async v => { this.plugin.settings.endpoint = v; await this.plugin.saveSettings(); }));
    new Setting(el).setName('Coordinator token').setDesc('Copy from the token file shown when the coordinator starts. Stored in this vault’s plugin settings.').addText(t => {
      t.inputEl.type = 'password'; t.setValue(this.plugin.settings.token).onChange(async v => { this.plugin.settings.token = v.trim(); await this.plugin.saveSettings(); });
    });
    el.createEl('p', { text: 'Start with: python3 -m companion.server --state-dir /path/to/thread-state' });
    el.createEl('p', { text: 'Codex uses its existing sign-in and permission profile. Atlas credentials belong in the coordinator environment, never in your notes.' });
  }
}
module.exports = ThreadPlugin;
