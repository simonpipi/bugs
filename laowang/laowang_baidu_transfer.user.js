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

  function findPendingTaskForUrl(tasks, href) {
    const currentUrl = String(href || '');
    return (tasks || []).find((task) => task && task.status === 'pending' && currentUrl.startsWith(task.shareUrl)) || null;
  }

  const api = {
    TASK_KEY,
    cleanText,
    cleanTitle,
    safePathSegment,
    buildTargetPath,
    extractBaiduShare,
    isForumPage,
    isBaiduPage,
    parseTypeInfo,
    isPreviewImage,
    createTransferTask,
    findPendingTaskForUrl
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
    injectForumPanel(root, api);
  } else if (api.isBaiduPage(root.location.href)) {
    runBaidu(root, api).catch((error) => {
      console.error('[LWBT] Baidu automation failed', error);
    });
  }
}

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
      const text = `${info.title}\n下载方式: ${info.downloadType}\n大小: ${info.size}\n解压密码: ${info.password}\n保存目录: ${info.targetPath}`;
      if (root.navigator.clipboard && root.navigator.clipboard.writeText) {
        await root.navigator.clipboard.writeText(text);
        setStatus(document, '已复制关键信息');
      } else {
        setStatus(document, '当前浏览器不支持自动复制，请手动复制面板信息');
      }
    });
  }
  const transferButton = document.querySelector('#lwbt-transfer');
  if (transferButton) {
    transferButton.addEventListener('click', async () => {
      const bodyText = document.body.innerText || '';
      if (/您需要\s*登录/.test(bodyText) || /登录后/.test(bodyText)) {
        setStatus(document, '请先登录论坛后刷新页面');
        return;
      }
      const share = api.extractBaiduShare(bodyText);
      if (!share) {
        setStatus(document, '未找到百度分享链接，请先确认资源已购买并展开原帖');
        return;
      }
      const confirmed = root.confirm(`确认购买/保存该资源？\n\n标题: ${info.title}\n大小: ${info.size}\n目录: ${info.targetPath}`);
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
      const tasks = await readTasks(root, api);
      tasks.push(task);
      await writeTasks(root, api, tasks);
      setStatus(document, '已创建百度网盘保存任务');
      if (typeof GM_openInTab === 'function') GM_openInTab(task.shareUrl, { active: true });
      else root.open(task.shareUrl, '_blank');
    });
  }
}

async function readTasks(root, api) {
  const fallbackStorage = root.localStorage;
  const raw = typeof GM_getValue === 'function' ? await GM_getValue(api.TASK_KEY, '[]') : fallbackStorage.getItem(api.TASK_KEY) || '[]';
  try {
    return JSON.parse(raw);
  } catch (_error) {
    return [];
  }
}

async function writeTasks(root, api, tasks) {
  const raw = JSON.stringify(tasks);
  if (typeof GM_setValue === 'function') {
    await GM_setValue(api.TASK_KEY, raw);
  } else {
    root.localStorage.setItem(api.TASK_KEY, raw);
  }
}

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

async function findActiveBaiduTask(root, api) {
  const tasks = await readTasks(root, api);
  const active = api.findPendingTaskForUrl(tasks, root.location.href);
  return { tasks, active };
}

async function runBaidu(root, api) {
  const document = root.document;
  const { tasks, active } = await findActiveBaiduTask(root, api);
  if (!active) return;
  showBaiduToast(document, `准备保存到 ${active.targetPath}`);
  try {
    await fillBaiduCodeIfNeeded(root, active);
    await saveBaiduShare(root, active);
    active.status = 'saved';
    active.savedAt = new Date().toISOString();
    await writeTasks(root, api, tasks);
    showBaiduToast(document, '保存任务已提交');
  } catch (error) {
    active.status = 'failed';
    active.error = error.message;
    await writeTasks(root, api, tasks);
    showBaiduToast(document, `自动保存失败：${error.message}，请手动保存`);
  }
}

async function fillBaiduCodeIfNeeded(root, task) {
  if (!task.extractCode) return;
  const document = root.document;
  const input = document.querySelector('input[placeholder*="提取码"], input[placeholder*="密码"], input[type="text"]');
  if (!input) return;
  input.value = task.extractCode;
  input.dispatchEvent(new root.Event('input', { bubbles: true }));
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
  pathHint.style.cssText = 'position:fixed;right:16px;top:72px;z-index:999999;background:#fff;color:#111827;border:1px solid #d1d5db;padding:10px 12px;border-radius:8px;font-size:13px;max-width:420px;';
  document.body.appendChild(pathHint);
  throw new Error('百度网盘目录选择接口需登录态实测后绑定，已显示目标目录供手动确认');
}

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
