const assert = require('assert');
const helpers = require('./southplus_enhancer.user.js');

assert.strictEqual(helpers.getDefaultSettings().readerMode, true);
assert.strictEqual(helpers.getDefaultSettings().immersiveRead, true);
assert.strictEqual(helpers.getDefaultSettings().immersiveFontSize, 20);
assert.strictEqual(helpers.getDefaultSettings().unifiedPreviewGallery, true);
assert.strictEqual(helpers.getDefaultSettings().homeDashboard, true);
assert.strictEqual(helpers.getDefaultSettings().adBlock, true);
assert.strictEqual(
  helpers.shouldUseImmersiveRead(
    helpers.getDefaultSettings(),
    'https://south-plus.org/read.php?tid=2891131'
  ),
  true
);
assert.strictEqual(
  helpers.shouldUseImmersiveRead(
    helpers.getDefaultSettings(),
    'https://south-plus.org/thread.php?fid-48.html'
  ),
  false
);
assert.strictEqual(
  helpers.shouldUseHomeDashboard(
    helpers.getDefaultSettings(),
    'https://south-plus.org/index.php'
  ),
  true
);
assert.strictEqual(
  helpers.shouldUseHomeDashboard(
    helpers.getDefaultSettings(),
    'https://south-plus.org/read.php?tid=2891131'
  ),
  false
);

assert.strictEqual(helpers.parseThreadId('td_2891095'), '2891095');
assert.strictEqual(helpers.parseThreadId('a_ajax_2891095'), '2891095');
assert.strictEqual(helpers.parseThreadId('https://south-plus.org/read.php?tid=2891131'), '2891131');
assert.strictEqual(helpers.parseThreadId('read.php?tid-2891131-page-e-fpage-1.html#a'), '2891131');
assert.strictEqual(helpers.parseThreadId('thread.php?fid-48.html'), '');

assert.deepStrictEqual(
  helpers.parseLineList(' foo \n\nbar\r\n baz '),
  ['foo', 'bar', 'baz']
);

assert.strictEqual(helpers.parseTodayCount('茶馆 (1956)'), 1956);
assert.strictEqual(helpers.parseTodayCount('Comic Market 105 (0)'), 0);
assert.strictEqual(helpers.parseTodayCount('事务受理'), 0);

assert.strictEqual(helpers.isAdUrl('https://segucrwj.taobao.com/'), true);
assert.strictEqual(helpers.isAdUrl('https://equity.tmall.com/tm?agentId=abc'), true);
assert.strictEqual(helpers.isAdUrl('https://south-plus.org/thread.php?fid-9.html'), false);

assert.strictEqual(
  helpers.isPreviewImageCandidate({
    src: 'https://p.inari.site/usr/288/photo_2026-06-02_20-00-07.jpg',
    naturalWidth: 1280,
    naturalHeight: 720,
    postIndex: 0,
  }),
  true
);
assert.strictEqual(
  helpers.isPreviewImageCandidate({
    src: 'https://south-plus.org/images/post/smile/smallface/face077.gif',
    naturalWidth: 21,
    naturalHeight: 19,
    postIndex: 0,
  }),
  false
);
assert.strictEqual(
  helpers.isPreviewImageCandidate({
    src: 'https://p.inari.site/usr/288/photo_2026-06-02_19-28-41.jpg',
    naturalWidth: 0,
    naturalHeight: 0,
    postIndex: 0,
  }),
  true
);
assert.strictEqual(
  helpers.isPreviewImageCandidate({
    src: 'https://p.inari.site/usr/288/photo_2026-06-02_19-28-41.jpg',
    naturalWidth: 1280,
    naturalHeight: 720,
    postIndex: 2,
  }),
  false
);

const rules = {
  titleKeywords: ['合集', 'NTR'],
  authorKeywords: ['blockedUser'],
};
assert.strictEqual(
  helpers.matchesBlockRules({ title: '求一个合集资源', author: 'alice' }, rules),
  true
);
assert.strictEqual(
  helpers.matchesBlockRules({ title: '普通讨论', author: 'blockedUser123' }, rules),
  true
);
assert.strictEqual(
  helpers.matchesBlockRules({ title: '普通讨论', author: 'alice' }, rules),
  false
);

assert.strictEqual(
  helpers.buildPageUrl('https://south-plus.org/thread.php?fid-48.html', 2),
  'https://south-plus.org/thread.php?fid-48-page-2.html'
);
assert.strictEqual(
  helpers.buildPageUrl('https://south-plus.org/thread.php?fid-48-page-3.html', 4),
  'https://south-plus.org/thread.php?fid-48-page-4.html'
);
assert.strictEqual(
  helpers.buildPageUrl('https://south-plus.org/read.php?tid-2891131-page-2.html', 3),
  'https://south-plus.org/read.php?tid-2891131-page-3.html'
);

assert.strictEqual(
  helpers.detectPageType('https://south-plus.org/index.php'),
  'home'
);
assert.strictEqual(
  helpers.detectPageType('https://south-plus.org/thread.php?fid-48.html'),
  'forum'
);
assert.strictEqual(
  helpers.detectPageType('https://south-plus.org/read.php?tid=2891131'),
  'read'
);

console.log('southplus_enhancer tests passed');
