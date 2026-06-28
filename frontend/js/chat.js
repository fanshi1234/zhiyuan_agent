/* =============================================================
   chat.js  —  全局变量 / 认证 / 会话管理 / 渲染 / 事件绑定
              信息提取 / 数据管线 / 快捷键
   ============================================================= */

var SID_KEY = 'zf_sid';
var sessions = {};
var activeId = '';
var busy = false;
var currentUser = '';
var userScrolledUp = false;
// 消息分页状态
var messageCursor = null;
var hasMoreMessages = false;
var loadingMore = false;

var TEMPLATE_TEXT = "我是【省份】考生，选科【物理/历史】，\n今年考了【分数】分，全省排名大概【位次】名。\n家里是【普通工薪/做生意的/爸妈在XX行业】，\n想去【城市或省份】，最讨厌学【数学/背书/都还行】，\n毕业想【找个好工作/考公务员/考研/稳定就行】。\n帮我推荐专业和学校。";

var SYS_PROMPT = "现在是2026年6月，2026年高考已结束，志愿填报正在进行中。你是资深高考志愿规划师，风格直爽接地气。\n\n【格式要求】\n- 不要用###、**等Markdown标记\n- 不要用加粗、斜体等格式符号\n- 用数字序号和破折号做标题，例如：一、冲的学校\n- 纯文本输出即可，网页会自动处理换行\n\n【核心规则】\n1. 省份志愿政策感知（2025年起全部新高考）：\n   专业+院校模式（浙江80/山东96/河北96/重庆96/辽宁112）→推荐至少30-50所\n   院校+专业组模式（江苏40/广东45/湖北45/湖南45/福建40/北京30/天津50/上海24/海南24/河南48/四川45/陕西45/山西45/云南40/贵州45/内蒙古45/安徽45/江西45/黑龙江40/吉林40/广西40/甘肃45/新疆45/宁夏45/青海45/西藏45）→推荐填满80%+\n2. 冲稳保比例：冲20%稳50%保30%，保底至少3个\n3. 用户提供的数据默认准确不质疑\n4. 数据使用原则：内部有数据就参考，没有就说'暂无该校数据'，禁止编造分数位次\n5. 专业过滤：用户说了想学什么专业，就只推荐这些或相关方向\n6. 普通家庭优先技术类（计算机/软件/电子/电气/自动化/机械）\n7. 生化环材土木护理等天坑专业主动提醒避开\n8. 注意区分：用户说'家庭环境普通'是指经济条件，不是指环境专业！不要误解为想学环境专业\n\n【回答结构】\n一、确认省份政策（你是XX省考生，XX模式，可填N个志愿...）\n二、冲的学校\n三、稳的学校\n四、保的学校\n五、补充建议\n\n【数据使用】\n推荐学校时可以带上具体分数和位次数据。格式：\n  合肥工业大学 计算机 2024年 595分 31000位\n如果没有数据就不编造，直接推荐学校即可。\n\n重要:不要只给3-5所学校！冲15所，稳15所，保15所，总共45所。DB数据优先。没有真实数据的学校不要瞎编分数位次。每一所学校都要单独列出，不要合并。\n\n【追问规则】回答末尾检查这些信息是否清楚（不全就问，全就不问）：\n1.省份+文理科 2.分数+位次 3.选科 4.想学什么+排斥什么 5.家里在哪/想去哪 6.父母做什么+年收入 7.家里资源 8.考研还是就业 9.冲985211还是行业强校 10.接受调剂吗 11.学费范围。挑1-2个最关键的追问。";

(function () {
  try {
    var stored = JSON.parse(localStorage.getItem('zf_sessions') || '{}');
    // 恢复 sessions 对象，确保每个会话都有 messages 数组
    sessions = {};
    Object.keys(stored).forEach(function (id) {
      sessions[id] = {
        name: stored[id].name || '对话',
        messages: stored[id].messages || []
      };
    });
  } catch (e) { sessions = {}; }
  try { activeId = localStorage.getItem('zf_active') || ''; } catch (e) { activeId = ''; }
})();

