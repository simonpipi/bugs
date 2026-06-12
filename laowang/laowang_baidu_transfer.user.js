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
