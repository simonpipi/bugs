// ==UserScript==
// @name         老王论坛百度网盘转存助手
// @namespace    https://laowang.vip/
// @version      0.1.61
// @description  美化老王论坛资源帖，购买确认后按网盘类型打开或保存资源
// @match        https://laowang.vip/*
// @match        https://laowang.vip/forum.php*
// @match        https://laowang.vip/thread-*
// @match        https://pan.baidu.com/*
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_deleteValue
// @grant        GM_registerMenuCommand
// @grant        GM_openInTab
// @grant        GM_download
// @grant        GM_xmlhttpRequest
// @connect      laowang.vip
// @run-at       document-idle
// ==/UserScript==

const PREVIEW_IMAGE_TIMEOUT_MS = 20000;
const PREVIEW_ATTACHMENT_READY_TIMEOUT_MS = 180000;
const HOVER_PREVIEW_DELAY_MS = 150;
const PURCHASE_CONFIRM_TIMEOUT_MS = 5000;
const PURCHASE_DIRECT_RESOURCE_TIMEOUT_MS = 4000;
const PURCHASE_LOOKUP_RESOURCE_TIMEOUT_MS = 5000;
const PURCHASE_LOOKUP_TARGET_TIMEOUT_MS = 6000;
const PURCHASE_OPENED_RESOURCE_TIMEOUT_MS = 5000;
const PURCHASE_LOOKUP_POLL_INTERVAL_MS = 600;
const AUTO_SIGN_LOCK_MS = 120000;
const AUTO_SIGN_RETRY_INTERVAL_MS = 1800000;

