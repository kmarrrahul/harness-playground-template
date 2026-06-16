/**
 * streaming.js — SSE streaming helpers (shared between features and follow-up).
 */

/**
 * Open an SSE stream to the given endpoint.
 * @param {string} endpoint - API endpoint path
 * @param {object} body - JSON body
 * @param {string} token - Bearer token
 * @returns {ReadableStreamDefaultReader}
 */
async function openStream(endpoint, body, token) {
  const resp = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });

  if (!resp.ok) {
    const text = await resp.text();
    console.error('[Harness Playground] HTTP error from', endpoint, resp.status, text);
    throw new Error(`HTTP ${resp.status}: ${text}`);
  }

  return resp.body.getReader();
}

/**
 * Async-iterate SSE events from a ReadableStream reader.
 */
async function* iterateSSE(reader) {
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6).trim();
        if (!data || data === '[DONE]') continue;
        try {
          yield JSON.parse(data);
        } catch {
          // non-JSON line — skip
        }
      }
    }
  }

  if (buffer.startsWith('data: ')) {
    const data = buffer.slice(6).trim();
    if (data && data !== '[DONE]') {
      try { yield JSON.parse(data); } catch { /* ignore */ }
    }
  }
}