/* ---- Toast ---- */
var toastTimer = null;
function showToast(msg) {
  var t = $('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { t.classList.remove('show'); }, 2000);
}

/* ---- Pipeline progress ---- */
function pipelineStep(n, progress) {
  var steps = document.querySelectorAll('[data-step]');
  for (var i = 0; i < steps.length; i++) {
    var s = parseInt(steps[i].dataset.step);
    steps[i].className = s < n ? 'pipeline-step done' : s === n ? 'pipeline-step active' : 'pipeline-step';
  }
  var ps = $('pipelineProgress');
  if (ps && progress) ps.textContent = progress;
}
function pipelineDone(progress) {
  var steps = document.querySelectorAll('[data-step]');
  for (var i = 0; i < steps.length; i++) steps[i].className = 'pipeline-step done';
  var ps = $('pipelineProgress');
  if (ps && progress) ps.textContent = progress;
}

/* ---- Helpers ---- */
function $(id) { return document.getElementById(id); }

function toggleReasoning(idx) {
  var content = $('reasoning-content-' + idx);
  var toggle = $('reasoning-toggle-' + idx);
  if (!content) return;
  if (content.style.display === 'none') {
    content.style.display = 'block';
    if (toggle) toggle.textContent = '🧠 收起思考过程';
  } else {
    content.style.display = 'none';
    var rLen = content.textContent.length;
    if (toggle) toggle.textContent = '🧠 思考过程 (' + rLen + '字)';
  }
}

function escapeHtml(s) {
  var t = String(s);
  return t.replace(/&/g, '&#38;').replace(/</g, '&#60;').replace(/>/g, '&#62;');
}

function stripMarkdown(s) {
  try {
    return s
      .replace(/^#{1,6}\s+/gm, '')
      .replace(/\*\*(.+?)\*\*/g, '$1')
      .replace(/\*(.+?)\*/g, '$1')
      .replace(/__(.+?)__/g, '$1')
      .replace(/_(.+?)_/g, '$1')
      .replace(/~~(.+?)~~/g, '$1')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      .replace(/^[-*+]\s+/gm, '· ')
      .replace(/^>\s+/gm, '')
      .replace(/```[\s\S]*?```/g, function (m) {
        return m.replace(/```[a-z]*\n?/g, '').replace(/```$/g, '');
      });
  } catch (e) { return s; }
}

function persist() {
  // 只保存轻量状态（会话列表元数据、当前激活会话），不保存完整消息历史
  try {
    var lightweight = {};
    Object.keys(sessions).forEach(function (id) {
      lightweight[id] = { name: sessions[id].name, loaded: !!sessions[id].messages };
    });
    localStorage.setItem('zf_sessions', JSON.stringify(lightweight));
    localStorage.setItem('zf_active', activeId);
  } catch (e) {}
}

/* ---- Auth ---- */
function getSessionId() {
  var m = document.cookie.match(/sid=([^;]+)/);
  return m ? m[1] : '';
}
function setSessionId(sid) {
  document.cookie = 'sid=' + sid + '; Path=/; Max-Age=86400';
  localStorage.setItem(SID_KEY, sid);
}

async function doLogin() {
  var u = $('loginUser').value.trim();
  var p = $('loginPass').value.trim();
  var err = $('loginErr');
  if (!u || !p) { err.textContent = '请输入用户名和密码'; return; }
  err.textContent = '正在登录...';
  var btn = $('loginBtn');
  btn.disabled = true;
  btn.textContent = '登录中...';
  try {
    var r = await fetch('/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ username: u, password: p })
    });
    if (!r.ok) throw new Error('服务器返回错误: ' + r.status);
    var d = await r.json();
    if (d.ok) {
      setSessionId(d.session_id);
      currentUser = d.username;
      err.textContent = '';
      $('loginScreen').style.display = 'none';
      $('app-root').style.display = 'flex';
      $('userName').textContent = currentUser;
      $('mobileUserName').textContent = currentUser;
      initApp();
    } else {
      err.textContent = d.error || '登录失败';
    }
  } catch (e) {
    err.textContent = '登录失败: ' + e.message + ' (请检查服务器是否运行)';
    console.error('Login error:', e);
  }
  btn.disabled = false;
  btn.textContent = '登 录';
}

function doLogout() {
  fetch('/logout', { method: 'POST' }).catch(function () { });
  localStorage.removeItem(SID_KEY);
  document.cookie = 'sid=; Path=/; Max-Age=0';
  currentUser = '';
  $('app-root').style.display = 'none';
  $('loginScreen').style.display = 'flex';
  $('loginUser').value = '';
  $('loginPass').value = '';
}

async function checkAuth() {
  var sid = '';
  try { sid = localStorage.getItem(SID_KEY) || ''; } catch (e) {}
  if (!sid) return false;
  try {
    var r = await fetch('/config', { credentials: 'same-origin' });
    if (r.ok) {
      var d = await r.json();
      if (d.username) { currentUser = d.username; return true; }
    }
  } catch (e) {}
  try { localStorage.removeItem(SID_KEY); } catch (e) {}
  return false;
}

/* ---- Mobile sidebar ---- */
function toggleSidebar() {
  $('sidebar').classList.toggle('open');
  $('navOverlay').classList.toggle('open');
}
function closeSidebar() {
  $('sidebar').classList.remove('open');
  $('navOverlay').classList.remove('open');
}

/* ---- Session Management ---- */
async function createSession() {
  var id = Date.now() + '';
  sessions[id] = { name: '新对话', messages: [] };
  activeId = id;
  persist();
  paint();
  if (currentUser) {
    try {
      await fetch('/api/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ session_id: id, title: '新对话' })
      });
    } catch (e) { console.warn('createSession sync fail:', e.message); }
  }
}

async function removeSession(id) {
  delete sessions[id];
  if (activeId === id) {
    var keys = Object.keys(sessions);
    activeId = keys.length ? keys[keys.length - 1] : '';
    if (!activeId) createSession();
  }
  persist();
  paint();
  if (currentUser) {
    try {
      await fetch('/api/conversations/' + encodeURIComponent(id), {
        method: 'DELETE',
        credentials: 'same-origin'
      });
    } catch (e) { console.warn('removeSession sync fail:', e.message); }
  }
}

