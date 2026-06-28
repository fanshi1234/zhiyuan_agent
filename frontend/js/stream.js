/* =============================================================
   stream.js  —  SSE 流式输出接收和渲染
   统一 JSON SSE 协议:
     {"type":"start", "conversation_id":"xxx", "message_id":"xxx"}
     {"type":"reasoning", "conversation_id":"xxx", "message_id":"xxx", "content":"..."}
     {"type":"chunk", "conversation_id":"xxx", "message_id":"xxx", "content":"..."}
     {"type":"done", "conversation_id":"xxx", "message_id":"xxx", "reasoning_length":N}
     {"type":"error", "conversation_id":"xxx", "message_id":"xxx", "message":"..."}
   ============================================================= */

/**
 * streamChat - Receive SSE stream from /api/chat and render to chat content
 * @param {HTMLElement} cc - chat-content element
 * @param {Array} msgs - LLM messages array
 * @param {Object} sess - current session object
 * @param {string} context - reference context text
 * @param {string} convId - conversation_id to bind this stream to
 * @returns {Promise<Object>} { reply: string, reasoning: string }
 */
async function streamChat(cc, msgs, sess, context, convId) {
  console.log('[stream] start conv=' + (convId || activeId) + ' active=' + activeId);

  var ctrl = new AbortController();
  window.__currentStreamCtrl = ctrl;

  var resp = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    credentials: 'same-origin',
    signal: ctrl.signal,
    body: JSON.stringify({ messages: msgs, temperature: 0.7, stream: true, session_id: activeId })
  });

  if (!resp.ok) {
    var errBody = await resp.json().catch(function () { return {}; });
    throw new Error('LLM API 错误: ' + (errBody.error || 'HTTP ' + resp.status));
  }

  var reader = resp.body.getReader();
  var dec = new TextDecoder();
  var reply = '';
  var reasoning = '';
  var buf = '';
  var chunkCount = 0;
  var statusEl = null;

  // Find the loader bubble (last bot bubble with botStatus)
  var bubbles = cc.querySelectorAll('.bubble.bot');
  if (bubbles.length) {
    var loaderBubble = bubbles[bubbles.length - 1];
    statusEl = loaderBubble.querySelector('#botStatus') || loaderBubble.querySelector('.label + div');
  }

  if (statusEl) statusEl.innerHTML = '<span class="status-text">思考中...</span>';

  return new Promise(function (resolve, reject) {
    var timeoutId = setTimeout(function () {
      reader.cancel().catch(function () {});
      if (reply.length > 0) {
        console.warn('[stream] timeout, returning partial (' + reply.length + ' chars)');
        resolve({ reply: reply, reasoning: reasoning });
      } else {
        reject(new Error('LLM 响应超时，请检查网络连接'));
      }
    }, 120000);

    function parseEvents() {
      var parts = buf.split('\n\n');
      buf = parts.pop();
      for (var i = 0; i < parts.length; i++) {
        var block = parts[i];
        var lines = block.split('\n');
        var dataLine = '';
        for (var j = 0; j < lines.length; j++) {
          var ln = lines[j];
          if (ln.startsWith('data:')) {
            dataLine = ln.substring(5).trim();
          }
        }
        if (!dataLine) continue;
        var parsed = null;
        try {
          parsed = JSON.parse(dataLine);
        } catch (e) {
          console.warn('[stream] parse error:', dataLine.substring(0, 80));
          continue;
        }
        if (!parsed || !parsed.type) continue;

        if (parsed.type === 'reasoning') {
          var rContent = parsed.content || '';
          if (rContent) {
            reasoning += rContent;
            if (statusEl) {
              statusEl.innerHTML = '<span class="status-text">思考中 (' + reasoning.length + '字...)</span>';
            }
          }
        } else if (parsed.type === 'chunk') {
          var content = parsed.content || '';
          if (content) {
            reply += content;
            chunkCount++;
            if (statusEl) {
              statusEl.textContent = stripMarkdown(reply);
            }
            pipelineStep(4, '生成中 ' + reply.length + ' 字');
            autoScrollIfNotUp();
          }
        } else if (parsed.type === 'done') {
          console.log('[stream] done chunks=' + chunkCount + ' chars=' + reply.length + ' reasoning=' + reasoning.length);
          clearTimeout(timeoutId);
          resolve({ reply: reply, reasoning: reasoning });
          return true;
        } else if (parsed.type === 'error') {
          console.error('[stream] error:', parsed.message);
          clearTimeout(timeoutId);
          reject(new Error(parsed.message || '生成失败'));
          return true;
        } else if (parsed.type === 'start') {
          console.log('[stream] start msg_id=' + parsed.message_id);
        }
      }
      return false;
    }

    function read() {
      reader.read().then(function (result) {
        if (result.done) {
          var remaining = '';
          try { remaining = dec.decode(undefined, { stream: false }); } catch (e) {}
          console.log('[stream] result.done, remaining=' + (remaining ? remaining.substring(0, 100) : 'none') + ' buf="' + buf.substring(0, 100) + '" chars=' + reply.length + ' reasoning=' + reasoning.length);
          if (remaining) {
            buf += remaining;
            if (!parseEvents()) {
              clearTimeout(timeoutId);
              if (reply.length > 0) {
                console.warn('[stream] stream ended without done event, resolving partial (' + reply.length + ' chars)');
                resolve({ reply: reply, reasoning: reasoning });
              } else {
                reject(new Error('流式响应异常结束'));
              }
            }
          } else {
            clearTimeout(timeoutId);
            if (reply.length > 0) {
              console.warn('[stream] stream ended without done event, resolving partial (' + reply.length + ' chars)');
              resolve({ reply: reply, reasoning: reasoning });
            } else {
              reject(new Error('流式响应为空'));
            }
          }
          return;
        }
        buf += dec.decode(result.value, { stream: true });
        if (parseEvents()) return;
        read();
      }).catch(function (err) {
        clearTimeout(timeoutId);
        if (err && err.name === 'AbortError') {
          console.log('[stream] aborted by user');
          if (reply.length > 0) {
            resolve({ reply: '__ABORTED__' + reply, reasoning: reasoning });
            return;
          }
          reject(new Error('__ABORTED__'));
          return;
        }
        console.error('[stream] network error:', err);
        reject(new Error('连接中断，请重试'));
      });
    }
    read();
  });
}