(function bootstrap(root) {
  'use strict';

  const TASK_KEY = 'lwbt:tasks';
  const SIGN_RECORDS_KEY = 'lwbt:sign:records';
  const SIGN_STATE_KEY = 'lwbt:sign:state';
  const SIGN_RECORD_LIMIT = 200;
  const SIGN_URL = 'https://laowang.vip/sign.php';
  const CAPTCHA_CHECK_URL = 'https://laowang.vip/captcha/check.php';
  const CAPTCHA_IMAGE_URL = 'https://laowang.vip/captcha/tncode.php';
  const CAPTCHA_SECRET = 'GWDiugh398huiw0ioOYGd0934hew';
  const VERSION = '0.1.61';
  const DEFAULT_UNZIP_PASSWORD = '上老王论坛当老王';
  const BAIDU_SAVE_ROOT = 'resouces';
  const SKIP_FORUM_NAMES = ['高价悬赏', '悬赏求助'];

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

  function buildTargetPath(title, date = new Date(), password = '') {
    void title;
    void date;
    const rootFolder = safePathSegment(DEFAULT_UNZIP_PASSWORD);
    const passwordFolder = safePathSegment(cleanText(password));
    if (passwordFolder && passwordFolder !== rootFolder) {
      return `/${BAIDU_SAVE_ROOT}/${rootFolder}/${passwordFolder}/`;
    }
    return `/${BAIDU_SAVE_ROOT}/${rootFolder}/`;
  }

  function targetPathToSegments(targetPath) {
    return String(targetPath || '')
      .split('/')
      .map((segment) => cleanText(segment))
      .filter(Boolean);
  }

  function baiduPathSteps(targetPath) {
    const segments = targetPathToSegments(targetPath);
    return segments.map((_segment, index) => `/${segments.slice(0, index + 1).join('/')}`);
  }

  function baiduPathEntries(targetPath) {
    const segments = targetPathToSegments(targetPath);
    let parentPath = '/';
    return segments.map((folderName, index) => {
      const folderPath = `/${segments.slice(0, index + 1).join('/')}`;
      const entry = { parentPath, folderName, folderPath };
      parentPath = folderPath;
      return entry;
    });
  }

  function normalizeTargetPath(value, fallback = '') {
    const raw = String(value || '').trim();
    if (!raw) return fallback ? normalizeTargetPath(fallback) : '/';
    const segments = raw
      .split('/')
      .map((segment) => cleanText(segment))
      .filter(Boolean);
    return segments.length ? `/${segments.join('/')}/` : '/';
  }

  function normalizeBaiduApiPath(value) {
    const normalized = normalizeTargetPath(value);
    return normalized === '/' ? '/' : normalized.replace(/\/+$/g, '');
  }

  function buildBaiduApiUrl(pathname, params = {}) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') query.set(key, String(value));
    });
    if (!query.has('channel')) query.set('channel', 'chunlei');
    if (!query.has('web')) query.set('web', '1');
    if (!query.has('app_id')) query.set('app_id', '250528');
    if (!query.has('clienttype')) query.set('clienttype', '0');
    return `${pathname}?${query.toString()}`;
  }

  function buildBaiduCreateFolderBody(folderPath) {
    const body = new URLSearchParams();
    body.set('path', normalizeBaiduApiPath(folderPath));
    body.set('isdir', '1');
    body.set('block_list', '[]');
    return body;
  }

  function buildBaiduTransferUrl(context, token, sekey = '') {
    const params = {
      shareid: context && context.shareId,
      from: context && context.from,
      ondup: 'newcopy',
      async: '1',
      bdstoken: token
    };
    if (sekey) params.sekey = sekey;
    return buildBaiduApiUrl('/share/transfer', params);
  }

  function buildBaiduTransferBody(targetPath, fsIds) {
    const body = new URLSearchParams();
    body.set('fsidlist', `[${normalizeBaiduFsIds(fsIds).join(',')}]`);
    body.set('path', normalizeBaiduApiPath(targetPath));
    return body;
  }

  function normalizeBaiduFsIds(fsIds) {
    const seen = new Set();
    return (fsIds || [])
      .map((value) => String(value || '').trim())
      .filter((value) => /^\d+$/.test(value) && value !== '0')
      .filter((value) => {
        if (seen.has(value)) return false;
        seen.add(value);
        return true;
      });
  }

  function extractBaiduShareContextFromText(text) {
    const source = String(text || '');
    const shareMatch = source.match(/(?:shareid|share_id)["']?\s*[:=]\s*["']?(\d+)/i);
    const fromMatch = source.match(/(?:share_uk|link_share_uk|from)["']?\s*[:=]\s*["']?(\d+)/i);
    const fsIds = [];
    const fsPattern = /(?:fs_id|fsid)["']?\s*[:=]\s*["']?(\d+)/ig;
    let fsMatch;
    while ((fsMatch = fsPattern.exec(source))) {
      if (fsMatch[1] !== '0' && !fsIds.includes(fsMatch[1])) fsIds.push(fsMatch[1]);
    }
    if (!shareMatch || !fromMatch || !fsIds.length) return null;
    return {
      shareId: shareMatch[1],
      from: fromMatch[1],
      fsIds
    };
  }

  function extractBaiduTokenFromText(text) {
    const source = String(text || '');
    const pattern = /(?:[?&]bdstoken=|bdstoken["']?\s*[:=]\s*["']?)([0-9a-f]{32})/ig;
    let match;
    while ((match = pattern.exec(source))) {
      if (match[1]) return match[1];
    }
    return '';
  }

  function extractBaiduShare(text) {
    const source = normalizeShareText(text);
    const urlMatch = source.match(/https?:\/\/pan\.baidu\.com\/(?:s\/[A-Za-z0-9_-]+|share\/init\?surl=[A-Za-z0-9_-]+)/i);
    if (!urlMatch) return null;
    const afterUrl = source.slice(urlMatch.index + urlMatch[0].length, urlMatch.index + urlMatch[0].length + 80);
    const queryCodeMatch = afterUrl.match(/[?&](?:pwd|password|code)=([A-Za-z0-9]{4})/i);
    const codeMatch = source.match(/(?:提取码|提取碼|密码|密碼|访问码|访问碼)[:：\s]*([A-Za-z0-9]{4})/i);
    return {
      shareUrl: urlMatch[0],
      extractCode: queryCodeMatch ? queryCodeMatch[1] : (codeMatch ? codeMatch[1] : '')
    };
  }

  function hasPurchasedShare(text) {
    return Boolean(extractBaiduShare(text));
  }

  function extractResourceLinks(text, sourceUrl = 'https://laowang.vip/') {
    const source = normalizeShareText(text);
    const rawSource = String(text || '')
      .replace(/&amp;/g, '&')
      .replace(/&#x2F;/gi, '/')
      .replace(/&#(\d+);/g, (_match, code) => String.fromCharCode(Number(code)))
      .replace(/&#x([0-9a-f]+);/gi, (_match, code) => String.fromCharCode(parseInt(code, 16)))
      .replace(/\\\//g, '/');
    const origin = getUrlOrigin(sourceUrl);
    const baidu = extractBaiduShare(source);
    if (baidu) {
      return [{ type: 'baidu', ...baidu }];
    }
    const selfPanMatch = source.match(/(?:https?:\/\/laowang\.vip)?\/pan\/file\.php\?hash=[A-Za-z0-9]+/i);
    if (selfPanMatch) {
      return [{
        type: 'laowang',
        url: absoluteForumUrl(selfPanMatch[0], origin)
      }];
    }

    const tokens = [];
    const codeMatch = source.match(/(?:提取码|提取碼|密码|密碼|访问码|访问碼)[:：\s]*([A-Za-z0-9]{4})/i);
    const primaryCode = codeMatch ? codeMatch[1] : '';
    const seen = new Set();
    const patterns = [
      { type: 'magnet', regex: /magnet:\?[^\s<>"']+/gi },
      { type: 'pan123', regex: /https?:\/\/(?:[A-Za-z0-9-]+\.)*(?:123pan\.com|123865\.com)\/[^\s<>"']+/gi },
      { type: 'uc', regex: /https?:\/\/drive\.uc\.cn\/s\/[A-Za-z0-9_-]+/gi },
      { type: 'quark', regex: /https?:\/\/pan\.quark\.cn\/s\/[A-Za-z0-9_-]+/gi }
    ];
    for (const { type, regex } of patterns) {
      const searchSource = type === 'magnet' ? rawSource : source;
      let match;
      while ((match = regex.exec(searchSource))) {
        const url = match[0];
        if (seen.has(url)) continue;
        seen.add(url);
        tokens.push({
          type,
          url,
          extractCode: primaryCode && (type === 'uc' || type === 'pan123') && !tokens.some((item) => item.extractCode) ? primaryCode : ''
        });
      }
    }
    if (!tokens.length) return [];
    if (primaryCode && !tokens.some((item) => item.extractCode)) {
      tokens[0].extractCode = primaryCode;
    }
    return tokens;
  }

  function extractResourceLink(text, sourceUrl = 'https://laowang.vip/') {
    const links = extractResourceLinks(text, sourceUrl);
    if (!links.length) return null;
    if (links.length === 1) return links[0];
    if (links[0].type === 'baidu' || links[0].type === 'laowang') return links[0];
    return { type: 'external', links };
  }

  function hasPurchasedResource(text) {
    return extractResourceLinks(text).length > 0 || Boolean(extractResourceLink(text));
  }

  function actionButtonText(downloadType) {
    const text = String(downloadType || '');
    if (/多种下载方式/.test(text)) return '复制磁力并打开网盘';
    if (/老王自建盘/.test(text)) return '购买并打开下载页';
    if (/百度(?:云)?盘|百度网盘/.test(text)) return '购买并保存到百度网盘';
    if (/夸克|UC/.test(text)) return '购买并打开下载链接';
    return '购买并打开下载链接';
  }

  function shouldShowTargetPath(downloadType) {
    return /百度(?:云)?盘|百度网盘/.test(String(downloadType || ''));
  }

  function purchaseStatusText(purchased) {
    return purchased ? '已购买' : '未购买/未检测到';
  }

  function fieldVariantClass(label) {
    const text = cleanText(label);
    if (text === '售价') return 'lwbt-field-price';
    if (text === '购买状态') return 'lwbt-field-status';
    return '';
  }

  function purchaseStatusClass(statusText) {
    const text = cleanText(statusText);
    if (text === '已购买') return 'lwbt-status-purchased';
    if (text === '检测中') return 'lwbt-status-pending';
    if (text === '已失效') return 'lwbt-status-expired';
    return 'lwbt-status-missing';
  }

  function isExpiredThreadTitle(title) {
    const text = cleanText(title);
    if (/[【\[]\s*(?:已失效|资源失效|链接失效|失效资源)\s*[】\]]/.test(text)) return true;
    return /^(?:已失效|资源失效|链接失效|失效资源)(?:\s|[:：\-_|【\[]|$)/.test(text);
  }

  function normalizeShareText(text) {
    const raw = String(text || '')
      .replace(/&amp;/g, '&')
      .replace(/&#x2F;/gi, '/')
      .replace(/&#(\d+);/g, (_match, code) => String.fromCharCode(Number(code)))
      .replace(/&#x([0-9a-f]+);/gi, (_match, code) => String.fromCharCode(parseInt(code, 16)))
      .replace(/\\\//g, '/');
    const variants = [raw];
    let decoded = raw;
    for (let index = 0; index < 2; index += 1) {
      try {
        const next = decodeURIComponent(decoded);
        if (next === decoded) break;
        decoded = next;
        variants.push(decoded);
      } catch (_error) {
        break;
      }
    }
    return variants.join('\n');
  }

  function isPurchaseLink(href, text, className, actionSource) {
    const url = String(href || '');
    const label = cleanText(text);
    const classes = String(className || '');
    const action = String(actionSource || '');
    const haystack = `${url} ${action}`;
    if (!/(?:^|[/"'])jnpar_pansell-pay\.html\?|plugin\.php\?id=jnpar_pansell:pay(?:&|$)/i.test(haystack)) return false;
    return /(?:立即购买|确认购买|购买|purchase-btn)/i.test(`${label} ${classes} ${action}`);
  }

  function isResourceLookupLink(href, text, className, actionSource) {
    const url = String(href || '');
    const label = cleanText(text);
    const classes = String(className || '');
    const action = String(actionSource || '');
    const haystack = `${url} ${action}`;
    if (/jnpar_pansell-pay\.html|plugin\.php\?id=jnpar_pansell:pay(?:&|$)/i.test(haystack)) return false;
    if (!/jnpar_pansell-(?:check|view|download|get|link)\.html|plugin\.php\?id=jnpar_pansell:(?:check|view|download|get|link)(?:&|$)/i.test(haystack)) return false;
    return /(?:百度|网盘|链接|查看|检测|下载|pansell)/i.test(`${label} ${classes} ${action}`);
  }

  function isLoginRequired(text) {
    const source = String(text || '');
    return /本帖子中包含更多资源[\s\S]{0,40}您需要\s*登录[\s\S]{0,40}(?:下载|查看)/.test(source)
      || /您需要\s*登录\s*才可以(?:下载|查看)/.test(source);
  }

  function isSignLoginRequired(text) {
    const source = String(text || '');
    const uid = source.match(/discuz_uid\s*=\s*['"]?(\d+)['"]?/i);
    if (uid) return uid[1] === '0';
    const readable = cleanText(stripHtml(source.replace(/<script[\s\S]*?<\/script>/gi, ' ').replace(/<style[\s\S]*?<\/style>/gi, ' ')));
    return /请先登录|您需要登录|未登录|您还没有登录|需要先登录/.test(readable);
  }

  function isForumPage(url) {
    return /^https:\/\/laowang\.vip\/(?:forum\.php\?mod=viewthread|thread-)/.test(String(url || ''));
  }

  function isForumFirstPage(url) {
    const value = String(url || '');
    const rewriteMatch = value.match(/\/thread-\d+-(\d+)-\d+\.html(?:[?#]|$)/);
    if (rewriteMatch) return rewriteMatch[1] === '1';
    try {
      const parsed = new URL(value);
      if (parsed.hostname !== 'laowang.vip') return false;
      if (parsed.pathname !== '/forum.php') return false;
      if (parsed.searchParams.get('mod') !== 'viewthread') return false;
      const page = parsed.searchParams.get('page');
      return !page || page === '1';
    } catch (_error) {
      return false;
    }
  }

  function readForumNames(document) {
    if (!document || typeof document.querySelectorAll !== 'function') return [];
    const names = [];
    document.querySelectorAll('#pt a').forEach((node) => {
      const name = cleanText(node && node.textContent);
      if (name && !names.includes(name)) names.push(name);
    });
    return names;
  }

  function isSkippedForumName(name) {
    const value = cleanText(name);
    return SKIP_FORUM_NAMES.some((skipName) => value === skipName || value.includes(skipName));
  }

  function shouldSkipForumPanel(document) {
    return readForumNames(document).some((name) => isSkippedForumName(name));
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
      const match = source.match(new RegExp(`${label}(?:（[^）]*）|\\([^)]*\\))?[:：]\\s*([^\\n\\r]+)`));
      result[key] = match ? cleanText(match[1]) : '';
    }
    return result;
  }

  function parsePurchaseInfo(text) {
    const source = cleanText(stripHtml(text));
    const match = source.match(/(?:售价|资源售价|价格)[:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*(软妹币|积分|金币|威望)?/);
    return {
      price: match ? match[1] : '',
      priceCurrency: match ? (match[2] || '') : ''
    };
  }

  function parseCreditInfo(text) {
    const source = cleanText(stripHtml(text));
    const softMatch = source.match(/软妹币[:：]\s*([0-9]+(?:\.[0-9]+)?)/);
    const totalMatch = source.match(/(?:^|\s)积分[:：]\s*([0-9]+(?:\.[0-9]+)?)/);
    return {
      balance: softMatch ? softMatch[1] : '',
      balanceCurrency: softMatch ? '软妹币' : '',
      totalPoints: totalMatch ? totalMatch[1] : ''
    };
  }

  function isLaowangPage(url) {
    try {
      return new URL(String(url || '')).hostname === 'laowang.vip';
    } catch (_error) {
      return /^https:\/\/laowang\.vip\//.test(String(url || ''));
    }
  }

  function signDateKey(date = new Date()) {
    const value = date instanceof Date && !Number.isNaN(date.getTime()) ? date : new Date();
    return `${value.getFullYear()}-${pad2(value.getMonth() + 1)}-${pad2(value.getDate())}`;
  }

  function trimSignRecords(records, limit = SIGN_RECORD_LIMIT) {
    return (Array.isArray(records) ? records : [])
      .filter((record) => record && typeof record === 'object')
      .slice(0, Math.max(0, Number(limit) || 0));
  }

  function hasSignedToday(records, date = new Date()) {
    const today = signDateKey(date);
    return trimSignRecords(records).some((record) => {
      const status = String(record.status || '');
      return record.date === today && (status === 'success' || status === 'already');
    });
  }

  function shouldSkipAutoSign(state, records, date = new Date()) {
    const today = signDateKey(date);
    const now = date instanceof Date && !Number.isNaN(date.getTime()) ? date.getTime() : Date.now();
    if (hasSignedToday(records, date)) return true;
    if (!state || state.date !== today) return false;
    if (state.status === 'success' || state.status === 'already') return true;
    const attemptedAt = Date.parse(state.attemptedAt || '');
    if (!Number.isFinite(attemptedAt)) return false;
    if (state.status === 'running') return now - attemptedAt < AUTO_SIGN_LOCK_MS;
    return now - attemptedAt < AUTO_SIGN_RETRY_INTERVAL_MS;
  }

  function signStatusLabel(status) {
    if (status === 'success') return '成功';
    if (status === 'already') return '已签到';
    if (status === 'running') return '进行中';
    return '失败';
  }

  function extractSignEntry(html) {
    const source = String(html || '');
    const qdleftMatch = source.match(/<div\b[^>]*class=["'][^"']*\bqdleft\b[^"']*["'][^>]*>[\s\S]*?(?=<div\b[^>]*class=["'][^"']*\b(?:qdright|bm|wp)\b|<\/body>|$)/i);
    const scope = qdleftMatch ? qdleftMatch[0] : source;
    if (/\bbtnvisted\b|今日已签到|今天已签到|已经签到|您已签到|签到成功/.test(scope)) {
      return { alreadySigned: true, href: '' };
    }
    const hrefMatch = scope.match(/<a\b[^>]*href=["']([^"']+)["'][^>]*>/i);
    if (hrefMatch) return { alreadySigned: false, href: decodeHtmlAttribute(hrefMatch[1]) };
    if (/\bbtnvisted\b|今日已签到|今天已签到|已经签到|您已签到|签到成功/.test(source)) {
      return { alreadySigned: true, href: '' };
    }
    return { alreadySigned: false, href: '' };
  }

  function parseSignFormHtml(html) {
    const forms = String(html || '').match(/<form\b[\s\S]*?<\/form>/gi) || [];
    const parsed = forms.map((formHtml) => {
      const fields = [];
      formHtml.replace(/<(input|button)\b[^>]*>/gi, (fieldHtml, tagName) => {
        const tag = String(tagName || '').toLowerCase();
        fields.push({
          tag,
          type: (readHtmlAttribute(fieldHtml, 'type') || (tag === 'button' ? 'submit' : 'text')).toLowerCase(),
          name: readHtmlAttribute(fieldHtml, 'name'),
          value: readHtmlAttribute(fieldHtml, 'value'),
          disabled: /\bdisabled(?:\s|=|>|$)/i.test(fieldHtml),
          checked: /\bchecked(?:\s|=|>|$)/i.test(fieldHtml)
        });
        return fieldHtml;
      });
      return {
        action: readHtmlAttribute(formHtml, 'action'),
        method: (readHtmlAttribute(formHtml, 'method') || 'get').toLowerCase(),
        fields
      };
    });
    return parsed.find((form) => form.fields.some((field) => field.name === 'clicaptcha-submit-info') && form.fields.some((field) => field.name === 'fingerprint'))
      || parsed[0]
      || null;
  }

  function buildSignFormData(form) {
    const data = {};
    if (!form || !Array.isArray(form.fields)) return data;
    form.fields.forEach((field) => {
      if (!field || field.disabled || !field.name) return;
      const type = String(field.type || '').toLowerCase();
      if (field.tag === 'button' || ['button', 'submit', 'image', 'reset', 'file'].includes(type)) return;
      if ((type === 'checkbox' || type === 'radio') && !field.checked) return;
      data[field.name] = String(field.value || '');
    });
    return data;
  }

  function parseSignStatus(text) {
    const source = cleanText(stripHtml(text));
    if (/请先登录|您需要登录|未登录/.test(source)) return 'failed';
    if (/今日已签到|今天已签到|已经签到|您已签到|btnvisted/.test(source)) return 'already';
    if (/签到成功|打卡成功|成功签到|恭喜[^。；，,.]{0,30}(?:签到|获得|奖励)/.test(source)) return 'success';
    return 'failed';
  }

  function parseSignPoints(text, beforeCredit, afterCredit) {
    const before = Number(beforeCredit && beforeCredit.totalPoints);
    const after = Number(afterCredit && afterCredit.totalPoints);
    if (Number.isFinite(before) && Number.isFinite(after) && after >= before) {
      const delta = after - before;
      if (delta > 0) return String(delta);
    }
    const source = cleanText(stripHtml(text));
    const direct = source.match(/(?:获得|奖励|增加|得到)[^0-9+-]{0,12}([+-]?\d+(?:\.\d+)?)\s*(?:积分|金币|软妹币)?/)
      || source.match(/([+-]?\d+(?:\.\d+)?)\s*(?:积分|金币|软妹币)[^。；，,.]{0,16}(?:奖励|获得|增加|签到)/);
    return direct ? direct[1].replace(/^\+/, '') : '';
  }

  function computeBrowserFingerprint(root) {
    const view = root || (typeof window !== 'undefined' ? window : globalThis);
    const nav = view.navigator || {};
    const screenInfo = view.screen || {};
    const languages = nav.languages && nav.languages.length ? nav.languages.join(',') : (nav.language || nav.userLanguage || '');
    const source = [
      nav.userAgent || '',
      languages,
      `${screenInfo.width || ''}x${screenInfo.height || ''}x${screenInfo.colorDepth || ''}`,
      new Date().getTimezoneOffset(),
      nav.platform || '',
      nav.hardwareConcurrency || '',
      nav.deviceMemory || '',
      canvasFingerprint(view),
      webglRenderer(view)
    ].join('||');
    return compositeFingerprintHash(source);
  }

  function canvasFingerprint(root) {
    try {
      const canvas = root.document.createElement('canvas');
      canvas.width = 280;
      canvas.height = 60;
      const context = canvas.getContext('2d');
      if (!context) return 'nc';
      context.fillStyle = 'rgba(100,200,50,0.8)';
      context.textBaseline = 'alphabetic';
      context.fillRect(20, 12, 80, 20);
      context.fillStyle = '#069';
      context.font = '14px Arial,sans-serif';
      context.fillText('Lw老王_fp😀', 12, 35);
      context.fillStyle = '#f0a';
      context.font = '11px Georgia';
      context.fillText('hfsdn', 100, 22);
      return canvas.toDataURL().slice(-32);
    } catch (_error) {
      return 'ce';
    }
  }

  function webglRenderer(root) {
    try {
      const canvas = root.document.createElement('canvas');
      const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
      if (!gl) return '';
      const debug = gl.getExtension('WEBGL_debug_renderer_info');
      if (debug) return gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) || '';
      return gl.getParameter(gl.RENDERER) || '';
    } catch (_error) {
      return '';
    }
  }

  function compositeFingerprintHash(source) {
    const text = String(source || '');
    const first = paddedFnv1a32(text);
    const mid = text.length >> 1;
    const second = paddedFnv1a32(first + text.slice(0, mid));
    const third = paddedFnv1a32(second + text.slice(mid));
    const fourth = paddedFnv1a32(third + String(text.length));
    return `${first}${second}${third}${fourth}`;
  }

  function paddedFnv1a32(text) {
    let hash = 0x811c9dc5;
    const value = String(text || '');
    for (let index = 0; index < value.length; index += 1) {
      hash ^= value.charCodeAt(index);
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return hash.toString(16).padStart(8, '0');
  }

  function makeCaptchaCheckPayload(points, offset, date = new Date()) {
    const trackInfo = buildCaptchaTrackInfo(points);
    const rawJson = JSON.stringify(trackInfo);
    const ts = String(date.getTime());
    const tnR = `${Number(offset || 0).toFixed(2)}`;
    return {
      tn_r: tnR,
      track: xorTrackBase64(rawJson, CAPTCHA_SECRET),
      ts,
      sign: fnv1a32(rawJson + ts + tnR + CAPTCHA_SECRET)
    };
  }

  function buildCaptchaTrackInfo(points) {
    const normalized = (points || []).map((point) => ({
      x: Number(point && point.x) || 0,
      y: Number(point && point.y) || 0,
      t: Number(point && point.t) || 0
    }));
    if (normalized.length <= 2) return { valid: false };
    const speeds = [];
    const directions = [];
    let totalDist = 0;
    for (let index = 1; index < normalized.length; index += 1) {
      const prev = normalized[index - 1];
      const current = normalized[index];
      const dx = current.x - prev.x;
      const dy = current.y - prev.y;
      const dt = current.t - prev.t;
      if (dt <= 0) continue;
      const dist = Math.sqrt(dx * dx + dy * dy);
      totalDist += dist;
      speeds.push(dist / dt);
      directions.push(Math.atan2(dy, dx));
    }
    const avgSpeed = speeds.length ? speeds.reduce((sum, value) => sum + value, 0) / speeds.length : 0;
    const maxSpeed = speeds.length ? Math.max(...speeds) : 0;
    const minSpeed = speeds.length ? Math.min(...speeds) : 0;
    const speedVar = speeds.length ? speeds.reduce((sum, value) => sum + Math.pow(value - avgSpeed, 2), 0) / speeds.length : 0;
    let dirChanges = 0;
    for (let index = 1; index < directions.length; index += 1) {
      if (Math.abs(directions[index] - directions[index - 1]) > Math.PI / 3) dirChanges += 1;
    }
    return {
      valid: true,
      points: normalized.length,
      totalTime: normalized[normalized.length - 1].t,
      totalDist,
      avgSpeed,
      maxSpeed,
      minSpeed,
      speedVar,
      dirChanges,
      finalX: normalized[normalized.length - 1].x - normalized[0].x
    };
  }

  function xorTrackBase64(rawJson, secret) {
    const encoder = typeof TextEncoder !== 'undefined' ? new TextEncoder() : null;
    if (!encoder || typeof btoa !== 'function') return '';
    const textBytes = encoder.encode(String(rawJson || ''));
    const secretBytes = encoder.encode(String(secret || ''));
    let binary = '';
    for (let index = 0; index < textBytes.length; index += 1) {
      binary += String.fromCharCode(textBytes[index] ^ secretBytes[index % secretBytes.length]);
    }
    return btoa(binary);
  }

  function fnv1a32(text) {
    let hash = 0x811c9dc5;
    const value = String(text || '');
    for (let index = 0; index < value.length; index += 1) {
      hash ^= value.charCodeAt(index);
      hash = (hash + ((hash << 1) >>> 0) + ((hash << 4) >>> 0) + ((hash << 7) >>> 0) + ((hash << 8) >>> 0) + ((hash << 24) >>> 0)) >>> 0;
    }
    return hash.toString(16);
  }

  function stripHtml(value) {
    return String(value || '').replace(/<[^>]*>/g, ' ');
  }

  function buildPurchaseConfirmText(info, creditInfo) {
    const price = info && info.price ? `${info.price}${info.priceCurrency || ''}` : '未识别';
    const balance = creditInfo && creditInfo.balance ? `${creditInfo.balance}` : '未识别';
    const balanceCurrency = creditInfo && creditInfo.balanceCurrency ? creditInfo.balanceCurrency : '软妹币';
    const totalPoints = creditInfo && creditInfo.totalPoints ? creditInfo.totalPoints : '未识别';
    const isSelfPan = /老王自建盘/.test(String(info && info.downloadType || ''));
    const isBaidu = /百度(?:云)?盘|百度网盘/.test(String(info && info.downloadType || ''));
    const lines = [
      isSelfPan ? '确认购买该资源并打开下载页？' : (isBaidu ? '确认购买该资源并保存到百度网盘？' : '确认购买该资源并打开下载链接？'),
      '',
      `标题: ${info.title}`,
      `售价: ${price}`,
      `我的${balanceCurrency}: ${balance}`,
      `我的总积分: ${totalPoints}`,
      `大小: ${info.size || '-'}`
    ];
    if (isBaidu) lines.push(`目录: ${info.targetPath}`);
    return lines.join('\n');
  }

  function isPreviewImage(url) {
    const value = String(url || '');
    if (!/\.(?:jpg|jpeg|png|webp|gif)(?:[?#].*)?$/i.test(value)) return false;
    if (/\/uc_server\/data\/avatar\//i.test(value)) return false;
    if (/\/static\/image\/(?:common|smiley)\//i.test(value)) return false;
    if (/\/template\//i.test(value)) return false;
    return /\/data\/attachment\/|\/forum\/|\/album\//i.test(value);
  }

  function readPreviewImageUrl(img) {
    if (!img) return '';
    return img.getAttribute('zoomfile')
      || img.getAttribute('file')
      || img.getAttribute('data-original')
      || img.currentSrc
      || img.src
      || '';
  }

  function isPreviewImageElement(img) {
    if (!img) return false;
    const url = readPreviewImageUrl(img);
    if (!isPreviewImage(url)) return false;
    if (typeof img.closest !== 'function') return true;
    if (img.closest('.pls, .avatar, .tns, .authi, .p_pop, .md_ctrl, .pil, .imicn')) return false;
    return Boolean(img.closest('[id^="postmessage_"], .t_f, .pcb, .pattl, .tattl'));
  }

  function isPreviewAttachmentLink(href, label = '') {
    const url = String(href || '').replace(/&amp;/g, '&');
    if (!/(?:^|[/?&])(?:forum\.php\?mod=attachment|mod=attachment)(?:&|$)/i.test(url)) return false;
    return /\.(?:jpg|jpeg|png|webp|gif)(?:\s|\(|$)/i.test(String(label || ''));
  }

  function previewRequestUrl(url) {
    return String(url || '').replace(/#lwbt_filename=.*$/i, '');
  }

  function previewDownloadMethod(url) {
    return /mod=attachment/i.test(String(url || '')) ? 'gm' : 'fetch';
  }

  function previewImageLoadSummary(urls, imageUrls) {
    const attachmentUrls = (urls || [])
      .filter((url) => /mod=attachment/i.test(String(url || '')))
      .map((url) => previewRequestUrl(url));
    const loaded = new Set((imageUrls || []).map((url) => previewRequestUrl(url)));
    return {
      total: attachmentUrls.length,
      loaded: attachmentUrls.filter((url) => loaded.has(url)).length
    };
  }

  function buildPreviewZipFilename(title) {
    return `${safePathSegment(cleanTitle(title)).slice(0, 70) || '预览图'}-预览图.zip`;
  }

  function previewZipFolderName(title) {
    const cleaned = cleanTitle(title);
    return cleaned ? safePathSegment(cleaned).slice(0, 70) : '预览图';
  }

  function imageExtensionFromMimeType(mimeType) {
    const type = String(mimeType || '').split(';')[0].trim().toLowerCase();
    if (type === 'image/jpeg') return 'jpg';
    if (type === 'image/png') return 'png';
    if (type === 'image/webp') return 'webp';
    if (type === 'image/gif') return 'gif';
    return '';
  }

  function previewImageFilename(url, index, mimeType = '') {
    const explicitExt = previewFilenameExtension(url);
    const match = String(url || '').match(/\.(jpg|jpeg|png|webp|gif)(?:[?#].*)?$/i);
    const ext = explicitExt || imageExtensionFromMimeType(mimeType) || (match ? match[1].toLowerCase().replace('jpeg', 'jpg') : 'jpg');
    return `${String((Number(index) || 0) + 1).padStart(3, '0')}.${ext}`;
  }

  function previewFilenameExtension(url) {
    const match = String(url || '').match(/[#&?]lwbt_filename=([^&#]+)/i);
    if (!match) return '';
    let filename = match[1];
    try {
      filename = decodeURIComponent(filename);
    } catch (_error) {
      filename = match[1];
    }
    const extMatch = filename.match(/\.(jpg|jpeg|png|webp|gif)(?:\s|\(|$)/i);
    return extMatch ? extMatch[1].toLowerCase().replace('jpeg', 'jpg') : '';
  }

  function previewDownloadSummary(successCount, failedCount) {
    const success = Number(successCount) || 0;
    const failed = Number(failedCount) || 0;
    if (!success) return '预览图下载失败，请稍后重试';
    return failed ? `已打包下载 ${success} 张预览图，${failed} 张失败` : `已打包下载 ${success} 张预览图`;
  }

  function buildStoreZipBytes(files, date = new Date()) {
    const encoder = new TextEncoder();
    const entries = (files || []).map((file) => {
      const data = toUint8Array(file.data);
      return {
        nameBytes: encoder.encode(String(file.name || 'file')),
        data,
        crc: crc32(data),
        localOffset: 0
      };
    });
    const { time, day } = toDosDateTime(date);
    const parts = [];
    let offset = 0;
    for (const entry of entries) {
      entry.localOffset = offset;
      const header = new Uint8Array(30);
      writeUint32(header, 0, 0x04034b50);
      writeUint16(header, 4, 20);
      writeUint16(header, 6, 0x0800);
      writeUint16(header, 8, 0);
      writeUint16(header, 10, time);
      writeUint16(header, 12, day);
      writeUint32(header, 14, entry.crc);
      writeUint32(header, 18, entry.data.length);
      writeUint32(header, 22, entry.data.length);
      writeUint16(header, 26, entry.nameBytes.length);
      writeUint16(header, 28, 0);
      parts.push(header, entry.nameBytes, entry.data);
      offset += header.length + entry.nameBytes.length + entry.data.length;
    }
    const centralOffset = offset;
    for (const entry of entries) {
      const header = new Uint8Array(46);
      writeUint32(header, 0, 0x02014b50);
      writeUint16(header, 4, 20);
      writeUint16(header, 6, 20);
      writeUint16(header, 8, 0x0800);
      writeUint16(header, 10, 0);
      writeUint16(header, 12, time);
      writeUint16(header, 14, day);
      writeUint32(header, 16, entry.crc);
      writeUint32(header, 20, entry.data.length);
      writeUint32(header, 24, entry.data.length);
      writeUint16(header, 28, entry.nameBytes.length);
      writeUint16(header, 30, 0);
      writeUint16(header, 32, 0);
      writeUint16(header, 34, 0);
      writeUint16(header, 36, 0);
      writeUint32(header, 38, 0);
      writeUint32(header, 42, entry.localOffset);
      parts.push(header, entry.nameBytes);
      offset += header.length + entry.nameBytes.length;
    }
    const centralSize = offset - centralOffset;
    const end = new Uint8Array(22);
    writeUint32(end, 0, 0x06054b50);
    writeUint16(end, 4, 0);
    writeUint16(end, 6, 0);
    writeUint16(end, 8, entries.length);
    writeUint16(end, 10, entries.length);
    writeUint32(end, 12, centralSize);
    writeUint32(end, 16, centralOffset);
    writeUint16(end, 20, 0);
    parts.push(end);
    return concatUint8Arrays(parts, offset + end.length);
  }

  function toUint8Array(value) {
    if (value instanceof Uint8Array) return value;
    if (value instanceof ArrayBuffer) return new Uint8Array(value);
    if (ArrayBuffer.isView(value)) return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
    return new Uint8Array(0);
  }

  function toDosDateTime(date) {
    const value = date instanceof Date && !Number.isNaN(date.getTime()) ? date : new Date();
    const year = Math.max(1980, value.getFullYear());
    return {
      time: (value.getHours() << 11) | (value.getMinutes() << 5) | Math.floor(value.getSeconds() / 2),
      day: ((year - 1980) << 9) | ((value.getMonth() + 1) << 5) | value.getDate()
    };
  }

  function writeUint16(bytes, offset, value) {
    bytes[offset] = value & 0xff;
    bytes[offset + 1] = (value >>> 8) & 0xff;
  }

  function writeUint32(bytes, offset, value) {
    bytes[offset] = value & 0xff;
    bytes[offset + 1] = (value >>> 8) & 0xff;
    bytes[offset + 2] = (value >>> 16) & 0xff;
    bytes[offset + 3] = (value >>> 24) & 0xff;
  }

  let crcTable = null;
  function crc32(bytes) {
    if (!crcTable) {
      crcTable = new Uint32Array(256);
      for (let index = 0; index < 256; index += 1) {
        let value = index;
        for (let bit = 0; bit < 8; bit += 1) {
          value = (value & 1) ? (0xedb88320 ^ (value >>> 1)) : (value >>> 1);
        }
        crcTable[index] = value >>> 0;
      }
    }
    let crc = 0xffffffff;
    for (let index = 0; index < bytes.length; index += 1) {
      crc = crcTable[(crc ^ bytes[index]) & 0xff] ^ (crc >>> 8);
    }
    return (crc ^ 0xffffffff) >>> 0;
  }

  function concatUint8Arrays(parts, totalLength) {
    const output = new Uint8Array(totalLength);
    let offset = 0;
    for (const part of parts) {
      output.set(part, offset);
      offset += part.length;
    }
    return output;
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
      targetPath: normalizeTargetPath(input.targetPath, buildTargetPath(input.rawTitle || input.title, date, input.password)),
      status: 'pending',
      error: ''
    };
  }

  function findPendingTaskForUrl(tasks, href) {
    const currentUrl = String(href || '');
    return (tasks || []).find((task) => task && task.status === 'pending' && currentUrl.startsWith(task.shareUrl)) || null;
  }

  function buildBaiduOpenUrl(shareUrl, extractCode) {
    const code = cleanText(extractCode);
    if (!code) return String(shareUrl || '');
    try {
      const url = new URL(String(shareUrl || ''));
      url.searchParams.set('pwd', code);
      return url.toString();
    } catch (_error) {
      const separator = String(shareUrl || '').includes('?') ? '&' : '?';
      return `${shareUrl}${separator}pwd=${encodeURIComponent(code)}`;
    }
  }

  function buildBaiduTaskOpenUrl(task) {
    const openUrl = buildBaiduOpenUrl(task && task.shareUrl, task && task.extractCode);
    const taskPayload = encodeURIComponent(JSON.stringify(task || {}));
    try {
      const url = new URL(openUrl);
      url.searchParams.set('lwbt_task', taskPayload);
      return url.toString();
    } catch (_error) {
      const separator = String(openUrl || '').includes('?') ? '&' : '?';
      return `${openUrl}${separator}lwbt_task=${encodeURIComponent(taskPayload)}`;
    }
  }

  function readBaiduTaskFromUrl(href) {
    try {
      const url = new URL(String(href || ''));
      const raw = url.searchParams.get('lwbt_task');
      if (!raw) return null;
      const task = JSON.parse(decodeURIComponent(raw));
      if (!task || task.status !== 'pending' || !task.shareUrl) return null;
      return task;
    } catch (_error) {
      return null;
    }
  }

  function stripBaiduTaskParamFromUrl(href) {
    try {
      const url = new URL(String(href || ''));
      url.searchParams.delete('lwbt_task');
      return url.toString();
    } catch (_error) {
      return String(href || '').replace(/([?&])lwbt_task=[^&#]*&?/, (match, prefix) => prefix === '?' ? '?' : '').replace(/\?($|#)/, '$1');
    }
  }

  function parseThreadId(url) {
    const value = String(url || '');
    const queryMatch = value.match(/[?&]tid=(\d+)/);
    if (queryMatch) return queryMatch[1];
    const rewriteMatch = value.match(/\/thread-(\d+)-/);
    return rewriteMatch ? rewriteMatch[1] : '';
  }

  function buildForumLookupUrl(sourceUrl) {
    const tid = parseThreadId(sourceUrl);
    if (!tid) return '';
    try {
      const base = new URL(sourceUrl).origin;
      return `${base}/plugin.php?id=jnpar_pansell:check&tid=${encodeURIComponent(tid)}&k=0`;
    } catch (_error) {
      return `/plugin.php?id=jnpar_pansell:check&tid=${encodeURIComponent(tid)}&k=0`;
    }
  }

  function buildForumLookupUrls(sourceUrl) {
    const urls = [];
    const current = String(sourceUrl || '');
    if (current) urls.push(current);
    const checkUrl = buildForumLookupUrl(sourceUrl);
    if (checkUrl) urls.push(checkUrl);
    return Array.from(new Set(urls));
  }

  function buildForumAjaxUrl(targetUrl, sourceUrl) {
    const origin = getUrlOrigin(sourceUrl);
    const url = new URL(String(targetUrl || ''), origin);
    url.searchParams.set('infloat', 'yes');
    url.searchParams.set('handlekey', 'dtpaytip');
    url.searchParams.set('inajax', '1');
    url.searchParams.set('ajaxtarget', 'fwin_content_dtpaytip');
    return url.toString();
  }

  function parseForumPurchaseForm(text) {
    const source = normalizeShareText(text);
    const formMatch = source.match(/<form\b[^>]*\baction=["']([^"']+)["'][\s\S]*?<\/form>/i);
    if (!formMatch) return null;
    const formHtml = formMatch[0];
    const fields = {};
    formHtml.replace(/<input\b[^>]*>/gi, (inputHtml) => {
      const name = readHtmlAttribute(inputHtml, 'name');
      if (!name) return inputHtml;
      fields[name] = readHtmlAttribute(inputHtml, 'value');
      return inputHtml;
    });
    const submitMatch = formHtml.match(/<(?:button|input)\b[^>]*\bname=["']submit["'][^>]*>/i);
    if (submitMatch) {
      fields.submit = readHtmlAttribute(submitMatch[0], 'value') || 'true';
    }
    if (!fields.submit) fields.submit = 'true';
    return {
      action: readHtmlAttribute(formMatch[0], 'action') || formMatch[1],
      fields
    };
  }

  function readHtmlAttribute(html, name) {
    const pattern = new RegExp(`\\b${name}=[\"']([^\"']*)[\"']`, 'i');
    const match = String(html || '').match(pattern);
    return match ? decodeHtmlAttribute(match[1]) : '';
  }

  function decodeHtmlAttribute(value) {
    return String(value || '')
      .replace(/&amp;/g, '&')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>');
  }

  function extractForumResourceUrls(text, sourceUrl) {
    const source = normalizeShareText(text);
    const origin = getUrlOrigin(sourceUrl);
    const matches = source.match(/(?:https?:\/\/[^'"\s<>]+)?(?:plugin\.php\?id=jnpar_pansell:(?:check|view|download|get|link)[^'"\s<>]*)|(?:https?:\/\/[^'"\s<>]+)?jnpar_pansell-(?:check|view|download|get|link)\.html\?[^'"\s<>]*/gi) || [];
    return Array.from(new Set(matches.map((url) => absoluteForumUrl(url, origin))));
  }

  function getUrlOrigin(sourceUrl) {
    try {
      return new URL(String(sourceUrl || '')).origin;
    } catch (_error) {
      return 'https://laowang.vip';
    }
  }

  function absoluteForumUrl(url, origin) {
    const value = String(url || '').replace(/&amp;/g, '&');
    if (/^https?:\/\//i.test(value)) return value;
    return `${origin}/${value.replace(/^\/+/, '')}`;
  }

  function chooseActionTarget(targets) {
    const list = Array.isArray(targets) ? targets : [];
    return list.find((target) => target.type === 'purchase' && target.visible)
      || list.find((target) => target.type === 'lookup' && target.visible)
      || list.find((target) => target.type === 'purchase')
      || list.find((target) => target.type === 'lookup')
      || null;
  }

  function chooseLookupTarget(targets) {
    const list = Array.isArray(targets) ? targets : [];
    return list.find((target) => target.type === 'lookup' && target.visible)
      || list.find((target) => target.type === 'lookup')
      || null;
  }

  function isForumPurchaseConfirmButton(label, href) {
    if (/取消|关闭/.test(String(label || ''))) return false;
    if (/check\.html|plugin\.php\?id=jnpar_pansell:check/i.test(String(href || ''))) return false;
    return /^(确定|确认|确认购买|立即购买|购买|提交)$/i.test(String(label || ''));
  }

  function shouldBlockForLogin(text, targets) {
    return isLoginRequired(text) && !chooseActionTarget(targets);
  }

  function resourceOpenTargets(resource) {
    if (!resource) return [];
    if (resource.type === 'laowang') return [resource.url].filter(Boolean);
    if (resource.type === 'external') {
      return (resource.links || [])
        .filter((link) => link && link.type !== 'magnet')
        .map((link) => link && link.url)
        .filter(Boolean);
    }
    if (resource.type === 'uc' || resource.type === 'quark' || resource.type === 'pan123') return [resource.url].filter(Boolean);
    return [];
  }

  function resourceCopyTexts(resource) {
    if (!resource) return [];
    const links = resource.type === 'external' ? (resource.links || []) : [resource];
    return links
      .filter((link) => link && link.type === 'magnet' && link.url)
      .map((link) => link.url);
  }

  function resourceSummary(resource) {
    if (!resource) return '未找到下载链接';
    if (resource.type === 'laowang') return '已找到老王自建盘下载页';
    if (resource.type === 'baidu') return '已找到百度网盘链接';
    const links = resource.type === 'external' ? (resource.links || []) : [resource];
    if (!links.length) return '未找到下载链接';
    const labels = links.map((link) => {
      const typeName = resourceTypeName(link.type);
      return link.extractCode ? `${typeName} 提取码 ${link.extractCode}` : typeName;
    });
    const noun = links.some((link) => link && (link.type === 'magnet' || link.type === 'pan123')) ? '下载方式' : '下载链接';
    return `已找到 ${links.length} 个${noun}：${labels.join('、')}`;
  }

  function resourceTypeName(type) {
    if (type === 'uc') return 'UC';
    if (type === 'quark') return '夸克';
    if (type === 'magnet') return '磁力';
    if (type === 'pan123') return '123网盘';
    return '下载链接';
  }

  function nextImageIndex(current, delta, total) {
    if (!total) return 0;
    return (current + delta + total) % total;
  }

  function isPostContentNoise(text, className, id) {
    const source = cleanText(text);
    const marker = `${className || ''} ${id || ''}`;
    if (/attach|pansell|download|pay|purchase|tattach|locked/i.test(marker)) return true;
    if (/下载信息分类|下载方式[:：]|资源大小[:：]|文件数量[:：]|解压密码[:：]/.test(source)) return true;
    if (/百度网盘链接|点击检测是否有效|立即购买|售价[:：]?\s*\d+\s*软妹币/.test(source)) return true;
    if (/本帖子中包含更多资源|您需要\s*登录\s*才可以/.test(source)) return true;
    return false;
  }

  const api = {
    TASK_KEY,
    SIGN_RECORDS_KEY,
    SIGN_STATE_KEY,
    SIGN_RECORD_LIMIT,
    SIGN_URL,
    CAPTCHA_CHECK_URL,
    CAPTCHA_IMAGE_URL,
    VERSION,
    SKIP_FORUM_NAMES,
    cleanText,
    cleanTitle,
    safePathSegment,
    buildTargetPath,
    targetPathToSegments,
    normalizeTargetPath,
    baiduPathSteps,
    baiduPathEntries,
    normalizeBaiduFsIds,
    buildBaiduApiUrl,
    buildBaiduCreateFolderBody,
    buildBaiduTransferUrl,
    buildBaiduTransferBody,
    extractBaiduShareContextFromText,
    extractBaiduTokenFromText,
    extractBaiduShare,
    hasPurchasedShare,
    extractResourceLinks,
    extractResourceLink,
    hasPurchasedResource,
    actionButtonText,
    shouldShowTargetPath,
    purchaseStatusText,
    fieldVariantClass,
    purchaseStatusClass,
    isExpiredThreadTitle,
    normalizeShareText,
    isPurchaseLink,
    isResourceLookupLink,
    isLoginRequired,
    isSignLoginRequired,
    isForumPage,
    isForumFirstPage,
    readForumNames,
    isSkippedForumName,
    shouldSkipForumPanel,
    isBaiduPage,
    parseTypeInfo,
    parsePurchaseInfo,
    parseCreditInfo,
    isLaowangPage,
    signDateKey,
    trimSignRecords,
    hasSignedToday,
    shouldSkipAutoSign,
    signStatusLabel,
    extractSignEntry,
    parseSignFormHtml,
    buildSignFormData,
    parseSignStatus,
    parseSignPoints,
    computeBrowserFingerprint,
    compositeFingerprintHash,
    paddedFnv1a32,
    makeCaptchaCheckPayload,
    buildCaptchaTrackInfo,
    xorTrackBase64,
    fnv1a32,
    buildPurchaseConfirmText,
    isPreviewImage,
    readPreviewImageUrl,
    isPreviewImageElement,
    isPreviewAttachmentLink,
    previewRequestUrl,
    previewDownloadMethod,
    previewImageLoadSummary,
    buildPreviewZipFilename,
    previewZipFolderName,
    imageExtensionFromMimeType,
    previewImageFilename,
    previewFilenameExtension,
    previewDownloadSummary,
    buildStoreZipBytes,
    createTransferTask,
    findPendingTaskForUrl,
    buildBaiduOpenUrl,
    buildBaiduTaskOpenUrl,
    readBaiduTaskFromUrl,
    stripBaiduTaskParamFromUrl,
    parseThreadId,
    buildForumLookupUrl,
    buildForumLookupUrls,
    buildForumAjaxUrl,
    parseForumPurchaseForm,
    extractForumResourceUrls,
    chooseActionTarget,
    chooseLookupTarget,
    isForumPurchaseConfirmButton,
    shouldBlockForLogin,
    resourceOpenTargets,
    resourceCopyTexts,
    resourceSummary,
    nextImageIndex,
    isPostContentNoise,
    renderForumPanel,
    originalHiddenCss
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
  registerSignRecordsMenu(root, api);
  if (api.isLaowangPage(root.location.href)) {
    injectSignRecordsEntry(root, api);
    maybeAutoSign(root, api).catch((error) => {
      console.warn('[LWBT] Auto sign failed', error);
    });
  }
  if (api.isForumPage(root.location.href) && api.isForumFirstPage(root.location.href) && !api.shouldSkipForumPanel(root.document)) {
    injectForumPanel(root, api);
  } else if (api.isBaiduPage(root.location.href)) {
    runBaidu(root, api).catch((error) => {
      console.error('[LWBT] Baidu automation failed', error);
    });
  }
}

function registerSignRecordsMenu(root, api) {
  if (root.__lwbtSignMenuRegistered) return;
  root.__lwbtSignMenuRegistered = true;
  if (typeof GM_registerMenuCommand === 'function') {
    GM_registerMenuCommand('查看老王签到记录', () => {
      showSignRecordsDialog(root, api).catch((error) => {
        console.warn('[LWBT] Failed to show sign records', error);
      });
    });
    GM_registerMenuCommand('立即执行老王签到', () => {
      maybeAutoSign(root, api, { force: true, quiet: false }).catch((error) => {
        console.warn('[LWBT] Manual sign failed', error);
      });
    });
  }
}

function injectSignRecordsEntry(root, api) {
  const document = root.document;
  if (!document || !document.body || document.querySelector('#lwbt-sign-entry')) return;
  const button = document.createElement('button');
  button.id = 'lwbt-sign-entry';
  button.type = 'button';
  button.textContent = '签到记录';
  button.style.cssText = [
    'position:fixed',
    'right:24px',
    'bottom:24px',
    'z-index:2147483646',
    'border:0',
    'border-radius:999px',
    'background:#111827',
    'color:#fff',
    'box-shadow:0 10px 28px rgba(15,23,42,.22)',
    'font:700 13px/1 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',
    'padding:10px 13px',
    'cursor:pointer'
  ].join(';');
  button.addEventListener('click', () => {
    showSignRecordsDialog(root, api).catch((error) => {
      console.warn('[LWBT] Failed to show sign records', error);
    });
  });
  document.body.appendChild(button);
}

async function maybeAutoSign(root, api, options = {}) {
  if (!api || !api.isLaowangPage(root.location && root.location.href) || !root.fetch) return null;
  const records = await readSignRecords(root, api);
  const state = await readSignState(root, api);
  if (!options.force && api.shouldSkipAutoSign(state, records, new Date())) return null;

  const startedAt = new Date();
  await writeSignState(root, api, {
    date: api.signDateKey(startedAt),
    status: 'running',
    attemptedAt: startedAt.toISOString()
  });

  let result;
  try {
    result = await performAutoSign(root, api);
  } catch (error) {
    result = {
      status: 'failed',
      points: '',
      message: error && error.message ? error.message : String(error || '签到失败'),
      signedAt: new Date().toISOString()
    };
  }

  const record = await appendSignRecord(root, api, result);
  if (result.status === 'success') {
    showBaiduToast(root.document, `自动签到成功${record.points ? `，积分 +${record.points}` : ''}`, 'success', 9000);
  } else if (result.status === 'already') {
    if (!options.quiet) showBaiduToast(root.document, '今日已经签到', 'success', 6000);
  } else if (!options.quiet) {
    showBaiduToast(root.document, `自动签到失败：${record.message || '未知错误'}`, 'error', 12000);
  }
  refreshSignRecordsDialog(root, api).catch(() => null);
  return record;
}

async function performAutoSign(root, api) {
  const beforeCredit = await fetchCurrentCredit(root, api).catch(() => ({}));
  const signResponse = await fetchText(root, api.SIGN_URL, { credentials: 'include' });
  if (isCloudflareChallenge(signResponse.text)) {
    throw new Error('签到页被 Cloudflare 校验拦截，请在浏览器页面完成校验后重试');
  }
  if (api.isSignLoginRequired(signResponse.text)) {
    throw new Error('当前浏览器未登录论坛，跳过自动签到');
  }
  const entry = api.extractSignEntry(signResponse.text);
  if (entry.alreadySigned) {
    return {
      status: 'already',
      points: '',
      message: '页面显示今日已签到',
      signedAt: new Date().toISOString()
    };
  }
  if (!entry.href) throw new Error('未找到签到入口');

  const formUrl = resolveUrl(root, entry.href, signResponse.url || api.SIGN_URL);
  const formResponse = await fetchText(root, formUrl, { credentials: 'include' });
  const form = api.parseSignFormHtml(formResponse.text);
  if (!form) {
    const status = api.parseSignStatus(formResponse.text);
    if (status === 'success' || status === 'already') {
      const afterCredit = await fetchCurrentCredit(root, api).catch(() => ({}));
      return {
        status,
        points: api.parseSignPoints(formResponse.text, beforeCredit, afterCredit),
        message: status === 'success' ? '签到成功' : '页面显示今日已签到',
        signedAt: new Date().toISOString()
      };
    }
    throw new Error('未找到签到提交表单');
  }

  const data = api.buildSignFormData(form);
  const needsCaptcha = form.fields.some((field) => field && field.name === 'clicaptcha-submit-info');
  if (needsCaptcha) {
    data['clicaptcha-submit-info'] = await passSignCaptcha(root, api, formResponse.url || formUrl);
  }
  if (form.fields.some((field) => field && field.name === 'fingerprint')) {
    data.fingerprint = api.computeBrowserFingerprint(root);
  }

  const submitUrl = resolveUrl(root, form.action || formResponse.url || formUrl, formResponse.url || formUrl);
  const method = String(form.method || 'post').toLowerCase();
  const submitOptions = {
    method: method === 'get' ? 'GET' : 'POST',
    credentials: 'include',
    headers: { 'X-Requested-With': 'XMLHttpRequest' }
  };
  let finalUrl = submitUrl;
  if (method === 'get') {
    const url = new root.URL(submitUrl, root.location.href);
    Object.entries(data).forEach(([key, value]) => url.searchParams.set(key, value));
    finalUrl = url.toString();
  } else {
    submitOptions.headers['Content-Type'] = 'application/x-www-form-urlencoded';
    submitOptions.body = new root.URLSearchParams(data).toString();
  }

  const submitResponse = await fetchText(root, finalUrl, submitOptions);
  const afterCredit = await fetchCurrentCredit(root, api).catch(() => ({}));
  const combinedText = [submitResponse.text, formResponse.text, signResponse.text].join('\n');
  const status = api.parseSignStatus(combinedText);
  const points = api.parseSignPoints(combinedText, beforeCredit, afterCredit);
  if (status !== 'success' && status !== 'already') {
    throw new Error(signFailureMessage(api, combinedText, submitResponse.status));
  }
  return {
    status,
    points,
    message: status === 'success' ? '签到成功' : '页面显示今日已签到',
    signedAt: new Date().toISOString()
  };
}

async function passSignCaptcha(root, api, referer) {
  const captchaUrl = `${api.CAPTCHA_IMAGE_URL}?t=${Math.random()}`;
  const imageResponse = await root.fetch(captchaUrl, {
    credentials: 'include',
    referrer: referer || root.location.href
  });
  if (!imageResponse.ok) throw new Error(`验证码图片请求失败：HTTP ${imageResponse.status}`);
  const blob = await imageResponse.blob();
  const imageData = await readCaptchaImageData(root, blob);
  const solved = solveSignCaptchaImage(imageData);
  const payload = api.makeCaptchaCheckPayload(solved.points, solved.moveX, new Date());
  const checkResponse = await root.fetch(api.CAPTCHA_CHECK_URL, {
    method: 'POST',
    credentials: 'include',
    referrer: referer || root.location.href,
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'X-Requested-With': 'XMLHttpRequest'
    },
    body: new root.URLSearchParams(payload).toString()
  });
  const text = (await checkResponse.text()).trim();
  if (!/^[0-9a-fA-F]{32}_ok$/.test(text)) {
    throw new Error(`验证码校验失败：${text.slice(0, 80) || `HTTP ${checkResponse.status}`}`);
  }
  return text;
}

async function fetchText(root, url, options = {}) {
  const response = await root.fetch(url, options);
  return {
    url: response.url || url,
    status: response.status,
    ok: response.ok,
    text: await response.text()
  };
}

function resolveUrl(root, url, baseUrl) {
  return new root.URL(String(url || ''), baseUrl || root.location.href).toString();
}

function isCloudflareChallenge(text) {
  return /Just a moment|Enable JavaScript and cookies|cdn-cgi\/challenge-platform/i.test(String(text || ''));
}

function signFailureMessage(api, text, status) {
  const source = String(text || '');
  const plain = source.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
  if (api && typeof api.isSignLoginRequired === 'function') {
    if (api.isSignLoginRequired(source)) return '当前浏览器未登录论坛';
  } else if (/请先登录|您需要登录|未登录/.test(plain)) {
    return '当前浏览器未登录论坛';
  }
  if (/验证码|clicaptcha|tncode|位置不正确|行为异常|签名验证失败/.test(plain)) return '验证码校验未通过';
  if (status && status >= 400) return `签到提交失败：HTTP ${status}`;
  return plain.slice(0, 80) || '签到提交后未识别成功结果';
}

async function readSignState(root, api) {
  return readJsonValue(root, api.SIGN_STATE_KEY, {});
}

async function writeSignState(root, api, state) {
  await writeJsonValue(root, api.SIGN_STATE_KEY, state || {});
}

async function readSignRecords(root, api) {
  return api.trimSignRecords(await readJsonValue(root, api.SIGN_RECORDS_KEY, []));
}

async function writeSignRecords(root, api, records) {
  await writeJsonValue(root, api.SIGN_RECORDS_KEY, api.trimSignRecords(records));
}

async function appendSignRecord(root, api, result) {
  const now = new Date(result && result.signedAt || Date.now());
  const status = result && result.status ? result.status : 'failed';
  const record = {
    id: `lwbt-sign-${now.getTime()}`,
    date: api.signDateKey(now),
    signedAt: now.toISOString(),
    status,
    points: result && result.points ? String(result.points) : '',
    message: api.cleanText(result && result.message || signStatusLabel(status)).slice(0, 160),
    pageUrl: root.location && root.location.href || ''
  };
  const existing = await readSignRecords(root, api);
  const deduped = existing.filter((item) => !(item && item.date === record.date && (record.status === 'success' || record.status === 'already') && (item.status === 'success' || item.status === 'already')));
  const records = api.trimSignRecords([record].concat(deduped));
  await writeSignRecords(root, api, records);
  await writeSignState(root, api, {
    date: record.date,
    status: record.status,
    attemptedAt: record.signedAt,
    points: record.points,
    message: record.message
  });
  return record;
}

async function readJsonValue(root, key, fallback) {
  const fallbackStorage = root.localStorage;
  const raw = typeof GM_getValue === 'function'
    ? await GM_getValue(key, '')
    : (fallbackStorage ? fallbackStorage.getItem(key) : '');
  if (!raw) return fallback;
  if (typeof raw !== 'string') return raw;
  try {
    return JSON.parse(raw);
  } catch (_error) {
    return fallback;
  }
}

async function writeJsonValue(root, key, value) {
  const raw = JSON.stringify(value);
  if (typeof GM_setValue === 'function') {
    await GM_setValue(key, raw);
  } else if (root.localStorage) {
    root.localStorage.setItem(key, raw);
  }
}

async function showSignRecordsDialog(root, api) {
  const records = await readSignRecords(root, api);
  renderSignRecordsDialog(root, api, records);
}

async function refreshSignRecordsDialog(root, api) {
  if (!root.document.querySelector('#lwbt-sign-records')) return;
  await showSignRecordsDialog(root, api);
}

function renderSignRecordsDialog(root, api, records) {
  const document = root.document;
  let dialog = document.querySelector('#lwbt-sign-records');
  if (!dialog) {
    dialog = document.createElement('div');
    dialog.id = 'lwbt-sign-records';
    document.body.appendChild(dialog);
    dialog.addEventListener('click', (event) => {
      const action = event.target && event.target.dataset && event.target.dataset.action;
      if (action === 'close') dialog.remove();
      if (action === 'sign-now') {
        maybeAutoSign(root, api, { force: true, quiet: false }).catch((error) => {
          showBaiduToast(document, `自动签到失败：${error.message}`, 'error', 12000);
        });
      }
    });
  }
  const rows = records.map((record) => `
        <tr>
          <td>${escapeHtml(formatSignDisplayTime(record.signedAt))}</td>
          <td><span class="lwbt-sign-badge lwbt-sign-${escapeAttr(record.status || 'failed')}">${escapeHtml(api.signStatusLabel(record.status))}</span></td>
          <td>${escapeHtml(record.points ? `+${record.points}` : '-')}</td>
          <td>${escapeHtml(record.message || '')}</td>
        </tr>`).join('');
  dialog.innerHTML = `
    <style>${signRecordsCss()}</style>
    <div class="lwbt-sign-backdrop" data-action="close"></div>
    <section class="lwbt-sign-dialog" role="dialog" aria-modal="true" aria-label="签到记录">
      <header>
        <h2>签到记录</h2>
        <div class="lwbt-sign-actions">
          <button type="button" data-action="sign-now">立即签到</button>
          <button type="button" data-action="close">关闭</button>
        </div>
      </header>
      <p>本地最多保存 ${api.SIGN_RECORD_LIMIT} 条记录。</p>
      <div class="lwbt-sign-table-wrap">
        <table>
          <thead><tr><th>时间</th><th>状态</th><th>积分</th><th>说明</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="4" class="lwbt-sign-empty">暂无签到记录</td></tr>'}</tbody>
        </table>
      </div>
    </section>`;
}

function formatSignDisplayTime(value) {
  const date = new Date(value || '');
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString('zh-CN', { hour12: false });
}

function signRecordsCss() {
  return `
    #lwbt-sign-records{position:fixed;inset:0;z-index:2147483647;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    .lwbt-sign-backdrop{position:absolute;inset:0;background:rgba(17,24,39,.52)}
    .lwbt-sign-dialog{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:min(760px,calc(100vw - 28px));max-height:min(680px,calc(100vh - 28px));display:flex;flex-direction:column;background:#fff;border-radius:8px;box-shadow:0 24px 80px rgba(15,23,42,.32);overflow:hidden;color:#111827}
    .lwbt-sign-dialog header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 16px;border-bottom:1px solid #e5e7eb;background:#f9fafb}
    .lwbt-sign-dialog h2{margin:0;font-size:18px;line-height:1.3}
    .lwbt-sign-dialog p{margin:0;padding:10px 16px;color:#6b7280;font-size:13px}
    .lwbt-sign-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
    .lwbt-sign-actions button{border:0;border-radius:6px;background:#2563eb;color:#fff;font-weight:800;padding:8px 10px;cursor:pointer}
    .lwbt-sign-actions button+button{background:#e5e7eb;color:#111827}
    .lwbt-sign-table-wrap{overflow:auto;padding:0 16px 16px}
    .lwbt-sign-dialog table{width:100%;border-collapse:collapse;font-size:13px}
    .lwbt-sign-dialog th,.lwbt-sign-dialog td{border-bottom:1px solid #e5e7eb;padding:9px 8px;text-align:left;vertical-align:top}
    .lwbt-sign-dialog th{position:sticky;top:0;background:#fff;color:#374151;font-weight:900}
    .lwbt-sign-dialog td:nth-child(1){white-space:nowrap;color:#374151}
    .lwbt-sign-dialog td:nth-child(3){white-space:nowrap;font-weight:900;color:#166534}
    .lwbt-sign-empty{text-align:center!important;color:#6b7280!important;padding:26px 8px!important}
    .lwbt-sign-badge{display:inline-flex;border-radius:999px;padding:3px 8px;font-weight:900;font-size:12px;background:#e5e7eb;color:#374151;white-space:nowrap}
    .lwbt-sign-success,.lwbt-sign-already{background:#dcfce7;color:#166534}
    .lwbt-sign-running{background:#dbeafe;color:#1d4ed8}
    .lwbt-sign-failed{background:#fee2e2;color:#991b1b}
  `;
}

async function readCaptchaImageData(root, blob) {
  const canvas = root.document.createElement('canvas');
  const context = canvas.getContext('2d', { willReadFrequently: true });
  if (!context) throw new Error('当前浏览器不支持 Canvas 验证码识别');
  if (typeof root.createImageBitmap === 'function') {
    const bitmap = await root.createImageBitmap(blob);
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    context.drawImage(bitmap, 0, 0);
    if (bitmap.close) bitmap.close();
    return context.getImageData(0, 0, canvas.width, canvas.height);
  }
  const image = await loadBlobImage(root, blob);
  canvas.width = image.naturalWidth || image.width;
  canvas.height = image.naturalHeight || image.height;
  context.drawImage(image, 0, 0);
  return context.getImageData(0, 0, canvas.width, canvas.height);
}

function loadBlobImage(root, blob) {
  return new Promise((resolve, reject) => {
    const url = root.URL.createObjectURL(blob);
    const image = new root.Image();
    image.onload = () => {
      root.URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      root.URL.revokeObjectURL(url);
      reject(new Error('验证码图片解码失败'));
    };
    image.src = url;
  });
}

function solveSignCaptchaImage(imageData) {
  const bands = splitCaptchaBands(imageData);
  const piece = findCaptchaPiece(imageData, bands.slider);
  const target = matchCaptchaTarget(imageData, bands.bottom, piece) || findCaptchaDiffTarget(imageData, bands.top, bands.bottom, piece);
  if (!target) throw new Error('未能识别验证码缺口');
  const moveX = Math.round(target.x - piece.x);
  if (!Number.isFinite(moveX) || moveX <= 0) throw new Error(`验证码位移异常：${moveX}`);
  return {
    moveX,
    targetX: target.x,
    targetY: target.y,
    points: makeSignHorizontalTrack(moveX)
  };
}

function splitCaptchaBands(imageData) {
  const { width, height } = imageData;
  const rows = [];
  for (let y = 0; y < height; y += 1) {
    let black = 0;
    for (let x = 0; x < width; x += 1) {
      if (captchaGray(imageData, x, y) < 25) black += 1;
    }
    if (black / width > 0.68) rows.push(y);
  }
  if (!rows.length) throw new Error('验证码图片结构异常');
  let best = [rows[0], rows[0] + 1];
  let start = rows[0];
  let prev = rows[0];
  for (let index = 1; index < rows.length; index += 1) {
    const row = rows[index];
    if (row === prev + 1) {
      prev = row;
      continue;
    }
    if (prev + 1 - start > best[1] - best[0]) best = [start, prev + 1];
    start = prev = row;
  }
  if (prev + 1 - start > best[1] - best[0]) best = [start, prev + 1];
  if (best[1] - best[0] < 20 || best[0] <= 0 || best[1] >= height) throw new Error('验证码滑块区域异常');
  return {
    top: { y: 0, height: best[0] },
    slider: { y: best[0], height: best[1] - best[0] },
    bottom: { y: best[1], height: height - best[1] }
  };
}

function findCaptchaPiece(imageData, band) {
  const { width } = imageData;
  const height = band.height;
  const visited = new Uint8Array(width * height);
  let best = null;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const index = y * width + x;
      if (visited[index] || captchaGray(imageData, x, band.y + y) <= 35) continue;
      const component = floodCaptchaComponent(imageData, band, x, y, visited);
      if (component.count < 120) continue;
      const bw = component.maxX - component.minX + 1;
      const bh = component.maxY - component.minY + 1;
      if (bw < 12 || bh < 12 || bw > width * 0.55 || bh > height * 0.8) continue;
      if (!best || component.count > best.count) best = component;
    }
  }
  if (!best) throw new Error('未从验证码中定位滑块');
  const pad = 2;
  const x = Math.max(0, best.minX - pad);
  const y = Math.max(0, best.minY - pad);
  const w = Math.min(width, best.maxX + pad + 1) - x;
  const h = Math.min(height, best.maxY + pad + 1) - y;
  let mask = buildCaptchaPieceMask(imageData, band.y, x, y, w, h, 55, true);
  if (mask.length < 80) mask = buildCaptchaPieceMask(imageData, band.y, x, y, w, h, 25, false);
  return {
    x,
    y,
    absoluteY: band.y + y,
    width: w,
    height: h,
    mask: sampleCaptchaMask(mask, 700)
  };
}

function floodCaptchaComponent(imageData, band, startX, startY, visited) {
  const { width } = imageData;
  const stack = [[startX, startY]];
  let count = 0;
  let minX = startX;
  let maxX = startX;
  let minY = startY;
  let maxY = startY;
  while (stack.length) {
    const [x, y] = stack.pop();
    if (x < 0 || y < 0 || x >= width || y >= band.height) continue;
    const index = y * width + x;
    if (visited[index]) continue;
    visited[index] = 1;
    if (captchaGray(imageData, x, band.y + y) <= 35) continue;
    count += 1;
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
    stack.push([x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]);
  }
  return { count, minX, maxX, minY, maxY };
}

function buildCaptchaPieceMask(imageData, bandY, pieceX, pieceY, width, height, threshold, removeGreen) {
  const mask = [];
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const px = pieceX + x;
      const py = bandY + pieceY + y;
      const offset = (py * imageData.width + px) * 4;
      const r = imageData.data[offset];
      const g = imageData.data[offset + 1];
      const b = imageData.data[offset + 2];
      const gray = (r + g + b) / 3;
      const green = removeGreen && g > 80 && g > r * 1.25 && g > b * 1.25;
      if (gray > threshold && !green) mask.push({ x, y, r, g, b });
    }
  }
  return mask;
}

function sampleCaptchaMask(mask, maxPoints) {
  if (mask.length <= maxPoints) return mask;
  const step = Math.ceil(mask.length / maxPoints);
  return mask.filter((_point, index) => index % step === 0);
}

function matchCaptchaTarget(imageData, band, piece) {
  if (!piece.mask.length || band.height < piece.height) return null;
  let best = null;
  for (let y = 0; y <= band.height - piece.height; y += 1) {
    for (let x = 0; x <= imageData.width - piece.width; x += 1) {
      let total = 0;
      for (const point of piece.mask) {
        const offset = ((band.y + y + point.y) * imageData.width + x + point.x) * 4;
        const dr = imageData.data[offset] - point.r;
        const dg = imageData.data[offset + 1] - point.g;
        const db = imageData.data[offset + 2] - point.b;
        total += dr * dr + dg * dg + db * db;
      }
      const score = 1 - total / (piece.mask.length * 255 * 255 * 3);
      if (!best || score > best.score) best = { x, y, score };
    }
  }
  return best && best.score > 0.62 ? best : null;
}

function findCaptchaDiffTarget(imageData, top, bottom, piece) {
  const height = Math.min(top.height, bottom.height);
  const width = imageData.width;
  const visited = new Uint8Array(width * height);
  let best = null;
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const index = y * width + x;
      if (visited[index] || captchaDiffGray(imageData, x, top.y + y, bottom.y + y) <= 30) continue;
      const component = floodCaptchaDiffComponent(imageData, top, bottom, x, y, visited, height);
      const bw = component.maxX - component.minX + 1;
      const bh = component.maxY - component.minY + 1;
      if (bw < piece.width * 0.35 || bh < piece.height * 0.35 || bw > piece.width * 2.25 || bh > piece.height * 2.0) continue;
      const sizePenalty = Math.abs(bw - piece.width) / Math.max(piece.width, 1) + Math.abs(bh - piece.height) / Math.max(piece.height, 1);
      const score = component.count / Math.max(bw * bh, 1) + Math.min(component.count / Math.max(piece.width * piece.height, 1), 2) - sizePenalty * 0.25;
      if (!best || score > best.score) best = { x: component.minX, y: component.minY, score };
    }
  }
  return best;
}

function floodCaptchaDiffComponent(imageData, top, bottom, startX, startY, visited, height) {
  const { width } = imageData;
  const stack = [[startX, startY]];
  let count = 0;
  let minX = startX;
  let maxX = startX;
  let minY = startY;
  let maxY = startY;
  while (stack.length) {
    const [x, y] = stack.pop();
    if (x < 0 || y < 0 || x >= width || y >= height) continue;
    const index = y * width + x;
    if (visited[index]) continue;
    visited[index] = 1;
    if (captchaDiffGray(imageData, x, top.y + y, bottom.y + y) <= 30) continue;
    count += 1;
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
    stack.push([x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]);
  }
  return { count, minX, maxX, minY, maxY };
}

function captchaGray(imageData, x, y) {
  const offset = (y * imageData.width + x) * 4;
  return (imageData.data[offset] + imageData.data[offset + 1] + imageData.data[offset + 2]) / 3;
}

function captchaDiffGray(imageData, x, y1, y2) {
  const offset1 = (y1 * imageData.width + x) * 4;
  const offset2 = (y2 * imageData.width + x) * 4;
  return (Math.abs(imageData.data[offset1] - imageData.data[offset2])
    + Math.abs(imageData.data[offset1 + 1] - imageData.data[offset2 + 1])
    + Math.abs(imageData.data[offset1 + 2] - imageData.data[offset2 + 2])) / 3;
}

function makeSignHorizontalTrack(distance) {
  const total = Math.round(Number(distance) || 0);
  const startX = 547;
  const startY = 425;
  const direction = total >= 0 ? 1 : -1;
  const dist = Math.abs(total);
  if (!dist) return [{ x: startX, y: startY, t: 0 }];
  const steps = Math.max(14, Math.min(42, Math.floor(dist / 3) + 12));
  const tailPause = randomInt(40, 90);
  const duration = randomInt(1100, 1999 - tailPause);
  const points = [{ x: startX, y: startY, t: 0 }];
  let lastX = 0;
  let yOffset = 0;
  for (let index = 1; index <= steps; index += 1) {
    const p = index / steps;
    let x = Math.round(dist * (1 - Math.pow(1 - p, 3)));
    if (x <= lastX) x = Math.min(dist, lastX + 1);
    if (x > dist) x = dist;
    const lastPoint = points[points.length - 1];
    const t = Math.max(lastPoint.t + 8, Math.round(duration * p + randomInt(-8, 8)));
    yOffset = nextSignYOffset(yOffset);
    points.push({ x: startX + direction * x, y: startY + yOffset, t });
    lastX = x;
    if (lastX >= dist) break;
  }
  const finalT = Math.min(1999, Math.max(1001, points[points.length - 1].t + tailPause));
  yOffset = nextSignYOffset(yOffset);
  points.push({ x: startX + total, y: startY + yOffset, t: finalT });
  return points;
}

function nextSignYOffset(current) {
  const maxJitter = 5;
  let offset = current + randomInt(-2, 2);
  offset = Math.max(-maxJitter, Math.min(maxJitter, offset));
  if (Math.abs(offset) >= 1) return offset;
  return (current < 0 ? -1 : (Math.random() < 0.5 ? -1 : 1));
}

function randomInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
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
  const purchaseInfo = api.parsePurchaseInfo([
    text,
    postRoot.textContent || '',
    document.body && document.body.innerText
  ].join('\n'));
  const authorNode = postRoot.querySelector('.authi a.xw1, .pls .authi a');
  const timeNode = postRoot.querySelector('[id^="authorposton"]');
  return {
    rawTitle,
    title: api.cleanTitle(rawTitle),
    author: api.cleanText(authorNode && authorNode.textContent),
    postTime: api.cleanText(timeNode && timeNode.textContent),
    ...info,
    ...purchaseInfo,
    isExpired: api.isExpiredThreadTitle(rawTitle),
    targetPath: api.buildTargetPath(rawTitle, new Date(), info.password)
  };
}

function collectPreviewImages(document, api) {
  const postRoot = getForumPostRoot(document) || document.body;
  const contentRoot = postRoot.querySelector('[id^="postmessage_"]') || postRoot.querySelector('.t_f') || postRoot.querySelector('.pcb') || postRoot;
  const imageUrls = Array.from(contentRoot.querySelectorAll('img'))
    .filter((img) => api.isPreviewImageElement(img))
    .map((img) => api.readPreviewImageUrl(img));
  const attachmentUrls = Array.from(postRoot.querySelectorAll('.pattl a[href*="mod=attachment"], .tattl a[href*="mod=attachment"], a[href*="forum.php?mod=attachment"]'))
    .filter((link) => api.isPreviewAttachmentLink(link.getAttribute('href') || link.href, link.textContent || link.title || ''))
    .map((link) => `${link.href || link.getAttribute('href')}#lwbt_filename=${encodeURIComponent(api.cleanText(link.textContent || link.title || ''))}`);
  const urls = imageUrls.concat(attachmentUrls);
  return Array.from(new Set(urls));
}

function injectForumPanel(root, api) {
  const document = root.document;
  if (document.querySelector('#lwbt-panel')) return;
  const info = getForumInfo(root, document, api);
  const images = collectPreviewImages(document, api);
  const postContentHtml = collectPostContentHtml(document, api);
  const panel = document.createElement('section');
  panel.id = 'lwbt-panel';
  panel.innerHTML = renderForumPanel(api, info, images, postContentHtml);
  const target = document.querySelector('#postlist') || document.querySelector('#wp') || document.body;
  target.parentNode.insertBefore(panel, target);
  bindForumPanel(root, api, info, images);
  if (info.isExpired) {
    setStatus(document, '资源已失效，请勿购买，等待楼主补链后再操作');
    return;
  }
  refreshPurchaseStatus(root, api, info).catch((error) => {
    console.warn('[LWBT] Failed to refresh purchase status', error);
    updatePurchaseStatus(document, api.purchaseStatusText(false));
  });
}

function collectPostContentHtml(document, api) {
  const postRoot = getForumPostRoot(document) || document.body;
  const source = postRoot.querySelector('[id^="postmessage_"]') || postRoot.querySelector('.t_f') || postRoot.querySelector('.pcb');
  if (!source) return '';
  const clone = source.cloneNode(true);
  clone.querySelectorAll('script,style,iframe,video,audio,canvas,object,embed,img').forEach((node) => node.remove());
  clone.querySelectorAll('a,button,input,textarea,select,[onclick],.attach_nopermission,.attach_tips,.pattl,.locked').forEach((node) => {
    const text = node.innerText || node.textContent || node.value || '';
    if (api.isPostContentNoise(text, node.className || '', node.id || '')) node.remove();
  });
  Array.from(clone.children).forEach((node) => {
    const text = node.innerText || node.textContent || '';
    if (api.isPostContentNoise(text, node.className || '', node.id || '')) node.remove();
  });
  const html = clone.innerHTML
    .replace(/(?:\s|&nbsp;|<br\s*\/?>)+$/gi, '')
    .trim();
  return html;
}

function renderForumPanel(api, info, images, postContentHtml) {
  const hasImage = images.length > 0;
  const galleryItems = images.map((url, index) => `
          <button class="lwbt-gallery-item" data-index="${index}" type="button" title="预览图 ${index + 1}">
            <img src="${escapeAttr(url)}" alt="" loading="lazy" decoding="async">
            <span>${index + 1}</span>
          </button>`).join('');
  const galleryBody = hasImage
    ? `<div class="lwbt-gallery-summary">预览图 ${images.length} 张</div><div class="lwbt-gallery-grid">${galleryItems}
        </div>`
    : '<div class="lwbt-no-image">未找到可预览图片</div>';
  const purchaseStatus = info.isExpired ? '已失效' : '检测中';
  const expiredAlert = info.isExpired
    ? '<div class="lwbt-expired-alert"><strong>资源已失效，请勿购买</strong><span>等待楼主补链后再操作。</span></div>'
    : '';
  return `
    <style>${panelCss()}</style>
    <div class="lwbt-card">
      <div class="lwbt-info">
        <h2>${escapeHtml(info.title)}</h2>
        <p class="lwbt-sub">${escapeHtml(info.author || '')} ${escapeHtml(info.postTime || '')}</p>
        ${expiredAlert}
        <div class="lwbt-grid">
          ${fieldHtml('下载方式', info.downloadType)}
          ${fieldHtml('来源', info.source)}
          ${fieldHtml('资源大小', info.size)}
          ${fieldHtml('文件数量', info.fileCount)}
          ${fieldHtml('解压密码', info.password)}
          ${fieldHtml('售价', formatPrice(info), api.fieldVariantClass('售价'))}
          ${fieldHtml('购买状态', purchaseStatus, `${api.fieldVariantClass('购买状态')} ${api.purchaseStatusClass(purchaseStatus)}`)}
          ${api.shouldShowTargetPath(info.downloadType) ? targetPathFieldHtml(info.targetPath) : ''}
        </div>
        <div class="lwbt-actions">
          <button id="lwbt-transfer" type="button">${escapeHtml(api.actionButtonText(info.downloadType))}</button>
          <button id="lwbt-copy" type="button">复制信息</button>
        </div>
        <div id="lwbt-status" class="lwbt-status">等待操作</div>
        <div class="lwbt-version">LWBT v${escapeHtml(api.VERSION)}</div>
        ${postContentHtml ? `<section class="lwbt-post-content"><div class="lwbt-post-title">帖子内容</div><div class="lwbt-post-body">${postContentHtml}</div></section>` : ''}
      </div>
      <div class="lwbt-gallery">
        <div class="lwbt-gallery-actions">
          <button id="lwbt-download-images" type="button" ${hasImage ? '' : 'disabled'}>下载全部预览图</button>
        </div>
        ${galleryBody}
      </div>
    </div>`;
}

function bindForumPanel(root, api, info, images) {
  const document = root.document;
  document.querySelectorAll('.lwbt-gallery-item').forEach((button) => {
    button.addEventListener('click', () => {
      openImageLightbox(root, api, images, Number(button.dataset.index));
    });
  });
  setupGalleryHoverPreview(root, images);
  const downloadButton = document.querySelector('#lwbt-download-images');
  if (downloadButton) {
    downloadButton.addEventListener('click', async () => {
      await downloadPreviewImages(root, api, info, images, downloadButton);
    });
  }
  const copyButton = document.querySelector('#lwbt-copy');
  if (copyButton) {
    copyButton.addEventListener('click', async () => {
      syncTargetPathFromInput(document, api, info);
      const lines = [
        info.title,
        `下载方式: ${info.downloadType}`,
        `大小: ${info.size}`,
        `解压密码: ${info.password}`
      ];
      if (api.shouldShowTargetPath(info.downloadType)) lines.push(`保存目录: ${info.targetPath}`);
      const text = lines.join('\n');
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
      syncTargetPathFromInput(document, api, info);
      const resource = info.preloadedResource || extractResourceFromDocument(document, api);
      if (resource) {
        const confirmed = root.confirm(buildResourceConfirmText(api, info, resource));
        if (!confirmed) {
          setStatus(document, '已取消');
          return;
        }
        await openResource(root, api, info, resource);
        return;
      }
      await purchaseThenQueueTransfer(root, api, info);
    });
  }
  const targetPathInput = document.querySelector('#lwbt-target-path');
  if (targetPathInput) {
    targetPathInput.addEventListener('input', () => {
      info.targetPath = targetPathInput.value;
    });
    targetPathInput.addEventListener('blur', () => {
      syncTargetPathFromInput(document, api, info);
    });
  }
}

function setupGalleryHoverPreview(root, images) {
  const document = root.document;
  if (!images.length || !root.matchMedia || !root.matchMedia('(hover: hover) and (pointer: fine)').matches) return;
  let hoverTimer = 0;
  document.querySelectorAll('.lwbt-gallery-item').forEach((button) => {
    button.addEventListener('pointerenter', (event) => {
      const index = Math.max(0, Math.min(Number(button.dataset.index) || 0, images.length - 1));
      hoverTimer = root.setTimeout(() => {
        showGalleryHoverPreview(root, images[index], event);
      }, HOVER_PREVIEW_DELAY_MS);
    });
    button.addEventListener('pointermove', (event) => {
      positionGalleryHoverPreview(root, event);
    });
    button.addEventListener('pointerleave', () => {
      if (hoverTimer) root.clearTimeout(hoverTimer);
      hoverTimer = 0;
      hideGalleryHoverPreview(root);
    });
  });
}

function ensureGalleryHoverPreview(root) {
  const document = root.document;
  let preview = document.querySelector('#lwbt-hover-preview');
  if (preview) return preview;
  preview = document.createElement('div');
  preview.id = 'lwbt-hover-preview';
  preview.hidden = true;
  preview.innerHTML = '<img alt="">';
  document.body.appendChild(preview);
  return preview;
}

function showGalleryHoverPreview(root, url, event) {
  const preview = ensureGalleryHoverPreview(root);
  const image = preview.querySelector('img');
  if (image) image.src = url;
  preview.hidden = false;
  positionGalleryHoverPreview(root, event);
}

function hideGalleryHoverPreview(root) {
  const preview = root.document.querySelector('#lwbt-hover-preview');
  if (!preview) return;
  preview.hidden = true;
}

function positionGalleryHoverPreview(root, event) {
  const preview = root.document.querySelector('#lwbt-hover-preview');
  if (!preview || preview.hidden || !event) return;
  const margin = 14;
  const rect = preview.getBoundingClientRect();
  let left = event.clientX + margin;
  let top = event.clientY + margin;
  if (left + rect.width + margin > root.innerWidth) {
    left = Math.max(margin, event.clientX - rect.width - margin);
  }
  if (top + rect.height + margin > root.innerHeight) {
    top = Math.max(margin, root.innerHeight - rect.height - margin);
  }
  preview.style.left = `${Math.round(left)}px`;
  preview.style.top = `${Math.round(top)}px`;
}

function syncTargetPathFromInput(document, api, info) {
  const input = document.querySelector('#lwbt-target-path');
  if (!input) return info.targetPath;
  const normalized = api.normalizeTargetPath(input.value, info.targetPath);
  input.value = normalized;
  info.targetPath = normalized;
  return normalized;
}

async function refreshPurchaseStatus(root, api, info) {
  const document = root.document;
  const visibleResource = extractResourceFromDocument(document, api);
  if (visibleResource) {
    info.preloadedResource = visibleResource;
    updatePurchaseStatus(document, api.purchaseStatusText(true));
    return;
  }
  const refreshedResource = await fetchForumLookupResource(root, api, info);
  if (refreshedResource) {
    info.preloadedResource = refreshedResource;
    updatePurchaseStatus(document, api.purchaseStatusText(true));
    return;
  }
  updatePurchaseStatus(document, api.purchaseStatusText(false));
}

function buildResourceConfirmText(api, info, resource) {
  if (resource && resource.type === 'laowang') {
    return `确认打开老王自建盘下载页？\n\n标题: ${info.title}\n大小: ${info.size || '-'}`;
  }
  if (resource && (resource.type === 'external' || resource.type === 'uc' || resource.type === 'quark' || resource.type === 'magnet' || resource.type === 'pan123')) {
    return `确认打开下载链接？\n\n标题: ${info.title}\n大小: ${info.size || '-'}\n${api.resourceSummary(resource)}`;
  }
  return `确认保存该资源到百度网盘？\n\n标题: ${info.title}\n大小: ${info.size}\n目录: ${info.targetPath}`;
}

async function openResource(root, api, info, resource, statusMessage) {
  if (resource && resource.type === 'laowang') {
    setStatus(root.document, statusMessage || '正在打开老王自建盘下载页');
    openUrl(root, resource.url);
    return 'opened';
  }
  if (resource && (resource.type === 'external' || resource.type === 'uc' || resource.type === 'quark' || resource.type === 'magnet' || resource.type === 'pan123')) {
    const copied = await copyResourceTexts(root, api, resource);
    const targets = api.resourceOpenTargets(resource);
    if (copied && targets.length) {
      setStatus(root.document, `${copied}，正在打开网盘链接`);
      targets.forEach((url) => openUrl(root, url));
      return 'opened';
    }
    if (copied && !targets.length) {
      setStatus(root.document, copied);
      return 'copied';
    }
    if (!targets.length) {
      setStatus(root.document, '未找到可打开的下载链接');
      return 'waiting';
    }
    setStatus(root.document, statusMessage || `${api.resourceSummary(resource)}，正在打开`);
    targets.forEach((url) => openUrl(root, url));
    return 'opened';
  }
  await queueBaiduTransfer(root, api, info, resource, statusMessage || '正在打开百度网盘保存任务');
  return 'queued';
}

async function copyResourceTexts(root, api, resource) {
  const texts = api.resourceCopyTexts(resource);
  if (!texts.length) return '';
  if (root.navigator && root.navigator.clipboard && root.navigator.clipboard.writeText) {
    await root.navigator.clipboard.writeText(texts.join('\n'));
    return texts.length === 1 ? '已复制磁力地址' : `已复制 ${texts.length} 条磁力地址`;
  }
  return '检测到磁力地址，但当前浏览器不支持自动复制';
}

function updatePurchaseStatus(document, statusText) {
  const field = Array.from(document.querySelectorAll('.lwbt-field')).find((node) => {
    const label = node.querySelector('span');
    return label && label.textContent.trim() === '购买状态';
  });
  const value = field && field.querySelector('strong');
  if (value) value.textContent = statusText;
  if (field && document.defaultView && document.defaultView.LWBT) {
    field.classList.remove('lwbt-status-purchased', 'lwbt-status-pending', 'lwbt-status-expired', 'lwbt-status-missing');
    field.classList.add(document.defaultView.LWBT.purchaseStatusClass(statusText));
  }
}

function openImageLightbox(root, api, images, startIndex) {
  const document = root.document;
  if (!images.length) return;
  let index = Math.max(0, Math.min(Number(startIndex) || 0, images.length - 1));
  let overlay = document.querySelector('#lwbt-lightbox');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'lwbt-lightbox';
    overlay.innerHTML = `
      <div class="lwbt-lightbox-backdrop" data-action="close"></div>
      <div class="lwbt-lightbox-stage">
        <button class="lwbt-lightbox-close" data-action="close" type="button">关闭</button>
        <button class="lwbt-lightbox-prev" data-action="prev" type="button">上一张</button>
        <img class="lwbt-lightbox-image" alt="">
        <button class="lwbt-lightbox-next" data-action="next" type="button">下一张</button>
        <div class="lwbt-lightbox-count"></div>
      </div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (event) => {
      const action = event.target && event.target.dataset && event.target.dataset.action;
      if (action === 'close') closeLightbox();
      if (action === 'prev') update(api.nextImageIndex(index, -1, images.length));
      if (action === 'next') update(api.nextImageIndex(index, 1, images.length));
    });
    document.addEventListener('keydown', (event) => {
      if (!document.body.classList.contains('lwbt-lightbox-open')) return;
      if (event.key === 'Escape') closeLightbox();
      if (event.key === 'ArrowLeft') update(api.nextImageIndex(index, -1, images.length));
      if (event.key === 'ArrowRight') update(api.nextImageIndex(index, 1, images.length));
    });
  }
  function update(nextIndex) {
    index = nextIndex;
    const image = overlay.querySelector('.lwbt-lightbox-image');
    const count = overlay.querySelector('.lwbt-lightbox-count');
    if (image) image.src = images[index];
    if (count) count.textContent = `${index + 1} / ${images.length}`;
  }
  function closeLightbox() {
    document.body.classList.remove('lwbt-lightbox-open');
    overlay.hidden = true;
  }
  overlay.hidden = false;
  document.body.classList.add('lwbt-lightbox-open');
  update(index);
}

async function downloadPreviewImages(root, api, info, images, button) {
  const document = root.document;
  if (!images.length) {
    setStatus(document, '没有可下载的预览图');
    return;
  }
  button.disabled = true;
  const originalText = button.textContent;
  button.textContent = '打包中...';
  try {
    const files = [];
    const folderName = api.previewZipFolderName(info.title);
    let success = 0;
    let failed = 0;
    setStatus(document, `准备下载 ${images.length} 张预览图...`);
    for (let index = 0; index < images.length; index += 1) {
      const url = images[index];
      button.textContent = `下载 ${index + 1}/${images.length}`;
      setStatus(document, `正在下载预览图 ${index + 1}/${images.length}`);
      try {
        const imageFile = await readPreviewImageFile(root, api, url);
        files.push({
          name: `${folderName}/${api.previewImageFilename(url, index, imageFile.type)}`,
          data: imageFile.data
        });
        success += 1;
      } catch (error) {
        console.warn('[LWBT] Failed to fetch preview image', url, error);
        failed += 1;
      }
    }
    if (!success) {
      setStatus(document, api.previewDownloadSummary(success, failed));
      return;
    }
    button.textContent = '生成 ZIP...';
    setStatus(document, `正在生成 ZIP：已加入 ${success} 张${failed ? `，失败 ${failed} 张` : ''}`);
    const zipBytes = api.buildStoreZipBytes(files);
    const blob = new root.Blob([zipBytes], { type: 'application/zip' });
    triggerPreviewZipDownload(root, blob, api.buildPreviewZipFilename(info.title));
    setStatus(document, api.previewDownloadSummary(success, failed));
  } catch (error) {
    console.warn('[LWBT] Failed to download preview images', error);
    setStatus(document, `预览图打包失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function readPreviewImageFile(root, api, url) {
  if (api.previewDownloadMethod(url) === 'gm') {
    return gmFetchPreviewImage(root, api, url);
  }
  const blob = await fetchPreviewImage(root, api, url);
  return {
    data: await blob.arrayBuffer(),
    type: blob.type
  };
}

async function fetchPreviewImage(root, api, url) {
  const targetUrl = new root.URL(api.previewRequestUrl(url), root.location.href).toString();
  const controller = typeof root.AbortController === 'function' ? new root.AbortController() : null;
  const timer = controller ? root.setTimeout(() => controller.abort(), PREVIEW_IMAGE_TIMEOUT_MS) : null;
  try {
    const response = await root.fetch(targetUrl, {
      credentials: 'include',
      signal: controller ? controller.signal : undefined
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    return blob;
  } finally {
    if (timer) root.clearTimeout(timer);
  }
}

function gmFetchPreviewImage(root, api, url) {
  if (typeof GM_xmlhttpRequest !== 'function') {
    throw new Error('当前脚本缺少 GM_xmlhttpRequest 权限，无法下载原始附件图片');
  }
  const targetUrl = new root.URL(api.previewRequestUrl(url), root.location.href).toString();
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = root.setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new Error('原始附件图片下载超时'));
    }, PREVIEW_ATTACHMENT_READY_TIMEOUT_MS);
    GM_xmlhttpRequest({
      method: 'GET',
      url: targetUrl,
      headers: {
        Accept: 'image/gif,image/jpeg,image/png,image/*,*/*;q=0.8',
        'Cache-Control': 'no-transform'
      },
      responseType: 'arraybuffer',
      timeout: PREVIEW_ATTACHMENT_READY_TIMEOUT_MS,
      anonymous: false,
      onload(response) {
        if (settled) return;
        settled = true;
        root.clearTimeout(timer);
        const status = Number(response.status) || 0;
        if (status < 200 || status >= 300) {
          reject(new Error(`HTTP ${status}`));
          return;
        }
        const data = gmResponseToArrayBuffer(response.response);
        resolve({
          data,
          type: readResponseHeader(response, 'content-type')
        });
      },
      onerror(error) {
        if (settled) return;
        settled = true;
        root.clearTimeout(timer);
        reject(new Error(error && error.error ? String(error.error) : '原始附件图片下载失败'));
      },
      ontimeout() {
        if (settled) return;
        settled = true;
        root.clearTimeout(timer);
        reject(new Error('原始附件图片下载超时'));
      }
    });
  });
}

function readResponseHeader(response, name) {
  const headers = String(response && response.responseHeaders || '');
  const pattern = new RegExp(`^${name}:\\s*(.+)$`, 'im');
  const match = headers.match(pattern);
  return match ? match[1].trim() : '';
}

function gmResponseToArrayBuffer(value) {
  if (value instanceof ArrayBuffer) return value;
  if (ArrayBuffer.isView(value)) return value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength);
  throw new Error('原始附件图片响应不是 ArrayBuffer');
}

function triggerPreviewZipDownload(root, blob, filename) {
  const objectUrl = root.URL.createObjectURL(blob);
  const cleanup = () => {
    root.setTimeout(() => root.URL.revokeObjectURL(objectUrl), 60000);
  };
  if (typeof GM_download === 'function') {
    try {
      GM_download({
        url: objectUrl,
        name: filename,
        saveAs: false,
        onload: cleanup,
        ontimeout: () => {
          console.warn('[LWBT] GM_download timed out, falling back to anchor download');
          triggerAnchorDownload(root, objectUrl, filename);
          cleanup();
        },
        onerror: (error) => {
          console.warn('[LWBT] GM_download failed, falling back to anchor download', error);
          triggerAnchorDownload(root, objectUrl, filename);
          cleanup();
        }
      });
      return;
    } catch (error) {
      console.warn('[LWBT] GM_download unavailable, falling back to anchor download', error);
    }
  }
  triggerAnchorDownload(root, objectUrl, filename);
  cleanup();
}

function triggerAnchorDownload(root, objectUrl, filename) {
  const link = root.document.createElement('a');
  link.href = objectUrl;
  link.download = filename;
  link.rel = 'noopener';
  root.document.body.appendChild(link);
  link.click();
  root.setTimeout(() => link.remove(), 3000);
}

async function purchaseThenQueueTransfer(root, api, info) {
  const document = root.document;
  syncTargetPathFromInput(document, api, info);
  setStatus(document, '正在刷新帖子状态...');
  const refreshedResource = await fetchForumLookupResource(root, api, info);
  if (refreshedResource) {
    const confirmed = root.confirm(buildResourceConfirmText(api, info, refreshedResource));
    if (!confirmed) {
      setStatus(document, '已取消');
      return 'cancelled';
    }
    return openResource(root, api, info, refreshedResource);
  }
  const actionTargets = findActionTargets(root, api);
  const target = api.chooseActionTarget(actionTargets);
  const purchaseCount = actionTargets.filter((item) => item.type === 'purchase').length;
  const lookupCount = actionTargets.filter((item) => item.type === 'lookup').length;
  if (!target) {
    if (api.shouldBlockForLogin(document.body.innerText || '', actionTargets)) {
      setStatus(document, '请先登录论坛后刷新页面');
      return;
    }
    setStatus(document, `未找到百度分享链接、资源链接或论坛购买按钮，请确认资源状态（${api.VERSION}）`);
    return 'waiting';
  }
  if (target.type === 'lookup') {
    setStatus(document, `找到已购买资源入口 ${lookupCount} 个，正在打开资源链接...`);
    target.node.click();
    const resource = await waitForResource(root, api, PURCHASE_OPENED_RESOURCE_TIMEOUT_MS);
    if (resource) {
      return openResource(root, api, info, resource);
    }
    setStatus(document, '已打开资源链接窗口，但还没有读取到真实下载链接；请确认弹窗内容');
    return 'waiting';
  }
  const purchaseLink = target.node;
  const creditInfo = await fetchCurrentCredit(root, api);
  const confirmed = root.confirm(api.buildPurchaseConfirmText(info, creditInfo));
  if (!confirmed) {
    setStatus(document, '已取消');
    return 'cancelled';
  }
  setStatus(document, `找到购买入口 ${purchaseCount} 个，正在提交购买请求...`);
  const directPurchase = await submitForumPurchaseRequest(root, api, purchaseLink.href);
  if (directPurchase.ok) {
    setStatus(document, '已确认论坛购买，正在刷新帖子读取百度链接...');
  } else {
    console.warn('[LWBT] Direct forum purchase failed, falling back to modal click', directPurchase.error || directPurchase.text);
    setStatus(document, `直接购买未完成，正在回退到论坛弹窗：${target.text || '立即购买'}`);
    purchaseLink.click();
    if (await waitAndClickForumPurchaseConfirm(root, api, PURCHASE_CONFIRM_TIMEOUT_MS)) {
      setStatus(document, '已确认论坛购买，正在读取百度链接...');
    } else {
      setStatus(document, '已打开论坛购买窗口，正在等待百度链接...');
    }
  }
  let resource = await waitForResource(root, api, PURCHASE_DIRECT_RESOURCE_TIMEOUT_MS);
  if (resource) {
    return openResource(root, api, info, resource);
  }
  setStatus(document, '已购买，正在自动打开资源链接...');
  let lookupResource = await waitForForumLookupResource(root, api, info, PURCHASE_LOOKUP_RESOURCE_TIMEOUT_MS);
  if (lookupResource) {
    return openResource(root, api, info, lookupResource);
  }
  const lookupTarget = await waitForLookupTarget(root, api, PURCHASE_LOOKUP_TARGET_TIMEOUT_MS);
  if (!lookupTarget) {
    lookupResource = await waitForForumLookupResource(root, api, info, PURCHASE_LOOKUP_RESOURCE_TIMEOUT_MS);
    if (lookupResource) {
      return openResource(root, api, info, lookupResource);
    }
    setStatus(document, '已打开购买流程；未等到资源链接，请确认购买弹窗状态');
    return 'waiting';
  }
  if (lookupTarget.resource) {
    return openResource(root, api, info, lookupTarget.resource);
  }
  lookupTarget.node.click();
  resource = await waitForResource(root, api, PURCHASE_OPENED_RESOURCE_TIMEOUT_MS);
  if (!resource) {
    setStatus(document, '已打开资源链接，但还没有读取到真实下载链接；请确认弹窗内容');
    return 'waiting';
  }
  return openResource(root, api, info, resource);
}

async function submitForumPurchaseRequest(root, api, purchaseUrl) {
  if (!root.fetch || !purchaseUrl) return { ok: false, error: 'fetch unavailable' };
  try {
    const formResponse = await root.fetch(api.buildForumAjaxUrl(purchaseUrl, root.location.href), {
      credentials: 'include',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    });
    const formText = await formResponse.text();
    const form = api.parseForumPurchaseForm(formText);
    if (!form) return { ok: false, text: formText, error: 'purchase form not found' };
    const body = new root.URLSearchParams(form.fields);
    const postResponse = await root.fetch(api.buildForumAjaxUrl(form.action || purchaseUrl, root.location.href), {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: body.toString()
    });
    const postText = await postResponse.text();
    const ok = postResponse.ok && /购买成功|已经购买|已购买|success/i.test(postText);
    return { ok, text: postText };
  } catch (error) {
    return { ok: false, error: error.message };
  }
}

function findActionTargets(root, api) {
  const document = root.document;
  return Array.from(document.querySelectorAll('a,button,[onclick]')).map((node) => {
    const href = node.href || node.getAttribute('href') || '';
    const text = node.innerText || node.textContent || node.value || node.title || '';
    const actionSource = node.getAttribute('onclick') || '';
    const className = node.className || '';
    const visible = isVisible(root, node);
    if (api.isPurchaseLink(href, text, className, actionSource)) {
      return { type: 'purchase', node, visible, text: cleanNodeText(node), href };
    }
    if (api.isResourceLookupLink(href, text, className, actionSource)) {
      return { type: 'lookup', node, visible, text: cleanNodeText(node), href };
    }
    return null;
  }).filter(Boolean);
}

async function waitAndClickForumPurchaseConfirm(root, api, timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (clickForumPurchaseConfirm(root, api)) return true;
    await sleep(300);
  }
  return false;
}

function clickForumPurchaseConfirm(root, api) {
  const document = root.document;
  const modalRoots = Array.from(document.querySelectorAll('#fwin_dtpaytip, [id^="fwin_"], .fwinmask, .floatwin'));
  for (const scope of modalRoots) {
    const candidate = Array.from(scope.querySelectorAll('button, a, input[type="button"], input[type="submit"]')).find((node) => {
      if (!isVisible(root, node) || node.id === 'lwbt-transfer') return false;
      const label = cleanNodeText(node);
      const href = node.href || node.getAttribute('href') || '';
      return api.isForumPurchaseConfirmButton(label, href);
    });
    if (candidate) {
      candidate.click();
      return true;
    }
  }
  return false;
}

function isVisible(root, node) {
  const style = root.getComputedStyle ? root.getComputedStyle(node) : null;
  return (!style || (style.display !== 'none' && style.visibility !== 'hidden')) && Boolean(node.offsetParent || node.getClientRects().length);
}

function cleanNodeText(node) {
  return String(node.innerText || node.textContent || node.value || node.title || '').replace(/\s+/g, ' ').trim();
}

async function waitForBaiduShare(root, api, timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const share = extractBaiduShareFromDocument(root.document, api);
    if (share) return share;
    await sleep(500);
  }
  return null;
}

async function waitForResource(root, api, timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const resource = extractResourceFromDocument(root.document, api);
    if (resource) return resource;
    await sleep(500);
  }
  return null;
}

async function waitForLookupTarget(root, api, timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const target = api.chooseLookupTarget(findActionTargets(root, api));
    if (target) return target;
    const resource = extractResourceFromDocument(root.document, api);
    if (resource) return { type: 'resource', node: { click() {} }, visible: true, resource };
    await sleep(500);
  }
  return null;
}

async function waitForForumLookupShare(root, api, info, timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const share = await fetchForumLookupShare(root, api, info);
    if (share) return share;
    await sleep(PURCHASE_LOOKUP_POLL_INTERVAL_MS);
  }
  return null;
}

async function fetchForumLookupShare(root, api, info) {
  const resource = await fetchForumLookupResource(root, api, info);
  return resource && resource.type === 'baidu' ? resource : null;
}

async function waitForForumLookupResource(root, api, info, timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const resource = await fetchForumLookupResource(root, api, info);
    if (resource) return resource;
    await sleep(PURCHASE_LOOKUP_POLL_INTERVAL_MS);
  }
  return null;
}

async function fetchForumLookupResource(root, api, info) {
  if (!root.fetch) return null;
  const lookupUrls = api.buildForumLookupUrls(info && info.sourceUrl ? info.sourceUrl : root.location.href);
  if (!lookupUrls.length) return null;
  const seen = new Set();
  for (const lookupUrl of lookupUrls) {
    const resource = await fetchForumResourceFromUrl(root, api, lookupUrl, seen, 0);
    if (resource) return resource;
  }
  return null;
}

async function fetchForumShareFromUrl(root, api, url, seen, depth) {
  const resource = await fetchForumResourceFromUrl(root, api, url, seen, depth);
  return resource && resource.type === 'baidu' ? resource : null;
}

async function fetchForumResourceFromUrl(root, api, url, seen, depth) {
  if (!url || seen.has(url) || depth > 3) return null;
  seen.add(url);
  try {
    const response = await root.fetch(url, {
      credentials: 'include',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    });
    const text = await response.text();
    const resource = api.extractResourceLink(text, url);
    if (resource) return resource;
    const chainedUrls = api.extractForumResourceUrls(text, root.location.href);
    for (const nextUrl of chainedUrls) {
      const chainedResource = await fetchForumResourceFromUrl(root, api, nextUrl, seen, depth + 1);
      if (chainedResource) return chainedResource;
    }
    return null;
  } catch (error) {
    console.warn('[LWBT] Failed to fetch forum lookup link', error);
    return null;
  }
}

async function fetchCurrentCredit(root, api) {
  if (!root.fetch) return {};
  try {
    const response = await root.fetch('/home.php?mod=spacecp&ac=credit', { credentials: 'include' });
    const html = await response.text();
    return api.parseCreditInfo(html);
  } catch (error) {
    console.warn('[LWBT] Failed to fetch credit info', error);
    return {};
  }
}

function extractBaiduShareFromDocument(document, api) {
  const resource = extractResourceFromDocument(document, api);
  return resource && resource.type === 'baidu' ? resource : null;
}

function extractResourceFromDocument(document, api) {
  const chunks = [
    document.body && document.body.innerText,
    document.documentElement && document.documentElement.innerHTML
  ];
  document.querySelectorAll('a,button,input,textarea,[onclick],[data-url],[data-href],[data-clipboard-text]').forEach((node) => {
    chunks.push(
      node.href,
      node.value,
      node.title,
      node.textContent,
      node.getAttribute('href'),
      node.getAttribute('onclick'),
      node.getAttribute('data-url'),
      node.getAttribute('data-href'),
      node.getAttribute('data-clipboard-text')
    );
  });
  return api.extractResourceLink(chunks.filter(Boolean).join('\n'), document.location && document.location.href);
}

async function queueBaiduTransfer(root, api, info, share, statusMessage) {
  const task = api.createTransferTask({
    sourceUrl: root.location.href,
    rawTitle: info.rawTitle,
    shareUrl: share.shareUrl,
    extractCode: share.extractCode,
    password: info.password,
    size: info.size,
    targetPath: info.targetPath
  });
  const tasks = await readTasks(root, api);
  tasks.push(task);
  await writeTasks(root, api, tasks);
  setStatus(root.document, statusMessage);
  const openUrl = api.buildBaiduTaskOpenUrl(task);
  openBaiduUrl(root, openUrl);
}

function openBaiduUrl(root, openUrl) {
  openUrlInTab(root, openUrl);
}

function openUrl(root, openUrl) {
  openUrlInTab(root, openUrl);
}

function openUrlInTab(root, openUrl) {
  if (typeof GM_openInTab === 'function') {
    try {
      GM_openInTab(openUrl, { active: true });
      return;
    } catch (error) {
      console.warn('[LWBT] GM_openInTab failed, falling back to window.open', error);
    }
  }
  const opened = root.open(openUrl, '_blank');
  if (!opened) root.location.href = openUrl;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
  if (active) return { tasks, active };
  const urlTask = api.readBaiduTaskFromUrl(root.location.href);
  if (urlTask && api.findPendingTaskForUrl([urlTask], root.location.href)) {
    stripBaiduTaskParam(root, api);
    tasks.push(urlTask);
    return { tasks, active: urlTask };
  }
  return { tasks, active: null };
}

async function runBaidu(root, api) {
  const document = root.document;
  removeBaiduHints(document);
  const { tasks, active } = await findActiveBaiduTask(root, api);
  if (!active) return;
  showBaiduToast(document, `准备保存到 ${active.targetPath}`, 'info');
  try {
    await fillBaiduCodeIfNeeded(root, active);
    await saveBaiduShare(root, active);
    active.status = 'saved';
    active.savedAt = new Date().toISOString();
    await writeTasks(root, api, tasks);
    showBaiduToast(document, `保存成功：已保存到 ${active.targetPath}`, 'success', 12000);
  } catch (error) {
    active.status = 'failed';
    active.error = error.message;
    await writeTasks(root, api, tasks);
    showBaiduToast(document, `自动保存失败：${error.message}，请手动保存`, 'error', 20000);
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
  const targetPathReady = await ensureBaiduTargetPath(root, root.LWBT, task.targetPath);
  if (targetPathReady && await transferBaiduShareToTargetPath(root, root.LWBT, task.targetPath)) {
    closeBaiduPathDialog(root);
    return;
  }
  await chooseBaiduSavePath(root, task.targetPath, { allowCreate: !targetPathReady });
  if (isBaiduSaveComplete(document)) return;
  const saveButton = findBaiduSaveButton(root);
  if (!saveButton && isBaiduSaveComplete(document)) return;
  if (!saveButton) throw new Error('未找到百度网盘保存按钮');
  clickBaiduElement(root, saveButton);
  await waitForBaiduSaveComplete(document, 30000);
}

async function transferBaiduShareToTargetPath(root, api, targetPath) {
  if (!api || !root.fetch || !api.buildBaiduTransferUrl || !api.buildBaiduTransferBody) return false;
  const token = readBaiduToken(root);
  const context = readBaiduShareContext(root, api);
  if (!token || !context || !context.shareId || !context.from || !context.fsIds || !context.fsIds.length) return false;
  const response = await root.fetch(api.buildBaiduTransferUrl(context, token, readBaiduSeKey(root)), {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
    },
    body: api.buildBaiduTransferBody(targetPath, context.fsIds).toString()
  });
  const data = await response.json();
  if (data && data.errno === 0) return true;
  console.warn('[LWBT] Direct baidu transfer failed, falling back to page save flow', data);
  return false;
}

async function ensureBaiduTargetPath(root, api, targetPath) {
  if (!api || !root.fetch) return false;
  const token = readBaiduToken(root);
  if (!token) return false;
  const entries = api.baiduPathEntries(targetPath);
  for (const entry of entries) {
    const existing = await baiduChildFolderExists(root, api, token, entry.parentPath, entry.folderName);
    if (existing) continue;
    await createBaiduFolder(root, api, token, entry.folderPath);
    await waitForCondition(() => baiduChildFolderExists(root, api, token, entry.parentPath, entry.folderName), 8000, 500);
  }
  return true;
}

function stripBaiduTaskParam(root, api) {
  if (!root.history || !root.location || !api || !api.stripBaiduTaskParamFromUrl) return;
  const cleaned = api.stripBaiduTaskParamFromUrl(root.location.href);
  if (cleaned && cleaned !== root.location.href) {
    root.history.replaceState(root.history.state, root.document && root.document.title || '', cleaned);
  }
}

function readBaiduToken(root) {
  const fromResources = root.performance && root.performance.getEntriesByType
    ? root.performance.getEntriesByType('resource').map((entry) => entry.name).join(' ')
    : '';
  const api = root.LWBT;
  const resourceToken = api && api.extractBaiduTokenFromText ? api.extractBaiduTokenFromText(fromResources) : '';
  if (resourceToken) return resourceToken;
  const html = root.document && root.document.documentElement ? root.document.documentElement.innerHTML : '';
  return api && api.extractBaiduTokenFromText ? api.extractBaiduTokenFromText(html) : '';
}

function readBaiduSeKey(root) {
  const surl = readBaiduSurl(root);
  if (surl && root.localStorage) {
    const stored = root.localStorage.getItem(`${surl}_bdclnd`);
    if (stored) return decodeURIComponent(stored);
  }
  const cookieMatch = String(root.document && root.document.cookie || '').match(/(?:^|;\s*)BDCLND=([^;]+)/);
  return cookieMatch ? decodeURIComponent(cookieMatch[1]) : '';
}

function readBaiduSurl(root) {
  const match = String(root.location && root.location.pathname || '').match(/\/s\/([^/?#]+)/);
  return match ? match[1] : '';
}

function readBaiduShareContext(root, api) {
  const chunks = [
    root.document && root.document.documentElement && root.document.documentElement.innerHTML,
    root.performance && root.performance.getEntriesByType
      ? root.performance.getEntriesByType('resource').map((entry) => entry.name).join('\n')
      : ''
  ];
  return api.extractBaiduShareContextFromText(chunks.join('\n'));
}

async function baiduFolderExists(root, api, token, folderPath) {
  const response = await root.fetch(api.buildBaiduApiUrl('/api/list', {
    order: 'time',
    desc: 1,
    showempty: 0,
    page: 1,
    num: 1,
    dir: folderPath,
    bdstoken: token
  }), { credentials: 'include' });
  const data = await response.json();
  return data && data.errno === 0;
}

async function baiduChildFolderExists(root, api, token, parentPath, folderName) {
  const response = await root.fetch(api.buildBaiduApiUrl('/api/list', {
    order: 'name',
    desc: 0,
    showempty: 0,
    page: 1,
    num: 1000,
    dir: parentPath,
    bdstoken: token
  }), { credentials: 'include' });
  const data = await response.json();
  if (!data || data.errno !== 0 || !Array.isArray(data.list)) {
    throw new Error(`百度网盘目录确认失败：${parentPath}${data && data.errno !== undefined ? ` errno=${data.errno}` : ''}`);
  }
  return data.list.some((item) => item && item.isdir === 1 && cleanNodeLabel(item.server_filename) === cleanNodeLabel(folderName));
}

async function createBaiduFolder(root, api, token, folderPath) {
  const response = await root.fetch(api.buildBaiduApiUrl('/api/create', {
    a: 'commit',
    bdstoken: token
  }), {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
    },
    body: api.buildBaiduCreateFolderBody(folderPath).toString()
  });
  const data = await response.json();
  if (data && (data.errno === 0 || data.errno === -8)) return data;
  throw new Error(`百度网盘目录创建失败：${folderPath}${data && data.errno !== undefined ? ` errno=${data.errno}` : ''}`);
}

async function chooseBaiduSavePath(root, targetPath, options = {}) {
  const document = root.document;
  if (baiduCurrentSavePathMatches(document, targetPath)) {
    await confirmBaiduPathDialogIfOpen(root);
    return;
  }
  const dialog = await openBaiduPathDialog(root);
  const recent = findBaiduRecentPath(dialog, targetPath);
  if (recent) {
    await clickBaiduRecentPath(root, recent);
    await sleep(300);
  } else {
    const segments = root.LWBT ? root.LWBT.targetPathToSegments(targetPath) : String(targetPath || '').split('/').filter(Boolean);
    if (!segments.length) throw new Error('目标目录为空');
    let liveDialog = dialog;
    for (const segment of segments) {
      liveDialog = document.querySelector('.dialog-fileTreeDialog') || liveDialog;
      await selectOrCreateBaiduFolder(root, liveDialog, segment, options);
    }
  }
  const liveDialog = document.querySelector('.dialog-fileTreeDialog') || dialog;
  const confirmButton = findBaiduDialogButtonByText(liveDialog, /^确定$/) || liveDialog.querySelector('[node-type="confirm"]');
  if (!confirmButton) throw new Error('未找到百度网盘目录确认按钮');
  clickBaiduElement(root, confirmButton);
  await waitForCondition(() => baiduCurrentSavePathMatches(document, targetPath) || !document.querySelector('.dialog-fileTreeDialog'), 10000);
  if (!baiduCurrentSavePathMatches(document, targetPath)) {
    throw new Error(`目标目录未切换成功：${targetPath}`);
  }
}

async function confirmBaiduPathDialogIfOpen(root) {
  const dialog = root.document.querySelector('.dialog-fileTreeDialog');
  if (!dialog) return false;
  const confirmButton = findBaiduDialogButtonByText(dialog, /^确定$/) || dialog.querySelector('[node-type="confirm"]');
  if (!confirmButton) return false;
  clickBaiduElement(root, confirmButton);
  await waitForCondition(() => !root.document.querySelector('.dialog-fileTreeDialog'), 5000, 200).catch(() => null);
  return true;
}

function closeBaiduPathDialog(root) {
  const dialog = root.document.querySelector('.dialog-fileTreeDialog');
  if (!dialog) return false;
  const closeButton = dialog.querySelector('.dialog-icon, .icon-svg-s-close') || findBaiduDialogButtonByText(dialog, /^取消$/);
  if (!closeButton) return false;
  clickBaiduElement(root, closeButton);
  return true;
}

async function openBaiduPathDialog(root) {
  const document = root.document;
  const existing = document.querySelector('.dialog-fileTreeDialog');
  if (existing) return existing;
  const trigger = document.querySelector('.bottom-save-path-icon')
    || document.querySelector('.bottom-save-path')
    || document.querySelector('.save-path');
  if (!trigger) throw new Error('未找到百度网盘目录选择入口');
  trigger.click();
  return waitForSelector(document, '.dialog-fileTreeDialog', 10000);
}

async function selectOrCreateBaiduFolder(root, dialog, folderName, options = {}) {
  const allowCreate = options.allowCreate !== false;
  const existing = await waitForBaiduTreeNode(dialog, folderName, allowCreate ? 800 : 2500);
  if (existing) {
    clickBaiduTreeNode(root, existing);
    await sleep(1000);
    return;
  }
  if (!allowCreate) {
    throw new Error(`百度网盘目录未在弹窗中加载：${folderName}，已阻止新建同名目录`);
  }
  const createButton = findButtonByText(dialog, /^新建文件夹$/);
  if (!createButton) throw new Error(`未找到新建文件夹按钮，无法创建：${folderName}`);
  createButton.click();
  const input = await waitForBaiduNewFolderInput(dialog, 5000);
  setEditableValue(root, input, folderName);
  input.dispatchEvent(new root.KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
  input.dispatchEvent(new root.KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
  await sleep(1200);
  const created = findBaiduTreeNode(dialog, folderName);
  if (!created) throw new Error(`百度网盘目录创建后未找到：${folderName}`);
  clickBaiduTreeNode(root, created);
  await sleep(800);
}

async function waitForBaiduTreeNode(dialog, folderName, timeoutMs) {
  try {
    return await waitForCondition(() => findBaiduTreeNode(dialog, folderName), timeoutMs, 200);
  } catch (_error) {
    return null;
  }
}

function findBaiduTreeNode(dialog, folderName) {
  const target = cleanNodeLabel(folderName);
  const label = Array.from(dialog.querySelectorAll('.treeview-txt')).find((node) => cleanNodeLabel(node.textContent) === target);
  if (!label) return null;
  return label.closest('.treeview-node') || label;
}

function clickBaiduTreeNode(root, node) {
  node.click();
  if (!/\b_minus\b/.test(String(node.className || ''))) {
    const view = node.ownerDocument && node.ownerDocument.defaultView;
    const MouseEventCtor = view && view.MouseEvent ? view.MouseEvent : root.MouseEvent;
    node.dispatchEvent(new MouseEventCtor('dblclick', { bubbles: true, cancelable: true }));
  }
}

function findBaiduRecentPath(dialog, targetPath) {
  const direct = Array.from(dialog.querySelectorAll('.save-path-item')).find((node) => baiduPathTextMatches(node.title || node.textContent, targetPath));
  if (direct) return direct;
  const candidates = Array.from(dialog.querySelectorAll('label, span, div'))
    .filter((node) => /最近保存路径/.test(node.textContent || '') && baiduPathTextMatches(node.textContent || '', targetPath))
    .sort((left, right) => cleanNodeText(left).length - cleanNodeText(right).length);
  if (!candidates.length) return null;
  return findBaiduRecentPathClickTarget(candidates[0]);
}

function findBaiduRecentPathClickTarget(node) {
  let current = node;
  for (let depth = 0; current && depth < 5; depth += 1) {
    const checkbox = current.querySelector && current.querySelector('input[type="checkbox"], [role="checkbox"]');
    if (checkbox) return checkbox;
    if (String(current.tagName || '').toUpperCase() === 'LABEL') return current;
    current = current.parentElement;
  }
  return node;
}

async function clickBaiduRecentPath(root, node) {
  if (isBaiduRecentPathChecked(node)) return;
  clickBaiduElement(root, node);
  await sleep(120);
  if (isBaiduRecentPathChecked(node)) return;
  clickBaiduRecentPathCheckboxPoint(root, node);
  await sleep(120);
  if (!isBaiduRecentPathChecked(node)) {
    clickBaiduElement(root, node);
  }
}

function clickBaiduRecentPathCheckboxPoint(root, node) {
  const document = node.ownerDocument || root.document;
  const row = findBaiduRecentPathRow(node);
  const rect = row && row.getBoundingClientRect ? row.getBoundingClientRect() : null;
  if (!rect || !rect.width || !rect.height) return false;
  const textRect = node.getBoundingClientRect ? node.getBoundingClientRect() : rect;
  const x = Math.max(rect.left + 10, Math.min(textRect.left - 16, rect.right - 10));
  const y = textRect.top + (textRect.height || rect.height) / 2;
  const target = document.elementFromPoint ? document.elementFromPoint(x, y) : null;
  clickBaiduElement(root, target || row, x, y);
  return true;
}

function findBaiduRecentPathRow(node) {
  let current = node;
  for (let depth = 0; current && depth < 6; depth += 1) {
    const text = current.textContent || '';
    if (/最近保存路径/.test(text) && current.getBoundingClientRect) return current;
    current = current.parentElement;
  }
  return node;
}

function findBaiduDialogButtonByText(scope, pattern) {
  const candidates = Array.from(scope.querySelectorAll('button,a,input[type="button"],input[type="submit"],[role="button"],.g-button,[class*="btn"],[class*="button"],span,div'))
    .filter((node) => {
      const view = node.ownerDocument && node.ownerDocument.defaultView;
      return view && isVisible(view, node) && pattern.test(cleanNodeText(node));
    })
    .sort((left, right) => cleanNodeText(left).length - cleanNodeText(right).length);
  if (!candidates.length) return null;
  const buttonLike = candidates[0].closest && candidates[0].closest('button,a,input[type="button"],input[type="submit"],[role="button"],.g-button,[class*="btn"],[class*="button"]');
  return buttonLike || candidates[0];
}

function clickBaiduElement(root, node, clientX, clientY) {
  if (!node) return;
  const view = node.ownerDocument && node.ownerDocument.defaultView || root;
  const rect = node.getBoundingClientRect ? node.getBoundingClientRect() : null;
  const x = Number.isFinite(clientX) ? clientX : (rect ? rect.left + rect.width / 2 : 0);
  const y = Number.isFinite(clientY) ? clientY : (rect ? rect.top + rect.height / 2 : 0);
  const MouseEventCtor = view && view.MouseEvent ? view.MouseEvent : root.MouseEvent;
  ['mousedown', 'mouseup', 'click'].forEach((type) => {
    node.dispatchEvent(new MouseEventCtor(type, { bubbles: true, cancelable: true, clientX: x, clientY: y }));
  });
  if (typeof node.click === 'function') node.click();
}

function isBaiduRecentPathChecked(node) {
  if (!node) return false;
  if (node.checked === true || node.getAttribute && node.getAttribute('aria-checked') === 'true') return true;
  const marker = String(node.className || '');
  if (/\b(?:checked|selected|active)\b/i.test(marker)) return true;
  const input = node.querySelector && node.querySelector('input[type="checkbox"], [role="checkbox"]');
  return Boolean(input && (input.checked === true || input.getAttribute('aria-checked') === 'true' || /\b(?:checked|selected|active)\b/i.test(String(input.className || ''))));
}

function findBaiduSaveButton(root) {
  return Array.from(root.document.querySelectorAll('.bottom_save_btn, .save_btn, a, button')).find((node) => {
    if (!isVisible(root, node)) return false;
    const label = cleanNodeText(node);
    const title = node.title || '';
    return /保存到网盘/.test(`${label} ${title}`);
  }) || null;
}

function baiduCurrentSavePathMatches(document, targetPath) {
  return Array.from(document.querySelectorAll('.save-path, .bottom-save-path, .bottom_save_path, [class*="save-path"]')).some((node) => {
    if (node.closest && node.closest('.dialog-fileTreeDialog')) return false;
    return baiduPathTextMatches(node.textContent || node.title || '', targetPath);
  });
}

function baiduPathTextMatches(value, targetPath) {
  const current = normalizeBaiduPath(value);
  const expected = normalizeBaiduPath(targetPath);
  if (!current || !expected) return false;
  return current === expected
    || current.endsWith(`/${expected}`)
    || current.includes(`/${expected}`)
    || current.startsWith(`${expected} `)
    || current.includes(` ${expected}`);
}

function normalizeBaiduPath(value) {
  return String(value || '')
    .replace(/^最近保存路径[:：]\s*/, '')
    .replace(/^保存到[:：]\s*/, '')
    .replace(/^我的网盘\/?/, '')
    .replace(/^\/+|\/+$/g, '')
    .replace(/\/+/g, '/')
    .trim();
}

function cleanNodeLabel(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function findButtonByText(scope, pattern) {
  return Array.from(scope.querySelectorAll('a,button,input[type="button"],input[type="submit"],.g-button')).find((node) => {
    const label = cleanNodeText(node);
    const title = node.title || '';
    return pattern.test(label) || pattern.test(title);
  }) || null;
}

function waitForBaiduNewFolderInput(dialog, timeoutMs) {
  return waitForCondition(() => {
    return Array.from(dialog.querySelectorAll('input[type="text"], input:not([type]), textarea, [contenteditable="true"]')).find((node) => {
      const style = node.ownerDocument.defaultView.getComputedStyle(node);
      return style.display !== 'none' && style.visibility !== 'hidden' && (node.offsetParent || node.getClientRects().length);
    }) || null;
  }, timeoutMs);
}

function setEditableValue(root, node, value) {
  if (node.isContentEditable) {
    node.textContent = value;
  } else {
    node.value = value;
  }
  node.dispatchEvent(new root.Event('input', { bubbles: true }));
  node.dispatchEvent(new root.Event('change', { bubbles: true }));
}

function waitForBaiduSaveComplete(document, timeoutMs) {
  return waitForCondition(() => isBaiduSaveComplete(document), timeoutMs);
}

function isBaiduSaveComplete(document) {
  return /保存成功|已保存至/.test(document.body.innerText || '');
}

function waitForCondition(predicate, timeoutMs = 10000, intervalMs = 250) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const tick = () => {
      let result = null;
      try {
        result = predicate();
      } catch (_error) {
        result = null;
      }
      if (result) {
        resolve(result);
        return;
      }
      if (Date.now() - started >= timeoutMs) {
        reject(new Error('等待页面状态超时'));
        return;
      }
      setTimeout(tick, intervalMs);
    };
    tick();
  });
}

function removeBaiduHints(document) {
  document.querySelectorAll('#lwbt-baidu-toast, #lwbt-baidu-path-hint').forEach((node) => node.remove());
}

function showBaiduToast(document, message, type = 'info', durationMs = 6000) {
  removeBaiduHints(document);
  if (document.defaultView && document.defaultView.console) {
    document.defaultView.console.info('[LWBT]', message);
  }
  if (!document.body) return;
  const node = document.createElement('div');
  node.id = 'lwbt-baidu-toast';
  node.setAttribute('role', type === 'error' ? 'alert' : 'status');
  node.textContent = message;
  const palette = {
    info: { background: '#eff6ff', border: '#2563eb', color: '#1e3a8a' },
    success: { background: '#ecfdf5', border: '#16a34a', color: '#14532d' },
    error: { background: '#fef2f2', border: '#dc2626', color: '#7f1d1d' }
  }[type] || { background: '#eff6ff', border: '#2563eb', color: '#1e3a8a' };
  node.style.cssText = [
    'position:fixed',
    'right:24px',
    'top:24px',
    'z-index:2147483647',
    `background:${palette.background}`,
    `border:1px solid ${palette.border}`,
    `border-left:5px solid ${palette.border}`,
    `color:${palette.color}`,
    'border-radius:8px',
    'box-shadow:0 12px 32px rgba(15,23,42,.18)',
    'font:600 14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',
    'max-width:min(460px,calc(100vw - 48px))',
    'padding:12px 14px',
    'word-break:break-word',
    'white-space:pre-wrap'
  ].join(';');
  document.body.appendChild(node);
  const view = document.defaultView;
  if (view && durationMs > 0) {
    view.setTimeout(() => {
      if (node.parentNode) node.remove();
    }, durationMs);
  }
}

function escapeHtml(value) {
  return String(value || '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function fieldHtml(label, value, extraClass = '') {
  const className = ['lwbt-field', extraClass].filter(Boolean).join(' ');
  return `<div class="${escapeAttr(className)}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || '-')}</strong></div>`;
}

function targetPathFieldHtml(value) {
  return `<div class="lwbt-field lwbt-field-wide"><label for="lwbt-target-path">保存目录</label><input id="lwbt-target-path" type="text" value="${escapeAttr(value || '')}"></div>`;
}

function formatPrice(info) {
  return info && info.price ? `${info.price}${info.priceCurrency || ''}` : '';
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
    .lwbt-field span,.lwbt-field label{display:block;font-size:11px;color:#6b7280}
    .lwbt-field strong{display:block;margin-top:3px;color:#111827;font-size:14px}
    .lwbt-field input{width:100%;box-sizing:border-box;margin-top:5px;border:1px solid #d1d5db;border-radius:5px;background:#fff;color:#111827;font-size:14px;font-weight:700;line-height:1.35;padding:6px 7px}
    .lwbt-field-wide{grid-column:1/-1}
    .lwbt-field-price{background:#fff7ed;border:1px solid #fed7aa;box-shadow:inset 3px 0 0 #f97316}
    .lwbt-field-price span{color:#9a3412;font-weight:800}
    .lwbt-field-price strong{color:#c2410c;font-size:17px}
    .lwbt-field-status{border:1px solid #d1d5db}
    .lwbt-field-status span{font-weight:800}
    .lwbt-field-status strong{display:inline-flex;align-items:center;margin-top:5px;border-radius:999px;padding:4px 9px;font-size:13px;font-weight:900}
    .lwbt-expired-alert{margin:0 0 12px;border:1px solid #fecaca;border-left:5px solid #dc2626;border-radius:8px;background:#fef2f2;color:#7f1d1d;padding:10px 12px}
    .lwbt-expired-alert strong{display:block;font-size:15px}
    .lwbt-expired-alert span{display:block;margin-top:3px;font-size:13px;color:#991b1b}
    .lwbt-status-purchased{background:#ecfdf5;border-color:#86efac;box-shadow:inset 3px 0 0 #16a34a}
    .lwbt-status-purchased span{color:#166534}
    .lwbt-status-purchased strong{background:#16a34a;color:#fff}
    .lwbt-status-pending{background:#eff6ff;border-color:#bfdbfe;box-shadow:inset 3px 0 0 #2563eb}
    .lwbt-status-pending span{color:#1d4ed8}
    .lwbt-status-pending strong{background:#2563eb;color:#fff}
    .lwbt-status-expired{background:#fef2f2;border-color:#fecaca;box-shadow:inset 3px 0 0 #dc2626}
    .lwbt-status-expired span{color:#991b1b}
    .lwbt-status-expired strong{background:#dc2626;color:#fff}
    .lwbt-status-missing{background:#f9fafb;border-color:#d1d5db;box-shadow:inset 3px 0 0 #6b7280}
    .lwbt-status-missing span{color:#4b5563}
    .lwbt-status-missing strong{background:#6b7280;color:#fff}
    .lwbt-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
    .lwbt-actions button{border:0;border-radius:6px;padding:9px 12px;background:#2563eb;color:#fff;font-weight:700;cursor:pointer}
    .lwbt-actions button+button{background:#e5e7eb;color:#111827}
    .lwbt-status{margin-top:10px;color:#374151;font-size:13px}
    .lwbt-version{margin-top:4px;color:#9ca3af;font-size:11px}
    .lwbt-post-content{margin-top:14px;border:1px solid #e5e7eb;border-radius:8px;background:#fff;padding:12px;max-height:520px;overflow:auto}
    .lwbt-post-title{font-size:12px;color:#6b7280;font-weight:800;margin-bottom:8px}
    .lwbt-post-body{color:#374151;font-size:14px;line-height:1.75;word-break:break-word}
    .lwbt-post-body p{margin:0 0 10px}
    .lwbt-post-body br{line-height:1.8}
    .lwbt-post-body font[color="red"],.lwbt-post-body span[style*="red"]{line-height:1.45}
    .lwbt-gallery{border:1px solid #e5e7eb;border-radius:8px;background:#fafafa;padding:10px}
    .lwbt-gallery-actions{display:flex;justify-content:flex-end;margin-bottom:8px}
    .lwbt-gallery-actions button{border:0;border-radius:6px;background:#111827;color:#fff;font-weight:800;font-size:13px;padding:8px 10px;cursor:pointer}
    .lwbt-gallery-actions button:disabled{cursor:not-allowed;background:#9ca3af}
    .lwbt-gallery-summary{margin-bottom:8px;color:#4b5563;font-size:13px;font-weight:800}
    .lwbt-gallery-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(92px,1fr));gap:8px;max-height:640px;overflow:auto;padding-right:2px}
    .lwbt-gallery-item{position:relative;aspect-ratio:16/10;border:1px solid #e5e7eb;border-radius:6px;background:#fff;overflow:hidden;padding:0;cursor:zoom-in}
    .lwbt-gallery-item img{width:100%;height:100%;object-fit:cover;display:block}
    .lwbt-gallery-item span{position:absolute;left:5px;top:5px;border-radius:999px;background:rgba(17,24,39,.78);color:#fff;font-size:11px;font-weight:800;line-height:1;padding:4px 6px}
    .lwbt-no-image{color:#6b7280;font-weight:700}
    #lwbt-hover-preview[hidden]{display:none!important}
    #lwbt-hover-preview{position:fixed;z-index:1000000;pointer-events:none;border-radius:8px;background:#111827;padding:6px;box-shadow:0 18px 50px rgba(0,0,0,.35)}
    #lwbt-hover-preview img{display:block;max-width:min(420px,46vw);max-height:70vh;object-fit:contain;border-radius:5px}
    #lwbt-lightbox[hidden]{display:none!important}
    #lwbt-lightbox{position:fixed;inset:0;z-index:999999}
    .lwbt-lightbox-backdrop{position:absolute;inset:0;background:rgba(17,24,39,.9)}
    .lwbt-lightbox-stage{position:absolute;inset:18px;display:grid;grid-template-columns:80px minmax(0,1fr) 80px;grid-template-rows:auto minmax(0,1fr) auto;gap:10px;align-items:center}
    .lwbt-lightbox-image{grid-column:2;grid-row:2;max-width:100%;max-height:100%;justify-self:center;align-self:center;object-fit:contain;border-radius:6px;box-shadow:0 20px 60px rgba(0,0,0,.45)}
    .lwbt-lightbox-close,.lwbt-lightbox-prev,.lwbt-lightbox-next{border:0;border-radius:6px;background:#fff;color:#111827;font-weight:700;padding:10px 12px;cursor:pointer}
    .lwbt-lightbox-close{grid-column:3;grid-row:1;justify-self:end}
    .lwbt-lightbox-prev{grid-column:1;grid-row:2}
    .lwbt-lightbox-next{grid-column:3;grid-row:2}
    .lwbt-lightbox-count{grid-column:2;grid-row:3;justify-self:center;color:#fff;font-size:13px}
    body.lwbt-lightbox-open{overflow:hidden}
    @media(max-width:900px){.lwbt-card{grid-template-columns:1fr}.lwbt-grid{grid-template-columns:1fr 1fr}.lwbt-gallery-grid{grid-template-columns:repeat(auto-fill,minmax(76px,1fr));max-height:520px}.lwbt-lightbox-stage{inset:10px;grid-template-columns:56px minmax(0,1fr) 56px}.lwbt-lightbox-prev,.lwbt-lightbox-next{padding:8px 6px}}
    ${originalHiddenCss()}
  `;
}

function originalHiddenCss() {
  return `
    .deanbkjs,
    #postlistreply,
    #f_pst{display:none!important}
  `;
}
