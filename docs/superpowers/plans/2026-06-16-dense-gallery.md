# Dense Gallery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the preview panel's main-image-plus-all-thumbs layout with a dense scrolling gallery for posts with many preview images.

**Architecture:** Keep the existing `images` array, download flow, and lightbox behavior. Change only the rendered gallery markup, binding selectors, and CSS so thumbnails are displayed as a dense lazy-loaded wall and each thumbnail opens the existing lightbox at its image index.

**Tech Stack:** Tampermonkey userscript JavaScript, inline CSS in `panelCss()`, existing Node `assert` tests in `laowang_baidu_transfer.test.js`.

---

### Task 1: Add Gallery Markup Test

**Files:**
- Modify: `laowang/laowang_baidu_transfer.test.js`
- Modify: `laowang/laowang_baidu_transfer.user.js`

- [ ] **Step 1: Write the failing test**

Add a test after the existing `renderForumPanel highlights expired resources without disabling actions` test:

```js
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
  assert(!html.includes('lwbt-main-trigger'));
  assert(!html.includes('lwbt-thumbs'));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node laowang_baidu_transfer.test.js`

Expected: FAIL because `renderForumPanel()` still emits `.lwbt-main-trigger` and `.lwbt-thumbs`, not `.lwbt-gallery-grid`.

- [ ] **Step 3: Write minimal implementation**

In `renderForumPanel()`, replace the main image and thumb string with a gallery grid:

```js
const galleryItems = images.map((url, index) => `
  <button class="lwbt-gallery-item" data-index="${index}" type="button" title="预览图 ${index + 1}">
    <img src="${escapeAttr(url)}" alt="" loading="lazy" decoding="async">
    <span>${index + 1}</span>
  </button>`).join('');
```

Render:

```html
<div class="lwbt-gallery-summary">预览图 ${images.length} 张</div>
<div class="lwbt-gallery-grid">${galleryItems}</div>
```

When there are no images, keep the existing empty message.

- [ ] **Step 4: Run test to verify it passes**

Run: `node laowang_baidu_transfer.test.js`

Expected: PASS.

### Task 2: Bind Dense Gallery Items To Existing Lightbox

**Files:**
- Modify: `laowang/laowang_baidu_transfer.test.js`
- Modify: `laowang/laowang_baidu_transfer.user.js`

- [ ] **Step 1: Write the failing test**

Add a source-level regression test:

```js
test('dense gallery item clicks open the existing lightbox', () => {
  assert(scriptSource.includes("document.querySelectorAll('.lwbt-gallery-item')"));
  assert(scriptSource.includes('openImageLightbox(root, api, images, Number(button.dataset.index))'));
  assert(!scriptSource.includes("document.querySelectorAll('.lwbt-thumb')"));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node laowang_baidu_transfer.test.js`

Expected: FAIL because `bindForumPanel()` still binds `.lwbt-thumb` and `.lwbt-main-trigger`.

- [ ] **Step 3: Write minimal implementation**

In `bindForumPanel()`, remove `activeImageIndex`, `showImage()`, `.lwbt-thumb`, and `.lwbt-main-trigger` binding. Add:

```js
document.querySelectorAll('.lwbt-gallery-item').forEach((button) => {
  button.addEventListener('click', () => {
    openImageLightbox(root, api, images, Number(button.dataset.index));
  });
});
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node laowang_baidu_transfer.test.js`

Expected: PASS.

### Task 3: Add Dense Gallery CSS

**Files:**
- Modify: `laowang/laowang_baidu_transfer.test.js`
- Modify: `laowang/laowang_baidu_transfer.user.js`

- [ ] **Step 1: Write the failing test**

Add a source-level CSS test:

```js
test('dense gallery css supports a scrollable image wall', () => {
  assert(scriptSource.includes('.lwbt-gallery-summary'));
  assert(scriptSource.includes('.lwbt-gallery-grid{'));
  assert(scriptSource.includes('grid-template-columns:repeat(auto-fill,minmax(92px,1fr))'));
  assert(scriptSource.includes('max-height:640px'));
  assert(scriptSource.includes('.lwbt-gallery-item span'));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node laowang_baidu_transfer.test.js`

Expected: FAIL because the CSS still defines `.lwbt-main`, `.lwbt-thumb`, and `.lwbt-thumbs`.

- [ ] **Step 3: Write minimal implementation**

In `panelCss()`, replace the old gallery main/thumb CSS with:

```css
.lwbt-gallery-summary{margin-bottom:8px;color:#4b5563;font-size:13px;font-weight:800}
.lwbt-gallery-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(92px,1fr));gap:8px;max-height:640px;overflow:auto;padding-right:2px}
.lwbt-gallery-item{position:relative;aspect-ratio:16/10;border:1px solid #e5e7eb;border-radius:6px;background:#fff;overflow:hidden;padding:0;cursor:zoom-in}
.lwbt-gallery-item img{width:100%;height:100%;object-fit:cover;display:block}
.lwbt-gallery-item span{position:absolute;left:5px;top:5px;border-radius:999px;background:rgba(17,24,39,.78);color:#fff;font-size:11px;font-weight:800;line-height:1;padding:4px 6px}
```

Update the mobile media query to reduce grid cell size:

```css
.lwbt-gallery-grid{grid-template-columns:repeat(auto-fill,minmax(76px,1fr));max-height:520px}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node laowang_baidu_transfer.test.js`

Expected: PASS.

### Task 4: Final Verification

**Files:**
- Modify: `laowang/laowang_baidu_transfer.test.js`
- Modify: `laowang/laowang_baidu_transfer.user.js`

- [ ] **Step 1: Run all existing userscript tests**

Run: `node laowang_baidu_transfer.test.js`

Expected: all tests print `ok - ...`.

- [ ] **Step 2: Inspect final diff**

Run: `git diff -- laowang/laowang_baidu_transfer.user.js laowang/laowang_baidu_transfer.test.js`

Expected: diff is limited to dense gallery rendering, binding, CSS, and related tests.
