const assert = require('assert');
const fs = require('fs');
const path = require('path');
const api = require('./laowang_baidu_transfer.user.js');
const scriptSource = fs.readFileSync(path.join(__dirname, 'laowang_baidu_transfer.user.js'), 'utf8');

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

test('preview timeout constants are visible to outer download functions', () => {
  const bootstrapIndex = scriptSource.indexOf('(function bootstrap');
  assert(bootstrapIndex > 0);
  assert(scriptSource.indexOf('const PREVIEW_IMAGE_TIMEOUT_MS =') < bootstrapIndex);
  assert(scriptSource.indexOf('const PREVIEW_ATTACHMENT_READY_TIMEOUT_MS =') < bootstrapIndex);
});

test('preview downloads use original binary access instead of canvas conversion', () => {
  assert(scriptSource.includes('// @grant        GM_xmlhttpRequest'));
  assert(scriptSource.includes('// @connect      laowang.vip'));
  assert(scriptSource.includes("Accept: 'image/gif,image/jpeg,image/png,image/*,*/*;q=0.8'"));
  assert(scriptSource.includes("'Cache-Control': 'no-transform'"));
  assert(!scriptSource.includes('drawImage('));
  assert(!scriptSource.includes('toBlob('));
});

test('userscript match covers forum thread urls with query parameters', () => {
  assert(scriptSource.includes('// @match        https://laowang.vip/forum.php*'));
});

test('baidu tree mouse events do not pass sandbox window as event view', () => {
  assert(!scriptSource.includes("new root.MouseEvent('dblclick', { bubbles: true, cancelable: true, view: root })"));
});

test('baidu automation does not render visible status toast overlays', () => {
  assert(!scriptSource.includes("node.id = 'lwbt-baidu-toast'"));
  assert(!scriptSource.includes('LWBT ${message}'));
  assert(!scriptSource.includes('right:18px'));
});

