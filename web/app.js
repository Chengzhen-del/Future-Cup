'use strict';

const $ = (id) => document.getElementById(id);
let ws = null, chat = null, imageBase64 = '', running = false;
let pendingFollowUp = null;
let tokenCursor = null, tokenBuf = '';
let tlEl = null, tlSteps = {};

function $$(sel, root) { return (root || document).querySelectorAll(sel); }

// ── 健康检查 ──
async function checkHealth() {
  const url = $('baseUrl').value.replace(/\/$/, '') + '/health';
  try {
    const r = await fetch(url);
    const j = await r.json();
    $('health').textContent = j.ok
      ? '● 已连接  env=' + j.env + '  mock=' + j.mock + '  llm=' + j.llm + '  vision=' + j.vision
      : '● 响应异常';
    $('health').className = 'ok';
  } catch (e) {
    $('health').textContent = '● 未连接（' + e.message + '）';
    $('health').className = 'err';
  }
}

// ── 模式 / 传输切换 ──
function initSegButtons(sel, handler) {
  $$(sel).forEach(function(b) {
    b.addEventListener('click', function() {
      $$(sel).forEach(function(x) { x.classList.remove('active'); });
      b.classList.add('active');
      if (handler) handler(b);
    });
  });
}
function getMode() { return $$('#modeSeg .active')[0].dataset.mode; }
function getTrans() { return $$('#transSeg .active')[0].dataset.trans; }

// ── 图片上传 ──
function initImageUpload() {
  var fileInput = $('fileInput');
  var thumb = $('thumb');
  thumb.addEventListener('click', function() { fileInput.click(); });
  fileInput.addEventListener('change', async function(e) {
    var f = e.target.files[0];
    if (!f) return;
    var buf = await f.arrayBuffer();
    var bytes = new Uint8Array(buf);
    var bin = '';
    for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    imageBase64 = btoa(bin);
    thumb.innerHTML = '<img src="data:' + f.type + ';base64,' + imageBase64 + '"><br><span style="margin-top:4px;display:block">✅ ' + f.name + '（' + Math.round(f.size/1024) + 'KB）</span>';
  });
}

// ── 构建请求 ──
function buildReq(extra) {
  extra = extra || {};
  var now = new Date().toISOString().replace('T',' ').slice(0,19);
  var base = {
    taskId: 'T-TEST',
    deviceId: 'D-3001',
    deviceName: $('deviceName').value,
    deviceType: $('deviceType').value,
    voiceText: $('voiceText').value,
    location: $('location').value,
    operator: $('operator').value,
    capturedAt: now,
    sensor: {
      temperature: parseFloat($('temp').value) || null,
      humidity: parseFloat($('hum').value) || null,
      noise: null,
      simulated: true
    },
    mode: getMode()
  };
  for (var k in extra) { base[k] = extra[k]; }
  return base;
}

function addMsg(role, html) {
  var m = document.createElement('div');
  m.className = 'msg ' + role;
  var avatar = role === 'user' ? '我' : role === 'system' ? '!' : 'AI';
  m.innerHTML = '<div class="avatar">' + avatar + '</div><div class="bubble"><div class="bubble-inner">' + html + '</div></div>';
  chat.appendChild(m);
  chat.scrollTop = chat.scrollHeight;
  return m;
}

function addUserMsg() {
  var req = buildReq();
  var bits = [
    '设备：' + req.deviceName + '（' + req.deviceType + '）',
    '位置：' + req.location,
    req.voiceText ? '语音：' + req.voiceText : '（无语音）',
    '模式：' + (req.mode === 'detailed' ? '🔍 详细' : '⚡ 快速'),
    imageBase64 ? '📷 已附照片' : '（无照片）',
    '温度：' + req.sensor.temperature + '℃（模拟）',
  ];
  addMsg('user', bits.join('<br>'));
  return req;
}

