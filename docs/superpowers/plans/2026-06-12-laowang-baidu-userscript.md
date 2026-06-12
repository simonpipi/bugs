# Laowang Baidu Userscript Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dual-site Tampermonkey userscript that enhances Laowang forum resource posts and saves purchased Baidu Netdisk shares into `/老王转存/YYYY-MM/帖子标题/`.

**Architecture:** Implement one self-contained userscript with small pure helper functions, a Laowang forum controller, and a Baidu Netdisk controller. Export pure helpers under `module.exports` when running in Node so they can be unit tested without a browser.

**Tech Stack:** Plain JavaScript userscript, Tampermonkey APIs (`GM_setValue`, `GM_getValue`, `GM_openInTab`), Node.js built-in `assert`, no npm dependencies.

---

## File Structure

- Create `laowang/laowang_baidu_transfer.user.js`: production userscript. It contains metadata, shared helpers, task storage, forum page UI/parser, Baidu page automation, and safe fallbacks.
- Create `laowang/laowang_baidu_transfer.test.js`: Node unit tests for pure helper functions and DOM-light parsers.
- No changes to existing `laowang/*.py` automation files.

## Task 0: Isolated Workspace and Baseline

**Files:**
- No file changes.

- [ ] **Step 1: Use the worktree skill before implementation**

Use `superpowers:using-git-worktrees` before touching implementation files. Do not implement on `main` unless the user explicitly asks to work in place.

- [ ] **Step 2: Verify current branch and status**

Run:

```bash
git branch --show-current
git status --short
```

Expected: either a feature branch/worktree is active, or the user has explicitly approved working in place. Existing unrelated dirty files may remain; do not revert them.

- [ ] **Step 3: Check Node availability**

Run:

```bash
node --version
```

Expected: prints a Node version. If Node is missing, stop and ask for help.

## Task 1: Pure Helpers and Unit Tests

**Files:**
- Create: `laowang/laowang_baidu_transfer.test.js`
- Create: `laowang/laowang_baidu_transfer.user.js`

- [ ] **Step 1: Write failing tests for helper behavior**

Create `laowang/laowang_baidu_transfer.test.js` with:

```javascript
const assert = require('assert');
const api = require('./laowang_baidu_transfer.user.js');

function test(name, fn) {
  try {
    fn();
    console.log(`ok - ${name}`);
  } catch (error) {
    console.error(`not ok - ${name}`);
    throw error;
  }
}

test('cleanTitle removes bracketed size and netdisk suffixes', () => {
  const input = '[自行打包] 大美女【SkylarBlue】完美臀，超模身材 [41V 74P+4.58G][百度盘]';
  assert.strictEqual(api.cleanTitle(input), '大美女【SkylarBlue】完美臀，超模身材');
});

test('safePathSegment removes invalid path characters and truncates long titles', () => {
  const input = 'a/b:c*d?e\"f<g>h|'.repeat(20);
  const output = api.safePathSegment(input);
  assert(!/[\\\\/:*?"<>|]/.test(output));
  assert(output.length <= 80);
});

test('buildTargetPath uses month and cleaned title', () => {
  const output = api.buildTargetPath('[合集] 标题 [4.58G][百度盘]', new Date('2026-06-12T10:00:00Z'));
  assert.strictEqual(output, '/老王转存/2026-06/标题/');
});

test('extractBaiduShare finds share url and code', () => {
  const text = '链接: https://pan.baidu.com/s/1abcDEF 提取码: 8x7k 解压密码: abc';
  const result = api.extractBaiduShare(text);
  assert.deepStrictEqual(result, {
    shareUrl: 'https://pan.baidu.com/s/1abcDEF',
    extractCode: '8x7k'
  });
});

test('isForumPage and isBaiduPage classify urls', () => {
  assert.strictEqual(api.isForumPage('https://laowang.vip/forum.php?mod=viewthread&tid=1'), true);
  assert.strictEqual(api.isForumPage('https://laowang.vip/thread-2821033-1-1.html'), true);
  assert.strictEqual(api.isBaiduPage('https://pan.baidu.com/s/1abc'), true);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
node laowang/laowang_baidu_transfer.test.js
```

Expected: FAIL because `laowang_baidu_transfer.user.js` does not exist or does not export helper functions.

