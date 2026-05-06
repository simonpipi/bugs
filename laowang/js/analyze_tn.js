const fs = require('fs');
const vm = require('vm');

const src = fs.readFileSync(__dirname + '/tn_code.raw.js', 'utf8');

const noop = () => {};
const fakeCanvas = {
  width: 0,
  height: 0,
  style: {},
  getContext(type) {
    if (type === 'webgl' || type === 'experimental-webgl') {
      return {
        RENDERER: 0x1f01,
        getExtension() {
          return { UNMASKED_RENDERER_WEBGL: 0x9246 };
        },
        getParameter() {
          return 'Apple GPU';
        },
      };
    }
    return {
      fillStyle: '',
      textBaseline: '',
      font: '',
      fillRect: noop,
      fillText: noop,
      clearRect: noop,
      drawImage: noop,
      getImageData() {
        return { data: new Uint8ClampedArray(260 * 160 * 4) };
      },
    };
  },
  toDataURL() {
    return 'data:image/png;base64,stub';
  },
};

const elements = new Map();
function elem(id = '') {
  if (!elements.has(id)) {
    elements.set(id, {
      id,
      value: id === 'browser_fp' ? 'no_js' : '',
      innerHTML: '',
      style: {},
      nodeType: 1,
      parentNode: { insertBefore: noop },
      nextSibling: null,
      addEventListener: noop,
      attachEvent: noop,
      appendChild: noop,
      cloneNode() { return elem(id + '_clone'); },
      getBoundingClientRect() { return { left: 0, top: 0, width: 260, height: 160 }; },
      getContext: fakeCanvas.getContext.bind(fakeCanvas),
      toDataURL: fakeCanvas.toDataURL.bind(fakeCanvas),
    });
  }
  return elements.get(id);
}

const document = {
  readyState: 'complete',
  body: elem('body'),
  createElement(tag) {
    return tag === 'canvas' ? { ...fakeCanvas, style: {}, addEventListener: noop } : elem(tag);
  },
  getElementById(id) { return elem(id); },
  getElementsByTagName(name) { return name === 'body' ? [this.body] : []; },
  getElementByClassName() { return []; },
  getElementsByClassName() { return []; },
  addEventListener(_name, cb) {
    if (typeof cb === 'function') cb();
  },
  attachEvent: noop,
};

const context = {
  window: null,
  document,
  navigator: {
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) Gecko/20100101 Firefox/135.0',
    languages: ['zh-CN', 'zh'],
    language: 'zh-CN',
    platform: 'MacIntel',
    hardwareConcurrency: 8,
    deviceMemory: 8,
  },
  screen: { width: 1280, height: 720, colorDepth: 24 },
  console,
  Image: function Image() { return elem('image'); },
  XMLHttpRequest: function XMLHttpRequest() {},
  ActiveXObject: function ActiveXObject() {},
  setTimeout(cb) { if (typeof cb === 'function') cb(); return 1; },
  setInterval() { return 1; },
  clearInterval: noop,
  addEventListener(_name, cb) {
    if (typeof cb === 'function') cb();
  },
  attachEvent: noop,
  encodeURIComponent,
  decodeURIComponent,
  Math,
  Date,
  String,
  Uint8ClampedArray,
};
context.window = context;
context.XMLHttpRequest.prototype = {
  open: noop,
  send: noop,
  setRequestHeader: noop,
};

vm.createContext(context);
try {
  vm.runInContext(src, context, { timeout: 3000, filename: 'tn_code.raw.js' });
} catch (err) {
  console.error('run error:', err && err.stack || err);
}

const names = ['generateSecurePayload', '_ajax', 'tncode', 'TN', 'LAOWANG_FP', 'fingerprint'];
for (const name of names) {
  console.log(name, typeof context[name]);
}

if (typeof context._0x0_0x21ac === 'function') {
  const decodeSamples = [
    [0x307, '\x4a\x29\x39\x43'],
    [0x30c, '\x40\x54\x4e\x24'],
    [0x1f4, '\x55\x45\x6a\x43'],
    [0x279, '\x25\x4b\x39\x42'],
    [0x29e, '\x4a\x63\x52\x66'],
    [0x2b0, '\x54\x6c\x52\x29'],
    [0x303, '\x4f\x72\x57\x68'],
    [0x205, '\x55\x45\x6a\x43'],
    [0x259, '\x70\x78\x57\x4d'],
    [0x1fb, '\x79\x47\x48\x74'],
  ];
  for (const [n, k] of decodeSamples) {
    try {
      console.log('dec', n.toString(16), JSON.stringify(k), JSON.stringify(context._0x0_0x21ac(n, k)));
    } catch {}
  }
}

if (typeof context.generateSecurePayload === 'function') {
  fs.writeFileSync(__dirname + '/generateSecurePayload.runtime.js', context.generateSecurePayload.toString());
  vm.runInContext(`
    (function(){
      var orig = String.prototype.charCodeAt;
      var seen = {};
      String.prototype.charCodeAt = function(i) {
        var s = String(this);
        if (s.length <= 32) seen[s] = (seen[s] || 0) + 1;
        return orig.call(this, i);
      };
      window.__shortCharCodeSeen = seen;
    })();
  `, context);
  for (const sample of [
    [[], 0],
    [[{ x: 1, y: 2, t: 3 }], 120],
    [[{ x: 10, y: 20, t: 0 }, { x: 80, y: 22, t: 500 }], 90],
  ]) {
    try {
      console.log('payload', JSON.stringify(sample), context.generateSecurePayload(...sample));
    } catch (err) {
      console.log('payload_error', err.message);
    }
  }
  console.log('shortCharCodeSeen', JSON.stringify(context.__shortCharCodeSeen, null, 2));
}

const fpApi = context.LAOWANG_FP || context.fingerprint;
if (fpApi && typeof fpApi.compute === 'function') {
  console.log('fp', fpApi.compute());
  console.log('browser_fp_field', document.getElementById('browser_fp').value);
}