/* ---- Rename Session ---- */
async function startRenameSession(id) {
  var sess = sessions[id];
  if (!sess) return;
  var currentName = sess.name || '新对话';
  var newName = prompt('输入新标题（2-30字）', currentName);
  if (newName === null) return; // 取消
  newName = newName.trim();
  if (newName.length < 1) {
    showToast('标题不能为空');
    return;
  }
  if (newName.length > 30) {
    newName = newName.substring(0, 30);
  }
  // 本地更新
  sess.name = newName;
  persist();
  paint();
  // 同步到后端
  if (currentUser) {
    try {
      await fetch('/api/conversations/' + encodeURIComponent(id) + '/title', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ title: newName })
      });
    } catch (e) { console.warn('rename fail:', e.message); }
  }
}

/* ---- Regenerate Session Title ---- */
async function regenerateSessionTitle(id) {
  if (!currentUser) {
    showToast('请先登录');
    return;
  }
  try {
    var r = await fetch('/api/conversations/' + encodeURIComponent(id) + '/regenerate-title', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: '{}'
    });
    if (r.ok) {
      var d = await r.json();
      if (d.ok && sessions[id]) {
        sessions[id].name = d.title;
        persist();
        paint();
        showToast('标题已更新: ' + d.title);
      }
    } else {
      var errD = await r.json().catch(function () { return {}; });
      showToast(errD.error || '重新生成标题失败');
    }
  } catch (e) {
    showToast('网络错误，请稍后重试');
  }
}

/* ---- Switch Session ---- */
async function switchSession(id) {
  activeId = id;
  messageCursor = null;
  hasMoreMessages = false;
  persist();
  if (window.innerWidth <= 768) closeSidebar();

  // 如果本地已有消息（刚发送过），直接渲染
  if (sessions[id] && sessions[id].messages && sessions[id].messages.length) {
    paint();
    return;
  }

  // 从服务器加载消息
  if (!currentUser) return;
  try {
    var r = await fetch('/api/conversations/' + encodeURIComponent(id) + '/messages?limit=30', {
      credentials: 'same-origin'
    });
    if (r.ok) {
      var d = await r.json();
      if (d.messages && d.messages.length) {
        sessions[id].messages = d.messages.map(function (m) {
          return { role: m.role, text: m.content };
        });
        // 更新标题（优先使用服务器返回的标题，不再从首条消息截取）
        if (!sessions[id].name || sessions[id].name === '新对话') {
          // 从服务器会话列表获取标题，保持"新对话"直到后端自动生成
        }
        // 设置分页状态
        messageCursor = d.cursor || null;
        hasMoreMessages = d.has_more || false;
        persist();
        paint();
      } else {
        paint();
      }
    } else {
      paint();
    }
  } catch (e) {
    console.warn('switchSession load fail:', e.message);
    paint();
  }
}

/* ---- Load conversations from server ---- */
async function loadConversationsFromServer() {
  if (!currentUser) return;
  try {
    var r = await fetch('/api/conversations?page=1&limit=200', { credentials: 'same-origin' });
    if (r.ok) {
      var d = await r.json();
      if (d.conversations && d.conversations.length) {
        d.conversations.forEach(function (c) {
          if (!sessions[c.session_id]) {
            sessions[c.session_id] = { name: c.title || '对话', messages: [] };
          } else {
            // 更新服务器返回的标题
            sessions[c.session_id].name = c.title || sessions[c.session_id].name;
          }
        });
        if (!activeId || !sessions[activeId]) {
          activeId = d.conversations[0].session_id;
        }
        persist();
        paint();
      }
    }
  } catch (e) { console.warn('loadConversations fail:', e.message); }
}