- [ ] **Step 3: Create userscript metadata and helper implementation**

Create `laowang/laowang_baidu_transfer.user.js` with a userscript header and these exported helpers:

```javascript
// ==UserScript==
// @name         老王论坛百度网盘转存助手
// @namespace    https://laowang.vip/
// @version      0.1.0
// @description  美化老王论坛资源帖，购买确认后保存百度网盘分享到指定目录
// @match        https://laowang.vip/forum.php?mod=viewthread*
// @match        https://laowang.vip/thread-*
// @match        https://pan.baidu.com/*
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_deleteValue
// @grant        GM_openInTab
// @run-at       document-idle
// ==/UserScript==

(function bootstrap(root) {
  'use strict';

  const TASK_KEY = 'lwbt:tasks';

  function cleanText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function cleanTitle(rawTitle) {
    return cleanText(rawTitle)
      .replace(/^\[[^\]]+\]\s*/g, '')
      .replace(/\s*\[[^\]]*(?:G|M|T|百度|阿里|夸克|盘|V|P)[^\]]*\]\s*/gi, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function safePathSegment(value) {
    const cleaned = cleanText(value)
      .replace(/[\\/:*?"<>|]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
    return cleaned.slice(0, 80) || '未命名资源';
  }

  function pad2(value) {
    return String(value).padStart(2, '0');
  }

  function buildTargetPath(title, date = new Date()) {
    const year = date.getFullYear();
    const month = pad2(date.getMonth() + 1);
    return `/老王转存/${year}-${month}/${safePathSegment(cleanTitle(title))}/`;
  }

  function extractBaiduShare(text) {
    const source = String(text || '');
    const urlMatch = source.match(/https?:\/\/pan\.baidu\.com\/(?:s\/[A-Za-z0-9_-]+|share\/init\?surl=[A-Za-z0-9_-]+)/i);
    if (!urlMatch) return null;
    const codeMatch = source.match(/(?:提取码|提取碼|密码|密碼|访问码|访问碼)[:：\s]*([A-Za-z0-9]{4})/i);
    return {
      shareUrl: urlMatch[0],
      extractCode: codeMatch ? codeMatch[1] : ''
    };
  }

  function isForumPage(url) {
    return /^https:\/\/laowang\.vip\/(?:forum\.php\?mod=viewthread|thread-)/.test(String(url || ''));
  }

  function isBaiduPage(url) {
    return /^https:\/\/pan\.baidu\.com\//.test(String(url || ''));
  }

  const api = {
    TASK_KEY,
    cleanText,
    cleanTitle,
    safePathSegment,
    buildTargetPath,
    extractBaiduShare,
    isForumPage,
    isBaiduPage
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
    return;
  }

  root.LWBT = api;
  main(root, api);
})(typeof window !== 'undefined' ? window : globalThis);

function main(root, api) {
  if (!root || !root.location || !root.document) return;
  if (api.isForumPage(root.location.href)) {
    // Forum controller added in later tasks.
  } else if (api.isBaiduPage(root.location.href)) {
    // Baidu controller added in later tasks.
  }
}
```

- [ ] **Step 4: Run helper tests**

Run:

```bash
node laowang/laowang_baidu_transfer.test.js
```

Expected: PASS, with five `ok - ...` lines.

- [ ] **Step 5: Commit helper foundation**

Run:

```bash
git add laowang/laowang_baidu_transfer.user.js laowang/laowang_baidu_transfer.test.js
git commit -m "feat: add laowang baidu userscript helpers"
```

## Task 2: Forum Parser, Preview Image Filtering, and Panel Rendering

**Files:**
- Modify: `laowang/laowang_baidu_transfer.user.js`
- Modify: `laowang/laowang_baidu_transfer.test.js`

- [ ] **Step 1: Add parser tests**

Append to `laowang/laowang_baidu_transfer.test.js`:

```javascript
test('parseTypeInfo extracts forum resource fields', () => {
  const text = [
    '下载方式: 百度盘',
    '来源: 自行打包',
    '文件数量: 41V 74P',
    '资源大小: 4.58G',
    '解压密码: 上老王论坛当老王',
    '解压软件: -'
  ].join('\\n');
  assert.deepStrictEqual(api.parseTypeInfo(text), {
    downloadType: '百度盘',
    source: '自行打包',
    fileCount: '41V 74P',
    size: '4.58G',
    password: '上老王论坛当老王',
    unzipTool: '-'
  });
});

test('isPreviewImage rejects avatars, smileys, icons and accepts attachment images', () => {
  assert.strictEqual(api.isPreviewImage('https://laowang.vip/uc_server/data/avatar/001/a.jpg'), false);
  assert.strictEqual(api.isPreviewImage('https://laowang.vip/static/image/smiley/tieba/tb_17.png'), false);
  assert.strictEqual(api.isPreviewImage('https://laowang.vip/static/image/common/online_member.gif'), false);
  assert.strictEqual(api.isPreviewImage('https://laowang.vip/data/attachment/forum/202606/12/demo.jpg'), true);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
node laowang/laowang_baidu_transfer.test.js
```

Expected: FAIL because `parseTypeInfo` and `isPreviewImage` are not implemented.

- [ ] **Step 3: Implement parser and image filter helpers**

Add these functions inside the userscript before `const api = { ... }`, and export them in `api`:

```javascript
function parseTypeInfo(text) {
  const source = String(text || '');
  const fields = [
    ['downloadType', '下载方式'],
    ['source', '来源'],
    ['fileCount', '文件数量'],
    ['size', '资源大小'],
    ['password', '解压密码'],
    ['unzipTool', '解压软件']
  ];
  const result = {};
  for (const [key, label] of fields) {
    const match = source.match(new RegExp(`${label}[:：]\\s*([^\\n\\r]+)`));
    result[key] = match ? cleanText(match[1]) : '';
  }
  return result;
}

function isPreviewImage(url) {
  const value = String(url || '');
  if (!/\.(?:jpg|jpeg|png|webp|gif)(?:[?#].*)?$/i.test(value)) return false;
  if (/\/uc_server\/data\/avatar\//i.test(value)) return false;
  if (/\/static\/image\/(?:common|smiley)\//i.test(value)) return false;
  if (/\/template\//i.test(value)) return false;
  return /\/data\/attachment\/|\/forum\/|\/album\//i.test(value);
}
```

- [ ] **Step 4: Add forum controller UI**

Implement these browser-only functions in `laowang/laowang_baidu_transfer.user.js`:

```javascript
function getForumPostRoot(document) {
  return document.querySelector('[id^="post_"] table[id^="pid"]') || document.querySelector('[id^="pid"]');
}

function getForumInfo(root, document, api) {
  const titleNode = document.querySelector('#thread_subject');
  const rawTitle = titleNode ? titleNode.textContent : document.title;
  const postRoot = getForumPostRoot(document) || document.body;
  const text = postRoot.innerText || '';
  const info = api.parseTypeInfo(text);
  const authorNode = postRoot.querySelector('.authi a.xw1, .pls .authi a');
  const timeNode = postRoot.querySelector('[id^="authorposton"]');
  return {
    rawTitle,
    title: api.cleanTitle(rawTitle),
    author: api.cleanText(authorNode && authorNode.textContent),
    postTime: api.cleanText(timeNode && timeNode.textContent),
    targetPath: api.buildTargetPath(rawTitle),
    ...info
  };
}

function collectPreviewImages(document, api) {
  const postRoot = getForumPostRoot(document) || document.body;
  const urls = Array.from(postRoot.querySelectorAll('img'))
    .map((img) => img.getAttribute('zoomfile') || img.getAttribute('file') || img.getAttribute('data-original') || img.currentSrc || img.src)
    .filter((url) => api.isPreviewImage(url));
  return Array.from(new Set(urls));
}

function injectForumPanel(root, api) {
  const document = root.document;
  if (document.querySelector('#lwbt-panel')) return;
  const info = getForumInfo(root, document, api);
  const images = collectPreviewImages(document, api);
  const panel = document.createElement('section');
  panel.id = 'lwbt-panel';
  panel.innerHTML = renderForumPanel(info, images);
  const target = document.querySelector('#postlist') || document.querySelector('#wp') || document.body;
  target.parentNode.insertBefore(panel, target);
  bindForumPanel(root, api, info, images);
}
```

- [ ] **Step 5: Add `renderForumPanel` and `bindForumPanel`**

Add:

```javascript
function renderForumPanel(info, images) {
  const hasImage = images.length > 0;
  const mainImage = hasImage ? `<img class="lwbt-main-image" src="${escapeAttr(images[0])}" alt="">` : '<div class="lwbt-no-image">登录后可预览</div>';
  const thumbs = images.map((url, index) => `<button class="lwbt-thumb" data-index="${index}" type="button"><img src="${escapeAttr(url)}" alt=""></button>`).join('');
  return `
    <style>${panelCss()}</style>
    <div class="lwbt-card">
      <div class="lwbt-info">
        <h2>${escapeHtml(info.title)}</h2>
        <p class="lwbt-sub">${escapeHtml(info.author || '')} ${escapeHtml(info.postTime || '')}</p>
        <div class="lwbt-grid">
          ${fieldHtml('下载方式', info.downloadType)}
          ${fieldHtml('来源', info.source)}
          ${fieldHtml('资源大小', info.size)}
          ${fieldHtml('文件数量', info.fileCount)}
          ${fieldHtml('解压密码', info.password)}
          ${fieldHtml('保存目录', info.targetPath)}
        </div>
        <div class="lwbt-actions">
          <button id="lwbt-transfer" type="button">购买并保存到百度网盘</button>
          <button id="lwbt-copy" type="button">复制信息</button>
          <button id="lwbt-toggle-original" type="button">展开原帖</button>
        </div>
        <div id="lwbt-status" class="lwbt-status">等待操作</div>
      </div>
      <div class="lwbt-gallery">
        <div class="lwbt-main">${mainImage}</div>
        <div class="lwbt-thumbs">${thumbs}</div>
      </div>
    </div>`;
}

function bindForumPanel(root, api, info, images) {
  const document = root.document;
  document.querySelectorAll('.lwbt-thumb').forEach((button) => {
    button.addEventListener('click', () => {
      const image = document.querySelector('.lwbt-main-image');
      if (image) image.src = images[Number(button.dataset.index)];
    });
  });
  const copyButton = document.querySelector('#lwbt-copy');
  if (copyButton) {
    copyButton.addEventListener('click', async () => {
      const text = `${info.title}\\n下载方式: ${info.downloadType}\\n大小: ${info.size}\\n解压密码: ${info.password}\\n保存目录: ${info.targetPath}`;
      await root.navigator.clipboard.writeText(text);
      setStatus(document, '已复制关键信息');
    });
  }
}
```

- [ ] **Step 6: Run tests**

Run:

```bash
node laowang/laowang_baidu_transfer.test.js
```

Expected: PASS.

- [ ] **Step 7: Commit forum parser and panel**

Run:

```bash
git add laowang/laowang_baidu_transfer.user.js laowang/laowang_baidu_transfer.test.js
git commit -m "feat: render laowang resource summary panel"
```

## Task 3: Forum Purchase Confirmation, Link Extraction, and Task Queue

**Files:**
- Modify: `laowang/laowang_baidu_transfer.user.js`
- Modify: `laowang/laowang_baidu_transfer.test.js`

- [ ] **Step 1: Add task serialization tests**

Append:

```javascript
test('createTransferTask builds a serializable task', () => {
  const task = api.createTransferTask({
    sourceUrl: 'https://laowang.vip/thread-1-1-1.html',
    rawTitle: '[合集] 标题 [1G][百度盘]',
    shareUrl: 'https://pan.baidu.com/s/1abc',
    extractCode: 'abcd',
    password: 'pw',
    size: '1G'
  }, new Date('2026-06-12T10:00:00Z'));
  assert.strictEqual(task.title, '标题');
  assert.strictEqual(task.targetPath, '/老王转存/2026-06/标题/');
  assert.strictEqual(task.status, 'pending');
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
node laowang/laowang_baidu_transfer.test.js
```

Expected: FAIL because `createTransferTask` does not exist.

- [ ] **Step 3: Implement transfer task helper**

Add:

```javascript
function createTransferTask(input, date = new Date()) {
  return {
    id: `lwbt-${date.getTime()}`,
    sourceUrl: input.sourceUrl,
    title: cleanTitle(input.rawTitle || input.title),
    shareUrl: input.shareUrl,
    extractCode: input.extractCode || '',
    password: input.password || '',
    size: input.size || '',
    createdAt: date.toISOString(),
    targetPath: buildTargetPath(input.rawTitle || input.title, date),
    status: 'pending',
    error: ''
  };
}
```

