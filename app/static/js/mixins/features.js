/**
 * features.js — Feature interaction mixin for Alpine.js store.
 *
 * Handles feature selection, running, follow-up Q&A, output rendering, and templates.
 *
 * Depends on:
 *   - feature-constants.js  (FEATURE_LABELS, DIAGRAM_FEATURES)
 *   - feature-templates.js  (PROMPT_TEMPLATES)
 *   - lib/streaming.js       (openStream, iterateSSE)
 *   - lib/markdown.js        (parseMarkdown, applyHighlighting)
 *   - lib/mermaid-render.js  (tryRenderMermaid)
 */

/* eslint-disable no-undef */

function featuresMixin() {
  return {
    // ── Feature state ───────────────────────────────────────────────────
    features: {
      playground:     { status: 'idle', params: { prompt: '' } },
    },
    
    enabledSkills: [],

    activeFeature: null,
    generateDiagram: false,
    inheritGithubEnv: false,
    cardsVisible: true,
    focusMode: false,
    showTemplates: null,
    templateModalFeature: null,

    // Output panel
    outputVisible: false,
    outputTitle: '',
    outputView: 'rendered',
    rawContent: '',
    renderedMarkdown: '',
    toolActivity: '',
    activeToolCalls: [],     // tracks tools currently running (name → shown in header)

    // Thinking panel
    thinkingSteps: [],
    thinkingOpen: false,

    // Model reasoning (extended thinking)
    reasoningContent: '',
    reasoningOpen: false,

    // Follow-up Q&A
    currentSessionId: null,
    chatHistory: [],
    initialPrompt: '',
    followupQuery: '',
    followupLoading: false,

    // ── Feature selection ───────────────────────────────────────────────
    selectFeature(id) {
      if (this.activeFeature === id) {
        this.activeFeature = null;
        this.focusMode = false;
      } else {
        this.activeFeature = id;
        this.focusMode = true;
      }
      this.showTemplates = null;
    },

    exitFocus() {
      this.activeFeature = null;
      this.focusMode = false;
      this.showTemplates = null;
    },

    // ── Template helpers ────────────────────────────────────────────────
    toggleTemplates(featureId, $event) {
      $event.stopPropagation();
      this.showTemplates = this.showTemplates === featureId ? null : featureId;
    },

    openTemplateModal(featureId, $event) {
      if ($event) $event.stopPropagation();
      this.templateModalFeature = featureId;
      this.showTemplates = null;
    },

    closeTemplateModal() {
      this.templateModalFeature = null;
    },

    useTemplateFromModal(featureId, tpl) {
      const feat = this.features[featureId];
      if (!feat) return;
      const paramKey = 'prompt';
      feat.params[paramKey] = tpl.text;
      if (tpl.diagram) this.generateDiagram = true;
      if (tpl.model) this.selectedModel = tpl.model;
      this.templateModalFeature = null;
      this.activeFeature = featureId;
      this.focusMode = true;
    },

    usePromptTemplate(featureId, tpl, $event) {
      $event.stopPropagation();
      const feat = this.features[featureId];
      if (!feat) return;
      const paramKey = featureId === 'playground' ? 'prompt' : 'query';
      feat.params[paramKey] = tpl.text;
      if (tpl.service && feat.params.service !== undefined) feat.params.service = tpl.service;
      if (tpl.diagram) this.generateDiagram = true;
      if (tpl.model) this.selectedModel = tpl.model;
      this.showTemplates = null;
      this.activeFeature = featureId;
      this.focusMode = true;
    },

    // ── Run a feature ───────────────────────────────────────────────────
    async runFeature(featureId) {
      if (!this.isConnected()) return;
      const feat = this.features[featureId];
      if (!feat || feat.status === 'loading') return;

      feat.status = 'loading';
      this.rawContent = '';
      this.renderedMarkdown = '';
      this.toolActivity = '';
      this.activeToolCalls = [];
      this.outputTitle = FEATURE_LABELS[featureId] || featureId;
      this.outputView = 'rendered';
      this.outputVisible = true;
      this.currentSessionId = null;
      this.chatHistory = [];
      this.initialPrompt = (featureId === 'playground' ? feat.params.prompt : feat.params.query) || '';
      this.thinkingSteps = [];
      this.thinkingOpen = false;
      this.reasoningContent = '';
      this.reasoningOpen = false;

      const wantDiagram = this.generateDiagram && DIAGRAM_FEATURES.has(featureId);

      try {
        await this._streamFeature('api/run', {
          provider: this.aiProvider || 'copilot',
          feature: featureId,
          params: feat.params,
          model: this.selectedModel,
          generate_diagram: wantDiagram,
          gh_cli_hostname: (this.ghCliHostname || '').trim(),
          gh_cli_token: (this.ghCliToken || '').trim(),
          reasoning_effort: this.selectedReasoningEffort || '',
          claude_auth_method: this.claudeAuthMethod,
          claude_bedrock_region: this.claudeBedrockRegion,
          claude_vertex_project: this.claudeVertexProject,
          claude_vertex_region: this.claudeVertexRegion,
          claude_base_url: this.claudeBaseUrl,
          copilot_byok_type: this.copilotByokType,
          copilot_byok_base_url: this.copilotByokBaseUrl,
          copilot_byok_wire_api: this.copilotByokWireApi,
          copilot_byok_api_key: this.copilotByokApiKey,
          codex_api_key: this.codexApiKey,
          codex_auth_method: this.codexAuthMethod,
          codex_bedrock_region: this.codexBedrockRegion,
          codex_ollama_base_url: this.codexOllamaBaseUrl,
          enabled_skills: this.enabledSkills,
          inherit_github_env: this.inheritGithubEnv,
          app_session_key: window.APP_SESSION_KEY,
          session_id: this.currentSessionId,
        });
        console.log(`[Harness Playground] Feature "${featureId}" completed. session=${this.currentSessionId}`);
        feat.status = 'done';
      } catch (err) {
        console.error(`[Harness Playground] Feature "${featureId}" failed:`, err);
        feat.status = 'error';
        this._appendRaw('\n\n⚠️ Error: ' + err.message);
        this._renderMarkdown();
      }
    },

    _buildEncryptedPayload(body) {
      let payload = body;
      let token = this.getActiveToken();
      
      if (this.encryptNetworkPayload) {
        payload = { ...body, __auth_token: token };
        const jsonStr = JSON.stringify(payload);
        
        const keyBytes = new TextEncoder().encode(window.APP_SESSION_KEY || '');
        const textBytes = new TextEncoder().encode(jsonStr);
        let binStr = "";
        if (keyBytes.length > 0) {
          for (let i = 0; i < textBytes.length; i++) {
            binStr += String.fromCharCode(textBytes[i] ^ keyBytes[i % keyBytes.length]);
          }
        } else {
          for (let i = 0; i < textBytes.length; i++) {
            binStr += String.fromCharCode(textBytes[i]);
          }
        }
        payload = { encrypted_payload: btoa(binStr) };
        token = "ENCRYPTED";
      }
      return { payload, token };
    },

    // ── Follow-up Q&A ──────────────────────────────────────────────────
    async askFollowup() {
      const query = this.followupQuery.trim();
      if (!query || this.followupLoading || !this.currentSessionId) return;

      this.followupLoading = true;
      this.chatHistory.push({ role: 'user', content: query });
      this.followupQuery = '';
      this._scrollChat();
      this.thinkingSteps.push({ content: query, separator: true });

      let assistantContent = '';

      try {
        const { payload, token } = this._buildEncryptedPayload({
          provider: this.aiProvider || 'copilot',
          session_id: this.currentSessionId,
          app_session_key: window.APP_SESSION_KEY,
          query: query,
          model: this.selectedModel,
          gh_cli_hostname: (this.ghCliHostname || '').trim(),
          gh_cli_token: (this.ghCliToken || '').trim(),
          reasoning_effort: this.selectedReasoningEffort || '',
          claude_auth_method: this.claudeAuthMethod,
          claude_bedrock_region: this.claudeBedrockRegion,
          claude_vertex_project: this.claudeVertexProject,
          claude_vertex_region: this.claudeVertexRegion,
          claude_base_url: this.claudeBaseUrl,
          copilot_byok_type: this.copilotByokType,
          copilot_byok_base_url: this.copilotByokBaseUrl,
          copilot_byok_wire_api: this.copilotByokWireApi,
          copilot_byok_api_key: this.copilotByokApiKey,
          codex_api_key: this.codexApiKey,
          codex_auth_method: this.codexAuthMethod,
          codex_bedrock_region: this.codexBedrockRegion,
          codex_ollama_base_url: this.codexOllamaBaseUrl,
          enabled_skills: this.enabledSkills,
          inherit_github_env: this.inheritGithubEnv,
        });

        const reader = await openStream('api/followup', payload, token);

        for await (const event of iterateSSE(reader)) {
          if (event.type === 'delta') {
            assistantContent += event.content || '';
          } else if (event.type === 'message') {
            assistantContent = event.content || assistantContent;
            if (event.content) this.thinkingSteps.push({ content: event.content });
          } else if (event.type === 'reasoning' || event.type === 'reasoning_delta') {
            const chunk = event.content || '';
            if (chunk) {
              this.reasoningContent += chunk;
              if (!this.reasoningOpen) this.reasoningOpen = true;
            }
          } else if (event.type === 'tool_start') {
            this._toolStart(event.name, event.tool_id || '');
          } else if (event.type === 'tool_end') {
            this._toolEnd(event.name, event.tool_id || '');
          } else if (event.type === 'error') {
            assistantContent += '\n\n⚠️ ' + event.message;
            break;
          } else if (event.type === 'done') {
            break;
          }
        }
      } catch (err) {
        assistantContent = '⚠️ ' + err.message;
      } finally {
        this.followupLoading = false;
        this.toolActivity = '';
        if (assistantContent) {
          this.chatHistory.push({ role: 'assistant', content: assistantContent });
          await this._renderInlineMermaid('chatHistory');
        }
        this._scrollChat();
      }
    },

    // ── Core streaming ─────────────────────────────────────────────────
    async _streamFeature(endpoint, body) {
      const { payload, token } = this._buildEncryptedPayload(body);
      const reader = await openStream(endpoint, payload, token);

      try {
        for await (const event of iterateSSE(reader)) {
          if (event.type === 'delta') {
            this._appendRaw(event.content || '');
            this._renderMarkdown();
            this._scrollOutput();
          } else if (event.type === 'message') {
            this.rawContent = event.content || this.rawContent;
            this._renderMarkdown();
            this._scrollOutput();
            if (event.content) this.thinkingSteps.push({ content: event.content });
          } else if (event.type === 'reasoning' || event.type === 'reasoning_delta') {
            const chunk = event.content || '';
            if (chunk) {
              this.reasoningContent += chunk;
              if (!this.reasoningOpen) this.reasoningOpen = true;
            }
          } else if (event.type === 'tool_start') {
            this._toolStart(event.name, event.tool_id || '');
          } else if (event.type === 'tool_end') {
            this._toolEnd(event.name, event.tool_id || '');
          } else if (event.type === 'done') {
            this.currentSessionId = event.session_id || null;
            this._clearAllTools();
            break;
          } else if (event.type === 'error') {
            this._appendRaw('\n\n⚠️ ' + event.message);
            this._renderMarkdown();
            this._clearAllTools();
            throw new Error(event.message);
          }
        }
      } finally {
        // Always clear tool spinners when stream ends, even if done/error was missed
        this._clearAllTools();
      }

      await this._renderInlineMermaid('renderedOutput');
    },

    // ── Tool tracking helpers ──────────────────────────────────────────
    _toolStart(name, toolId) {
      // Add to active tools list (record start time for minimum display duration)
      this.activeToolCalls = [...this.activeToolCalls, { name, id: toolId || name, _startedAt: Date.now() }];
      // Update the single toolActivity text (used in follow-up chat bubble)
      this.toolActivity = `Using ${name}…`;
      // Add a step to the thinking panel — store toolId for reliable matching on tool_end
      this.thinkingSteps.push({ content: `🔧 Using tool: ${name}`, toolName: name, toolId: toolId || null, toolActive: true });
    },

    _toolEnd(name, toolId) {
      // Always match by tool_id when available (name may be "None" in tool_end events)
      const resolvedName = (name && name !== 'None' && name !== 'null') ? name : null;
      const MIN_DISPLAY_MS = 600;

      const _commitRemoval = (idToRemove, nameToRemove) => {
        if (idToRemove) {
          this.activeToolCalls = this.activeToolCalls.filter(t => t.id !== idToRemove);
        } else if (nameToRemove) {
          const idx = this.activeToolCalls.findIndex(t => t.name === nameToRemove);
          if (idx !== -1) this.activeToolCalls = this.activeToolCalls.filter((_, i) => i !== idx);
        }
        if (this.activeToolCalls.length === 0) {
          this.toolActivity = '';
        } else {
          this.toolActivity = `Using ${this.activeToolCalls[this.activeToolCalls.length - 1].name}…`;
        }
      };

      if (toolId) {
        const match = this.activeToolCalls.find(t => t.id === toolId);
        // Mark thinking step done immediately (checkmark appears right away)
        for (let i = this.thinkingSteps.length - 1; i >= 0; i--) {
          if (this.thinkingSteps[i].toolId === toolId && this.thinkingSteps[i].toolActive) {
            this.thinkingSteps[i] = { ...this.thinkingSteps[i], toolActive: false, toolDone: true };
            break;
          }
        }
        // Keep the flash badge visible for at least MIN_DISPLAY_MS
        const entry = this.activeToolCalls.find(t => t.id === toolId);
        const elapsed = entry?._startedAt ? (Date.now() - entry._startedAt) : MIN_DISPLAY_MS;
        const delay = Math.max(0, MIN_DISPLAY_MS - elapsed);
        setTimeout(() => _commitRemoval(toolId, null), delay);
      } else if (resolvedName) {
        for (let i = this.thinkingSteps.length - 1; i >= 0; i--) {
          if (this.thinkingSteps[i].toolName === resolvedName && this.thinkingSteps[i].toolActive) {
            this.thinkingSteps[i] = { ...this.thinkingSteps[i], toolActive: false, toolDone: true };
            break;
          }
        }
        const entry = this.activeToolCalls.find(t => t.name === resolvedName);
        const elapsed = entry?._startedAt ? (Date.now() - entry._startedAt) : MIN_DISPLAY_MS;
        const delay = Math.max(0, MIN_DISPLAY_MS - elapsed);
        setTimeout(() => _commitRemoval(null, resolvedName), delay);
      }
    },

    _clearAllTools() {
      this.activeToolCalls = [];
      this.toolActivity = '';
      for (let i = 0; i < this.thinkingSteps.length; i++) {
        if (this.thinkingSteps[i].toolActive) {
          this.thinkingSteps[i] = { ...this.thinkingSteps[i], toolActive: false, toolDone: true };
        }
      }
    },

    // ── Inline Mermaid rendering ───────────────────────────────────────
    async _renderInlineMermaid(refName) {
      await this.$nextTick();
      const container = this.$refs[refName];
      if (!container) return;
      const codeBlocks = container.querySelectorAll('pre code.language-mermaid');
      for (const block of codeBlocks) {
        const code = block.textContent.trim();
        if (!code) continue;
        const result = await tryRenderMermaid(code);
        if (result && result.ok) {
          const wrapper = document.createElement('div');
          wrapper.className = 'mermaid-diagram my-4 p-4 bg-surface-900/40 rounded-lg overflow-x-auto [&_svg]:max-w-full [&_svg]:h-auto [&_svg]:mx-auto relative group';
          wrapper.innerHTML = result.svg;

          const tray = document.createElement('div');
          tray.className = 'absolute top-2 right-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity';

          const copyBtn = document.createElement('button');
          copyBtn.className = 'p-1.5 rounded bg-surface-700/80 hover:bg-surface-600 text-slate-400 hover:text-slate-200 transition-colors';
          copyBtn.title = 'Copy Mermaid source';
          copyBtn.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3"/></svg>';
          copyBtn.addEventListener('click', () => {
            navigator.clipboard.writeText(code).then(() => {
              const orig = copyBtn.innerHTML;
              copyBtn.innerHTML = '<svg class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>';
              setTimeout(() => { copyBtn.innerHTML = orig; }, 1500);
            });
          });

          const dlBtn = document.createElement('button');
          dlBtn.className = 'p-1.5 rounded bg-surface-700/80 hover:bg-surface-600 text-slate-400 hover:text-slate-200 transition-colors';
          dlBtn.title = 'Download as SVG';
          dlBtn.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>';
          dlBtn.addEventListener('click', () => {
            const svgEl = wrapper.querySelector('svg');
            if (!svgEl) return;
            const svgData = new XMLSerializer().serializeToString(svgEl);
            const blob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'diagram.svg';
            a.click();
            URL.revokeObjectURL(url);
          });

          tray.appendChild(copyBtn);
          tray.appendChild(dlBtn);
          wrapper.appendChild(tray);
          block.parentElement.replaceWith(wrapper);
        }
      }
    },

    // ── UI helpers ──────────────────────────────────────────────────────
    _appendRaw(text) {
      this.rawContent += text;
    },

    _renderMarkdown() {
      this.renderedMarkdown = parseMarkdown(this.rawContent);
      this.$nextTick(() => {
        const el = this.$refs.renderedOutput;
        if (el) applyHighlighting(el);
      });
    },

    _scrollOutput() {
      this.$nextTick(() => {
        const el = this.outputView === 'rendered' ? this.$refs.renderedOutput : this.$refs.rawOutput;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },

    _scrollChat() {
      this.$nextTick(() => {
        const el = this.$refs.chatHistory;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },

    closeOutput() {
      this.outputVisible = false;
      this.rawContent = '';
      this.renderedMarkdown = '';
      this.currentSessionId = null;
      this.chatHistory = [];
      this.initialPrompt = '';
      this.thinkingSteps = [];
      this.thinkingOpen = false;
      this.activeToolCalls = [];
      this.toolActivity = '';
      this.reasoningContent = '';
      this.reasoningOpen = false;
    },

    copyOutput() {
      if (!this.rawContent) return;
      navigator.clipboard.writeText(this.rawContent);
    },

    /** Download the current session as a Markdown file. */
    downloadChatHistory() {
      const featureLabel = this.activeFeature ? (FEATURE_LABELS[this.activeFeature] || this.activeFeature) : 'Session';
      const date = new Date().toISOString().slice(0, 10);
      const lines = [];

      lines.push(`# Agent.Playground — ${featureLabel}`);
      lines.push(`> Downloaded ${new Date().toLocaleString()}`);
      lines.push('');

      // Initial prompt
      if (this.initialPrompt) {
        lines.push('## Prompt');
        lines.push('');
        lines.push(`**You:** ${this.initialPrompt.trim()}`);
        lines.push('');
      }

      if (this.rawContent) {
        lines.push('## Response');
        lines.push('');
        lines.push(this.rawContent.trim());
        lines.push('');
      }

      if (this.chatHistory.length > 0) {
        lines.push('## Follow-up Chat');
        lines.push('');
        for (const msg of this.chatHistory) {
          if (msg.role === 'user') {
            lines.push(`**You:** ${msg.content}`);
          } else {
            lines.push(`**Agent.Playground:** ${msg.content}`);
          }
          lines.push('');
        }
      }

      const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `agent-playground-${date}.md`;
      a.click();
      URL.revokeObjectURL(url);
    },

  };
}