/* ---- Render ---- */
function paint() {
  var html = '';
  Object.keys(sessions).forEach(function (id) {
    var s = sessions[id];
    var preview = '';
    if (s.messages && s.messages.length) {
      preview = s.messages[s.messages.length - 1].text.substring(0, 20);
    } else {
      preview = '空对话';
    }
    var activeCls = id === activeId ? ' active' : '';
    html += '<div class="conv-item' + activeCls + '" data-id="' + id + '">'
      + '<span class="conv-title">' + escapeHtml(s.name || preview) + '</span>'
      + '<span class="conv-actions" data-actions="' + id + '">'
      + '<span class="conv-rename" data-rename="' + id + '" title="重命名">✎</span>'
      + '<span class="conv-refresh-title" data-refresh-title="' + id + '" title="重新生成标题">↻</span>'
      + '</span>'
      + '<span class="dismiss" data-remove="' + id + '">×</span></div>';
  });
  var cl = $('conv-list');
  if (cl) cl.innerHTML = html;

  var cc = $('chat-content');
  if (!cc) return;
  if (!activeId || !sessions[activeId] || !sessions[activeId].messages || !sessions[activeId].messages.length) {
    cc.innerHTML = '<div class="greeting"><div class="emoji">🎓</div><h2>'
      + '志愿填报助手</h2>'
      + '<div class="tips"><h3>使用技巧</h3>'
      + '<div class="tip-item">位次比分数重要 — 有全省排名一定带上</div>'
      + '<div class="tip-item">讨厌什么和喜欢什么一样重要 — 说清楚不能接受的，Agent 帮你避开</div>'
      + '<div class="tip-item">家里干什么的别不好意思说 — 爸妈在电力、铁路、医院、学校、做生意的，这决定了很多隐藏的好路</div>'
      + '<div class="tip-item">多聊几轮效果更好 — Agent 追问的时候认真答，聊得越深建议越准</div></div>'
      + '<div class="template" id="sampleQ"><span class="copyHint">点击复制</span>'
      + escapeHtml(TEMPLATE_TEXT) + '</div></div>';
    return;
  }
  var out = '';
  var msgs = sessions[activeId].messages;
  for (var i = 0; i < msgs.length; i++) {
    var m = msgs[i];
    if (!m) continue;
    var who = m.role === 'user' ? '你' : '咨询顾问';
    var cls = m.role === 'user' ? 'user' : 'bot';
    var txt = m.role === 'user' ? m.text : stripMarkdown(m.text);
    var reasoningHtml = '';
    if (m.reasoning && m.reasoning.length > 0) {
      var rLen = stripMarkdown(m.reasoning).length;
      var rIdx = i;
      reasoningHtml = '<div class="reasoning-section" onclick="toggleReasoning(' + rIdx + ')" style="cursor:pointer;color:#94a3b8;font-size:12px;margin-bottom:8px;padding:6px 0;border-top:1px solid #e2e8f0;">'
        + '<span style="font-size:13px;" id="reasoning-toggle-' + rIdx + '">🧠 思考过程 (' + rLen + '字)</span>'
        + '<div class="reasoning-content" id="reasoning-content-' + rIdx + '" style="display:none;color:#64748b;font-size:13px;white-space:pre-wrap;line-height:1.6;max-height:300px;overflow-y:auto;margin-top:6px;">'
        + escapeHtml(stripMarkdown(m.reasoning))
        + '</div></div>';
    }
    out += '<div class="bubble ' + cls + '"><div class="label">' + who + '</div>' + reasoningHtml + escapeHtml(txt) + '</div>';
  }
  cc.innerHTML = out;
  scrollToBottom(false);
}

/* ---- Scroll management ---- */
function scrollToBottom(smooth) {
  var cc = $('chat-content');
  if (!cc) return;
  if (smooth) {
    cc.scrollTo({ top: cc.scrollHeight, behavior: 'smooth' });
  } else {
    cc.scrollTop = cc.scrollHeight;
  }
}

function checkUserScrolledUp() {
  var cc = $('chat-content');
  if (!cc) { userScrolledUp = false; return; }
  userScrolledUp = (cc.scrollHeight - cc.scrollTop - cc.clientHeight) > 120;
}

function autoScrollIfNotUp() {
  if (!userScrolledUp) {
    scrollToBottom(false);
  }
}

/* ---- Message Pagination (Scroll to load more) ---- */
async function loadMoreMessages() {
  if (!messageCursor || !hasMoreMessages || loadingMore || !activeId) return;
  loadingMore = true;
  var cc = $('chat-content');
  if (!cc) return;
  var scrollTopBefore = cc.scrollTop;
  var scrollHeightBefore = cc.scrollHeight;

  try {
    var r = await fetch('/api/conversations/' + encodeURIComponent(activeId) + '/messages?cursor=' + messageCursor + '&limit=30', {
      credentials: 'same-origin'
    });
    if (r.ok) {
      var d = await r.json();
      if (d.messages && d.messages.length) {
        // 更新游标和状态
        messageCursor = d.cursor;
        hasMoreMessages = d.has_more;

        // 保存当前可视位置，插入旧消息后恢复
        var currentMsgs = sessions[activeId].messages;
        for (var i = d.messages.length - 1; i >= 0; i--) {
          currentMsgs.unshift({ role: d.messages[i].role, text: d.messages[i].content });
        }

        // 只渲染新增的消息到前面
        var out = '';
        for (var i = 0; i < d.messages.length; i++) {
          var m = d.messages[i];
          var who = m.role === 'user' ? '你' : '咨询顾问';
          var cls = m.role === 'user' ? 'user' : 'bot';
          var txt = m.role === 'user' ? m.text : stripMarkdown(m.text);
          out += '<div class="bubble ' + cls + '"><div class="label">' + who + '</div>' + escapeHtml(txt) + '</div>';
        }
        cc.insertAdjacentHTML('afterbegin', out);
        // 恢复滚动位置，避免跳转
        cc.scrollTop = scrollHeightBefore - scrollTopBefore + (cc.scrollHeight - scrollHeightBefore);

        persist();
      }
    }
  } catch (e) {
    console.warn('loadMoreMessages fail:', e.message);
  }
  loadingMore = false;
}

// 绑定滚动加载 - 当滚动到顶部时触发
function onChatScroll() {
  checkUserScrolledUp();
  var cc = $('chat-content');
  if (!cc || loadingMore) return;
  if (cc.scrollTop < 50) {
    loadMoreMessages();
  }
}

