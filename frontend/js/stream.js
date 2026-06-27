/* =============================================================
   stream.js  —  SSE 流式输出接收和渲染
   ============================================================= */

/**
 * streamChat - Receive SSE stream from /api/chat and render to chat content
 * @param {HTMLElement} cc - chat-content element
 * @param {Array} msgs - LLM messages array
 * @param {Object} sess - current session object
 * @param {string} context - reference context text
 * @returns {Promise<string>} The full reply text
 */
async function streamChat(cc, msgs, sess, context) {
  var resp = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    credentials: 'same-origin',
    body: JSON.stringify({ messages: msgs, temperature: 0.7, stream: true, session_id: activeId })
  });

  if (!resp.ok) {
    var errBody = await resp.json().catch(function () { return {}; });
    throw new Error('LLM API 错误: ' + (errBody.error || 'HTTP ' + resp.status));
  }

  var reader = resp.body.getReader();
  var dec = new TextDecoder();
  var reply = '';
  var buf = '';
  var charCount = 0;
  var statusEl = $('botStatus');
  if (statusEl) statusEl.innerHTML = '';

  return new Promise(function (resolve, reject) {
    // 设置 120 秒超时，防止 stream 永远挂起
    var timeoutId = setTimeout(function () {
      reader.cancel().catch(function () {});
      if (charCount > 10) {
        resolve(reply);
      } else {
        reject(new Error('LLM 响应超时，请检查网络连接'));
      }
    }, 120000);

    function read() {
      reader.read().then(function (result) {
        if (result.done) {
          clearTimeout(timeoutId);
          resolve(reply);
          return;
        }
        buf += dec.decode(result.value, { stream: true });
        var lines = buf.split('\n');
        buf = lines.pop();
        for (var li = 0; li < lines.length; li++) {
          var ln = lines[li];
          if (!ln || !ln.startsWith('data:')) continue;
          var payload = ln.substring(5).trim();
          if (payload === '[DONE]' || payload === '"[DONE]"') {
            clearTimeout(timeoutId);
            resolve(reply);
            return;
          }
          try {
            var sd = JSON.parse(payload);
            var delta = sd.choices && sd.choices[0] && sd.choices[0].delta;
            if (delta) {
              var chunk = delta.content || delta.reasoning_content || '';
              if (chunk) {
                reply += chunk;
                charCount += chunk.length;
                if (statusEl) statusEl.textContent = stripMarkdown(reply);
                pipelineStep(4, '生成中 ' + charCount + ' 字');
                autoScrollIfNotUp();
              }
            }
          } catch (x) {}
        }
        read();
      }).catch(function (err) {
        clearTimeout(timeoutId);
        reject(err);
      });
    }
    read();
  });
}