// ── step 时间线渲染 ──
function newTimeline() {
  var wrap = document.createElement('div');
  wrap.className = 'timeline';
  tlEl = wrap; tlSteps = {};
  var lastBot = $$('.msg.bot');
  var bubble = lastBot.length ? lastBot[lastBot.length-1].querySelector('.bubble-inner') : null;
  if (bubble) bubble.appendChild(wrap);
}
function renderStep(step) {
  console.log('[step]', step);
  if (!tlEl) newTimeline();
  var el = tlSteps[step.name];
  if (!el) {
    el = document.createElement('div');
    el.className = 'tl-step';
    el.innerHTML = '<div class="tl-icon pending">•</div><div class="tl-name"></div><div class="tl-detail"></div><div class="tl-ms"></div>';
    tlEl.appendChild(el);
    tlSteps[step.name] = el;
  }
  var kids = el.children;
  kids[0].className = 'tl-icon ' + step.status;
  kids[0].textContent = step.status === 'done' ? '✓' : step.status === 'failed' ? '✗' : step.status === 'running' ? '●' : '•';
  kids[1].textContent = step.name;
  kids[2].textContent = step.detail || '';
  kids[3].textContent = step.durationMs ? step.durationMs + 'ms' : '';

  // subSteps: 重新渲染
  var subWrap = el.parentNode.querySelector('.tl-subs[data-for="' + step.name + '"]');
  if (subWrap) subWrap.remove();
  if (step.subSteps && step.subSteps.length) {
    subWrap = document.createElement('div');
    subWrap.className = 'tl-subs';
    subWrap.setAttribute('data-for', step.name);
    step.subSteps.forEach(function(sub) {
      var row = document.createElement('div');
      row.className = 'tl-sub level-' + (sub.level || 2) + ' ' + (sub.status || 'info');
      row.innerHTML = '<div class="tl-sub-dot"></div><div class="tl-sub-text"></div>';
      row.querySelector('.tl-sub-text').textContent = sub.text;
      subWrap.appendChild(row);
    });
    el.parentNode.insertBefore(subWrap, el.nextSibling);
  }
}

function renderSubStep(stepName, subStep) {
  console.log('[sub_step]', stepName, subStep);
  if (!tlEl || !tlSteps[stepName]) return;
  var mainEl = tlSteps[stepName];
  var wrap = mainEl.parentNode;
  var subWrap = wrap.querySelector('.tl-subs[data-for="' + stepName + '"]');
  if (!subWrap) {
    subWrap = document.createElement('div');
    subWrap.className = 'tl-subs';
    subWrap.setAttribute('data-for', stepName);
    wrap.insertBefore(subWrap, mainEl.nextSibling);
  }
  var row = document.createElement('div');
  row.className = 'tl-sub level-' + (subStep.level || 2) + ' ' + (subStep.status || 'info');
  row.innerHTML = '<div class="tl-sub-dot"></div><div class="tl-sub-text"></div>';
  row.querySelector('.tl-sub-text').textContent = subStep.text;
  subWrap.appendChild(row);
}

// ── verdict 卡片 ──
function levelCssClass(level) {
  return 'verdict-color-' + level;
}
function renderMemoryHit(memories) {
  console.log('[memory_hit]', memories);
  var html = '<div style="background:#f0f7ff;border:1px solid #b3d4ff;border-radius:10px;'
           + 'padding:10px 14px;margin-top:8px;font-size:13px;color:#1a3d7a;">'
           + '<div style="font-weight:600;margin-bottom:6px;">🧠 Agent 记忆唤醒 · 命中 '
           + memories.length + ' 条历史巡检</div>'
           + memories.slice(0, 3).map(function(m) {
               var lvl = m.level || '';
               var time = (m.capturedAt || m.createdAt || '').substring(5, 16);
               var sum = (m.summary || '').substring(0, 80);
               return '<div style="color:#4a5568;padding:3px 0;">'
                   + '• <strong style="color:'
                   + (lvl === '异常' || lvl === '紧急' ? '#d92d20' :
                      lvl === '关注' ? '#ff7d00' : '#00b42a')
                   + '">' + lvl + '</strong> · ' + time + ' · ' + sum + '</div>';
             }).join('')
           + '</div>';
  var botBubbles = document.querySelectorAll('.msg.bot .bubble-inner');
  var last = botBubbles[botBubbles.length - 1];
  if (last) last.insertAdjacentHTML('afterbegin', html);
}