/* ---- Regex-based Info Extraction ---- */
function parseInfo(text) {
  var info = { province: '', rank: 0, score: 0, major: '', school: '' };
  var provs = ['北京', '天津', '上海', '重庆', '河北', '山西', '辽宁', '吉林', '黑龙江',
    '江苏', '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南',
    '广东', '广西', '海南', '四川', '贵州', '云南', '西藏', '陕西', '甘肃',
    '青海', '宁夏', '新疆', '内蒙古'];
  var best = text.length, bp = '';
  for (var i = 0; i < provs.length; i++) {
    var idx = text.indexOf(provs[i]);
    if (idx >= 0 && idx < best) { best = idx; bp = provs[i]; }
  }
  info.province = bp;
  var rm = text.match(/(\d{4,7})\s*[位名]/) || text.match(/[位名]次?\s*(\d{4,7})/) || text.match(/排[名行]\s*(\d{4,7})/);
  if (rm) info.rank = parseInt(rm[1]) || parseInt(rm[2]) || 0;
  var sm = text.match(/(\d{3})\s*分/) || text.match(/分数\s*(\d{3})/);
  if (sm) info.score = parseInt(sm[1]);
  var majors = ['计算机', '软件', '电气', '机械', '自动化', '土木', '临床', '口腔',
    '法学', '会计', '金融', '物联网', '人工智能', '大数据', '电子', '通信',
    '材料', '化工', '生物', '医学', '护理', '师范', '英语', '新闻', '设计',
    '美术', '音乐', '体育', '汉语言', '数学', '化学', '地理', '航空航天', '能源', '交通'];
  var contextMajors = ['环境'];
  var neg = text.match(/(?:不学|不接受|不读|不选|别推荐|别学|拒绝|排斥|不想学|不考虑).*?(?:[。，,;\n]|$)/g) || [];
  var negStr = neg.join('');
  var found = [];
  for (var i = 0; i < majors.length; i++) {
    if (text.indexOf(majors[i]) >= 0 && negStr.indexOf(majors[i]) < 0) found.push(majors[i]);
  }
  for (var i = 0; i < contextMajors.length; i++) {
    var cm = contextMajors[i];
    if (text.indexOf(cm) >= 0 && negStr.indexOf(cm) < 0) {
      var pos = text.indexOf(cm);
      var before = text.substring(Math.max(0, pos - 4), pos);
      var easyWords = ['家庭', '经济', '生长', '生活', '社会', '工作', '自然', '实验'];
      var isContext = false;
      for (var j = 0; j < easyWords.length; j++) {
        if (before.indexOf(easyWords[j]) >= 0) { isContext = true; break; }
      }
      if (!isContext) found.push(cm);
    }
  }
  if (found.length) info.major = found.join(',');
  var sch = text.match(/[一-鿿]{2,8}(大学|学院)/);
  if (sch) info.school = sch[0];
  return info;
}

/* ---- Web Search ---- */
async function webSearch(q, n) {
  n = n || 3;
  try {
    var r = await fetch('/api/tavily', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
      body: JSON.stringify({ query: q, n: n })
    });
    if (r.ok) {
      var d = await r.json();
      if (d.results && d.results.length) return d.results;
    }
  } catch (e) { console.warn('Tavily fail:', e.message); }
  // 不阻塞兜底，Tavily 失败直接返回空
  return [];
}

/* ---- Should Use Web Search ---- */
function shouldUseWebSearch(text) {
  var webKw = ['最新', '今年', '2025', '2026', '刚发布', '官网', '投档线',
               '招生章程', '政策变化', '查一下', '联网查', '最新录取',
               '今年录取', '今年投档', '今年招生', '今年政策'];
  return webKw.some(function (kw) { return text.indexOf(kw) >= 0; });
}

/* ---- Single School Query ---- */
function isSingleSchoolQuery(text, info) {
  // 用户明确询问某一所具体学校
  return info.schools && info.schools.length > 0 && info.schools.length <= 2;
}

/* ---- KB Search ---- */
async function kbSearch(q) {
  try {
    var r = await fetch('/kb_search?q=' + encodeURIComponent(q), { credentials: 'same-origin' });
    if (r.ok) {
      var d = await r.json();
      return d.results || [];
    }
  } catch (e) { console.warn('KB search fail:', e.message); }
  return [];
}

