# South Plus Enhancer Userscript Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Tampermonkey userscript that improves South Plus browsing with local-only layout cleanup, navigation shortcuts, read-state tracking, and keyword/author blocking.

**Architecture:** The script is a single installable `.user.js` file with small helper functions grouped under one namespace. Pure helpers are exported under CommonJS when loaded in Node so behavior can be tested without a browser.

**Tech Stack:** JavaScript userscript, Tampermonkey/Greasemonkey APIs where available, browser `localStorage`, Node built-in `assert` for tests.

---

### Task 1: Core Helpers

**Files:**
- Create: `southplus/southplus_enhancer.test.js`
- Create: `southplus/southplus_enhancer.user.js`

- [ ] **Step 1: Write the failing test**

Create `southplus/southplus_enhancer.test.js` with tests for thread id extraction, block rule parsing, block matching, and page navigation URL generation.

- [ ] **Step 2: Run test to verify it fails**

Run: `node southplus/southplus_enhancer.test.js`
Expected: FAIL because `southplus_enhancer.user.js` does not exist yet.

- [ ] **Step 3: Write minimal helper implementation**

Create `southplus/southplus_enhancer.user.js` with a metadata block and exported helpers: `parseThreadId`, `parseLineList`, `matchesBlockRules`, `buildPageUrl`, `detectPageType`.

- [ ] **Step 4: Run test to verify it passes**

Run: `node southplus/southplus_enhancer.test.js`
Expected: PASS with all assertions completed.

### Task 2: Browser Enhancements

**Files:**
- Modify: `southplus/southplus_enhancer.user.js`

- [ ] **Step 1: Add layout cleanup**

Inject CSS and a clean-mode toggle that folds `#infobox`, `#notice`, footer/online sections, and oversized forum chrome without removing content permanently.

- [ ] **Step 2: Add forum list enhancements**

Enhance `td_<tid>` list cells with local read-state dimming, quick block buttons, and title/author keyword filtering.

- [ ] **Step 3: Add read-page enhancements**

Enhance `table.js-post` floors with compact mode, quote/signature folding, local author blocking, and optional only-author view.

- [ ] **Step 4: Add floating toolbar**

Add fixed toolbar buttons for top, bottom, previous page, next page, latest posts, homepage, settings, clean mode, unread-only, and only-author where applicable.

### Task 3: Verification

**Files:**
- Test: `southplus/southplus_enhancer.test.js`
- Verify: `southplus/southplus_enhancer.user.js`

- [ ] **Step 1: Run unit tests**

Run: `node southplus/southplus_enhancer.test.js`
Expected: PASS.

- [ ] **Step 2: Check script syntax**

Run: `node --check southplus/southplus_enhancer.user.js`
Expected: syntax check passes.

- [ ] **Step 3: Manual install note**

Report the userscript path and key controls for Tampermonkey installation.
