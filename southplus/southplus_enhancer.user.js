// ==UserScript==
// @name         South Plus Browsing Enhancer
// @namespace    https://south-plus.org/
// @version      0.6.0
// @description  Local-only browsing improvements for South Plus: compact layout, quick navigation, read state, and local block rules.
// @author       local
// @match        https://south-plus.org/*
// @match        https://www.south-plus.net/*
// @match        https://bbs.blue-plus.net/*
// @match        https://white-plus.net/*
// @grant        none
// @run-at       document-end
// ==/UserScript==

(function factoryWrapper(root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(true);
    return;
  }

  var api = factory(false);
  api.init();
})(typeof globalThis !== 'undefined' ? globalThis : this, function createSouthPlusEnhancer(testMode) {
  'use strict';

  var APP = 'spEnhancer';
  var STORE_KEY = APP + ':settings:v1';
  var READ_KEY = APP + ':readThreads:v1';
  var WATCH_KEY = APP + ':watchThreads:v1';
  var DEFAULT_SETTINGS = {
    cleanMode: true,
    readerMode: true,
    immersiveRead: true,
    immersiveFontSize: 20,
    unifiedPreviewGallery: true,
    homeDashboard: true,
    adBlock: true,
    compactRead: true,
    unreadOnly: false,
    onlyOriginalAuthor: false,
    foldSticky: true,
    foldQuotes: true,
    hideUserProfile: false,
    titleKeywords: [],
    authorKeywords: [],
  };

  function parseThreadId(value) {
    var text = String(value || '');
    var match =
      text.match(/(?:^|[_-])(?:td|ajax)_(\d+)(?:\D|$)/) ||
      text.match(/(?:td|a_ajax)_(\d+)/) ||
      text.match(/[?&]tid=(\d+)/) ||
      text.match(/[?&]tid-(\d+)/) ||
      text.match(/read\.php\?tid[=-](\d+)/);
    return match ? match[1] : '';
  }

  function parseLineList(value) {
    var seen = {};
    return String(value || '')
      .split(/\r?\n/)
      .map(function trimLine(line) {
        return line.trim();
      })
      .filter(function keepUnique(line) {
        if (!line || seen[line]) return false;
        seen[line] = true;
        return true;
      });
  }

  function containsAny(value, needles) {
    var haystack = String(value || '').toLowerCase();
    return (needles || []).some(function hasNeedle(needle) {
      return haystack.indexOf(String(needle || '').toLowerCase()) !== -1;
    });
  }

  function matchesBlockRules(item, rules) {
    var data = item || {};
    var config = rules || {};
    return (
      containsAny(data.title, config.titleKeywords) ||
      containsAny(data.author, config.authorKeywords)
    );
  }

  function isPreviewImageCandidate(image) {
    var data = image || {};
    var src = String(data.src || '');
    var width = Number(data.naturalWidth || data.width || 0);
    var height = Number(data.naturalHeight || data.height || 0);
    var postIndex = Number(data.postIndex || 0);

    if (postIndex !== 0) return false;
    if (!src) return false;
    if (/\/images\/post\/smile\//i.test(src)) return false;
    if (/\/images\/.*(?:face|smile|emotion)/i.test(src)) return false;
    if (width === 0 && height === 0) return true;
    return width >= 120 || height >= 120;
  }

  function parseTodayCount(text) {
    var match = String(text || '').match(/\((\d+)\)\s*$/);
    return match ? Number(match[1]) : 0;
  }

  function isAdUrl(url) {
    var text = String(url || '').toLowerCase();
    return /(?:taobao|tmall|alimama|doubleclick|googlesyndication|adservice)/.test(text);
  }

  function detectPageType(url) {
    var text = String(url || '');
    if (/\/read\.php\?tid[=-]\d+/.test(text)) return 'read';
    if (/\/thread\.php\?fid[=-]\d+/.test(text)) return 'forum';
    if (/\/(?:index\.php)?(?:[?#].*)?$/.test(text)) return 'home';
    if (/\/simple\//.test(text)) return 'simple';
    return 'other';
  }

  function shouldUseImmersiveRead(settings, url) {
    return !!(settings && settings.immersiveRead) && detectPageType(url) === 'read';
  }

  function shouldUseHomeDashboard(settings, url) {
    return !!(settings && settings.homeDashboard) && detectPageType(url) === 'home';
  }

  function buildPageUrl(url, page) {
    var targetPage = Math.max(1, Number(page) || 1);
    var parsed = new URL(String(url || ''), 'https://south-plus.org/');
    var href = parsed.href;
    var thread = href.match(/read\.php\?tid[=-](\d+)/);
    var forum = href.match(/thread\.php\?fid[=-](\d+)/);

    if (thread) {
      return parsed.origin + '/read.php?tid-' + thread[1] + '-page-' + targetPage + '.html';
    }

    if (forum) {
      if (targetPage === 1) {
        return parsed.origin + '/thread.php?fid-' + forum[1] + '.html';
      }
      return parsed.origin + '/thread.php?fid-' + forum[1] + '-page-' + targetPage + '.html';
    }

    return href;
  }

  function safeJsonParse(value, fallback) {
    try {
      return JSON.parse(value);
    } catch (error) {
      return fallback;
    }
  }

  function getStorage() {
    if (typeof window === 'undefined' || !window.localStorage) return null;
    return window.localStorage;
  }

  function loadSettings() {
    var storage = getStorage();
    if (!storage) return copySettings(DEFAULT_SETTINGS);
    var stored = safeJsonParse(storage.getItem(STORE_KEY), {});
    return Object.assign(copySettings(DEFAULT_SETTINGS), stored || {});
  }

  function saveSettings(settings) {
    var storage = getStorage();
    if (!storage) return;
    storage.setItem(STORE_KEY, JSON.stringify(settings));
  }

  function copySettings(settings) {
    return JSON.parse(JSON.stringify(settings));
  }

  function loadMap(key) {
    var storage = getStorage();
    if (!storage) return {};
    return safeJsonParse(storage.getItem(key), {}) || {};
  }

  function saveMap(key, map) {
    var storage = getStorage();
    if (!storage) return;
    storage.setItem(key, JSON.stringify(map || {}));
  }

  function currentPageNumber(url) {
    var text = String(url || '');
    var match = text.match(/-page-(\d+)/);
    return match ? Number(match[1]) : 1;
  }

  function qs(selector, root) {
    return (root || document).querySelector(selector);
  }

  function qsa(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function createEl(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (typeof text === 'string') node.textContent = text;
    return node;
  }

  function injectStyles() {
    if (qs('#sp-enhancer-style')) return;
    var style = createEl('style');
    style.id = 'sp-enhancer-style';
    style.textContent = [
      ':root{--spx-bg:#f7f8fb;--spx-panel:#fff;--spx-line:#cbd5e1;--spx-text:#1f2937;--spx-sub:#64748b;--spx-accent:#0f766e;--spx-warn:#b45309;}',
      '.spx-adblock .spx-ad-hidden{display:none!important;}',
      '.spx-adblock #banner a[href*="taobao"],.spx-adblock #banner a[href*="tmall"],.spx-adblock #banner a[href*="equity"]{display:none!important;}',
      '.spx-adblock a[href*="taobao"],.spx-adblock a[href*="tmall"],.spx-adblock a[href*="alimama"]{display:none!important;}',
      '.spx-adblock img[src*="taobao"],.spx-adblock img[src*="tmall"],.spx-adblock img[src*="alimama"]{display:none!important;}',
      '.spx-adblock #banner{min-height:0!important;}',
      '.spx-reader body{background:#f4f6f8!important;color:#263238!important;font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",Arial,sans-serif!important;}',
      '.spx-reader a{color:#075985!important;text-decoration:none!important;}',
      '.spx-reader a:hover{text-decoration:underline!important;}',
      '.spx-reader #wrapA{max-width:1240px!important;margin:0 auto!important;}',
      '.spx-reader #main,.spx-reader #content{font-size:15px!important;line-height:1.65!important;}',
      '.spx-reader .t,.spx-reader .t3,.spx-reader .t5,.spx-reader .tr1,.spx-reader .tr2,.spx-reader .tr3{font-size:15px!important;}',
      '.spx-reader .tr3 td,.spx-reader .tr1 td{padding-top:8px!important;padding-bottom:8px!important;}',
      '.spx-reader td[id^="td_"]{font-size:15px!important;line-height:1.65!important;}',
      '.spx-reader td[id^="td_"] a[id^="a_ajax_"]{font-size:16px!important;line-height:1.65!important;font-weight:600!important;}',
      '.spx-reader td[id^="td_"] .s8{display:inline-block;margin-right:6px;padding:1px 6px;border-radius:4px;background:#e8f3ff;color:#075985!important;font-size:13px!important;}',
      '.spx-reader table.js-post{max-width:1040px!important;margin:14px auto!important;background:#fff!important;border:1px solid #d9e2ec!important;border-radius:8px!important;box-shadow:0 3px 12px rgba(15,23,42,.06)!important;overflow:hidden!important;}',
      '.spx-reader table.js-post td{font-size:15px!important;line-height:1.75!important;}',
      '.spx-reader .h1,.spx-reader [id^="subject_"]{font-size:18px!important;line-height:1.55!important;font-weight:700!important;color:#111827!important;}',
      '.spx-reader .tpc_content{box-sizing:border-box!important;max-width:900px!important;margin:0 auto!important;padding:14px 18px 20px!important;font-size:17px!important;line-height:1.95!important;letter-spacing:0!important;color:#1f2937!important;word-break:break-word!important;}',
      '.spx-reader .tpc_content br{line-height:2!important;}',
      '.spx-reader .tpc_content img{max-width:100%!important;height:auto!important;border-radius:4px!important;}',
      '.spx-reader .tiptop,.spx-reader .readbot{max-width:920px!important;margin-left:auto!important;margin-right:auto!important;color:#64748b!important;}',
      '.spx-reader .signature,.spx-reader .sigline{max-width:900px!important;margin-left:auto!important;margin-right:auto!important;color:#64748b!important;font-size:13px!important;}',
      '.spx-home-dashboard,.spx-home-dashboard body{width:100%!important;min-width:0!important;overflow-x:hidden!important;background:#eef2f5!important;color:#172033!important;}',
      '.spx-home-dashboard #wrapA,.spx-home-dashboard #main{box-sizing:border-box!important;width:100vw!important;max-width:none!important;margin:0!important;padding:0!important;background:#eef2f5!important;border:0!important;}',
      '.spx-home-dashboard #content{box-sizing:border-box!important;width:min(1680px,calc(100vw - 44px))!important;margin:16px auto 42px!important;display:block!important;background:transparent!important;}',
      '.spx-home-dashboard #spx-home-grid{display:grid!important;grid-template-columns:repeat(12,minmax(0,1fr))!important;gap:14px!important;}',
      '.spx-home-dashboard #toptool,.spx-home-dashboard #footer,.spx-home-dashboard .footer,.spx-home-dashboard #cate_info{display:none!important;}',
      '.spx-home-dashboard #header,.spx-home-dashboard #mainNav,.spx-home-dashboard #infobox,.spx-home-dashboard #notice{box-sizing:border-box!important;width:min(1680px,calc(100vw - 44px))!important;margin-left:auto!important;margin-right:auto!important;}',
      '.spx-home-dashboard #header{margin-top:10px!important;}',
      '.spx-home-dashboard #mainNav{position:sticky!important;top:0!important;z-index:9990!important;border-radius:8px!important;box-shadow:0 4px 16px rgba(15,23,42,.08)!important;overflow:visible!important;}',
      '.spx-home-dashboard #notice{display:block!important;background:#fff!important;border:1px solid #d7e1eb!important;border-radius:8px!important;padding:10px 14px!important;box-shadow:0 4px 14px rgba(15,23,42,.05)!important;}',
      '.spx-home-dashboard #notice table,.spx-home-dashboard #notice tbody,.spx-home-dashboard #notice tr{display:block!important;width:100%!important;}',
      '.spx-home-dashboard #notice td{display:block!important;width:auto!important;padding:4px 0!important;}',
      '.spx-home-dashboard .spx-home-quick{box-sizing:border-box!important;width:min(1680px,calc(100vw - 44px))!important;margin:14px auto 0!important;display:grid!important;grid-template-columns:repeat(auto-fit,minmax(160px,1fr))!important;gap:10px!important;}',
      '.spx-home-dashboard .spx-home-quick a{display:flex!important;align-items:center!important;justify-content:space-between!important;gap:8px!important;min-height:42px!important;padding:0 12px!important;background:#fff!important;border:1px solid #d7e1eb!important;border-radius:8px!important;color:#0f172a!important;text-decoration:none!important;font-weight:700!important;box-shadow:0 3px 12px rgba(15,23,42,.05)!important;}',
      '.spx-home-dashboard .spx-home-quick a span{font-size:12px!important;color:#64748b!important;font-weight:500!important;}',
      '.spx-home-dashboard .spx-home-module{grid-column:span 6!important;box-sizing:border-box!important;margin:0!important;background:#fff!important;border:1px solid #d7e1eb!important;border-radius:8px!important;box-shadow:0 6px 18px rgba(15,23,42,.06)!important;overflow:hidden!important;}',
      '.spx-home-dashboard .spx-home-module[data-spx-large="1"]{grid-column:span 12!important;}',
      '.spx-home-dashboard .spx-home-module>h2,.spx-home-dashboard .spx-home-module .h{display:flex!important;align-items:center!important;justify-content:space-between!important;min-height:38px!important;padding:0 14px!important;margin:0!important;background:#f8fafc!important;border-bottom:1px solid #e2e8f0!important;color:#0f172a!important;font-size:15px!important;font-weight:800!important;}',
      '.spx-home-dashboard .spx-home-module table,.spx-home-dashboard .spx-home-module tbody{display:block!important;width:100%!important;border:0!important;background:transparent!important;}',
      '.spx-home-dashboard .spx-home-module tr.tr2{display:none!important;}',
      '.spx-home-dashboard .spx-home-module tr.tr3{display:grid!important;grid-template-columns:minmax(220px,1.15fr) 120px minmax(260px,1fr)!important;gap:10px!important;align-items:center!important;margin:0!important;padding:10px 14px!important;border-bottom:1px solid #edf2f7!important;background:#fff!important;}',
      '.spx-home-dashboard .spx-home-module tr.tr3:hover{background:#f8fbff!important;}',
      '.spx-home-dashboard .spx-home-module tr.tr3:last-child{border-bottom:0!important;}',
      '.spx-home-dashboard .spx-home-module tr.tr3>td{display:block!important;width:auto!important;padding:0!important;border:0!important;background:transparent!important;font-size:13px!important;line-height:1.45!important;color:#475569!important;}',
      '.spx-home-dashboard .spx-home-module tr.tr3>td:first-child{display:none!important;}',
      '.spx-home-dashboard .spx-home-module [id^="fn_"] a,.spx-home-dashboard .spx-home-module [id^="fn_"]{font-size:15px!important;font-weight:800!important;color:#0f172a!important;line-height:1.4!important;}',
      '.spx-home-dashboard .spx-home-module [id^="desc_"]{margin-top:4px!important;color:#64748b!important;font-size:12px!important;}',
      '.spx-home-dashboard .spx-home-hot [id^="fn_"] a,.spx-home-dashboard .spx-home-hot [id^="fn_"]{color:#075985!important;}',
      '.spx-home-dashboard .spx-home-badge{display:inline-flex!important;align-items:center!important;justify-content:center!important;min-width:26px!important;height:20px!important;margin-left:6px!important;padding:0 7px!important;border-radius:999px!important;background:#e0f2fe!important;color:#0369a1!important;font-size:12px!important;font-weight:800!important;}',
      '.spx-home-dashboard .spx-home-collapse{border:0!important;background:transparent!important;color:#64748b!important;font-size:12px!important;cursor:pointer!important;}',
      '.spx-immersive-read,.spx-immersive-read body{width:100%!important;min-width:0!important;overflow-x:hidden!important;background:#eef2f5!important;}',
      '.spx-immersive-read #toptool,.spx-immersive-read #header,.spx-immersive-read #banner,.spx-immersive-read #mainNav,.spx-immersive-read #infobox,.spx-immersive-read #breadcrumbs,.spx-immersive-read .crumbs-item,.spx-immersive-read #footer,.spx-immersive-read .footer,.spx-immersive-read #bottom,.spx-immersive-read #music,.spx-immersive-read #readlog,.spx-immersive-read #threadlog{display:none!important;}',
      '.spx-immersive-read #wrapA,.spx-immersive-read #main,.spx-immersive-read #content{box-sizing:border-box!important;width:100vw!important;max-width:none!important;margin:0!important;padding:0!important;background:#eef2f5!important;border:0!important;}',
      '.spx-immersive-read #content>table:not(.js-post),.spx-immersive-read #main>table:not(.js-post){width:min(1180px,calc(100vw - 72px))!important;margin:12px auto!important;}',
      '.spx-immersive-read table.js-post{box-sizing:border-box!important;width:min(1180px,calc(100vw - 88px))!important;max-width:none!important;margin:18px auto!important;border:1px solid #d6dee8!important;border-radius:8px!important;background:#fff!important;box-shadow:0 8px 26px rgba(15,23,42,.08)!important;}',
      '.spx-immersive-read table.js-post>tbody>tr>td:first-child{display:none!important;}',
      '.spx-immersive-read table.js-post>tbody>tr>td{display:block!important;box-sizing:border-box!important;width:100%!important;padding:0!important;border:0!important;background:#fff!important;}',
      '.spx-immersive-read .spx-post-tools{box-sizing:border-box!important;max-width:980px!important;margin:0 auto!important;padding:8px 18px 0!important;color:#94a3b8!important;font-size:12px!important;opacity:.62!important;}',
      '.spx-immersive-read .spx-post-tools:hover{opacity:1!important;}',
      '.spx-immersive-read .spx-post-tools span{font-size:12px!important;font-weight:400!important;color:#94a3b8!important;}',
      '.spx-immersive-read .spx-post-tools button{font-size:12px!important;color:#94a3b8!important;border-color:#e2e8f0!important;background:#f8fafc!important;padding:1px 7px!important;}',
      '.spx-immersive-read .spx-preview-panel{box-sizing:border-box!important;max-width:1180px!important;margin:0 auto 14px!important;padding:12px 18px 16px!important;background:#fff!important;border:1px solid #d7e1eb!important;border-radius:8px!important;box-shadow:0 6px 18px rgba(15,23,42,.06)!important;}',
      '.spx-immersive-read .spx-preview-header{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:0 0 10px;font-size:13px!important;color:#64748b!important;}',
      '.spx-immersive-read .spx-preview-header strong{font-size:14px!important;color:#0f172a!important;}',
      '.spx-immersive-read .spx-preview-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;}',
      '.spx-immersive-read .spx-preview-item{display:block;overflow:hidden;border:1px solid #e2e8f0;border-radius:8px;background:#f8fafc;text-decoration:none;}',
      '.spx-immersive-read .spx-preview-item img{display:block;width:100%;height:180px;object-fit:cover;background:#fff;}',
      '.spx-immersive-read .spx-preview-item span{display:block;padding:6px 8px;font-size:12px;line-height:1.35;color:#475569;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
      '.spx-immersive-read .spx-preview-empty{padding:10px 2px;color:#94a3b8;font-size:13px;}',
      '.spx-immersive-read .spx-preview-source{display:none!important;}',
      '.spx-immersive-read .h1,.spx-immersive-read [id^="subject_"]{display:block!important;box-sizing:border-box!important;max-width:980px!important;margin:0 auto!important;padding:22px 18px 8px!important;font-size:21px!important;line-height:1.45!important;color:#111827!important;}',
      '.spx-immersive-read .tpc_content{max-width:980px!important;margin:0 auto!important;padding:18px 34px 34px!important;font-size:var(--spx-immersive-font-size,20px)!important;line-height:2.06!important;color:#172033!important;background:#fff!important;}',
      '.spx-immersive-read .tiptop,.spx-immersive-read .readbot,.spx-immersive-read .signature,.spx-immersive-read .sigline{max-width:980px!important;margin-left:auto!important;margin-right:auto!important;padding-left:18px!important;padding-right:18px!important;color:#94a3b8!important;font-size:12px!important;opacity:.58!important;}',
      '.spx-immersive-read textarea,.spx-immersive-read input[type="text"]{font-size:16px!important;}',
      '.spx-clean #infobox,.spx-clean #notice,.spx-clean #footer,.spx-clean .footer{display:none!important;}',
      '.spx-clean #wrapA{max-width:1180px!important;margin:0 auto!important;}',
      '.spx-clean #main{margin-top:8px!important;}',
      '.spx-clean table{border-collapse:collapse;}',
      '.spx-toolbar{position:fixed;right:14px;bottom:18px;z-index:99999;display:flex;flex-direction:column;gap:6px;font:12px/1.2 Arial,Helvetica,sans-serif;}',
      '.spx-toolbar button,.spx-toolbar a{width:42px;height:30px;border:1px solid var(--spx-line);border-radius:6px;background:var(--spx-panel);color:var(--spx-text);box-shadow:0 2px 8px rgba(15,23,42,.12);cursor:pointer;text-align:center;text-decoration:none;display:flex;align-items:center;justify-content:center;padding:0;}',
      '.spx-toolbar button:hover,.spx-toolbar a:hover{border-color:var(--spx-accent);color:var(--spx-accent);}',
      '.spx-toolbar .spx-active{background:#e6fffb;border-color:var(--spx-accent);color:var(--spx-accent);font-weight:bold;}',
      '.spx-settings{position:fixed;right:66px;bottom:18px;width:min(360px,calc(100vw - 24px));max-height:80vh;overflow:auto;z-index:100000;background:var(--spx-panel);border:1px solid var(--spx-line);box-shadow:0 12px 36px rgba(15,23,42,.24);border-radius:8px;padding:12px;color:var(--spx-text);font:13px/1.45 Arial,Helvetica,sans-serif;}',
      '.spx-settings[hidden]{display:none!important;}',
      '.spx-settings h3{margin:0 0 10px;font-size:15px;}',
      '.spx-settings label{display:flex;gap:8px;align-items:center;margin:7px 0;}',
      '.spx-settings textarea{box-sizing:border-box;width:100%;min-height:74px;border:1px solid var(--spx-line);border-radius:6px;padding:7px;font:12px/1.4 monospace;}',
      '.spx-settings .spx-row{display:flex;gap:8px;margin-top:10px;}',
      '.spx-settings button{border:1px solid var(--spx-line);border-radius:6px;background:#fff;padding:6px 10px;cursor:pointer;}',
      '.spx-settings .spx-primary{background:var(--spx-accent);border-color:var(--spx-accent);color:#fff;}',
      '.spx-fold-box{border:1px dashed var(--spx-line);background:var(--spx-bg);padding:8px;margin:8px 0;border-radius:6px;color:var(--spx-sub);}',
      '.spx-fold-box button{margin-left:8px;border:1px solid var(--spx-line);background:#fff;border-radius:5px;padding:2px 8px;cursor:pointer;}',
      '.spx-read-thread{opacity:.48;}',
      '.spx-hidden-rule{display:none!important;}',
      '.spx-unread-hidden{display:none!important;}',
      '.spx-thread-tools{display:inline-flex;gap:4px;margin-left:8px;vertical-align:middle;}',
      '.spx-thread-tools button{border:1px solid var(--spx-line);background:#fff;border-radius:4px;color:var(--spx-sub);font-size:12px;line-height:16px;padding:0 5px;cursor:pointer;}',
      '.spx-thread-tools button:hover{color:var(--spx-accent);border-color:var(--spx-accent);}',
      '.spx-watch-badge{display:inline-block;margin-left:5px;color:var(--spx-warn);font-weight:bold;}',
      '.spx-post-tools{display:flex;gap:6px;justify-content:flex-end;margin:4px 0;}',
      '.spx-post-tools button{border:1px solid var(--spx-line);background:#fff;border-radius:5px;padding:2px 8px;cursor:pointer;color:var(--spx-sub);}',
      '.spx-post-hidden{display:none!important;}',
      '.spx-compact-read .user-pic,.spx-compact-read .user-info,.spx-compact-read .readprofile,.spx-hide-profile .user-pic,.spx-hide-profile .user-info,.spx-hide-profile .readprofile{display:none!important;}',
      '.spx-compact-read:not(.spx-reader) .tpc_content{font-size:14px;line-height:1.75;max-width:920px;}',
      '.spx-folded-quote{max-height:110px;overflow:hidden;position:relative;border-bottom:1px dashed var(--spx-line);}',
      '.spx-folded-quote:after{content:"";position:absolute;left:0;right:0;bottom:0;height:30px;background:linear-gradient(transparent,var(--spx-panel));}',
      '@media(max-width:900px){.spx-home-dashboard #content{width:calc(100vw - 16px)!important;margin:10px 8px 34px!important}.spx-home-dashboard #spx-home-grid{grid-template-columns:1fr!important}.spx-home-dashboard .spx-home-module,.spx-home-dashboard .spx-home-module[data-spx-large="1"]{grid-column:1!important}.spx-home-dashboard #header,.spx-home-dashboard #mainNav,.spx-home-dashboard #infobox,.spx-home-dashboard #notice,.spx-home-dashboard .spx-home-quick{width:calc(100vw - 16px)!important}.spx-home-dashboard .spx-home-module tr.tr3{grid-template-columns:1fr!important;gap:4px!important}.spx-home-dashboard .spx-home-module tr.tr3>td:first-child{display:none!important}}',
      '@media(max-width:760px){.spx-reader body{font-size:16px!important}.spx-reader #wrapA{width:auto!important;margin:0 6px!important}.spx-reader .tpc_content{font-size:17px!important;line-height:1.9!important;padding:12px!important}.spx-immersive-read #wrapA,.spx-immersive-read #main,.spx-immersive-read #content{width:100vw!important;margin:0!important}.spx-immersive-read table.js-post{width:calc(100vw - 14px)!important;margin:10px 7px!important}.spx-immersive-read .spx-preview-panel{width:calc(100vw - 14px)!important;margin:8px 7px!important;padding:10px!important}.spx-immersive-read .spx-preview-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.spx-immersive-read .spx-preview-item img{height:132px}.spx-immersive-read .h1,.spx-immersive-read [id^="subject_"]{font-size:19px!important;padding:16px 14px 6px!important}.spx-immersive-read .tpc_content{font-size:var(--spx-immersive-font-size,20px)!important;line-height:1.98!important;padding:14px!important}.spx-toolbar{right:8px;bottom:8px}.spx-toolbar button,.spx-toolbar a{width:38px;height:30px}.spx-settings{right:8px;bottom:52px}}',
    ].join('\n');
    document.head.appendChild(style);
  }

  function setBodyClasses(settings) {
    document.documentElement.classList.toggle('spx-adblock', !!settings.adBlock);
    document.documentElement.classList.toggle('spx-clean', !!settings.cleanMode);
    document.documentElement.classList.toggle('spx-reader', !!settings.readerMode);
    document.documentElement.classList.toggle('spx-immersive-read', shouldUseImmersiveRead(settings, location.href));
    document.documentElement.classList.toggle('spx-home-dashboard', shouldUseHomeDashboard(settings, location.href));
    document.documentElement.classList.toggle('spx-compact-read', !!settings.compactRead);
    document.documentElement.classList.toggle('spx-hide-profile', !!settings.hideUserProfile);
    document.documentElement.style.setProperty('--spx-immersive-font-size', String(settings.immersiveFontSize || 20) + 'px');
  }

  function extractThreadCellInfo(cell) {
    var row = cell.closest('tr') || cell;
    var id = parseThreadId(cell.id);
    var titleLink = qs('#a_ajax_' + id, row) || qs('a[href*="read.php?tid"]', row);
    var authorLink = qs('a.bl[href*="u.php"]', row);
    return {
      id: id,
      cell: cell,
      row: row,
      titleLink: titleLink,
      title: titleLink ? titleLink.textContent.trim() : cell.textContent.trim(),
      author: authorLink ? authorLink.textContent.trim() : '',
    };
  }

  function isStickyCell(cell) {
    var text = (cell.textContent || '').trim();
    if (!cell.id) return false;
    var tid = Number(parseThreadId(cell.id));
    if (!tid) return false;
    if (/\[公告\]|版规|指南|长期招人|Q&A|新人报道/.test(text)) return true;
    return tid < 1000000;
  }

  function foldStickyThreads(settings) {
    if (!settings.foldSticky || detectPageType(location.href) !== 'forum') {
      restoreStickyThreads();
      return;
    }
    var stickyCells = qsa('td[id^="td_"]').filter(isStickyCell);
    if (!stickyCells.length || qs('#spx-sticky-fold-box')) return;

    var box = createEl('div', 'spx-fold-box');
    box.id = 'spx-sticky-fold-box';
    box.textContent = '已折叠 ' + stickyCells.length + ' 个公告/置顶帖';
    var button = createEl('button', '', '展开');
    button.addEventListener('click', function toggleSticky() {
      var hidden = stickyCells.some(function isHidden(cell) {
        return (cell.closest('tr') || cell).style.display === 'none';
      });
      stickyCells.forEach(function toggleCell(cell) {
        (cell.closest('tr') || cell).style.display = hidden ? '' : 'none';
      });
      button.textContent = hidden ? '折叠' : '展开';
    });
    box.appendChild(button);
    stickyCells.forEach(function hideCell(cell) {
      (cell.closest('tr') || cell).style.display = 'none';
    });
    var firstRow = stickyCells[0].closest('tr');
    if (firstRow && firstRow.parentNode) {
      firstRow.parentNode.insertBefore(boxRow(box), firstRow);
    }
  }

  function restoreStickyThreads() {
    var foldBox = qs('#spx-sticky-fold-box');
    if (foldBox) {
      var foldRow = foldBox.closest('tr');
      if (foldRow) foldRow.remove();
    }
    qsa('td[id^="td_"]').filter(isStickyCell).forEach(function showCell(cell) {
      var row = cell.closest('tr') || cell;
      row.style.display = '';
    });
  }

  function boxRow(content) {
    var tr = createEl('tr');
    var td = createEl('td');
    td.colSpan = 8;
    td.appendChild(content);
    tr.appendChild(td);
    return tr;
  }

  function enhanceThreadList(settings, state) {
    if (detectPageType(location.href) !== 'forum') return;
    var cells = qsa('td[id^="td_"]').filter(function realThreadCell(cell) {
      return parseThreadId(cell.id) && qs('a[id^="a_ajax_"]', cell);
    });

    cells.forEach(function enhanceCell(cell) {
      var info = extractThreadCellInfo(cell);
      if (!info.id || !info.titleLink) return;

      var isRead = !!state.read[info.id];
      info.row.classList.toggle('spx-read-thread', isRead);
      info.row.classList.toggle('spx-unread-hidden', !!settings.unreadOnly && isRead);
      info.row.classList.toggle('spx-hidden-rule', matchesBlockRules(info, settings));

      if (state.watch[info.id] && !qs('.spx-watch-badge', info.cell)) {
        info.titleLink.insertAdjacentElement('afterend', createEl('span', 'spx-watch-badge', '★'));
      }

      if (qs('.spx-thread-tools', info.cell)) return;
      var tools = createEl('span', 'spx-thread-tools');
      var watchButton = createEl('button', '', state.watch[info.id] ? '已存' : '稍后');
      var titleBlockButton = createEl('button', '', '屏题');
      var authorBlockButton = createEl('button', '', '屏人');

      watchButton.title = '切换本地稍后看';
      titleBlockButton.title = '把标题加入本地屏蔽关键词';
      authorBlockButton.title = '把作者加入本地屏蔽关键词';

      watchButton.addEventListener('click', function toggleWatch(event) {
        event.preventDefault();
        event.stopPropagation();
        if (state.watch[info.id]) {
          delete state.watch[info.id];
          watchButton.textContent = '稍后';
          var badge = qs('.spx-watch-badge', info.cell);
          if (badge) badge.remove();
        } else {
          state.watch[info.id] = {
            title: info.title,
            url: info.titleLink.href,
            savedAt: Date.now(),
          };
          watchButton.textContent = '已存';
          info.titleLink.insertAdjacentElement('afterend', createEl('span', 'spx-watch-badge', '★'));
        }
        saveMap(WATCH_KEY, state.watch);
      });

      titleBlockButton.addEventListener('click', function blockTitle(event) {
        event.preventDefault();
        event.stopPropagation();
        var keyword = window.prompt('添加标题屏蔽关键词', info.title.slice(0, 30));
        if (!keyword) return;
        settings.titleKeywords = parseLineList(settings.titleKeywords.concat([keyword]).join('\n'));
        saveSettings(settings);
        enhanceAll(settings, state);
      });

      authorBlockButton.addEventListener('click', function blockAuthor(event) {
        event.preventDefault();
        event.stopPropagation();
        if (!info.author) return;
        settings.authorKeywords = parseLineList(settings.authorKeywords.concat([info.author]).join('\n'));
        saveSettings(settings);
        enhanceAll(settings, state);
      });

      tools.appendChild(watchButton);
      tools.appendChild(titleBlockButton);
      if (info.author) tools.appendChild(authorBlockButton);
      info.titleLink.insertAdjacentElement('afterend', tools);

      info.titleLink.addEventListener('click', function markRead() {
        state.read[info.id] = Date.now();
        saveMap(READ_KEY, state.read);
      }, { capture: true });
    });

    foldStickyThreads(settings);
  }

  function getPostAuthor(post) {
    var profileText = '';
    var profile = qs('.readprofile', post) || qs('.user-info', post);
    if (profile) profileText = profile.textContent.replace(/\s+/g, ' ').trim();
    var userLink = qs('a[href*="u.php?action-show"]', post) || qs('.readprofile a', post);
    var userText = userLink ? userLink.textContent.trim() : '';
    return userText || profileText;
  }

  function enhanceReadPage(settings, state) {
    if (detectPageType(location.href) !== 'read') return;
    var tid = parseThreadId(location.href);
    if (tid) {
      state.read[tid] = Date.now();
      saveMap(READ_KEY, state.read);
    }

    var posts = qsa('table.js-post');
    var originalAuthor = posts.length ? getPostAuthor(posts[0]) : '';

    posts.forEach(function enhancePost(post, index) {
      var author = getPostAuthor(post);
      var content = qs('.tpc_content', post);
      if (!content) return;

      post.classList.toggle('spx-post-hidden', matchesBlockRules({ title: content.textContent, author: author }, settings));
      if (settings.onlyOriginalAuthor && originalAuthor && author && author !== originalAuthor) {
        post.classList.add('spx-post-hidden');
      }

      if (!qs('.spx-post-tools', post)) {
        var tools = createEl('div', 'spx-post-tools');
        var floor = createEl('span', '', index === 0 ? '楼主' : 'B' + index + 'F');
        var blockAuthor = createEl('button', '', '屏蔽此人');
        var copyLink = createEl('button', '', '复制链接');
        floor.style.marginRight = 'auto';

        blockAuthor.addEventListener('click', function addAuthorBlock() {
          if (!author) return;
          settings.authorKeywords = parseLineList(settings.authorKeywords.concat([author]).join('\n'));
          saveSettings(settings);
          enhanceAll(settings, state);
        });

        copyLink.addEventListener('click', function copyPostLink() {
          var hash = '';
          var anchor = qs('a[name]', post) || qs('[id^="read_"]', post);
          if (anchor) hash = '#' + (anchor.getAttribute('name') || anchor.id);
          navigator.clipboard.writeText(location.href.split('#')[0] + hash).catch(function noop() {});
        });

        tools.appendChild(floor);
        tools.appendChild(blockAuthor);
        tools.appendChild(copyLink);
        post.insertBefore(tools, post.firstChild);
      }
    });

    enhancePreviewGallery(settings, posts);
    if (settings.foldQuotes) foldLongReadBlocks();
  }

  function enhancePreviewGallery(settings, posts) {
    restorePreviewGallery();
    if (!settings.unifiedPreviewGallery || !posts || !posts.length) return;

    var firstPost = posts[0];
    var content = qs('.tpc_content', firstPost);
    if (!content) return;

    var previewImages = qsa('img', content)
      .map(function mapImage(img) {
        return {
          node: img,
          src: img.currentSrc || img.src,
          naturalWidth: img.naturalWidth,
          naturalHeight: img.naturalHeight,
          postIndex: 0,
        };
      })
      .filter(isPreviewImageCandidate);

    var seen = {};
    previewImages = previewImages.filter(function uniqueImage(item) {
      if (seen[item.src]) return false;
      seen[item.src] = true;
      return true;
    });

    if (!previewImages.length) return;

    var panel = createEl('section', 'spx-preview-panel');
    panel.id = 'spx-preview-panel';
    var header = createEl('div', 'spx-preview-header');
    header.innerHTML = '<strong>预览图</strong><span>' + previewImages.length + ' 张，点击打开原图</span>';
    var grid = createEl('div', 'spx-preview-grid');

    previewImages.forEach(function appendPreview(item, index) {
      item.node.classList.add('spx-preview-source');
      item.node.dataset.spxPreviewSource = '1';

      var link = createEl('a', 'spx-preview-item');
      link.href = item.src;
      link.target = '_blank';
      link.rel = 'noreferrer';
      link.title = '打开第 ' + (index + 1) + ' 张原图';

      var thumb = createEl('img');
      thumb.src = item.src;
      thumb.loading = 'lazy';
      thumb.alt = '预览图 ' + (index + 1);

      var label = createEl('span', '', '图 ' + (index + 1));
      link.appendChild(thumb);
      link.appendChild(label);
      grid.appendChild(link);
    });

    panel.appendChild(header);
    panel.appendChild(grid);

    var subject = qs('[id^="subject_"]', firstPost);
    if (subject && subject.parentNode) {
      subject.insertAdjacentElement('afterend', panel);
    } else {
      firstPost.insertBefore(panel, firstPost.firstChild);
    }
  }

  function restorePreviewGallery() {
    var panel = qs('#spx-preview-panel');
    if (panel) panel.remove();
    qsa('[data-spx-preview-source="1"]').forEach(function restoreImage(img) {
      img.classList.remove('spx-preview-source');
      delete img.dataset.spxPreviewSource;
    });
  }

  function foldLongReadBlocks() {
    qsa('.quote, blockquote, .blockquote, .tpc_content .f12').forEach(function fold(node) {
      if (node.dataset.spxFolded) return;
      if ((node.textContent || '').length < 220 && node.scrollHeight < 150) return;
      node.dataset.spxFolded = '1';
      node.classList.add('spx-folded-quote');
      var button = createEl('button', '', '展开引用');
      button.style.margin = '4px 0 8px';
      button.addEventListener('click', function expand() {
        node.classList.remove('spx-folded-quote');
        button.remove();
      });
      node.insertAdjacentElement('afterend', button);
    });
  }

  function createSettingsPanel(settings, state) {
    var panel = qs('#spx-settings');
    if (panel) return panel;

    panel = createEl('div', 'spx-settings');
    panel.id = 'spx-settings';
    panel.hidden = true;
    panel.innerHTML = [
      '<h3>South Plus 增强设置</h3>',
      '<label><input type="checkbox" data-key="adBlock"> 隐藏广告</label>',
      '<label><input type="checkbox" data-key="cleanMode"> 清爽模式</label>',
      '<label><input type="checkbox" data-key="homeDashboard"> 首页模块全屏</label>',
      '<label><input type="checkbox" data-key="readerMode"> 阅读排版优化</label>',
      '<label><input type="checkbox" data-key="immersiveRead"> 帖子页沉浸全屏</label>',
      '<label><input type="checkbox" data-key="unifiedPreviewGallery"> 预览图集中显示</label>',
      '<label><input type="checkbox" data-key="compactRead"> 阅读页紧凑</label>',
      '<label><input type="checkbox" data-key="foldSticky"> 折叠公告/置顶</label>',
      '<label><input type="checkbox" data-key="foldQuotes"> 折叠长引用</label>',
      '<label><input type="checkbox" data-key="hideUserProfile"> 隐藏头像资料</label>',
      '<label><input type="checkbox" data-key="unreadOnly"> 列表只看未读</label>',
      '<label><input type="checkbox" data-key="onlyOriginalAuthor"> 阅读页只看楼主</label>',
      '<div>标题屏蔽关键词，每行一个</div>',
      '<textarea data-list="titleKeywords"></textarea>',
      '<div>作者屏蔽关键词，每行一个</div>',
      '<textarea data-list="authorKeywords"></textarea>',
      '<div class="spx-row">',
      '<button class="spx-primary" data-action="save">保存</button>',
      '<button data-action="clear-read">清空已读</button>',
      '<button data-action="close">关闭</button>',
      '</div>',
    ].join('');
    document.body.appendChild(panel);

    function syncForm() {
      qsa('input[data-key]', panel).forEach(function syncCheckbox(input) {
        input.checked = !!settings[input.dataset.key];
      });
      qsa('textarea[data-list]', panel).forEach(function syncList(textarea) {
        textarea.value = (settings[textarea.dataset.list] || []).join('\n');
      });
    }

    function saveForm() {
      qsa('input[data-key]', panel).forEach(function readCheckbox(input) {
        settings[input.dataset.key] = input.checked;
      });
      qsa('textarea[data-list]', panel).forEach(function readList(textarea) {
        settings[textarea.dataset.list] = parseLineList(textarea.value);
      });
      saveSettings(settings);
      enhanceAll(settings, state);
    }

    panel.addEventListener('click', function handleSettingsClick(event) {
      var action = event.target && event.target.dataset && event.target.dataset.action;
      if (!action) return;
      if (action === 'save') {
        saveForm();
        panel.hidden = true;
      }
      if (action === 'close') panel.hidden = true;
      if (action === 'clear-read') {
        state.read = {};
        saveMap(READ_KEY, state.read);
        enhanceAll(settings, state);
      }
    });

    panel.spxSync = syncForm;
    syncForm();
    return panel;
  }

  function createToolbar(settings, state) {
    if (qs('#spx-toolbar')) return;
    var toolbar = createEl('div', 'spx-toolbar');
    toolbar.id = 'spx-toolbar';
    var type = detectPageType(location.href);
    var page = currentPageNumber(location.href);

    toolbar.appendChild(toolbarButton('顶', '回到顶部', function top() {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }));
    toolbar.appendChild(toolbarButton('底', '滚到底部', function bottom() {
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' });
    }));

    if (type === 'forum' || type === 'read') {
      toolbar.appendChild(toolbarLink('上', '上一页', buildPageUrl(location.href, Math.max(1, page - 1))));
      toolbar.appendChild(toolbarLink('下', '下一页', buildPageUrl(location.href, page + 1)));
    }

    toolbar.appendChild(toolbarLink('新', '最新帖子', location.origin + '/search2.php?orderway-postdate-asc-desc-newatc-1.html'));
    toolbar.appendChild(toolbarLink('首', '论坛首页', location.origin + '/index.php'));

    var cleanButton = toolbarButton('净', '切换清爽模式', function toggleClean() {
      settings.cleanMode = !settings.cleanMode;
      saveSettings(settings);
      enhanceAll(settings, state);
      cleanButton.classList.toggle('spx-active', settings.cleanMode);
    });
    cleanButton.classList.toggle('spx-active', settings.cleanMode);
    toolbar.appendChild(cleanButton);

    var readerButton = toolbarButton('字', '切换阅读排版优化', function toggleReader() {
      settings.readerMode = !settings.readerMode;
      saveSettings(settings);
      enhanceAll(settings, state);
      readerButton.classList.toggle('spx-active', settings.readerMode);
    });
    readerButton.classList.toggle('spx-active', settings.readerMode);
    toolbar.appendChild(readerButton);

    var adButton = toolbarButton('广', '切换隐藏广告', function toggleAdBlock() {
      settings.adBlock = !settings.adBlock;
      saveSettings(settings);
      enhanceAll(settings, state);
      adButton.classList.toggle('spx-active', settings.adBlock);
    });
    adButton.classList.toggle('spx-active', settings.adBlock);
    toolbar.appendChild(adButton);

    if (type === 'home') {
      var homeButton = toolbarButton('模', '切换首页模块全屏', function toggleHomeDashboard() {
        settings.homeDashboard = !settings.homeDashboard;
        saveSettings(settings);
        enhanceAll(settings, state);
        homeButton.classList.toggle('spx-active', settings.homeDashboard);
      });
      homeButton.classList.toggle('spx-active', settings.homeDashboard);
      toolbar.appendChild(homeButton);
    }

    if (type === 'read') {
      var immersiveButton = toolbarButton('屏', '切换帖子页沉浸全屏', function toggleImmersive() {
        settings.immersiveRead = !settings.immersiveRead;
        saveSettings(settings);
        enhanceAll(settings, state);
        immersiveButton.classList.toggle('spx-active', settings.immersiveRead);
      });
      immersiveButton.classList.toggle('spx-active', settings.immersiveRead);
      toolbar.appendChild(immersiveButton);

      var previewButton = toolbarButton('图', '切换预览图集中显示', function togglePreviewGallery() {
        settings.unifiedPreviewGallery = !settings.unifiedPreviewGallery;
        saveSettings(settings);
        enhanceAll(settings, state);
        previewButton.classList.toggle('spx-active', settings.unifiedPreviewGallery);
      });
      previewButton.classList.toggle('spx-active', settings.unifiedPreviewGallery);
      toolbar.appendChild(previewButton);
    }

    if (type === 'forum') {
      var unreadButton = toolbarButton('未', '只看未读', function toggleUnread() {
        settings.unreadOnly = !settings.unreadOnly;
        saveSettings(settings);
        enhanceAll(settings, state);
        unreadButton.classList.toggle('spx-active', settings.unreadOnly);
      });
      unreadButton.classList.toggle('spx-active', settings.unreadOnly);
      toolbar.appendChild(unreadButton);
    }

    if (type === 'read') {
      var authorButton = toolbarButton('楼', '只看楼主', function toggleAuthor() {
        settings.onlyOriginalAuthor = !settings.onlyOriginalAuthor;
        saveSettings(settings);
        enhanceAll(settings, state);
        authorButton.classList.toggle('spx-active', settings.onlyOriginalAuthor);
      });
      authorButton.classList.toggle('spx-active', settings.onlyOriginalAuthor);
      toolbar.appendChild(authorButton);
    }

    toolbar.appendChild(toolbarButton('设', '打开设置', function openSettings() {
      var panel = createSettingsPanel(settings, state);
      if (panel.spxSync) panel.spxSync();
      panel.hidden = !panel.hidden;
    }));
    document.body.appendChild(toolbar);
  }

  function toolbarButton(text, title, onClick) {
    var button = createEl('button', '', text);
    button.type = 'button';
    button.title = title;
    button.addEventListener('click', onClick);
    return button;
  }

  function toolbarLink(text, title, href) {
    var link = createEl('a', '', text);
    link.title = title;
    link.href = href;
    return link;
  }

  function enhanceHome(settings) {
    if (detectPageType(location.href) !== 'home') return;
    enhanceHomeDashboard(settings);
    if (!settings.cleanMode) {
      qsa('[data-spx-home-hidden="1"]').forEach(function showTable(table) {
        table.style.display = '';
        delete table.dataset.spxHomeHidden;
      });
      return;
    }
    qsa('table').forEach(function markTable(table) {
      if (/友情链接|在线用户/.test(table.textContent || '')) {
        table.dataset.spxHomeHidden = '1';
        table.style.display = 'none';
      }
    });
  }

  function enhanceHomeDashboard(settings) {
    restoreHomeDashboard();
    if (!shouldUseHomeDashboard(settings, location.href)) return;

    createHomeQuickLinks();
    var modules = qsa('#content .t[id^="t_"]');
    if (!modules.length) return;

    var grid = createEl('div');
    grid.id = 'spx-home-grid';
    modules[0].parentNode.insertBefore(grid, modules[0]);

    modules.forEach(function markModule(module) {
      var marker = createEl('span');
      marker.dataset.spxHomeMarker = module.id || 'module';
      marker.style.display = 'none';
      module.parentNode.insertBefore(marker, module);
      grid.appendChild(module);

      module.classList.add('spx-home-module');
      var rows = qsa('tr.tr3', module);
      if (rows.length > 6) module.dataset.spxLarge = '1';

      var header = qs('.h', module) || qs('h2', module);
      if (header && !qs('.spx-home-collapse', header)) {
        var collapse = createEl('button', 'spx-home-collapse', '折叠');
        collapse.type = 'button';
        collapse.addEventListener('click', function toggleModule() {
          var collapsed = module.dataset.spxCollapsed === '1';
          module.dataset.spxCollapsed = collapsed ? '0' : '1';
          rows.forEach(function toggleRow(row) {
            row.style.display = collapsed ? '' : 'none';
          });
          collapse.textContent = collapsed ? '折叠' : '展开';
        });
        header.appendChild(collapse);
      }

      rows.forEach(function markForumRow(row) {
        var titleNode = qs('[id^="fn_"]', row);
        if (!titleNode || titleNode.dataset.spxHomeReady) return;
        titleNode.dataset.spxHomeReady = '1';
        var today = parseTodayCount(titleNode.textContent);
        if (today > 0) {
          row.classList.add('spx-home-hot');
          var badge = createEl('span', 'spx-home-badge', String(today));
          titleNode.appendChild(badge);
        }
      });
    });
  }

  function restoreHomeDashboard() {
    var quick = qs('#spx-home-quick');
    if (quick) quick.remove();
    qsa('.spx-home-module').forEach(function restoreModule(module) {
      var marker = qsa('[data-spx-home-marker]').filter(function findMarker(item) {
        return item.dataset.spxHomeMarker === (module.id || 'module');
      })[0];
      if (marker && marker.parentNode) {
        marker.parentNode.insertBefore(module, marker);
      }
      module.classList.remove('spx-home-module');
      delete module.dataset.spxLarge;
      delete module.dataset.spxCollapsed;
      qsa('.spx-home-collapse', module).forEach(function removeButton(button) {
        button.remove();
      });
      qsa('tr.tr3', module).forEach(function restoreRow(row) {
        row.style.display = '';
        row.classList.remove('spx-home-hot');
      });
      qsa('[data-spx-home-ready="1"]', module).forEach(function restoreTitle(titleNode) {
        delete titleNode.dataset.spxHomeReady;
      });
      qsa('.spx-home-badge', module).forEach(function removeBadge(badge) {
        badge.remove();
      });
    });
    qsa('[data-spx-home-marker]').forEach(function removeMarker(marker) {
      marker.remove();
    });
    var grid = qs('#spx-home-grid');
    if (grid) grid.remove();
  }

  function createHomeQuickLinks() {
    if (qs('#spx-home-quick')) return;
    var quickItems = [
      { label: '茶馆', fid: '9' },
      { label: '询问&求物', fid: '48' },
      { label: '免空资源区', fid: '13' },
      { label: 'GALGAME汉化区', fid: '128' },
      { label: 'AI交流', fid: '208' },
      { label: '最新帖子', href: '/search2.php?orderway-postdate-asc-desc-newatc-1.html' },
    ];
    var quick = createEl('nav', 'spx-home-quick');
    quick.id = 'spx-home-quick';
    quickItems.forEach(function appendQuick(item) {
      var link = createEl('a');
      link.href = item.href ? location.origin + item.href : location.origin + '/thread.php?fid-' + item.fid + '.html';
      link.textContent = item.label;
      link.appendChild(createEl('span', '', item.href ? 'new' : 'fid-' + item.fid));
      quick.appendChild(link);
    });
    var main = qs('#main') || document.body;
    var content = qs('#content');
    if (content && content.parentNode) {
      content.parentNode.insertBefore(quick, content);
    } else {
      main.insertBefore(quick, main.firstChild);
    }
  }

  function enhanceAdBlock(settings) {
    restoreAdBlock();
    if (!settings.adBlock) return;

    qsa('a[href], area[href]').forEach(function hideAdLink(link) {
      if (!isAdUrl(link.href)) return;
      markAdHidden(link);

      var cell = link.closest('td');
      if (cell && isMostlyAdContainer(cell)) markAdHidden(cell);

      var row = link.closest('tr');
      if (row && isMostlyAdContainer(row)) markAdHidden(row);

      var box = link.closest('div');
      if (box && box.id !== 'header' && box.id !== 'mainNav' && isMostlyAdContainer(box)) {
        markAdHidden(box);
      }
    });

    qsa('img[src]').forEach(function hideAdImage(img) {
      if (!isAdUrl(img.src)) return;
      markAdHidden(img);
      var link = img.closest('a');
      if (link) markAdHidden(link);
    });
  }

  function markAdHidden(node) {
    if (!node || node.dataset.spxAdHidden === '1') return;
    node.dataset.spxAdPreviousDisplay = node.style.display || '';
    node.dataset.spxAdHidden = '1';
    node.classList.add('spx-ad-hidden');
    node.style.display = 'none';
  }

  function restoreAdBlock() {
    qsa('[data-spx-ad-hidden="1"]').forEach(function restoreAd(node) {
      node.classList.remove('spx-ad-hidden');
      node.style.display = node.dataset.spxAdPreviousDisplay || '';
      delete node.dataset.spxAdHidden;
      delete node.dataset.spxAdPreviousDisplay;
    });
  }

  function isMostlyAdContainer(node) {
    if (!node) return false;
    var text = (node.textContent || '').replace(/\s+/g, '');
    var links = qsa('a[href], area[href]', node);
    var images = qsa('img', node);
    if (!links.length && !images.length) return false;
    var adLinks = links.filter(function checkLink(link) {
      return isAdUrl(link.href);
    });
    if (adLinks.length && adLinks.length === links.length && text.length < 20) return true;
    if (images.length && text.length < 12 && node.getBoundingClientRect && node.getBoundingClientRect().height <= 180) return true;
    return false;
  }

  function enhanceAll(settings, state) {
    setBodyClasses(settings);
    enhanceAdBlock(settings);
    enhanceHome(settings);
    enhanceThreadList(settings, state);
    enhanceReadPage(settings, state);
    var panel = qs('#spx-settings');
    if (panel && panel.spxSync) panel.spxSync();
  }

  function init() {
    if (testMode || typeof window === 'undefined' || !document.body) return;
    var settings = loadSettings();
    var state = {
      read: loadMap(READ_KEY),
      watch: loadMap(WATCH_KEY),
    };
    injectStyles();
    setBodyClasses(settings);
    createToolbar(settings, state);
    createSettingsPanel(settings, state);
    enhanceAll(settings, state);
  }

  return {
    init: init,
    getDefaultSettings: function getDefaultSettings() {
      return copySettings(DEFAULT_SETTINGS);
    },
    parseThreadId: parseThreadId,
    parseLineList: parseLineList,
    matchesBlockRules: matchesBlockRules,
    isPreviewImageCandidate: isPreviewImageCandidate,
    isAdUrl: isAdUrl,
    parseTodayCount: parseTodayCount,
    shouldUseImmersiveRead: shouldUseImmersiveRead,
    shouldUseHomeDashboard: shouldUseHomeDashboard,
    buildPageUrl: buildPageUrl,
    detectPageType: detectPageType,
  };
});