/* ---- Data Pipeline ---- */
async function fetchContext(text) {
  pipelineStep(1);
  var info = { province: '', rank: 0, score: 0, subject: '', majors: [], schools: [], keywords: [] };
  try {
    var er = await fetch('/api/extract', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin',
      body: JSON.stringify({ text: text })
    });
    if (er.ok) {
      var ai = await er.json();
      if (ai && !ai.error) {
        info.province = ai.province || '';
        info.rank = parseInt(ai.rank) || 0;
        info.score = parseInt(ai.score) || 0;
        info.subject = ai.subject || '';
        info.majors = ai.majors || [];
        info.schools = ai.schools || [];
        info.keywords = ai.keywords || [];
      }
    }
  } catch (e) { console.warn('AI extract fail, fallback regex:', e.message); }

  var re = parseInfo(text);
  if (!info.province && re.province) info.province = re.province;
  if (!info.rank && re.rank) info.rank = re.rank;
  if (!info.score && re.score) info.score = re.score;
  if (!info.majors.length && re.major) info.majors = [re.major];
  if (!info.schools.length && re.school) info.schools = [re.school];
  if (!info.subject) {
    if (text.indexOf('物理') >= 0 || text.indexOf('物化') >= 0) info.subject = '物理类';
    else if (text.indexOf('历史') >= 0 || text.indexOf('文史') >= 0 || text.indexOf('文科') >= 0) info.subject = '历史类';
    else if (text.indexOf('理科') >= 0) info.subject = '理科';
  }

  // 信息不全（缺省份或缺分数和位次），跳过所有查询直接回复
  var skip = !info.province || (!info.rank && !info.score);
  if (skip) return '';

  pipelineStep(2);
  var dbText = '';
  var rawJ = null;
  if (!skip) {
    try {
      var parts = ['province=' + encodeURIComponent(info.province), 'rank=' + info.rank, 'score=' + info.score];
      if (info.majors && info.majors.length) parts.push('keyword=' + encodeURIComponent(info.majors.join(',')));
      if (info.subject) parts.push('subject=' + encodeURIComponent(info.subject));
      if (info.schools.length) parts.push('school=' + encodeURIComponent(info.schools[0]));
      var resp = await fetch('/recommend?' + parts.join('&'));
      if (resp.ok) {
        rawJ = await resp.json();
        try {
          var sr = await fetch('/db_stats?province=' + encodeURIComponent(info.province));
          if (sr.ok) {
            var st = await sr.json();
            if (st.total && st.total < 100 && info.rank > 0 && info.rank < (st.min_pos || 0)) {
              dbText += '【注意】本地数据库' + info.province + '数据较少(仅' + st.total + '条)，请重点使用其他来源。\n';
            }
          }
        } catch (e) {}
        if (rawJ.chong || rawJ.wen || rawJ.bao) {
          var tc = (rawJ.chong ? rawJ.chong.length : 0) + (rawJ.wen ? rawJ.wen.length : 0) + (rawJ.bao ? rawJ.bao.length : 0);
          dbText = '【本地数据库·冲稳保推荐】位次' + (rawJ.pos || info.rank) + '，共' + tc + '条记录\n';
          if (rawJ.chong && rawJ.chong.length) {
            dbText += '\n\n﹟【冲】\n';
            rawJ.chong.slice(0, 15).forEach(function (d) {
              dbText += '- ' + d.school + ' ' + d.program + ' ' + (d.year || '') + '年 ' + (d.score || '?') + '分 ' + (d.position || '?') + '位\n';
            });
          }
          if (rawJ.wen && rawJ.wen.length) {
            dbText += '\n\n﹟【稳】\n';
            rawJ.wen.slice(0, 15).forEach(function (d) {
              dbText += '- ' + d.school + ' ' + d.program + ' ' + (d.year || '') + '年 ' + (d.score || '?') + '分 ' + (d.position || '?') + '位\n';
            });
          }
          if (rawJ.bao && rawJ.bao.length) {
            dbText += '\n\n﹟【保】\n';
            rawJ.bao.slice(0, 15).forEach(function (d) {
              dbText += '- ' + d.school + ' ' + d.program + ' ' + (d.year || '') + '年 ' + (d.score || '?') + '分 ' + (d.position || '?') + '位\n';
            });
          }
        } else if (rawJ.error) {
          dbText += 'DB查询返回: ' + rawJ.error + '\n';
        }
      }
    } catch (e) { console.warn('DB query fail:', e.message); }
  }

  pipelineStep(3);
  var webText = '';
  var kbText = '';
  try {
    // KB 搜索（始终执行）
    var kbQuery = (info.province || '') + ' ' + (info.majors && info.majors[0] || '') + ' ' + (info.schools && info.schools[0] || '');
    var kbResults = await kbSearch(kbQuery);
    if (kbResults.length) {
      kbText = '【知识仓库参考资料】\n';
      kbResults.slice(0, 10).forEach(function (k) { kbText += k + '\n\n'; });
    }

    // 联网搜索 — 仅当用户明确需要时
    var webSearchNeeded = shouldUseWebSearch(text);
    if (!webSearchNeeded) {
      // 普通问题不联网
    } else {
      // 生成少量全局 query（最多 5 条）
      var queries = [];
      // 单校查询
      if (isSingleSchoolQuery(text, info) && info.schools && info.schools.length > 0) {
        queries.push(info.schools[0] + ' ' + info.province + ' 录取分数线 投档线');
        queries.push(info.schools[0] + ' 2025年招生计划');
      } else {
        // 全局查询
        if (info.province && info.rank > 0) {
          if (info.majors && info.majors.length) {
            queries.push(info.province + ' ' + info.rank + '位次 ' + info.majors[0] + '专业 志愿填报');
          } else {
            queries.push(info.province + ' ' + info.rank + '位次 志愿填报');
          }
          queries.push(info.province + ' ' + info.score + '分 能上什么大学');
        }
        // 专业前景
        if (info.majors && info.majors.length) {
          queries.push(info.majors[0] + '专业 就业前景 薪资');
        }
      }
      // 去重并限制数量
      var seenQ = {}; var finalQ = [];
      for (var i = 0; i < queries.length; i++) {
        if (!seenQ[queries[i]]) { seenQ[queries[i]] = 1; finalQ.push(queries[i]); }
        if (finalQ.length >= 5) break;
      }
      // 并行执行
      var tasks = finalQ.map(function (q) { return webSearch(q, 3); });
      var allWebResults = await Promise.all(tasks);
      var allWeb = [];
      for (var i = 0; i < allWebResults.length; i++) {
        allWeb = allWeb.concat(allWebResults[i]);
      }
      // 去重
      var seen = {}; var unique = [];
      for (var i = 0; i < allWeb.length; i++) {
        var k = allWeb[i].substring(0, 50);
        if (!seen[k]) { seen[k] = 1; unique.push(allWeb[i]); }
      }
      if (unique.length) {
        webText = '【联网搜索·仅供参考】\n';
        unique.slice(0, 20).forEach(function (w) { webText += '- ' + w.substring(0, 400) + '\n'; });
      } else {
        webText = '【联网搜索无结果】已基于本地数据库和知识仓库回答。\n';
      }
    }
  } catch (e) {
    console.warn('Search fail:', e.message);
    webText = '';
  }

  var result = '[DEBUG] province=' + info.province + ' rank=' + info.rank + ' score=' + info.score + ' majors=' + (info.majors || []).join(',') + '\n';
  if (dbText) result += dbText + '\n';
  if (kbText) result += kbText + '\n';
  if (webText) result += webText + '\n';
  if (!dbText && !kbText && !webText) result += '所有数据源均无结果。\n';
  return result;
}

