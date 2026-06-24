# Hover Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a mouse hover preview overlay for dense gallery thumbnails without changing click-to-lightbox behavior.

**Architecture:** Reuse the existing `images` array and `.lwbt-gallery-item` buttons. Add a small hover-preview controller in `bindForumPanel()` that creates one fixed-position preview element, delays display by 150ms, positions it near the hovered thumbnail, and hides it on leave.

**Tech Stack:** Tampermonkey userscript JavaScript, inline CSS in `panelCss()`, existing Node `assert` tests in `laowang_baidu_transfer.test.js`.

---

### Task 1: Add Hover Preview Binding

**Files:**
- Modify: `laowang/laowang_baidu_transfer.test.js`
- Modify: `laowang/laowang_baidu_transfer.user.js`

- [ ] **Step 1: Write the failing test**

Add a source-level test near the dense gallery tests:

```js
test('dense gallery hover preview binds pointer events without replacing click lightbox', () => {
  assert(scriptSource.includes('setupGalleryHoverPreview(root, images)'));
  assert(scriptSource.includes("button.addEventListener('pointerenter'"));
  assert(scriptSource.includes("button.addEventListener('pointerleave'"));
  assert(scriptSource.includes('const HOVER_PREVIEW_DELAY_MS = 150'));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node laowang_baidu_transfer.test.js`

Expected: FAIL because no hover-preview controller exists.

- [ ] **Step 3: Implement minimal hover controller**

Add `const HOVER_PREVIEW_DELAY_MS = 150;` near the other preview constants.

In `bindForumPanel()`, after the click binding, call:

```js
setupGalleryHoverPreview(root, images);
```

Add `setupGalleryHoverPreview()`, `ensureGalleryHoverPreview()`, `showGalleryHoverPreview()`, `hideGalleryHoverPreview()`, and `positionGalleryHoverPreview()` below `bindForumPanel()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `node laowang_baidu_transfer.test.js`

Expected: PASS.

### Task 2: Add Hover Preview CSS

**Files:**
- Modify: `laowang/laowang_baidu_transfer.test.js`
- Modify: `laowang/laowang_baidu_transfer.user.js`

- [ ] **Step 1: Write the failing test**

Add a CSS source-level test:

```js
test('hover preview css renders a fixed image overlay', () => {
  assert(scriptSource.includes('#lwbt-hover-preview[hidden]'));
  assert(scriptSource.includes('#lwbt-hover-preview{position:fixed'));
  assert(scriptSource.includes('max-width:min(420px,46vw)'));
  assert(scriptSource.includes('pointer-events:none'));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node laowang_baidu_transfer.test.js`

Expected: FAIL because hover preview CSS is missing.

- [ ] **Step 3: Implement minimal CSS**

Add fixed overlay styles in `panelCss()`:

```css
#lwbt-hover-preview[hidden]{display:none!important}
#lwbt-hover-preview{position:fixed;z-index:1000000;pointer-events:none;border-radius:8px;background:#111827;padding:6px;box-shadow:0 18px 50px rgba(0,0,0,.35)}
#lwbt-hover-preview img{display:block;max-width:min(420px,46vw);max-height:70vh;object-fit:contain;border-radius:5px}
```

- [ ] **Step 4: Run all tests**

Run: `node laowang_baidu_transfer.test.js`

Expected: all tests print `ok - ...`.
