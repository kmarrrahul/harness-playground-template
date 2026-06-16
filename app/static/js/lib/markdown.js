/**
 * markdown.js — Markdown configuration and helpers.
 */

// Configure marked.js
if (typeof marked !== 'undefined') {
  marked.setOptions({
    gfm: true,
    breaks: true,
    headerIds: false,
    mangle: false,
  });
}

function configureMarked() {
  /* already configured at load time above */
}

function parseMarkdown(text) {
  if (!text) return '';
  if (typeof marked === 'undefined') return escapeHtml(text);
  try {
    return marked.parse(text);
  } catch {
    return escapeHtml(text);
  }
}

function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function applyHighlighting(container) {
  if (typeof hljs === 'undefined' || !container) return;
  container.querySelectorAll('pre code').forEach((block) => {
    hljs.highlightElement(block);
  });
}