/* ---- Send Message ---- */
async function submit() {
  var inp = $('userInput');
  if (!inp || busy) return;
  var text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  busy = true;
  $('submitBtn').disabled = true;
  userScrolledUp = false;

  // 中止旧的流式请求，避免旧流污染新会话
  if (window.__currentStreamCtrl) {
    try { window.__currentStreamCtrl.abort(); } catch (e) {}
    delete window.__currentStreamCtrl;
  }

  try {
    if (!activeId || !sessions[activeId]) createSession();
    var sess = sessions[activeId];
    var currentConvId = activeId;
    sess.messages.push({ role: 'user', text: text });
    // 暂不自动命名，交由后端标题生成服务处理
    paint();
    persist();

    var cc = $('chat-content');
    if (!cc) {
      sess.messages.push({ role: 'assistant', text: '页面异常，请刷新后重试' });
    } else {
      var loader = document.createElement('div');
      loader.className = 'bubble bot';
      loader.innerHTML = '<div class="label">咨询顾问</div><div id="botStatus"><div class="spinner"><span></span><span></span><span></span></div></div>';
      cc.appendChild(loader);
      scrollToBottom(true);

      pipelineStep(1);
      var context = await fetchContext(text);

      var msgs = [{ role: 'system', content: SYS_PROMPT }];
      if (context) {
        msgs.push({ role: 'system', content: '【参考资料，请基于这些数据给出建议】\n' + context });
      }
      pipelineDone();

      var start = Math.max(0, sess.messages.length - 25);
      for (var i = start; i < sess.messages.length; i++) {
        msgs.push({ role: sess.messages[i].role, content: sess.messages[i].text });
      }

      pipelineStep(4, '正在生成...');

      // Delegate SSE streaming to stream.js
      var result = await streamChat(cc, msgs, sess, context, currentConvId);
      var reply = typeof result === 'string' ? result : (result.reply || '');
      var reasoning = typeof result === 'object' ? (result.reasoning || '') : '';

      // 处理用户主动取消
      if (reply && reply.substring(0, 11) === '__ABORTED__') {
        var abortedText = reply.substring(11);
        sess.messages.push({ role: 'assistant', text: abortedText });
        var statusEl = $('botStatus');
        if (statusEl) statusEl.textContent = '已停止生成';
        pipelineDone('已停止生成');
      } else {
        // 正常完成
        var msgObj = { role: 'assistant', text: reply };
        if (reasoning) msgObj.reasoning = reasoning;
        sess.messages.push(msgObj);
        var charCount = reply ? reply.length : 0;
        pipelineDone('回答完成 ' + charCount + ' 字');
      }

      // 同步标题从后端（后端可能已自动生成标题）
      try {
        var titleResp = await fetch('/api/conversations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ action: 'list' })
        });
        if (titleResp.ok) {
          var titleData = await titleResp.json();
          if (titleData.conversations) {
            for (var ti = 0; ti < titleData.conversations.length; ti++) {
              var tc = titleData.conversations[ti];
              if (tc.session_id === activeId && sessions[activeId]) {
                var serverTitle = tc.title || '';
                // 如果服务器有标题且本地是"新对话"，更新本地
                if (serverTitle && serverTitle !== '' && sessions[activeId].name === '新对话') {
                  sessions[activeId].name = serverTitle;
                }
                break;
              }
            }
          }
        }
      } catch (e) { /* 标题同步失败不影响正常聊天 */ }
    }
  } catch (e) {
    console.error('[submit] error:', e);
    var errorMsg = e.message || '未知错误';
    var displayMsg = '';
    if (errorMsg === '__ABORTED__') {
      displayMsg = '已停止生成';
    } else if (errorMsg.indexOf('连接中断') >= 0) {
      displayMsg = '连接中断，请重试';
    } else {
      displayMsg = '生成失败，请重试';
    }
    try {
      if (activeId && sessions[activeId]) {
        sessions[activeId].messages.push({ role: 'assistant', text: displayMsg });
      }
      var statusEl = $('botStatus');
      if (statusEl) statusEl.textContent = displayMsg;
      pipelineDone(displayMsg);
    } catch (ex) {}
  }

  try { paint(); } catch (ex) { console.error('[paint] error:', ex); }
  try { persist(); } catch (ex) {}
  busy = false;
  var sb = $('submitBtn');
  if (sb) sb.disabled = false;
}

