/**
 * mermaid-render.js — Mermaid rendering helpers.
 */

function initMermaid() {
  const m = window.mermaid;
  if (m) {
    m.initialize({
      startOnLoad: false,
      theme: 'dark',
      flowchart: { useMaxWidth: true, nodeSpacing: 50, rankSpacing: 50, curve: 'linear' },
      securityLevel: 'loose',
    });
    console.log('[Harness Playground] Mermaid initialized:', typeof m.render);
  } else {
    console.warn('[Harness Playground] Mermaid library not found on window');
  }
}

async function tryRenderMermaid(code) {
  const m = window.mermaid;
  if (!m || typeof m.render !== 'function') {
    console.warn('[Harness Playground] tryRenderMermaid: mermaid.render not available');
    return null;
  }
  const id = 'mermaid-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
  try {
    const { svg } = await m.render(id, code);
    return { ok: true, svg };
  } catch (err) {
    const errEl = document.getElementById('d' + id);
    if (errEl) errEl.remove();
    return { ok: false, error: err.message || String(err) };
  }
}