test('safePathSegment removes invalid path characters and truncates long titles', () => {
  const input = 'a/b:c*d?e"f<g>h|'.repeat(20);
  const output = api.safePathSegment(input);
  assert(!/[\\/:*?"<>|]/.test(output));
  assert(output.length <= 80);
});

test('buildTargetPath saves resources in the default forum folder', () => {
  const output = api.buildTargetPath('[合集] 标题 [4.58G][百度盘]', new Date('2026-06-12T10:00:00Z'), '上老王论坛当老王');
  assert.strictEqual(output, '/resouces/上老王论坛当老王/');
});

test('buildTargetPath saves non-default password resources under the default forum folder', () => {
  const output = api.buildTargetPath('[合集] 标题 [4.58G][百度盘]', new Date('2026-06-12T10:00:00Z'), 'wangge666');
  assert.strictEqual(output, '/resouces/上老王论坛当老王/wangge666/');
});

test('buildTargetPath removes invalid characters from password subfolder names', () => {
  const output = api.buildTargetPath('[合集] 标题 [4.58G][百度盘]', new Date('2026-06-12T10:00:00Z'), 'pw/a:b*c?');
  assert.strictEqual(output, '/resouces/上老王论坛当老王/pw a b c/');
});

test('targetPathToSegments parses baidu target folders', () => {
  assert.deepStrictEqual(api.targetPathToSegments('/resouces/上老王论坛当老王/'), ['resouces', '上老王论坛当老王']);
  assert.deepStrictEqual(api.targetPathToSegments('resouces/wangge666'), ['resouces', 'wangge666']);
  assert.deepStrictEqual(api.targetPathToSegments('/'), []);
});

test('normalizeTargetPath keeps a user entered save folder usable for baidu', () => {
  assert.strictEqual(api.normalizeTargetPath('自定义/目录'), '/自定义/目录/');
  assert.strictEqual(api.normalizeTargetPath('/自定义//目录/'), '/自定义/目录/');
  assert.strictEqual(api.normalizeTargetPath('   ', '/resouces/default/'), '/resouces/default/');
});

test('baiduPathSteps builds incremental folders for API creation', () => {
  assert.deepStrictEqual(api.baiduPathSteps('/resouces/1478/'), ['/resouces', '/resouces/1478']);
  assert.deepStrictEqual(api.baiduPathSteps('resouces/a/b'), ['/resouces', '/resouces/a', '/resouces/a/b']);
  assert.deepStrictEqual(api.baiduPathSteps('/'), []);
});

test('baiduPathEntries checks each folder under its parent before creating', () => {
  assert.deepStrictEqual(api.baiduPathEntries('/resouces/上老王论坛当老王/1478/'), [
    { parentPath: '/', folderName: 'resouces', folderPath: '/resouces' },
    { parentPath: '/resouces', folderName: '上老王论坛当老王', folderPath: '/resouces/上老王论坛当老王' },
    { parentPath: '/resouces/上老王论坛当老王', folderName: '1478', folderPath: '/resouces/上老王论坛当老王/1478' }
  ]);
});

test('buildBaiduApiUrl encodes directory paths and standard web parameters', () => {
  assert.strictEqual(
    api.buildBaiduApiUrl('/api/list', {
      dir: '/resouces/1478',
      bdstoken: 'abc123',
      page: 1
    }),
    '/api/list?dir=%2Fresouces%2F1478&bdstoken=abc123&page=1&channel=chunlei&web=1&app_id=250528&clienttype=0'
  );
});

test('buildBaiduCreateFolderBody submits the target folder path as form data', () => {
  assert.strictEqual(
    api.buildBaiduCreateFolderBody('/resouces/1478').toString(),
    'path=%2Fresouces%2F1478&isdir=1&block_list=%5B%5D'
  );
});

test('baidu automation uses page save flow instead of direct transfer api', () => {
  assert(!scriptSource.includes('/share/transfer'));
  assert(!scriptSource.includes('directTransferBaiduShare'));
});

test('extractBaiduShareContextFromText reads transfer parameters from page data', () => {
  const text = 'shareid:"63038414460", share_uk:"1100806323999", fs_id:770484279146616';
  assert.deepStrictEqual(api.extractBaiduShareContextFromText(text), {
    shareId: '63038414460',
    from: '1100806323999',
    fsIds: ['770484279146616']
  });
});

test('extractBaiduTokenFromText ignores null tokens and returns a real bdstoken', () => {
  const token = '361a78480c0e4edf33b154d2c783e10d';
  assert.strictEqual(
    api.extractBaiduTokenFromText(`bdstoken=null bdstoken=null https://pan.baidu.com/api/list?bdstoken=${token}&clienttype=0`),
    token
  );
  assert.strictEqual(api.extractBaiduTokenFromText('bdstoken=null'), '');
});

test('extractBaiduShare finds share url and code', () => {
  const text = '链接: https://pan.baidu.com/s/1abcDEF 提取码: 8x7k 解压密码: abc';
  const result = api.extractBaiduShare(text);
  assert.deepStrictEqual(result, {
    shareUrl: 'https://pan.baidu.com/s/1abcDEF',
    extractCode: '8x7k'
  });
});

test('extractBaiduShare finds encoded share url from attributes', () => {
  const text = 'data-url="https%3A%2F%2Fpan.baidu.com%2Fs%2F1abcDEF%3Fpwd%3D8x7k"';
  const result = api.extractBaiduShare(text);
  assert.deepStrictEqual(result, {
    shareUrl: 'https://pan.baidu.com/s/1abcDEF',
    extractCode: '8x7k'
  });
});

test('extractBaiduShare decodes numeric html entities from forum ajax responses', () => {
  const text = '&#104;&#116;&#116;&#112;&#115;&#58;&#47;&#47;pan.baidu.com&#47;s&#47;1abcDEF 提取码: 8x7k';
  const result = api.extractBaiduShare(text);
  assert.deepStrictEqual(result, {
    shareUrl: 'https://pan.baidu.com/s/1abcDEF',
    extractCode: '8x7k'
  });
});

test('hasPurchasedShare only treats real baidu shares as purchased', () => {
  assert.strictEqual(api.hasPurchasedShare('链接: https://pan.baidu.com/s/1abcDEF?pwd=8x7k 提取码: 8x7k'), true);
  assert.strictEqual(api.hasPurchasedShare('恭喜，此链接目前有效，赶紧返回购买下载吧！'), false);
});

test('extractResourceLink supports baidu and laowang self-hosted resources', () => {
  assert.deepStrictEqual(api.extractResourceLink('链接: https://pan.baidu.com/s/1abcDEF?pwd=8x7k 提取码: 8x7k'), {
    type: 'baidu',
    shareUrl: 'https://pan.baidu.com/s/1abcDEF',
    extractCode: '8x7k'
  });
  assert.deepStrictEqual(
    api.extractResourceLink('<a href="/pan/file.php?hash=c909c27cbf3a0e38bf5faa2ca2c4f970">点击下载</a>', 'https://laowang.vip/forum.php?mod=viewthread&tid=2827361'),
    {
      type: 'laowang',
      url: 'https://laowang.vip/pan/file.php?hash=c909c27cbf3a0e38bf5faa2ca2c4f970'
    }
  );
});

test('extractResourceLinks supports quark and uc resources from purchased thread html', () => {
  const html = [
    'UC：<a href="https://drive.uc.cn/s/7d4de02499474">点击下载</a>',
    '提取码：48xm',
    '夸克1：<a href="https://pan.quark.cn/s/2c2bf1dbe99a">点击下载</a>',
    '夸克2：<a href="https://pan.quark.cn/s/9edf2420aab3">点击下载</a>'
  ].join('\n');
  assert.deepStrictEqual(api.extractResourceLinks(html, 'https://laowang.vip/forum.php?mod=viewthread&tid=2832035'), [
    {
      type: 'uc',
      url: 'https://drive.uc.cn/s/7d4de02499474',
      extractCode: '48xm'
    },
    {
      type: 'quark',
      url: 'https://pan.quark.cn/s/2c2bf1dbe99a',
      extractCode: ''
    },
    {
      type: 'quark',
      url: 'https://pan.quark.cn/s/9edf2420aab3',
      extractCode: ''
    }
  ]);
});

test('extractResourceLink groups multiple external netdisk links into one resource', () => {
  const html = [
    'UC：<a href="https://drive.uc.cn/s/7d4de02499474">点击下载</a>',
    '提取码：48xm',
    '夸克1：<a href="https://pan.quark.cn/s/2c2bf1dbe99a">点击下载</a>'
  ].join('\n');
  assert.deepStrictEqual(api.extractResourceLink(html, 'https://laowang.vip/forum.php?mod=viewthread&tid=2832035'), {
    type: 'external',
    links: [
      {
        type: 'uc',
        url: 'https://drive.uc.cn/s/7d4de02499474',
        extractCode: '48xm'
      },
      {
        type: 'quark',
        url: 'https://pan.quark.cn/s/2c2bf1dbe99a',
        extractCode: ''
      }
    ]
  });
});

test('extractResourceLink groups magnet and 123pan download methods', () => {
  const html = [
    '磁力链接：magnet:?xt=urn:btih:a8b9c437541aa009719502ec0e58a75dc6e6cc1a&dn=The%20Stepfather%E2%80%99s%20Hunger.zip',
    '123网盘：<a href="https://1859912451.share.123865.com/123pan/qoTzvd-U2D1d?pwd=axsN#">点击下载</a>',
    '提取码：axsN'
  ].join('\n');
  assert.deepStrictEqual(api.extractResourceLink(html, 'https://laowang.vip/forum.php?mod=viewthread&tid=2811819'), {
    type: 'external',
    links: [
      {
        type: 'magnet',
        url: 'magnet:?xt=urn:btih:a8b9c437541aa009719502ec0e58a75dc6e6cc1a&dn=The%20Stepfather%E2%80%99s%20Hunger.zip',
        extractCode: ''
      },
      {
        type: 'pan123',
        url: 'https://1859912451.share.123865.com/123pan/qoTzvd-U2D1d?pwd=axsN#',
        extractCode: 'axsN'
      }
    ]
  });
});

test('hasPurchasedResource treats baidu and laowang links as purchased resources', () => {
  assert.strictEqual(api.hasPurchasedResource('https://pan.baidu.com/s/1abcDEF?pwd=8x7k'), true);
  assert.strictEqual(api.hasPurchasedResource('/pan/file.php?hash=c909c27cbf3a0e38bf5faa2ca2c4f970'), true);
  assert.strictEqual(api.hasPurchasedResource('https://pan.quark.cn/s/2c2bf1dbe99a'), true);
  assert.strictEqual(api.hasPurchasedResource('https://drive.uc.cn/s/7d4de02499474 提取码：48xm'), true);
  assert.strictEqual(api.hasPurchasedResource('magnet:?xt=urn:btih:abc123'), true);
  assert.strictEqual(api.hasPurchasedResource('https://1859912451.share.123865.com/123pan/qoTzvd-U2D1d?pwd=axsN#'), true);
  assert.strictEqual(api.hasPurchasedResource('恭喜，此链接目前有效，赶紧返回购买下载吧！'), false);
});

test('actionButtonText matches the resource download type', () => {
  assert.strictEqual(api.actionButtonText('百度盘'), '购买并保存到百度网盘');
  assert.strictEqual(api.actionButtonText('百度云盘'), '购买并保存到百度网盘');
  assert.strictEqual(api.actionButtonText('老王自建盘'), '购买并打开下载页');
  assert.strictEqual(api.actionButtonText('夸克网盘'), '购买并打开下载链接');
  assert.strictEqual(api.actionButtonText('UC/夸克'), '购买并打开下载链接');
  assert.strictEqual(api.actionButtonText('多种下载方式'), '复制磁力并打开网盘');
});

test('shouldShowTargetPath only enables baidu save folder for baidu downloads', () => {
  assert.strictEqual(api.shouldShowTargetPath('百度盘'), true);
  assert.strictEqual(api.shouldShowTargetPath('百度云盘'), true);
  assert.strictEqual(api.shouldShowTargetPath('老王自建盘'), false);
  assert.strictEqual(api.shouldShowTargetPath('夸克网盘'), false);
});

test('resourceOpenTargets returns direct urls for external multi-link resources', () => {
  assert.deepStrictEqual(api.resourceOpenTargets({
    type: 'external',
    links: [
      { type: 'uc', url: 'https://drive.uc.cn/s/7d4de02499474', extractCode: '48xm' },
      { type: 'quark', url: 'https://pan.quark.cn/s/2c2bf1dbe99a', extractCode: '' },
      { type: 'magnet', url: 'magnet:?xt=urn:btih:abc123', extractCode: '' },
      { type: 'pan123', url: 'https://1859912451.share.123865.com/123pan/qoTzvd-U2D1d?pwd=axsN#', extractCode: 'axsN' }
    ]
  }), [
    'https://drive.uc.cn/s/7d4de02499474',
    'https://pan.quark.cn/s/2c2bf1dbe99a',
    'https://1859912451.share.123865.com/123pan/qoTzvd-U2D1d?pwd=axsN#'
  ]);
});

test('resourceCopyTexts returns magnet addresses without opening them', () => {
  assert.deepStrictEqual(api.resourceCopyTexts({
    type: 'external',
    links: [
      { type: 'magnet', url: 'magnet:?xt=urn:btih:abc123', extractCode: '' },
      { type: 'pan123', url: 'https://1859912451.share.123865.com/123pan/qoTzvd-U2D1d?pwd=axsN#', extractCode: 'axsN' }
    ]
  }), ['magnet:?xt=urn:btih:abc123']);
  assert.deepStrictEqual(api.resourceCopyTexts({ type: 'magnet', url: 'magnet:?xt=urn:btih:abc123', extractCode: '' }), ['magnet:?xt=urn:btih:abc123']);
  assert.deepStrictEqual(api.resourceOpenTargets({ type: 'pan123', url: 'https://1859912451.share.123865.com/123pan/qoTzvd-U2D1d?pwd=axsN#', extractCode: 'axsN' }), ['https://1859912451.share.123865.com/123pan/qoTzvd-U2D1d?pwd=axsN#']);
});

test('resourceSummary describes external download links and extraction codes', () => {
  assert.strictEqual(api.resourceSummary({
    type: 'external',
    links: [
      { type: 'uc', url: 'https://drive.uc.cn/s/7d4de02499474', extractCode: '48xm' },
      { type: 'quark', url: 'https://pan.quark.cn/s/2c2bf1dbe99a', extractCode: '' }
    ]
  }), '已找到 2 个下载链接：UC 提取码 48xm、夸克');
  assert.strictEqual(api.resourceSummary({
    type: 'external',
    links: [
      { type: 'magnet', url: 'magnet:?xt=urn:btih:abc123', extractCode: '' },
      { type: 'pan123', url: 'https://1859912451.share.123865.com/123pan/qoTzvd-U2D1d?pwd=axsN#', extractCode: 'axsN' }
    ]
  }), '已找到 2 个下载方式：磁力、123网盘 提取码 axsN');
});

test('purchaseStatusText formats detected and missing purchase states', () => {
  assert.strictEqual(api.purchaseStatusText(true), '已购买');
  assert.strictEqual(api.purchaseStatusText(false), '未购买/未检测到');
});

test('isExpiredThreadTitle only uses strong title signals', () => {
  assert.strictEqual(api.isExpiredThreadTitle('[已失效] [自行打包] 合法萝莉 [百度盘]'), true);
  assert.strictEqual(api.isExpiredThreadTitle('【资源失效】示例标题'), true);
  assert.strictEqual(api.isExpiredThreadTitle('如果提示链接失效，请勿购买，请等待补链'), false);
});

test('fieldVariantClass highlights price and purchase status fields', () => {
  assert.strictEqual(api.fieldVariantClass('售价'), 'lwbt-field-price');
  assert.strictEqual(api.fieldVariantClass('购买状态'), 'lwbt-field-status');
  assert.strictEqual(api.fieldVariantClass('资源大小'), '');
});

test('purchaseStatusClass maps status text to visual state classes', () => {
  assert.strictEqual(api.purchaseStatusClass('已购买'), 'lwbt-status-purchased');
  assert.strictEqual(api.purchaseStatusClass('检测中'), 'lwbt-status-pending');
  assert.strictEqual(api.purchaseStatusClass('已失效'), 'lwbt-status-expired');
  assert.strictEqual(api.purchaseStatusClass('未购买/未检测到'), 'lwbt-status-missing');
});

test('renderForumPanel highlights expired resources without disabling actions', () => {
  const html = api.renderForumPanel(api, {
    title: '合法萝莉',
    rawTitle: '[已失效] 合法萝莉',
    downloadType: '百度盘',
    source: '自行打包',
    size: '4.6G',
    fileCount: '1v',
    password: '上老王论坛当老王',
    price: '5',
    priceCurrency: '软妹币',
    targetPath: '/resouces/上老王论坛当老王/',
    isExpired: true
  }, [], '');
  assert(html.includes('lwbt-expired-alert'));
  assert(html.includes('资源已失效，请勿购买'));
  assert(html.includes('已失效'));
  assert(html.includes('购买并保存到百度网盘'));
});

test('renderForumPanel uses a dense lazy gallery for preview images', () => {
  const html = api.renderForumPanel(api, {
    title: '多图资源',
    rawTitle: '多图资源',
    downloadType: '百度盘',
    source: '转载搬运',
    size: '1G',
    fileCount: '180P',
    password: '上老王论坛当老王',
    price: '3',
    priceCurrency: '软妹币',
    targetPath: '/resouces/上老王论坛当老王/',
    isExpired: false
  }, [
    'https://laowang.vip/data/attachment/forum/a.gif',
    'https://laowang.vip/data/attachment/forum/b.gif'
  ], '');

  assert(html.includes('lwbt-gallery-summary'));
  assert(html.includes('预览图 2 张'));
  assert(html.includes('class="lwbt-gallery-grid"'));
  assert(html.includes('class="lwbt-gallery-item"'));
  assert(html.includes('loading="lazy"'));
  assert(html.includes('data-index="1"'));
  assert(!html.includes('class="lwbt-main-trigger"'));
  assert(!html.includes('class="lwbt-thumbs"'));
});

test('dense gallery item clicks open the existing lightbox', () => {
  assert(scriptSource.includes("document.querySelectorAll('.lwbt-gallery-item')"));
  assert(scriptSource.includes('openImageLightbox(root, api, images, Number(button.dataset.index))'));
  assert(!scriptSource.includes("document.querySelectorAll('.lwbt-thumb')"));
});

test('dense gallery hover preview binds pointer events without replacing click lightbox', () => {
  assert(scriptSource.includes('setupGalleryHoverPreview(root, images)'));
  assert(scriptSource.includes("button.addEventListener('pointerenter'"));
  assert(scriptSource.includes("button.addEventListener('pointerleave'"));
  assert(scriptSource.includes('const HOVER_PREVIEW_DELAY_MS = 150'));
});

test('dense gallery css supports a scrollable image wall', () => {
  assert(scriptSource.includes('.lwbt-gallery-summary'));
  assert(scriptSource.includes('.lwbt-gallery-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(92px,1fr))'));
  assert(scriptSource.includes('max-height:640px'));
  assert(scriptSource.includes('.lwbt-gallery-item span'));
});

test('hover preview css renders a fixed image overlay', () => {
  assert(scriptSource.includes('#lwbt-hover-preview[hidden]'));
  assert(scriptSource.includes('#lwbt-hover-preview{position:fixed'));
  assert(scriptSource.includes('max-width:min(420px,46vw)'));
  assert(scriptSource.includes('pointer-events:none'));
});

test('isPurchaseLink only accepts forum native pay links', () => {
  assert.strictEqual(api.isPurchaseLink('https://laowang.vip/jnpar_pansell-pay.html?tid=2821033&pid=', '立即购买', 'purchase-btn'), true);
  assert.strictEqual(api.isPurchaseLink('jnpar_pansell-pay.html?tid=2821033&pid=', '立即购买', 'purchase-btn'), true);
  assert.strictEqual(api.isPurchaseLink('javascript:;', '立即购买', 'purchase-btn', "showWindow('dtpaytip','jnpar_pansell-pay.html?tid=2821033&pid=','get','0')"), true);
  assert.strictEqual(api.isPurchaseLink('https://laowang.vip/plugin.php?id=jnpar_pansell:pay&tid=2824896&pid=', '立即购买', 'purchase-btn'), true);
  assert.strictEqual(api.isPurchaseLink('https://laowang.vip/jnpar_pansell-check.html?tid=2821033&k=0', '百度网盘链接，点击检测是否有效', ''), false);
  assert.strictEqual(api.isPurchaseLink('https://laowang.vip/home.php?mod=spacecp&ac=credit&op=buy', '充值软妹币', ''), false);
});

test('isResourceLookupLink accepts pansell lookup links but rejects pay links', () => {
  assert.strictEqual(api.isResourceLookupLink('https://laowang.vip/jnpar_pansell-check.html?tid=2821033&k=0', '百度网盘链接，点击检测是否有效', '', ''), true);
  assert.strictEqual(api.isResourceLookupLink('javascript:;', '查看百度网盘链接', '', "showWindow('dtpaytip','jnpar_pansell-view.html?tid=1','get','0')"), true);
  assert.strictEqual(api.isResourceLookupLink('https://laowang.vip/plugin.php?id=jnpar_pansell:check&tid=2824896&k=0', '百度网盘链接，点击检测是否有效', '', ''), true);
  assert.strictEqual(api.isResourceLookupLink('https://laowang.vip/jnpar_pansell-pay.html?tid=2821033&pid=', '立即购买', 'purchase-btn', ''), false);
  assert.strictEqual(api.isResourceLookupLink('https://laowang.vip/plugin.php?id=jnpar_pansell:pay&tid=2824896&pid=', '立即购买', 'purchase-btn', ''), false);
});

test('buildBaiduOpenUrl appends extract code as pwd query parameter', () => {
  assert.strictEqual(
    api.buildBaiduOpenUrl('https://pan.baidu.com/s/1abcDEF', '5kin'),
    'https://pan.baidu.com/s/1abcDEF?pwd=5kin'
  );
  assert.strictEqual(
    api.buildBaiduOpenUrl('https://pan.baidu.com/share/init?surl=buAZz3oghi2Fl8gFv_gIsw', '5kin'),
    'https://pan.baidu.com/share/init?surl=buAZz3oghi2Fl8gFv_gIsw&pwd=5kin'
  );
  assert.strictEqual(
    api.buildBaiduOpenUrl('https://pan.baidu.com/s/1abcDEF?pwd=old1', '5kin'),
    'https://pan.baidu.com/s/1abcDEF?pwd=5kin'
  );
});

test('parseThreadId extracts tid from forum urls', () => {
  assert.strictEqual(api.parseThreadId('https://laowang.vip/forum.php?mod=viewthread&tid=2827361'), '2827361');
  assert.strictEqual(api.parseThreadId('https://laowang.vip/thread-2812031-1-1.html'), '2812031');
  assert.strictEqual(api.parseThreadId('https://laowang.vip/forum.php'), '');
});

test('buildForumLookupUrl creates pansell check url from tid', () => {
  assert.strictEqual(
    api.buildForumLookupUrl('https://laowang.vip/forum.php?mod=viewthread&tid=2827361'),
    'https://laowang.vip/plugin.php?id=jnpar_pansell:check&tid=2827361&k=0'
  );
});

test('buildForumLookupUrls checks refreshed thread html before pansell check endpoint', () => {
  assert.deepStrictEqual(
    api.buildForumLookupUrls('https://laowang.vip/forum.php?mod=viewthread&tid=2827361&extra=page%3D1'),
    [
      'https://laowang.vip/forum.php?mod=viewthread&tid=2827361&extra=page%3D1',
      'https://laowang.vip/plugin.php?id=jnpar_pansell:check&tid=2827361&k=0'
    ]
  );
});

test('buildForumAjaxUrl adds Discuz ajax window parameters', () => {
  assert.strictEqual(
    api.buildForumAjaxUrl(
      'plugin.php?id=jnpar_pansell:pay&tid=2809931&pid=',
      'https://laowang.vip/forum.php?mod=viewthread&tid=2809931'
    ),
    'https://laowang.vip/plugin.php?id=jnpar_pansell%3Apay&tid=2809931&pid=&infloat=yes&handlekey=dtpaytip&inajax=1&ajaxtarget=fwin_content_dtpaytip'
  );
});

test('parseForumPurchaseForm extracts post target and hidden fields from ajax html', () => {
  const html = `
    <root><![CDATA[
      <form action="plugin.php?id=jnpar_pansell:pay" method="post" id="dtpaytipform">
        <input type="hidden" name="formhash" value="57039047" />
        <input type="hidden" name="handlekey" value="dtpaytip" />
        <input type="hidden" name="tid" value="2809931" />
        <input type="hidden" name="pid" value="" />
        <button type="submit" name="submit" value="true"><strong>购买</strong></button>
      </form>
    ]]></root>`;
  assert.deepStrictEqual(api.parseForumPurchaseForm(html), {
    action: 'plugin.php?id=jnpar_pansell:pay',
    fields: {
      formhash: '57039047',
      handlekey: 'dtpaytip',
      tid: '2809931',
      pid: '',
      submit: 'true'
    }
  });
});

test('extractForumResourceUrls finds chained pansell links in ajax html', () => {
  const html = "showWindow('dtpaytip','plugin.php?id=jnpar_pansell:download&tid=2827361&k=0','get','0') jnpar_pansell-link.html?tid=2827361&k=0";
  assert.deepStrictEqual(api.extractForumResourceUrls(html, 'https://laowang.vip/forum.php?mod=viewthread&tid=2827361'), [
    'https://laowang.vip/plugin.php?id=jnpar_pansell:download&tid=2827361&k=0',
    'https://laowang.vip/jnpar_pansell-link.html?tid=2827361&k=0'
  ]);
});

test('extractForumResourceUrls decodes numeric html entities', () => {
  const html = '&#112;&#108;&#117;&#103;&#105;&#110;&#46;&#112;&#104;&#112;&#63;id=jnpar_pansell:link&amp;tid=2827361&amp;k=0';
  assert.deepStrictEqual(api.extractForumResourceUrls(html, 'https://laowang.vip/forum.php?mod=viewthread&tid=2827361'), [
    'https://laowang.vip/plugin.php?id=jnpar_pansell:link&tid=2827361&k=0'
  ]);
});

test('chooseActionTarget prefers visible purchase links over resource lookup links', () => {
  const targets = api.chooseActionTarget([
    { type: 'lookup', visible: true, text: '百度网盘链接，点击检测是否有效' },
    { type: 'purchase', visible: true, text: '立即购买' }
  ]);
  assert.strictEqual(targets.type, 'purchase');
});

test('chooseActionTarget ignores hidden purchase links when visible lookup is the only usable action', () => {
  const targets = api.chooseActionTarget([
    { type: 'purchase', visible: false, text: '立即购买' },
    { type: 'lookup', visible: true, text: '百度网盘链接，点击检测是否有效' }
  ]);
  assert.strictEqual(targets.type, 'lookup');
});

test('chooseLookupTarget selects lookup links after purchase completes', () => {
  const target = api.chooseLookupTarget([
    { type: 'purchase', visible: true, text: '立即购买' },
    { type: 'lookup', visible: false, text: '隐藏资源入口' },
    { type: 'lookup', visible: true, text: '百度网盘链接，点击检测是否有效' }
  ]);
  assert.strictEqual(target.text, '百度网盘链接，点击检测是否有效');
});

test('isForumPurchaseConfirmButton accepts only final purchase confirm actions', () => {
  assert.strictEqual(api.isForumPurchaseConfirmButton('购买', ''), true);
  assert.strictEqual(api.isForumPurchaseConfirmButton('确认购买', ''), true);
  assert.strictEqual(api.isForumPurchaseConfirmButton('取消', ''), false);
  assert.strictEqual(api.isForumPurchaseConfirmButton('百度网盘链接，点击检测是否有效', 'jnpar_pansell-check.html?tid=1'), false);
});

test('nextImageIndex wraps gallery navigation', () => {
  assert.strictEqual(api.nextImageIndex(0, 1, 3), 1);
  assert.strictEqual(api.nextImageIndex(2, 1, 3), 0);
  assert.strictEqual(api.nextImageIndex(0, -1, 3), 2);
  assert.strictEqual(api.nextImageIndex(0, 1, 0), 0);
});

test('isPostContentNoise filters duplicated resource controls', () => {
  assert.strictEqual(api.isPostContentNoise('下载信息分类 下载方式: 百度盘 资源大小: 78G', '', ''), true);
  assert.strictEqual(api.isPostContentNoise('百度网盘链接，点击检测是否有效 立即购买 售价：3软妹币', '', ''), true);
  assert.strictEqual(api.isPostContentNoise('持续更新高质量合集，喜欢的兄弟们点个关注和赞支持一下', '', ''), false);
});

test('shouldBlockForLogin does not block when a purchase action is available', () => {
  assert.strictEqual(
    api.shouldBlockForLogin('本帖子中包含更多资源 您需要 登录 才可以下载或查看', [{ type: 'purchase', visible: true }]),
    false
  );
  assert.strictEqual(
    api.shouldBlockForLogin('本帖子中包含更多资源 您需要 登录 才可以下载或查看', []),
    true
  );
});

test('isLoginRequired only matches blocked resource login prompts', () => {
  assert.strictEqual(api.isLoginRequired('本帖子中包含更多资源 您需要 登录 才可以下载或查看'), true);
  assert.strictEqual(api.isLoginRequired('登录后可以评论，立即购买 售价 15 软妹币'), false);
});

test('isForumPage and isBaiduPage classify urls', () => {
  assert.strictEqual(api.isForumPage('https://laowang.vip/forum.php?mod=viewthread&tid=1'), true);
  assert.strictEqual(api.isForumPage('https://laowang.vip/thread-2821033-1-1.html'), true);
  assert.strictEqual(api.isBaiduPage('https://pan.baidu.com/s/1abc'), true);
});

test('isForumFirstPage only accepts the first page of a thread', () => {
  assert.strictEqual(api.isForumFirstPage('https://laowang.vip/forum.php?mod=viewthread&tid=255956'), true);
  assert.strictEqual(api.isForumFirstPage('https://laowang.vip/forum.php?mod=viewthread&tid=255956&page=1'), true);
  assert.strictEqual(api.isForumFirstPage('https://laowang.vip/thread-255956-1-1.html'), true);
  assert.strictEqual(api.isForumFirstPage('https://laowang.vip/forum.php?mod=viewthread&tid=255956&page=2'), false);
  assert.strictEqual(api.isForumFirstPage('https://laowang.vip/thread-255956-2-1.html'), false);
});

function fakeForumDocument(names) {
  return {
    querySelectorAll() {
      return names.map((name) => ({ textContent: name }));
    }
  };
}

function fakeForumDocumentBySelector(selectorMap) {
  return {
    querySelectorAll(selector) {
      return (selectorMap[selector] || []).map((name) => ({ textContent: name }));
    }
  };
}

test('skipped forum names are configured in one editable list', () => {
  assert(api.SKIP_FORUM_NAMES.includes('高价悬赏'));
  assert(api.SKIP_FORUM_NAMES.includes('悬赏求助'));
});

test('readForumNames extracts forum names from navigation links', () => {
  assert.deepStrictEqual(api.readForumNames(fakeForumDocument(['首页', '套图', '高价悬赏'])), ['首页', '套图', '高价悬赏']);
});

test('shouldSkipForumPanel skips configured special forums only', () => {
  assert.strictEqual(api.shouldSkipForumPanel(fakeForumDocument(['首页', '高价悬赏'])), true);
  assert.strictEqual(api.shouldSkipForumPanel(fakeForumDocument(['首页', '悬赏求助'])), true);
  assert.strictEqual(api.shouldSkipForumPanel(fakeForumDocument(['首页', '套图'])), false);
});

test('shouldSkipForumPanel ignores special forums from global navigation', () => {
  const document = fakeForumDocumentBySelector({
    '#pt a': ['首页', '视频资源下载', '国产自拍下载'],
    '.bm_h a': [],
    '.wp .z a': ['高价悬赏', '悬赏求助'],
    'a[href*="forum.php?mod=forumdisplay"]': ['高价悬赏', '悬赏求助', '国产自拍下载'],
    'a[href*="/forum-"]': []
  });
  assert.deepStrictEqual(api.readForumNames(document), ['首页', '视频资源下载', '国产自拍下载']);
  assert.strictEqual(api.shouldSkipForumPanel(document), false);
});

test('parseTypeInfo extracts forum resource fields', () => {
  const text = [
    '下载方式: 百度盘',
    '来源: 自行打包',
    '文件数量: 41V 74P',
    '资源大小: 4.58G',
    '解压密码: 上老王论坛当老王',
    '解压软件: -'
  ].join('\n');
  assert.deepStrictEqual(api.parseTypeInfo(text), {
    downloadType: '百度盘',
    source: '自行打包',
    fileCount: '41V 74P',
    size: '4.58G',
    password: '上老王论坛当老王',
    unzipTool: '-'
  });
});

test('parseTypeInfo extracts other-netdisk download type labels', () => {
  const text = [
    '下载信息分类（其他网盘版）',
    '下载方式（其他网盘版）: 夸克网盘',
    '来源: 转载搬运',
    '文件数量: 3V',
    '资源大小: 1.2G',
    '解压密码: PADIO294',
    '解压软件: winrar'
  ].join('\n');
  assert.deepStrictEqual(api.parseTypeInfo(text), {
    downloadType: '夸克网盘',
    source: '转载搬运',
    fileCount: '3V',
    size: '1.2G',
    password: 'PADIO294',
    unzipTool: 'winrar'
  });
});

test('parsePurchaseInfo extracts resource price', () => {
  assert.deepStrictEqual(api.parsePurchaseInfo('💰 售价： 3软妹币'), {
    price: '3',
    priceCurrency: '软妹币'
  });
  assert.deepStrictEqual(api.parsePurchaseInfo('售价: 15 积分'), {
    price: '15',
    priceCurrency: '积分'
  });
});

test('parseCreditInfo extracts soft currency and total points from credit page text', () => {
  const text = '<li><em> 软妹币: </em>219</li><li class="cl"><em>积分: </em>82 <span>总积分</span></li>';
  assert.deepStrictEqual(api.parseCreditInfo(text), {
    balance: '219',
    balanceCurrency: '软妹币',
    totalPoints: '82'
  });
});

test('buildPurchaseConfirmText includes price and current credit', () => {
  const message = api.buildPurchaseConfirmText(
    { title: '标题', size: '1G', targetPath: '/resouces/pw/', price: '3', priceCurrency: '软妹币' },
    { balance: '219', balanceCurrency: '软妹币', totalPoints: '82' }
  );
  assert(message.includes('售价: 3软妹币'));
  assert(message.includes('我的软妹币: 219'));
  assert(message.includes('我的总积分: 82'));
});

test('isPreviewImage rejects avatars, smileys, icons and accepts attachment images', () => {
  assert.strictEqual(api.isPreviewImage('https://laowang.vip/uc_server/data/avatar/001/a.jpg'), false);
  assert.strictEqual(api.isPreviewImage('https://laowang.vip/static/image/smiley/tieba/tb_17.png'), false);
  assert.strictEqual(api.isPreviewImage('https://laowang.vip/static/image/common/online_member.gif'), false);
  assert.strictEqual(api.isPreviewImage('https://laowang.vip/data/attachment/forum/202606/12/demo.jpg'), true);
});

test('isPreviewImageElement rejects author profile images even when the url looks like an attachment', () => {
  const image = {
    getAttribute(name) {
      return name === 'zoomfile' ? 'https://laowang.vip/data/attachment/forum/author-level.jpg' : '';
    },
    closest(selector) {
      if (selector.includes('.pls')) return { className: 'pls' };
      if (selector.includes('postmessage_')) return null;
      return null;
    }
  };
  assert.strictEqual(api.isPreviewImageElement(image), false);
});

test('isPreviewImageElement accepts attachment images inside post message content', () => {
  const image = {
    getAttribute(name) {
      return name === 'zoomfile' ? 'https://laowang.vip/data/attachment/forum/202606/12/demo.jpg' : '';
    },
    closest(selector) {
      if (selector.includes('.pls')) return null;
      if (selector.includes('postmessage_')) return { id: 'postmessage_123' };
      return null;
    }
  };
  assert.strictEqual(api.isPreviewImageElement(image), true);
});

test('isPreviewAttachmentLink accepts Discuz image attachment download links', () => {
  assert.strictEqual(
    api.isPreviewAttachmentLink(
      'forum.php?mod=attachment&aid=MTQ4MjQ4MDl8MmNlMzQwZTR8MTc4MTU3MjE3MXwxOTg5MjA0fDI4MjczNjE%3D&nothumb=yes',
      '200637tpeb3tznibsuotpc.gif'
    ),
    true
  );
  assert.strictEqual(
    api.isPreviewAttachmentLink('forum.php?mod=attachment&aid=abc&nothumb=yes', 'resource.zip'),
    false
  );
});

test('previewRequestUrl removes local filename metadata before network requests', () => {
  assert.strictEqual(
    api.previewRequestUrl('forum.php?mod=attachment&aid=abc&nothumb=yes#lwbt_filename=demo.gif'),
    'forum.php?mod=attachment&aid=abc&nothumb=yes'
  );
});

test('previewImageLoadSummary counts loaded attachment previews by normalized url', () => {
  assert.deepStrictEqual(api.previewImageLoadSummary([
    'forum.php?mod=attachment&aid=a&nothumb=yes#lwbt_filename=a.gif',
    'forum.php?mod=attachment&aid=b&nothumb=yes#lwbt_filename=b.gif',
    'https://laowang.vip/data/attachment/forum/demo.jpg'
  ], [
    'forum.php?mod=attachment&aid=a&nothumb=yes#lwbt_filename=a.gif',
    'https://laowang.vip/data/attachment/forum/demo.jpg'
  ]), {
    total: 2,
    loaded: 1
  });
});

test('buildPreviewZipFilename creates a safe zip name from the thread title', () => {
  assert.strictEqual(
    api.buildPreviewZipFilename('[合集] a/b:c*d?e"f<g>h| [百度盘]'),
    'a b c d e f g h-预览图.zip'
  );
});

test('previewZipFolderName creates a safe folder name inside preview zip', () => {
  assert.strictEqual(api.previewZipFolderName('[合集] a/b:c*d?e"f<g>h| [百度盘]'), 'a b c d e f g h');
  assert.strictEqual(api.previewZipFolderName(''), '预览图');
});

test('imageExtensionFromMimeType maps image content types to file extensions', () => {
  assert.strictEqual(api.imageExtensionFromMimeType('image/jpeg'), 'jpg');
  assert.strictEqual(api.imageExtensionFromMimeType('image/webp;charset=utf-8'), 'webp');
  assert.strictEqual(api.imageExtensionFromMimeType('text/html'), '');
});

test('previewImageFilename preserves known image extensions and uses sequence numbers', () => {
  assert.strictEqual(api.previewImageFilename('https://laowang.vip/data/attachment/forum/demo.JPG?x=1', 0), '001.jpg');
  assert.strictEqual(api.previewImageFilename('https://laowang.vip/data/attachment/forum/demo.gif', 1), '002.gif');
  assert.strictEqual(api.previewImageFilename('https://laowang.vip/data/attachment/forum/no-extension', 2), '003.jpg');
  assert.strictEqual(api.previewImageFilename('https://laowang.vip/data/attachment/forum/demo.gif', 3, 'image/webp'), '004.webp');
  assert.strictEqual(api.previewImageFilename('forum.php?mod=attachment&aid=abc#lwbt_filename=demo.gif', 4), '005.gif');
  assert.strictEqual(api.previewImageFilename('forum.php?mod=attachment&aid=abc#lwbt_filename=demo.gif', 5, 'image/webp'), '006.gif');
});

test('previewDownloadMethod uses original binary requests for Discuz attachments', () => {
  assert.strictEqual(api.previewDownloadMethod('forum.php?mod=attachment&aid=abc#lwbt_filename=demo.gif'), 'gm');
  assert.strictEqual(api.previewDownloadMethod('https://laowang.vip/data/attachment/forum/demo.gif'), 'fetch');
});

test('previewDownloadSummary reports completed and failed image downloads', () => {
  assert.strictEqual(api.previewDownloadSummary(8, 0), '已打包下载 8 张预览图');
  assert.strictEqual(api.previewDownloadSummary(6, 2), '已打包下载 6 张预览图，2 张失败');
  assert.strictEqual(api.previewDownloadSummary(0, 3), '预览图下载失败，请稍后重试');
});

test('buildStoreZipBytes creates a zip with local headers, central directory and eocd', () => {
  const output = api.buildStoreZipBytes([
    { name: '预览图/001.png', data: new Uint8Array([1, 2, 3]).buffer },
    { name: '预览图/002.png', data: new Uint8Array([4, 5]).buffer }
  ], new Date('2026-06-16T00:00:00Z'));
  assert(output instanceof Uint8Array);
  assert.strictEqual(output[0], 0x50);
  assert.strictEqual(output[1], 0x4b);
  assert.strictEqual(output[2], 0x03);
  assert.strictEqual(output[3], 0x04);
  const decoded = new TextDecoder().decode(output);
  assert(decoded.includes('预览图/001.png'));
  assert(decoded.includes('预览图/002.png'));
  assert.strictEqual(output[output.length - 22], 0x50);
  assert.strictEqual(output[output.length - 21], 0x4b);
  assert.strictEqual(output[output.length - 20], 0x05);
  assert.strictEqual(output[output.length - 19], 0x06);
});

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
  assert.strictEqual(task.targetPath, '/resouces/上老王论坛当老王/pw/');
  assert.strictEqual(task.status, 'pending');
});