Export `createTransferTask` in `api`.

- [ ] **Step 4: Implement GM storage wrapper**

Add:

```javascript
async function readTasks(api) {
  const raw = typeof GM_getValue === 'function' ? await GM_getValue(api.TASK_KEY, '[]') : localStorage.getItem(api.TASK_KEY) || '[]';
  try {
    return JSON.parse(raw);
  } catch (_error) {
    return [];
  }
}

async function writeTasks(api, tasks) {
  const raw = JSON.stringify(tasks);
  if (typeof GM_setValue === 'function') {
    await GM_setValue(api.TASK_KEY, raw);
  } else {
    localStorage.setItem(api.TASK_KEY, raw);
  }
}
```

- [ ] **Step 5: Implement forum transfer button flow**

Extend `bindForumPanel` so `#lwbt-transfer`:

```javascript
const transferButton = document.querySelector('#lwbt-transfer');
if (transferButton) {
  transferButton.addEventListener('click', async () => {
    const bodyText = document.body.innerText || '';
    if (/您需要\\s*登录/.test(bodyText) || /登录后/.test(bodyText)) {
      setStatus(document, '请先登录论坛后刷新页面');
      return;
    }
    const share = api.extractBaiduShare(bodyText);
    if (!share) {
      setStatus(document, '未找到百度分享链接，请先确认资源已购买并展开原帖');
      return;
    }
    const confirmed = root.confirm(`确认购买/保存该资源？\\n\\n标题: ${info.title}\\n大小: ${info.size}\\n目录: ${info.targetPath}`);
    if (!confirmed) {
      setStatus(document, '已取消');
      return;
    }
    const task = api.createTransferTask({
      sourceUrl: root.location.href,
      rawTitle: info.rawTitle,
      shareUrl: share.shareUrl,
      extractCode: share.extractCode,
      password: info.password,
      size: info.size
    });
    const tasks = await readTasks(api);
    tasks.push(task);
    await writeTasks(api, tasks);
    setStatus(document, '已创建百度网盘保存任务');
    if (typeof GM_openInTab === 'function') GM_openInTab(task.shareUrl, { active: true });
    else root.open(task.shareUrl, '_blank');
  });
}
```

Note: This first version creates a task only after the share link is visible. If the live forum exposes a separate purchase endpoint after login, add the endpoint-specific POST only after capturing it with logged-in evidence.

- [ ] **Step 6: Run tests**

Run:

```bash
node laowang/laowang_baidu_transfer.test.js
```

Expected: PASS.

- [ ] **Step 7: Commit task queue and forum flow**

Run:

```bash
git add laowang/laowang_baidu_transfer.user.js laowang/laowang_baidu_transfer.test.js
git commit -m "feat: queue baidu transfer tasks from forum posts"
```

## Task 4: Baidu Page Automation and Safe Fallbacks

**Files:**
- Modify: `laowang/laowang_baidu_transfer.user.js`

- [ ] **Step 1: Add DOM wait helper**

Add:

```javascript
function waitForSelector(document, selectors, timeoutMs = 15000) {
  const selectorList = Array.isArray(selectors) ? selectors : [selectors];
  return new Promise((resolve, reject) => {
    const found = selectorList.map((selector) => document.querySelector(selector)).find(Boolean);
    if (found) return resolve(found);
    const observer = new MutationObserver(() => {
      const node = selectorList.map((selector) => document.querySelector(selector)).find(Boolean);
      if (node) {
        observer.disconnect();
        resolve(node);
      }
    });
    observer.observe(document.documentElement, { childList: true, subtree: true });
    setTimeout(() => {
      observer.disconnect();
      reject(new Error(`Timed out waiting for ${selectorList.join(', ')}`));
    }, timeoutMs);
  });
}
```

- [ ] **Step 2: Add active task finder**

Add:

```javascript
async function findActiveBaiduTask(api, href) {
  const tasks = await readTasks(api);
  const active = tasks.find((task) => task.status === 'pending' && href.startsWith(task.shareUrl));
  return { tasks, active };
}
```

- [ ] **Step 3: Implement Baidu controller skeleton**

Update `main` Baidu branch:

```javascript
} else if (api.isBaiduPage(root.location.href)) {
  runBaidu(root, api).catch((error) => {
    console.error('[LWBT] Baidu automation failed', error);
  });
}
```