/* ---- Event binding helper ---- */
function on(id, ev, fn) {
  var el = $(id);
  if (el) el.addEventListener(ev, fn);
}

/* ---- Init app ---- */
async function initApp() {
  if (localStorage.getItem('zf_dark') === '1') document.body.classList.add('dark');
  if (!activeId || !sessions[activeId]) createSession();
  paint();
  await loadConversationsFromServer();

  // Init resizers (desktop only)
  if (typeof isMobile === 'function' && !isMobile()) {
    if (typeof initSidebarResizer === 'function') initSidebarResizer();
    if (typeof initInputResizer === 'function') initInputResizer();
  }

  bindEvents();
}

function bindEvents() {
  on('loginPass', 'keydown', function (e) { if (e.key === 'Enter') doLogin(); });
  on('loginUser', 'keydown', function (e) { if (e.key === 'Enter') $('loginPass').focus(); });
  on('addNew', 'click', createSession);
  on('submitBtn', 'click', submit);
  on('darkToggle', 'click', function () {
    document.body.classList.toggle('dark');
    localStorage.setItem('zf_dark', document.body.classList.contains('dark') ? '1' : '');
  });

  // Template copy via event delegation
  var cc = $('chat-content');
  if (cc) {
    cc.addEventListener('click', function (e) {
      var sampleQ = e.target.closest('#sampleQ');
      if (!sampleQ) return;
      e.preventDefault();
      e.stopPropagation();
      if (window.getSelection) window.getSelection().removeAllRanges();
      var ta = document.createElement('textarea');
      ta.textContent = TEMPLATE_TEXT;
      ta.value = TEMPLATE_TEXT;
      ta.readOnly = false;
      ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0;pointer-events:none';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      try { ta.setSelectionRange(0, 99999); } catch (ignore) {}
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (ignore) {}
      document.body.removeChild(ta);
      if (window.getSelection) window.getSelection().removeAllRanges();
      if (ok) {
        showToast('复制成功，请按照自己的情况修改【】内容');
      } else {
        if ($('userInput')) { $('userInput').value = TEMPLATE_TEXT; $('userInput').focus(); }
        showToast('模板已填入输入框，请修改【】内容后发送');
      }
    });
  }

  on('userInput', 'keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
  });

  on('conv-list', 'click', function (e) {
    var t = e.target;
    // 重命名按钮
    if (t.dataset.rename) { e.stopPropagation(); e.preventDefault(); startRenameSession(t.dataset.rename); return; }
    // 重新生成标题按钮
    if (t.dataset.refreshTitle) { e.stopPropagation(); e.preventDefault(); regenerateSessionTitle(t.dataset.refreshTitle); return; }
    // 删除按钮
    if (t.dataset.remove) { e.stopPropagation(); removeSession(t.dataset.remove); return; }
    var item = t.closest('.conv-item');
    if (item) switchSession(item.dataset.id);
  });

  on('navOverlay', 'click', closeSidebar);

  // Chat scroll detection (scroll up detection + pagination)
  var chatContent = $('chat-content');
  if (chatContent) {
    chatContent.addEventListener('scroll', onChatScroll);
  }

  // Window resize handler
  var resizeTimer;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      if (typeof onWindowResize === 'function') onWindowResize();
    }, 200);
  });
}

/* ---- Boot ---- */
async function boot() {
  if (await checkAuth()) {
    $('loginScreen').style.display = 'none';
    $('app-root').style.display = 'flex';
    $('userName').textContent = currentUser;
    $('mobileUserName').textContent = currentUser;
    initApp();
  }
}

// Expose to global
window.submit = submit;
window.doLogin = doLogin;
window.doLogout = doLogout;
window.toggleSidebar = toggleSidebar;
window.closeSidebar = closeSidebar;
window.createSession = createSession;
window.removeSession = removeSession;
window.switchSession = switchSession;
window.startRenameSession = startRenameSession;
window.regenerateSessionTitle = regenerateSessionTitle;
window.paint = paint;
window.showToast = showToast;
window.scrollToBottom = scrollToBottom;
window.autoScrollIfNotUp = autoScrollIfNotUp;
window.checkUserScrolledUp = checkUserScrolledUp;

boot();