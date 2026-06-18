/**
 * auth.js — Authentication mixin for Alpine.js store.
 *
 * Handles GitHub PAT, OAuth, token validation, and AWS credentials management.
 */

/* eslint-disable no-undef */

function authMixin() {
  return {
    // ── AI Provider selection ─────────────────────────────────────────
    // "copilot" | "antigravity" | "cursor" | "claude_code"
    aiProvider: 'copilot',

    // GitHub auth (for Copilot provider)
    token: '',
    connected: false,
    showSettings: false,
    authMethod: 'pat',
    oauthUser: null,
    oauthAvailable: false,

    // Copilot BYOK
    copilotByokType: '',
    copilotByokBaseUrl: '',
    copilotByokWireApi: 'responses',
    copilotByokApiKey: '',

    // Antigravity auth (Gemini API key)
    antigravityApiKey: '',
    antigravityConnected: false,
    antigravityValidation: null,

    // Cursor auth (Cursor API key)
    cursorApiKey: '',
    cursorConnected: false,
    cursorValidation: null,

    // Claude auth (Anthropic API key / Bedrock API key)
    claudeAuthMethod: 'anthropic', // 'anthropic' | 'bedrock' | 'vertex' | 'custom'
    claudeApiKey: '',
    claudeBedrockRegion: 'us-east-1',
    claudeVertexProject: '',
    claudeVertexRegion: 'us-central1',
    claudeBaseUrl: '',
    claudeConnected: false,
    claudeValidation: null,

    // Codex auth
    codexApiKey: '',
    codexAuthMethod: 'openai',
    codexBedrockRegion: 'us-east-1',
    codexOllamaBaseUrl: 'http://localhost:11434/v1',
    codexConnected: false,
    codexValidation: null,
    isValidatingCodex: false,
    codexChatgptPolling: false,
    codexChatgptAuthUrl: '',
    codexChatgptCallbackUrl: '',

    // Model
    selectedModel: 'claude-sonnet-4.6',
    selectedReasoningEffort: '',
    availableModels: [],
    modelsLoading: false,

    get currentModelSupportsReasoning() {
      const m = this.availableModels.find(x => x.id === this.selectedModel);
      if (m) {
        return m.supports_reasoning_effort === true || (m.name && m.name.toLowerCase().includes('thinking'));
      }
      const lower = (this.selectedModel || '').toLowerCase();
      return lower.includes('thinking') || lower.includes('o1') || lower.includes('o3');
    },

    get reasoningEffortOptions() {
      const m = this.availableModels.find(x => x.id === this.selectedModel);
      if (m?.supports_reasoning_effort && Array.isArray(m.reasoning_effort_options)) {
        return m.reasoning_effort_options;
      }
      return [{label: 'Low', value: 'low'}, {label: 'Medium', value: 'medium'}, {label: 'High', value: 'high'}]; // Fallback
    },

    // Version info
    versionInfo: null,

    // GitHub CLI token
    githubExpanded: false,
    ghCliToken: '',
    ghCliHostname: 'github.com',

    // Privacy / Encryption
    encryptNetworkPayload: false,

    // Server-side config
    serverConfig: { gh_cli_configured: false },

    // Token validation state
    tokenValidation: { github: null, gh_cli: null },

    initAuth() {
      this.showSettings = false;

      // Check OAuth availability
      fetch('api/oauth/config')
        .then(r => r.ok ? r.json() : { available: false })
        .then(data => { this.oauthAvailable = !!data.available; })
        .catch(() => { this.oauthAvailable = false; });

      // Load server config
      this.loadServerConfig();

      // Load version info (no auth required)
      this.loadVersionInfo();

      // Listen for OAuth popup callback
      window.addEventListener('message', (event) => {
        if (event.origin !== window.location.origin) return;
        if (event.data && event.data.type === 'github-oauth-callback') {
          this._handleOAuthCallback(event.data);
        }
      });
    },

    onTokenChange() {
      if (this.aiProvider === 'copilot') {
        this.connected = this.token.trim().length > 10;
      }
    },

    saveToken() {
      const tok = this.token.trim();
      if (tok.length < 10) return;
      this.connected = true;
      this.showSettings = false;
      console.log('[Harness Playground] Connected. GitHub PAT in memory only.');
      this.loadModels();
    },

    clearToken() {
      this.token = '';
      this.antigravityApiKey = '';
      this.antigravityConnected = false;
      this.antigravityValidation = null;
      this.cursorApiKey = '';
      this.cursorConnected = false;
      this.cursorValidation = null;
      this.ghCliToken = '';
      this.ghCliHostname = 'github.com';
      this.connected = false;
      this.authMethod = 'pat';
      this.oauthUser = null;
      this.tokenValidation = { github: null, gh_cli: null };
      this.availableModels = [];
      this.selectedReasoningEffort = '';
      this.codexApiKey = '';
      this.codexConnected = false;
      this.codexValidation = null;
      this.codexChatgptPolling = false;
      this.codexChatgptAuthUrl = '';
    },

    async _postEncrypted(endpoint, body, authHeader = null) {
      let payload = body;
      let headers = { 'Content-Type': 'application/json' };
      if (authHeader) headers['Authorization'] = `Bearer ${authHeader}`;

      if (this.encryptNetworkPayload) {
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
        if (authHeader) headers['Authorization'] = "Bearer ENCRYPTED";
      }
      return fetch(endpoint, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      });
    },

    /** Returns true if the user is connected via any provider. */
    isConnected() {
      if (this.aiProvider === 'copilot') {
        return this.connected || this.copilotByokType !== '';
      }
      if (this.aiProvider === 'antigravity') return this.antigravityConnected;
      if (this.aiProvider === 'cursor') return this.cursorConnected;
      if (this.aiProvider === 'claude') return this.claudeConnected;
      if (this.aiProvider === 'codex') return this.codexConnected;
      return false;
    },

    /** Returns the active auth token for the current provider. */
    getActiveToken() {
      if (this.aiProvider === 'copilot') {
        return this.token || (this.copilotByokType !== '' ? this.copilotByokApiKey : '');
      }
      if (this.aiProvider === 'antigravity') return this.antigravityApiKey;
      if (this.aiProvider === 'cursor') return this.cursorApiKey;
      if (this.aiProvider === 'claude') return this.claudeApiKey;
      if (this.aiProvider === 'codex') {
        if (this.codexAuthMethod === 'ollama') return this.codexApiKey || 'dummy-ollama-token';
        if (this.codexAuthMethod === 'chatgpt') return 'chatgpt-session';
        return this.codexApiKey;
      }
      return '';
    },

    /** Switch AI provider. */
    switchProvider(newProvider) {
      this.aiProvider = newProvider;
      // Reset models when switching
      this.availableModels = [];
      this.selectedReasoningEffort = '';
      // Load models for the new provider if connected
      if (this.isConnected()) {
        this.loadModels();
      }
    },

    /** Connect with Antigravity (Gemini API key). */
    async connectAntigravity() {
      const key = this.antigravityApiKey.trim();
      if (!key) return;
      this.antigravityValidation = { loading: true };
      try {
        const resp = await this._postEncrypted('api/auth/antigravity/validate', { api_key: key });
        const data = await resp.json();
        this.antigravityValidation = { loading: false, ...data };
        if (data.valid) {
          this.antigravityConnected = true;
          this.showSettings = false;
          console.log('[Playground] Connected via Antigravity (Gemini API Key).');
          this.loadModels();
        }
      } catch (err) {
        this.antigravityValidation = { loading: false, valid: false, error: err.message };
      }
    },

    /** Connect with Cursor (Cursor API key). */
    async connectCursor() {
      const key = this.cursorApiKey.trim();
      if (!key) return;
      this.cursorValidation = { loading: true };
      try {
        const resp = await this._postEncrypted('api/auth/cursor/validate', { api_key: key });
        const data = await resp.json();
        this.cursorValidation = { loading: false, ...data };
        if (data.valid) {
          this.cursorConnected = true;
          this.showSettings = false;
          console.log('[Playground] Connected via Cursor (Cursor API Key).');
          this.loadModels();
        }
      } catch (err) {
        this.cursorValidation = { loading: false, valid: false, error: err.message };
      }
    },

    async connectCodex() {
      if (this.codexAuthMethod === 'chatgpt') {
        return this.startCodexChatgptLogin();
      }
      const key = this.codexApiKey.trim();
      if (!key && this.codexAuthMethod !== 'ollama') return;
      this.isValidatingCodex = true;
      this.codexValidation = { loading: true };
      try {
        const resp = await this._postEncrypted('api/auth/codex/validate', { 
            api_key: key,
            auth_method: this.codexAuthMethod,
            bedrock_region: this.codexBedrockRegion,
            ollama_base_url: this.codexOllamaBaseUrl
        });
        const data = await resp.json();
        this.codexValidation = { loading: false, ...data };
        if (data.valid) {
          this.codexConnected = true;
          this.showSettings = false;
          console.log('[Playground] Connected via Codex.');
          this.loadModels();
        }
      } catch (err) {
        this.codexValidation = { loading: false, valid: false, error: err.message };
      } finally {
        this.isValidatingCodex = false;
      }
    },

    disconnectCodex() {
      this.codexConnected = false;
      this.codexApiKey = '';
      this.codexValidation = null;
      this.codexChatgptPolling = false;
      this.codexChatgptAuthUrl = '';
      console.log('[Playground] Disconnected Codex API key.');
      if (this.aiProvider === 'codex') {
        this.availableModels = [];
      }
    },

    async startCodexChatgptLogin() {
      this.isValidatingCodex = true;
      this.codexValidation = { loading: true };
      try {
        const resp = await this._postEncrypted('api/auth/codex/chatgpt-login', { 
            session_id: window.APP_SESSION_KEY
        });
        const data = await resp.json();
        
        if (data.status === 'pending' && data.auth_url) {
          this.codexChatgptAuthUrl = data.auth_url;
          this.codexChatgptPolling = true;
          this.pollCodexChatgptLogin();
        } else {
          throw new Error("Failed to initialize ChatGPT login");
        }
      } catch (err) {
        this.codexValidation = { loading: false, valid: false, error: err.message };
        this.isValidatingCodex = false;
      }
    },

    async pollCodexChatgptLogin() {
      if (!this.codexChatgptPolling) return;
      
      try {
        const resp = await fetch(`api/auth/codex/chatgpt-wait/${window.APP_SESSION_KEY}`);
        if (resp.ok) {
          const data = await resp.json();
          if (data.status === 'success') {
            this.codexChatgptPolling = false;
            this.isValidatingCodex = false;
            this.codexValidation = { loading: false, valid: true, user: 'ChatGPT Subscription User' };
            this.codexConnected = true;
            this.showSettings = false;
            console.log('[Playground] Connected via Codex ChatGPT Subscription.');
            this.loadModels();
            return;
          } else if (data.status === 'failed') {
            throw new Error("Login failed or cancelled");
          }
        }
      } catch (err) {
        console.error("ChatGPT poll error:", err);
        if (!this.codexChatgptPolling) return;
        this.codexChatgptPolling = false;
        this.isValidatingCodex = false;
        this.codexValidation = { loading: false, valid: false, error: err.message };
        return;
      }
      
      // Poll again in 2 seconds
      setTimeout(() => this.pollCodexChatgptLogin(), 2000);
    },

    async submitCodexChatgptCallback() {
      if (!this.codexChatgptCallbackUrl) return;
      try {
        const resp = await this._postEncrypted('api/auth/codex/chatgpt-submit-callback', {
          callback_url: this.codexChatgptCallbackUrl
        });
        const data = await resp.json();
        if (data.valid === false) {
           alert("Error: " + data.error);
        }
        this.codexChatgptCallbackUrl = '';
      } catch (e) {
        console.error(e);
      }
    },

    /** Connect Copilot BYOK */
    connectCopilotByok() {
      // For Ollama (openai type) we allow empty API key, but we need to send some dummy token for Authorization header
      if (this.copilotByokType === 'openai' && !this.copilotByokApiKey.trim()) {
         this.copilotByokApiKey = 'dummy-ollama-token';
      }
      this.showSettings = false;
      this.loadModels();
    },

    /** Connect with Claude (Anthropic API key). */
    async connectClaude() {
      const key = this.claudeApiKey.trim();
      if (!key) return;
      this.claudeValidation = { loading: true };
      try {
        const resp = await this._postEncrypted('api/auth/claude/validate', { 
            api_key: key, 
            auth_method: this.claudeAuthMethod,
            bedrock_region: this.claudeBedrockRegion
        });
        const data = await resp.json();
        this.claudeValidation = { loading: false, ...data };
        if (data.valid) {
          this.claudeConnected = true;
          this.showSettings = false;
          console.log('[Playground] Connected via Claude (Anthropic API Key).');
          this.loadModels();
        }
      } catch (err) {
        this.claudeValidation = { loading: false, valid: false, error: err.message };
      }
    },

    disconnectClaude() {
      this.claudeConnected = false;
      this.claudeApiKey = '';
      this.claudeValidation = null;
      console.log('[Playground] Disconnected Claude API key.');
      if (this.aiProvider === 'claude') {
        this.availableModels = [];
      }
    },

    async loadServerConfig() {
      try {
        const resp = await fetch('api/server-config');
        if (resp.ok) this.serverConfig = await resp.json();
      } catch { /* defaults remain false */ }
    },

    async validateToken(type, tokenValue, url = '') {
      if (!tokenValue.trim()) return;
      this.tokenValidation = { ...this.tokenValidation, [type]: { loading: true } };
      try {
        const resp = await this._postEncrypted('api/validate-token', { type, token: tokenValue.trim(), url, hostname: this.ghCliHostname.trim(), inherit_github_env: this.inheritGithubEnv });
        const data = await resp.json();
        this.tokenValidation = { ...this.tokenValidation, [type]: { loading: false, ...data } };
      } catch (err) {
        this.tokenValidation = { ...this.tokenValidation, [type]: { loading: false, valid: false, error: err.message } };
      }
    },



    loginWithGitHub() {
      const w = 600, h = 700;
      const left = window.screenX + (window.innerWidth - w) / 2;
      const top = window.screenY + (window.innerHeight - h) / 2;
      window.open('api/oauth/login', 'github-oauth', `width=${w},height=${h},left=${left},top=${top},popup=yes`);
    },

    _handleOAuthCallback(data) {
      if (!data.access_token) return;
      this.token = data.access_token;
      this.oauthUser = data.user || null;
      this.authMethod = 'oauth';
      this.connected = true;
      this.showSettings = false;
      console.log('[Playground] Authenticated via GitHub OAuth.', this.oauthUser?.login || '');
      this.loadModels();
    },

    /** Returns true if GitHub CLI token is available (user-supplied or server-configured). */
    hasGhCli() {
      return this.ghCliToken.trim().length > 0 || this.serverConfig.gh_cli_configured;
    },



    /** Load available models from the API. Called after connecting. */
    async loadModels() {
      if (!this.isConnected()) return;
      this.modelsLoading = true;
      try {
        const activeToken = this.getActiveToken();
        const providerParam = this.aiProvider || 'copilot';
        const body = {
          provider: providerParam,
          auth_method: this.aiProvider === 'codex' ? this.codexAuthMethod : this.claudeAuthMethod,
          base_url: this.aiProvider === 'codex' ? this.codexOllamaBaseUrl : this.claudeBaseUrl,
          region: this.aiProvider === 'codex' ? this.codexBedrockRegion : this.claudeBedrockRegion,
        };
        
        if (this.aiProvider === 'copilot' && this.copilotByokType !== '') {
          body.auth_method = this.copilotByokType;
          body.base_url = this.copilotByokBaseUrl;
        }

        if (this.encryptNetworkPayload) {
          body.__auth_token = activeToken;
        }

        const resp = await this._postEncrypted('api/models', body, activeToken);
        if (resp.ok) {
          const data = await resp.json();
          this.availableModels = data.models || [];
          if (this.availableModels.length > 0) {
            const ids = this.availableModels.map(m => m.id);
            if (this.aiProvider === 'antigravity') {
              // Prefer gemini-3.5-flash for Antigravity
              const preferred = 'gemini-3.5-flash';
              if (ids.includes(preferred)) {
                this.selectedModel = preferred;
              } else {
                this.selectedModel = this.availableModels[0].id;
              }
            } else if (this.aiProvider === 'cursor') {
              // Prefer composer-2.5 for Cursor
              const preferred = 'composer-2.5';
              if (ids.includes(preferred)) {
                this.selectedModel = preferred;
              } else {
                this.selectedModel = this.availableModels[0].id;
              }
            } else if (this.aiProvider === 'claude') {
              const preferred = 'claude-3-5-sonnet-20241022';
              if (ids.includes(preferred)) {
                this.selectedModel = preferred;
              } else if (ids.includes('claude-3-5-sonnet-20240620')) {
                this.selectedModel = 'claude-3-5-sonnet-20240620';
              } else {
                this.selectedModel = this.availableModels[0].id;
              }
            } else if (this.aiProvider === 'codex') {
              const preferred = 'gpt-5.4-mini';
              if (ids.includes(preferred)) {
                this.selectedModel = preferred;
              } else {
                this.selectedModel = this.availableModels[0].id;
              }
            } else {
              // Copilot: prefer claude-sonnet-4.6
              const preferred = 'claude-sonnet-4.6';
              if (ids.includes(preferred)) {
                this.selectedModel = preferred;
              } else {
                const sonnet = ids.find(id => id.toLowerCase().includes('claude-sonnet'));
                const claude = ids.find(id => id.toLowerCase().includes('claude'));
                if (sonnet) {
                  this.selectedModel = sonnet;
                } else if (claude) {
                  this.selectedModel = claude;
                } else if (!ids.includes(this.selectedModel)) {
                  this.selectedModel = this.availableModels[0].id;
                }
              }
            }
          }
          // Reset reasoning effort to model default when loading
          this.onModelChange();
          
          if (typeof this.fetchSkills === 'function') {
            this.fetchSkills();
          }
        }
      } catch (err) {
        console.warn('[Playground] loadModels failed:', err);
      } finally {
        this.modelsLoading = false;
      }
    },

    /** Called when the model selection changes — resets reasoning effort to model default. */
    onModelChange() {
      const model = this.availableModels.find(m => m.id === this.selectedModel);
      if (model && model.supportsReasoning) {
        this.selectedReasoningEffort = model.defaultReasoningEffort || 'high';
      } else {
        this.selectedReasoningEffort = '';
      }
    },

    /** Returns true if the currently selected model supports reasoning effort. */
    currentModelSupportsReasoning() {
      if (this.availableModels.length === 0) return false;
      const model = this.availableModels.find(m => m.id === this.selectedModel);
      return model ? !!model.supportsReasoning : false;
    },

    /** Returns the reasoning effort options for the currently selected model. */
    reasoningEffortOptions() {
      const model = this.availableModels.find(m => m.id === this.selectedModel);
      const efforts = (model && model.supportedReasoningEfforts && model.supportedReasoningEfforts.length > 0)
        ? model.supportedReasoningEfforts
        : ['low', 'medium', 'high', 'xhigh'];
      return efforts.map(e => ({
        value: e,
        label: e.charAt(0).toUpperCase() + e.slice(1),
      }));
    },

    /** Fetch CLI and SDK version info from the server. */
    async loadVersionInfo() {
      try {
        const resp = await fetch('api/version');
        if (resp.ok) this.versionInfo = await resp.json();
      } catch { /* non-critical */ }
    },
  };
}