test('createTransferTask uses a custom target path when supplied', () => {
  const task = api.createTransferTask({
    sourceUrl: 'https://laowang.vip/thread-1-1-1.html',
    rawTitle: '[合集] 标题 [1G][百度盘]',
    shareUrl: 'https://pan.baidu.com/s/1abc',
    extractCode: 'abcd',
    password: 'pw',
    size: '1G',
    targetPath: '自定义/目录'
  }, new Date('2026-06-12T10:00:00Z'));
  assert.strictEqual(task.targetPath, '/自定义/目录/');
});

test('findPendingTaskForUrl matches pending baidu share task', () => {
  const tasks = [
    { status: 'saved', shareUrl: 'https://pan.baidu.com/s/old' },
    { status: 'pending', shareUrl: 'https://pan.baidu.com/s/1abc' }
  ];
  const task = api.findPendingTaskForUrl(tasks, 'https://pan.baidu.com/s/1abc?pwd=abcd');
  assert.strictEqual(task.shareUrl, 'https://pan.baidu.com/s/1abc');
});

test('findPendingTaskForUrl matches share init url after pwd is appended', () => {
  const tasks = [
    { status: 'pending', shareUrl: 'https://pan.baidu.com/share/init?surl=buAZz3oghi2Fl8gFv_gIsw' }
  ];
  const task = api.findPendingTaskForUrl(tasks, 'https://pan.baidu.com/share/init?surl=buAZz3oghi2Fl8gFv_gIsw&pwd=5kin');
  assert.strictEqual(task.shareUrl, 'https://pan.baidu.com/share/init?surl=buAZz3oghi2Fl8gFv_gIsw');
});