function renderVerdict(resp) {
  console.log('[final]', resp);
  // 如果有 memories（HTTP 模式直接在 resp 里），也展示
  if (resp.memories && resp.memories.length) renderMemoryHit(resp.memories);
  var cls = 'level-' + resp.level;
  var badge = resp.needHuman ? '<span class="badge danger">需人工复核</span>' : '';
  var mock = resp.mock ? '<span class="badge warn">Mock 模式</span>' : '';
  var wo = resp.workOrderId ? '<span class="badge">自动工单 ' + resp.workOrderId + '</span>' : '';
  var lvlCls = levelCssClass(resp.level);

  var html = '<div class="verdict ' + cls + '">'
    + '<div class="verdict-row">'
    + '<span class="verdict-level ' + lvlCls + '">' + resp.level + '</span>'
    + '<span class="badge">置信度 ' + Math.round(resp.confidence*100) + '%</span>'
    + badge + mock + wo
    + '<span class="verdict-meta">总耗时 ' + resp.durationMs + 'ms</span>'
    + '</div>'
    + '<div class="verdict-advice"><strong>处置建议：</strong>' + resp.advice + '</div>'
    + '</div>';

  if (resp.findings && resp.findings.length) {
    html += '<table class="findings"><thead><tr><th>检查项</th><th>观测值</th><th>判定</th><th>依据</th></tr></thead><tbody>';
    resp.findings.forEach(function(f) {
      html += '<tr><td>' + f.item + '</td><td>' + f.value + '</td>'
        + '<td class="' + (f.abnormal ? 'abnormal' : 'normal') + '">'
        + (f.abnormal ? '⚠ 异常' : '✓ 正常') + '</td>'
        + '<td style="color:var(--text-3)">' + (f.basis || '-') + '</td></tr>';
    });
    html += '</tbody></table>';
  }

  if (resp.followUpQuestions && resp.followUpQuestions.length) {
    html += renderFollowUp(resp);
  }

  var botBubble = $$('.msg.bot');
  var last = botBubble[botBubble.length - 1];
  if (last) last.querySelector('.bubble-inner').insertAdjacentHTML('beforeend', html);
}

function renderFollowUp(resp) {
  pendingFollowUp = resp;
  var html = '<div class="followup">'
    + '<h4>💡 Agent 发现档案不完整，请补充：</h4>'
    + '<ul>' + resp.followUpQuestions.map(function(q) { return '<li>' + q + '</li>'; }).join('') + '</ul>'
    + '<div id="fuInput"></div>'
    + '<button class="btn btn-primary" id="submitClarBtn">📤 提交补答，再次巡检</button>'
    + '</div>';
  setTimeout(function() {
    var box = document.getElementById('fuInput');
    if (!box) return;
    resp.followUpQuestions.forEach(function(q) {
      var ip = document.createElement('input');
      ip.placeholder = '对「' + q + '」的回答…';
      box.appendChild(ip);
    });
    var btn = document.getElementById('submitClarBtn');
    if (btn) btn.addEventListener('click', submitClar);
  }, 50);
  return html;
}

function submitClar() {
  if (!pendingFollowUp) return;
  var inputs = $$('#fuInput input');
  var answers = Array.from(inputs).map(function(i) { return i.value.trim(); }).filter(function(v) { return v; });
  if (!answers.length) { alert('请至少填写一个回答'); return; }
  var base = buildReq({ clarifications: { answers: answers } });
  addMsg('user', '📤 补答：' + answers.join('；'));
  var t = getTrans();
  if (t === 'stream') startWs(base); else startHttp(base);
}

// ── token 打字机 ──
function onToken(text) {
  if (!tokenCursor) {
    tokenCursor = document.createElement('span');
    tokenCursor.className = 'token-cursor';
    var botBubble = $$('.msg.bot');
    var last = botBubble[botBubble.length - 1];
    if (last) last.querySelector('.bubble-inner').appendChild(tokenCursor);
  }
  tokenBuf += text;
  tokenCursor.textContent = tokenBuf;
  chat.scrollTop = chat.scrollHeight;
}
function endToken() {
  if (tokenCursor) tokenCursor.classList.remove('token-cursor');
  tokenCursor = null; tokenBuf = '';
}

function finishRunning() {
  running = false;
  $('startBtn').disabled = false;
  $('cancelBtn').classList.add('hidden');
  $('connInfo').textContent = '已完成';
}

