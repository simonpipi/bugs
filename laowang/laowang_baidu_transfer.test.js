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
  const input = 'a/b:c*d?e"f<g>h|'.repeat(20);
  const output = api.safePathSegment(input);
  assert(!/[\\/:*?"<>|]/.test(output));
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

test('isPreviewImage rejects avatars, smileys, icons and accepts attachment images', () => {
  assert.strictEqual(api.isPreviewImage('https://laowang.vip/uc_server/data/avatar/001/a.jpg'), false);
  assert.strictEqual(api.isPreviewImage('https://laowang.vip/static/image/smiley/tieba/tb_17.png'), false);
  assert.strictEqual(api.isPreviewImage('https://laowang.vip/static/image/common/online_member.gif'), false);
  assert.strictEqual(api.isPreviewImage('https://laowang.vip/data/attachment/forum/202606/12/demo.jpg'), true);
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
  assert.strictEqual(task.targetPath, '/老王转存/2026-06/标题/');
  assert.strictEqual(task.status, 'pending');
});

test('findPendingTaskForUrl matches pending baidu share task', () => {
  const tasks = [
    { status: 'saved', shareUrl: 'https://pan.baidu.com/s/old' },
    { status: 'pending', shareUrl: 'https://pan.baidu.com/s/1abc' }
  ];
  const task = api.findPendingTaskForUrl(tasks, 'https://pan.baidu.com/s/1abc?pwd=abcd');
  assert.strictEqual(task.shareUrl, 'https://pan.baidu.com/s/1abc');
});
