// ==UserScript==
// @name         老王论坛百度网盘转存助手
// @namespace    https://laowang.vip/
// @version      0.1.53
// @description  美化老王论坛资源帖，购买确认后按网盘类型打开或保存资源
// @match        https://laowang.vip/forum.php*
// @match        https://laowang.vip/thread-*
// @match        https://pan.baidu.com/*
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_deleteValue
// @grant        GM_openInTab
// @grant        GM_download
// @grant        GM_xmlhttpRequest
// @connect      laowang.vip
// @run-at       document-idle
// ==/UserScript==

const PREVIEW_IMAGE_TIMEOUT_MS = 20000;
const PREVIEW_ATTACHMENT_READY_TIMEOUT_MS = 180000;
const HOVER_PREVIEW_DELAY_MS = 150;

(function bootstrap(root) {
  'use strict';

  const TASK_KEY = 'lwbt:tasks';
  const VERSION = '0.1.53';
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

  function extractBaiduShareContextFromText(text) {
    const source = String(text || '');
    const shareMatch = source.match(/(?:shareid|share_id)["']?\s*[:=]\s*["']?(\d+)/i);
    const fromMatch = source.match(/(?:share_uk|link_share_uk|from)["']?\s*[:=]\s*["']?(\d+)/i);
    const fsIds = [];
    const fsPattern = /(?:fs_id|fsid)["']?\s*[:=]\s*["']?(\d+)/ig;
    let fsMatch;
    while ((fsMatch = fsPattern.exec(source))) {
      if (!fsIds.includes(fsMatch[1])) fsIds.push(fsMatch[1]);
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
    buildBaiduApiUrl,
    buildBaiduCreateFolderBody,
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
    isForumPage,
    isForumFirstPage,
    readForumNames,
    isSkippedForumName,
    shouldSkipForumPanel,
    isBaiduPage,
    parseTypeInfo,
    parsePurchaseInfo,
    parseCreditInfo,
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
  if (api.isForumPage(root.location.href) && api.isForumFirstPage(root.location.href) && !api.shouldSkipForumPanel(root.document)) {
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
    const resource = await waitForResource(root, api, 15000);
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
    if (await waitAndClickForumPurchaseConfirm(root, api, 10000)) {
      setStatus(document, '已确认论坛购买，正在读取百度链接...');
    } else {
      setStatus(document, '已打开论坛购买窗口，正在等待百度链接...');
    }
  }
  let resource = await waitForResource(root, api, 12000);
  if (resource) {
    return openResource(root, api, info, resource);
  }
  setStatus(document, '已购买，正在自动打开资源链接...');
  let lookupResource = await waitForForumLookupResource(root, api, info, 8000);
  if (lookupResource) {
    return openResource(root, api, info, lookupResource);
  }
  const lookupTarget = await waitForLookupTarget(root, api, 18000);
  if (!lookupTarget) {
    lookupResource = await waitForForumLookupResource(root, api, info, 12000);
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
  resource = await waitForResource(root, api, 15000);
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
    await sleep(1200);
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
    await sleep(1200);
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
  await ensureBaiduTargetPath(root, root.LWBT, task.targetPath);
  await chooseBaiduSavePath(root, task.targetPath);
  if (isBaiduSaveComplete(document)) return;
  const saveButton = findBaiduSaveButton(root);
  if (!saveButton && isBaiduSaveComplete(document)) return;
  if (!saveButton) throw new Error('未找到百度网盘保存按钮');
  saveButton.click();
  await waitForBaiduSaveComplete(document, 30000);
}

async function ensureBaiduTargetPath(root, api, targetPath) {
  if (!api || !root.fetch) return;
  const token = readBaiduToken(root);
  if (!token) return;
  const entries = api.baiduPathEntries(targetPath);
  for (const entry of entries) {
    const existing = await baiduChildFolderExists(root, api, token, entry.parentPath, entry.folderName);
    if (existing) continue;
    await createBaiduFolder(root, api, token, entry.folderPath);
    await waitForCondition(() => baiduChildFolderExists(root, api, token, entry.parentPath, entry.folderName), 8000, 500);
  }
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

async function chooseBaiduSavePath(root, targetPath) {
  const document = root.document;
  if (baiduCurrentSavePathMatches(document, targetPath)) return;
  const dialog = await openBaiduPathDialog(root);
  const recent = findBaiduRecentPath(dialog, targetPath);
  if (recent) {
    recent.click();
  } else {
    const segments = root.LWBT ? root.LWBT.targetPathToSegments(targetPath) : String(targetPath || '').split('/').filter(Boolean);
    if (!segments.length) throw new Error('目标目录为空');
    for (const segment of segments) {
      await selectOrCreateBaiduFolder(root, dialog, segment);
    }
  }
  const liveDialog = document.querySelector('.dialog-fileTreeDialog') || dialog;
  const confirmButton = findButtonByText(liveDialog, /^确定$/) || liveDialog.querySelector('[node-type="confirm"]');
  if (!confirmButton) throw new Error('未找到百度网盘目录确认按钮');
  confirmButton.click();
  await waitForCondition(() => baiduCurrentSavePathMatches(document, targetPath) || !document.querySelector('.dialog-fileTreeDialog'), 10000);
  if (!baiduCurrentSavePathMatches(document, targetPath)) {
    throw new Error(`目标目录未切换成功：${targetPath}`);
  }
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

async function selectOrCreateBaiduFolder(root, dialog, folderName) {
  const existing = findBaiduTreeNode(dialog, folderName);
  if (existing) {
    clickBaiduTreeNode(root, existing);
    await sleep(1000);
    return;
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
  const expected = normalizeBaiduPath(targetPath);
  return Array.from(dialog.querySelectorAll('.save-path-item')).find((node) => normalizeBaiduPath(node.title || node.textContent) === expected) || null;
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
  const node = document.querySelector('.save-path');
  if (!node) return false;
  const current = normalizeBaiduPath(node.textContent);
  const expected = normalizeBaiduPath(targetPath);
  return current === expected || current.endsWith(`/${expected}`);
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

function showBaiduToast(document, message) {
  removeBaiduHints(document);
  if (document.defaultView && document.defaultView.console) {
    document.defaultView.console.info('[LWBT]', message);
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