test('buildBaiduTaskOpenUrl carries the pending task for cross-site fallback', () => {
  const task = api.createTransferTask({
    sourceUrl: 'https://laowang.vip/forum.php?mod=viewthread&tid=1822961',
    rawTitle: '[合集] 标题 [1G][百度盘]',
    shareUrl: 'https://pan.baidu.com/s/1abc',
    extractCode: 'abcd',
    password: '1478',
    size: '1G',
    targetPath: '/resouces/上老王论坛当老王/1478/'
  }, new Date('2026-06-12T10:00:00Z'));
  const openUrl = api.buildBaiduTaskOpenUrl(task);
  const parsed = new URL(openUrl);
  assert.strictEqual(parsed.searchParams.get('pwd'), 'abcd');
  assert(parsed.searchParams.get('lwbt_task'));
  assert.deepStrictEqual(api.readBaiduTaskFromUrl(openUrl), task);
  const stripped = api.stripBaiduTaskParamFromUrl(`${openUrl}#list/path=%2F`);
  const strippedUrl = new URL(stripped);
  assert.strictEqual(strippedUrl.searchParams.get('pwd'), 'abcd');
  assert.strictEqual(strippedUrl.searchParams.has('lwbt_task'), false);
  assert(stripped.endsWith('#list/path=%2F'));
});

test('originalHiddenCss hides noisy thread areas permanently', () => {
  const css = api.originalHiddenCss();
  assert(!css.includes('lwbt-show-original'));
  assert(!css.includes('[id^="post_"]'));
  assert(css.includes('#postlistreply'));
  assert(css.includes('#f_pst'));
});