// ── WebSocket 流式 ──
function startWs(prebuiltReq) {
  if (running) return;
  running = true;
  $('startBtn').disabled = true;
  $('cancelBtn').classList.remove('hidden');

  var req = prebuiltReq || addUserMsg();
  var base = $('baseUrl').value.replace(/\/$/, '');
  var sid = Date.now().toString(16) + Math.floor(Math.random()*0xFFFF).toString(16);
  var wsUrl = base.replace('http', 'ws') + '/ws/agent/' + sid;

  $('connInfo').textContent = '⏳ 连接 WS…';
  console.log('WS 连接:', wsUrl);

  var ws_ = new WebSocket(wsUrl);
  ws = ws_;
  var gotFirst = false;
  var firstTimer = setTimeout(function() {
    if (!gotFirst && running) {
      addMsg('system', '⚠ WebSocket 5 秒内没收到任何消息，自动降级为 HTTP 一次性…');
      try { ws_.close(); } catch(e){}
      startHttp(req);
    }
  }, 5000);

  ws_.onopen = function() {
    $('connInfo').textContent = '🟢 已连接';
    console.log('WS 已连接，发送 start...');
    var payload = JSON.parse(JSON.stringify(req));
    payload.imageBase64 = imageBase64;
    ws_.send(JSON.stringify({ type: 'start', payload: payload }));
    addMsg('bot', '🤖 Agent 开始工作…');
    tlEl = null;
  };

  ws_.onmessage = function(ev) {
    gotFirst = true;
    clearTimeout(firstTimer);
    var msg; try { msg = JSON.parse(ev.data); } catch(e) { return; }
    console.log('[WS →]', msg);
    switch (msg.type) {
      case 'step': renderStep(msg.step); break;
      case 'sub_step': renderSubStep(msg.stepName, msg.subStep); break;
      case 'memory_hit': renderMemoryHit(msg.memories); break;
      case 'token': onToken(msg.text); break;
      case 'final': endToken(); renderVerdict(msg.data); break;
      case 'end': finishRunning(); break;
      case 'error':
        endToken();
        addMsg('bot', '❌ 错误：' + msg.message);
        finishRunning();
        break;
    }
  };

  ws_.onerror = function() {
    console.error('WS 错误');
    clearTimeout(firstTimer);
    addMsg('bot', '❌ WebSocket 连接失败');
    if (running) {
      addMsg('system', '💡 已自动降级 HTTP 一次性请求，请耐心等待约 50 秒…');
      startHttp(req);
    }
  };

  ws_.onclose = function() {
    console.log('WS 关闭');
    clearTimeout(firstTimer);
    if (running) finishRunning();
  };
}

// ── HTTP 一次性 ──
async function startHttp(prebuiltReq) {
  if (running) return;
  running = true;
  $('startBtn').disabled = true;
  $('cancelBtn').classList.remove('hidden');

  var req = prebuiltReq || addUserMsg();
  var base = $('baseUrl').value.replace(/\/$/, '');
  var url = imageBase64
    ? (base + '/api/v1/inspections/upload')
    : (base + '/api/v1/inspections');

  $('connInfo').textContent = '⏳ HTTP 请求中（真模型约 50 秒）…';
  addMsg('bot', '🤖 Agent 开始工作（HTTP 一次性模式，真模型约 50 秒出结果）…');
  tlEl = null;

  try {
    var resp;
    if (imageBase64) {
      var chars = atob(imageBase64).split('').map(function(c) { return c.charCodeAt(0); });
      var blob = new Blob([new Uint8Array(chars)], {type:'image/jpeg'});
      var fd = new FormData();
      fd.append('payload', JSON.stringify(req));
      fd.append('image', blob, 'capture.jpg');
      resp = await fetch(url, { method: 'POST', body: fd });
    } else {
      resp = await fetch(url, {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify(req)
      });
    }
    var j = await resp.json();
    newTimeline();
    if (j.steps && j.steps.length) {
      // 用后端真实 steps（含 subSteps 思考细节）
      j.steps.forEach(function(s) { renderStep(s); });
    } else {
      // 兜底合成
      var steps = [
        {name:'任务规划',status:'done',detail:'HTTP 模式',durationMs:0},
        {name:'语音解析',status:'done',detail:'HTTP 模式',durationMs:0},
        {name:'视觉判读',status:'done',detail:'HTTP 模式',durationMs:0},
        {name:'台账比对',status:'done',detail:'HTTP 模式',durationMs:0},
        {name:'手册检索',status:'done',detail:'HTTP 模式',durationMs:0},
        {name:'定级决策',status:'done',detail:j.level + '（置信度 ' + j.confidence + '）',durationMs:j.durationMs || 0},
      ];
      steps.forEach(function(s) { renderStep(s); });
    }
    renderVerdict(j);
  } catch (e) {
    addMsg('bot', '❌ 请求失败：' + e.message);
  }
  finishRunning();
}

// ── 启动绑定 ──
function init() {
  chat = $('chat');
  initSegButtons('#modeSeg button');
  initSegButtons('#transSeg button');
  initImageUpload();

  $('startBtn').addEventListener('click', function() {
    var t = getTrans();
    if (t === 'stream') startWs(); else startHttp();
  });
  $('cancelBtn').addEventListener('click', function() {
    if (ws) { try { ws.close(); } catch(e){} }
    finishRunning();
  });

  $('voiceText').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('startBtn').click(); }
  });

  setInterval(checkHealth, 8000);
  checkHealth();
}

document.addEventListener('DOMContentLoaded', init);