Add:

```javascript
async function runBaidu(root, api) {
  const document = root.document;
  const { tasks, active } = await findActiveBaiduTask(api, root.location.href);
  if (!active) return;
  showBaiduToast(document, `准备保存到 ${active.targetPath}`);
  try {
    await fillBaiduCodeIfNeeded(root, active);
    await saveBaiduShare(root, active);
    active.status = 'saved';
    active.savedAt = new Date().toISOString();
    await writeTasks(api, tasks);
    showBaiduToast(document, '保存任务已提交');
  } catch (error) {
    active.status = 'failed';
    active.error = error.message;
    await writeTasks(api, tasks);
    showBaiduToast(document, `自动保存失败：${error.message}，请手动保存`);
  }
}
```

- [ ] **Step 4: Implement code fill and save fallback selectors**

Add:

```javascript
async function fillBaiduCodeIfNeeded(root, task) {
  if (!task.extractCode) return;
  const document = root.document;
  const input = document.querySelector('input[placeholder*="提取码"], input[placeholder*="密码"], input[type="text"]');
  if (!input) return;
  input.value = task.extractCode;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  const button = document.querySelector('button, .g-button, .submit-btn');
  if (button) button.click();
  await new Promise((resolve) => setTimeout(resolve, 1500));
}

async function saveBaiduShare(root, task) {
  const document = root.document;
  const saveButton = await waitForSelector(document, [
    '[title*="保存"]',
    'button[aria-label*="保存"]',
    'button'
  ], 15000);
  saveButton.click();
  await new Promise((resolve) => setTimeout(resolve, 1000));
  const pathHint = document.createElement('div');
  pathHint.id = 'lwbt-baidu-path-hint';
  pathHint.textContent = `目标目录：${task.targetPath}`;
  document.body.appendChild(pathHint);
  throw new Error('百度网盘目录选择接口需登录态实测后绑定，已显示目标目录供手动确认');
}
```

This step intentionally stops at a safe fallback if Baidu directory selectors are not confirmed. Do not guess destructive or brittle selectors for directory creation.

- [ ] **Step 5: Run tests**

Run:

```bash
node laowang/laowang_baidu_transfer.test.js
```

Expected: PASS.

- [ ] **Step 6: Commit Baidu automation fallback**

Run:

```bash
git add laowang/laowang_baidu_transfer.user.js laowang/laowang_baidu_transfer.test.js
git commit -m "feat: add baidu transfer automation fallback"
```

## Task 5: Styling, Original Content Controls, and Manual Verification Notes

**Files:**
- Modify: `laowang/laowang_baidu_transfer.user.js`

- [ ] **Step 1: Add escaping, status, CSS, and field helpers**

Add:

```javascript
function escapeHtml(value) {
  return String(value || '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function fieldHtml(label, value) {
  return `<div class="lwbt-field"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || '-')}</strong></div>`;
}

function setStatus(document, message) {
  const node = document.querySelector('#lwbt-status');
  if (node) node.textContent = message;
}

function panelCss() {
  return `
    #lwbt-panel{margin:16px auto;max-width:1180px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    .lwbt-card{display:grid;grid-template-columns:minmax(0,1.08fr) minmax(300px,.92fr);gap:16px;border:1px solid #e5e7eb;border-radius:8px;background:#fff;padding:16px}
    .lwbt-info h2{margin:0 0 8px;font-size:22px;line-height:1.35;color:#111827}
    .lwbt-sub{margin:0 0 12px;color:#6b7280;font-size:13px}
    .lwbt-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
    .lwbt-field{background:#f3f4f6;border-radius:6px;padding:8px}
    .lwbt-field span{display:block;font-size:11px;color:#6b7280}
    .lwbt-field strong{display:block;margin-top:3px;color:#111827;font-size:14px}
    .lwbt-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
    .lwbt-actions button{border:0;border-radius:6px;padding:9px 12px;background:#2563eb;color:#fff;font-weight:700;cursor:pointer}
    .lwbt-actions button+button{background:#e5e7eb;color:#111827}
    .lwbt-status{margin-top:10px;color:#374151;font-size:13px}
    .lwbt-gallery{border:1px solid #e5e7eb;border-radius:8px;background:#fafafa;padding:10px}
    .lwbt-main{height:190px;display:flex;align-items:center;justify-content:center;background:#f3f4f6;border-radius:6px;overflow:hidden}
    .lwbt-main img{max-width:100%;max-height:100%;object-fit:contain}
    .lwbt-no-image{color:#6b7280;font-weight:700}
    .lwbt-thumbs{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-top:8px}
    .lwbt-thumb{height:48px;border:1px solid #d1d5db;border-radius:5px;background:#fff;overflow:hidden;padding:0;cursor:pointer}
    .lwbt-thumb img{width:100%;height:100%;object-fit:cover}
    @media(max-width:900px){.lwbt-card{grid-template-columns:1fr}.lwbt-grid{grid-template-columns:1fr 1fr}.lwbt-main{height:160px}}
  `;
}
```

- [ ] **Step 2: Add original content toggle**

In `bindForumPanel`, implement `#lwbt-toggle-original`:

```javascript
const toggleButton = document.querySelector('#lwbt-toggle-original');
if (toggleButton) {
  toggleButton.addEventListener('click', () => {
    document.body.classList.toggle('lwbt-show-original');
    toggleButton.textContent = document.body.classList.contains('lwbt-show-original') ? '折叠原帖' : '展开原帖';
  });
}
```

Then add CSS inside `panelCss()`:

```css
body:not(.lwbt-show-original) .deanbkjs,
body:not(.lwbt-show-original) [id^="post_"]:not(:first-of-type),
body:not(.lwbt-show-original) #postlistreply,
body:not(.lwbt-show-original) #f_pst{display:none!important}
```

- [ ] **Step 3: Add Baidu toast styling**

Add:

```javascript
function showBaiduToast(document, message) {
  let node = document.querySelector('#lwbt-baidu-toast');
  if (!node) {
    node = document.createElement('div');
    node.id = 'lwbt-baidu-toast';
    node.style.cssText = 'position:fixed;right:16px;top:16px;z-index:999999;background:#111827;color:#fff;padding:12px 14px;border-radius:8px;font-size:13px;max-width:360px;line-height:1.5';
    document.body.appendChild(node);
  }
  node.textContent = message;
}
```

- [ ] **Step 4: Run tests**

Run:

```bash
node laowang/laowang_baidu_transfer.test.js
```

Expected: PASS.

- [ ] **Step 5: Syntax check userscript**

Run:

```bash
node --check laowang/laowang_baidu_transfer.user.js
```

Expected: no output and exit code 0.

- [ ] **Step 6: Commit UI polish**

Run:

```bash
git add laowang/laowang_baidu_transfer.user.js laowang/laowang_baidu_transfer.test.js
git commit -m "feat: polish laowang baidu userscript ui"
```

## Task 6: Live Browser Smoke Test

**Files:**
- No source changes unless smoke test reveals a bug.

- [ ] **Step 1: Install or paste userscript manually for local smoke test**

Open Tampermonkey and install `laowang/laowang_baidu_transfer.user.js`, or paste it into a new script.

- [ ] **Step 2: Verify forum page enhancement**

Navigate to:

```text
https://laowang.vip/forum.php?mod=viewthread&tid=2821033
```

Expected:

- Summary panel appears above the thread.
- Title is `大美女【SkylarBlue】完美臀，超模身材`.
- Fields include `百度盘`, `自行打包`, `41V 74P`, `4.58G`, and `上老王论坛当老王`.
- Image area shows either a preview image or `登录后可预览`.

- [ ] **Step 3: Verify no purchase happens without confirmation**

Click `购买并保存到百度网盘` while not purchased or not logged in.

Expected: either a login/status message appears, or a browser confirmation dialog appears. No automatic purchase is submitted without explicit confirmation.

- [ ] **Step 4: Verify helper tests still pass**

Run:

```bash
node laowang/laowang_baidu_transfer.test.js
node --check laowang/laowang_baidu_transfer.user.js
```

Expected: all tests pass and syntax check exits 0.

- [ ] **Step 5: Commit smoke-test fixes if any**

If code changed during smoke testing:

```bash
git add laowang/laowang_baidu_transfer.user.js laowang/laowang_baidu_transfer.test.js
git commit -m "fix: address userscript smoke test findings"
```

If no code changed, skip this commit.
