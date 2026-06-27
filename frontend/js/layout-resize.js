/* =============================================================
   layout-resize.js  —  侧边栏横向拖拽 + 输入区纵向拖拽
   ============================================================= */

var SIDEBAR_WIDTH_KEY = 'xuefeng.sidebar.width';
var INPUT_HEIGHT_KEY  = 'xuefeng.input.height';
var DEFAULT_SIDEBAR   = 280;
var SIDEBAR_MIN       = 220;
var SIDEBAR_MAX       = 420;
var DEFAULT_INPUT     = 96;
var INPUT_MIN         = 72;
var INPUT_MAX_VH      = 40; // percentage of viewport

/* ---- Helpers ---- */
function isMobile() { return window.innerWidth <= 768; }

function $(id) { return document.getElementById(id); }

/* ---- Sidebar horizontal resize ---- */
function initSidebarResizer() {
  var handle  = $('sidebar-resizer');
  var sidebar = $('sidebar');
  if (!handle || !sidebar) return;

  // Restore saved width
  var saved;
  try { saved = localStorage.getItem(SIDEBAR_WIDTH_KEY); } catch(e) { saved = null; }
  if (saved) {
    var w = parseInt(saved);
    if (w >= SIDEBAR_MIN && w <= SIDEBAR_MAX) applySidebarWidth(w);
  }

  function applySidebarWidth(w) {
    sidebar.style.width = w + 'px';
    document.documentElement.style.setProperty('--sidebar-width', w + 'px');
  }

  handle.addEventListener('pointerdown', function (e) {
    e.preventDefault();
    document.body.classList.add('resizing-sidebar');
    handle.classList.add('active');
    var startX = e.clientX;
    var startW = sidebar.offsetWidth;

    function onMove(ev) {
      var dx = ev.clientX - startX;
      var newW = startW + dx;
      if (newW < SIDEBAR_MIN) newW = SIDEBAR_MIN;
      if (newW > SIDEBAR_MAX) newW = SIDEBAR_MAX;
      applySidebarWidth(newW);
    }

    function onUp() {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
      document.body.classList.remove('resizing-sidebar');
      handle.classList.remove('active');
      try { localStorage.setItem(SIDEBAR_WIDTH_KEY, sidebar.offsetWidth); } catch(e) {}
    }

    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
  });

  // Double-click to reset
  handle.addEventListener('dblclick', function (e) {
    e.preventDefault();
    applySidebarWidth(DEFAULT_SIDEBAR);
    try { localStorage.removeItem(SIDEBAR_WIDTH_KEY); } catch(e) {}
  });
}

/* ---- Input panel vertical resize ---- */
function initInputResizer() {
  var handle  = $('input-resizer');
  var panel   = $('input-panel');
  if (!handle || !panel) return;

  // Restore saved height
  var saved;
  try { saved = localStorage.getItem(INPUT_HEIGHT_KEY); } catch(e) { saved = null; }
  if (saved) {
    var h = parseInt(saved);
    var maxH = Math.floor(window.innerHeight * INPUT_MAX_VH / 100);
    if (h >= INPUT_MIN && h <= maxH) applyInputHeight(h);
  }

  function applyInputHeight(h) {
    panel.style.height = h + 'px';
    document.documentElement.style.setProperty('--input-height', h + 'px');
    syncTextareaHeight();
  }

  handle.addEventListener('pointerdown', function (e) {
    e.preventDefault();
    document.body.classList.add('resizing-input');
    handle.classList.add('active');
    var startY = e.clientY;
    var startH = panel.offsetHeight;
    var maxH   = Math.floor(window.innerHeight * INPUT_MAX_VH / 100);

    function onMove(ev) {
      var dy = startY - ev.clientY; // drag up → dy positive → bigger
      var newH = startH + dy;
      if (newH < INPUT_MIN) newH = INPUT_MIN;
      if (newH > maxH) newH = maxH;
      applyInputHeight(newH);
    }

    function onUp() {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
      document.body.classList.remove('resizing-input');
      handle.classList.remove('active');
      try { localStorage.setItem(INPUT_HEIGHT_KEY, panel.offsetHeight); } catch(e) {}
    }

    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
  });

  // Double-click to reset
  handle.addEventListener('dblclick', function (e) {
    e.preventDefault();
    applyInputHeight(DEFAULT_INPUT);
    try { localStorage.removeItem(INPUT_HEIGHT_KEY); } catch(e) {}
  });
}

/* ---- Sync textarea height to panel height ---- */
function syncTextareaHeight() {
  var ta = $('userInput');
  var panel = $('input-panel');
  if (!ta || !panel) return;
  var h = panel.offsetHeight;
  var pad = 26; // top + bottom padding
  ta.style.height = Math.max(36, h - pad) + 'px';
}

/* ---- Resize handler for window ---- */
function onWindowResize() {
  if (isMobile()) {
    // Hide resizers on mobile
    var sh = $('sidebar-resizer');
    var ih = $('input-resizer');
    if (sh) sh.style.display = 'none';
    if (ih) ih.style.display = 'none';
  } else {
    var sh = $('sidebar-resizer');
    var ih = $('input-resizer');
    if (sh) sh.style.display = '';
    if (ih) ih.style.display = '';
    // Clamp saved input height to current viewport
    var panel = $('input-panel');
    if (panel) {
      var currentH = panel.offsetHeight;
      var maxH = Math.floor(window.innerHeight * INPUT_MAX_VH / 100);
      if (currentH > maxH) {
        panel.style.height = maxH + 'px';
        syncTextareaHeight();
      }
    }
  }
}

/* ---- Exports ---- */
if (typeof window !== 'undefined') {
  window.isMobile             = isMobile;
  window.initSidebarResizer   = initSidebarResizer;
  window.initInputResizer     = initInputResizer;
  window.syncTextareaHeight   = syncTextareaHeight;
  window.onWindowResize       = onWindowResize;
}