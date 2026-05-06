#!/usr/bin/env node

const crypto = require("node:crypto");

const TRANS_BASE = "https://dict-trans.youdao.com";
const DICT_BASE = "https://dict.youdao.com";
const AI_BASE = "https://luna-ai.youdao.com";

const KEY_GETTER_ID = "translate-webmain-key-getter";
const KEY_GETTER_SECRET = "kSy5gtKA4yRUxAVPJPrdYKZ0jBKyd3t1";
const TRANSLATE_KEY_ID = "translate-webfanyi-webmain";
const JSON_API_SECRET = "t2he2k4m2g6QKRigK0KAmSpXKgAezywG";
const DIRECTION_KEY_ID = "ai-translate-direction";
const DIRECTION_SECRET = "I5WacgKEZaloWBiDnE1fThnzxYWN30PH";

const DEFAULT_HEADERS = {
  Origin: "https://fanyi.youdao.com",
  Referer: "https://fanyi.youdao.com/",
  "Accept-Language": "zh-CN,zh;q=0.9",
  "User-Agent":
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
};

function md5Hex(input) {
  return crypto.createHash("md5").update(input).digest("hex");
}

function buildHeaders(extra = {}, cookie = "") {
  const headers = { ...DEFAULT_HEADERS, ...extra };
  if (cookie) {
    headers.Cookie = cookie;
  }
  return headers;
}

function buildYduuid() {
  return crypto.randomBytes(16).toString("hex");
}

function normalizeSignPayload(payload) {
  const copy = { ...payload };

  for (const key of Object.keys(copy)) {
    if (copy[key] === "") {
      delete copy[key];
    }
  }

  return copy;
}

function signParams(payload, secret) {
  const normalized = normalizeSignPayload(payload);
  const sortedKeys = Object.keys(normalized)
    .filter((key) => normalized[key] !== undefined)
    .sort();

  sortedKeys.push("key");
  normalized.key = secret;

  const source = sortedKeys.map((key) => `${key}=${normalized[key]}`).join("&");
  return {
    sign: md5Hex(source),
    pointParam: sortedKeys.join(","),
  };
}

function genParamV3(extra, secret, options) {
  const payload = {
    product: options.product,
    appVersion: options.appVersion,
    client: options.client,
    mid: 1,
    vendor: "web",
    screen: 1,
    model: 1,
    imei: 1,
    network: "wifi",
    keyfrom: options.keyfrom,
    keyid: options.keyid,
    mysticTime: Date.now(),
    yduuid: options.yduuid,
    abtest: 0,
    ...extra,
  };

  const { sign, pointParam } = signParams(payload, secret);
  return {
    ...payload,
    sign,
    pointParam,
  };
}

function buildFormData(payload) {
  const form = new FormData();
  for (const [key, value] of Object.entries(payload)) {
    form.append(key, String(value));
  }
  return form;
}

async function fetchText(url, init) {
  const response = await fetch(url, init);
  const text = await response.text();

  if (!response.ok) {
    throw new Error(`HTTP ${response.status} ${response.statusText}: ${text}`);
  }

  return text;
}

async function fetchJson(url, init) {
  const text = await fetchText(url, init);

  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`Failed to parse JSON from ${url}: ${text}`);
  }
}

function parseSseEvents(rawText) {
  const events = [];
  const chunks = [];
  let requestId = null;
  let direction = null;

  for (const block of rawText.split(/\r?\n\r?\n/)) {
    const lines = block
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);

    if (lines.length === 0) {
      continue;
    }

    const event = {};
    for (const line of lines) {
      const index = line.indexOf(":");
      if (index === -1) {
        continue;
      }
      const key = line.slice(0, index);
      const value = line.slice(index + 1).trim();
      event[key] = value;
    }

    let data = null;
    if (event.data) {
      try {
        data = JSON.parse(event.data);
      } catch (error) {
        data = event.data;
      }
    }

    if (event.event === "begin" && data) {
      requestId = data.requestId || requestId;
      direction = data.type || direction;
    }

    if (event.event === "message" && data && data.transIncre) {
      chunks.push(data.transIncre);
    }

    if (event.event === "end" && data) {
      requestId = data.requestId || requestId;
      direction = data.type || direction;
    }

    events.push({
      id: event.id || null,
      event: event.event || null,
      data,
    });
  }

  return {
    requestId,
    direction,
    translation: chunks.join(""),
    events,
  };
}

async function getTranslateKey({ yduuid, cookie, cachedTextToken }) {
  const params = genParamV3(
    {
      targetKeyid: TRANSLATE_KEY_ID,
      ...(cachedTextToken ? { token: cachedTextToken } : {}),
    },
    KEY_GETTER_SECRET,
    {
      product: "webfanyi",
      appVersion: "12.0.0",
      client: "webmain",
      keyfrom: "webfanyi.webmain",
      keyid: KEY_GETTER_ID,
      yduuid,
    },
  );

  const url = new URL(`${TRANS_BASE}/translate/key`);
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, String(value));
  }

  return fetchJson(url, {
    method: "POST",
    headers: buildHeaders(
      {
        Accept: "application/json, text/plain, */*",
      },
      cookie,
    ),
  });
}

async function detectDirection({ text, yduuid, cookie, ydtoken }) {
  const params = genParamV3(
    {
      input: encodeURIComponent(text),
      ...(ydtoken ? { token: ydtoken } : {}),
    },
    DIRECTION_SECRET,
    {
      product: "webfanyi",
      appVersion: "12.0.0",
      client: "web",
      keyfrom: "fanyi.web",
      keyid: DIRECTION_KEY_ID,
      yduuid,
    },
  );

  return fetchJson(`${AI_BASE}/translate_llm/v3/translateDirection`, {
    method: "POST",
    headers: buildHeaders(
      {
        Accept: "application/json, text/plain, */*",
      },
      cookie,
    ),
    body: buildFormData(params),
  });
}

async function translateSse({ text, from, to, yduuid, cookie, token, secretKey, useTerm }) {
  const params = genParamV3(
    {
      modelName: "llmLite",
      useTerm: String(useTerm),
      i: encodeURIComponent(text),
      from,
      to,
      signSecretKey: secretKey,
      keyId: TRANSLATE_KEY_ID,
      token,
      source: "webmain",
    },
    secretKey,
    {
      product: "webfanyi",
      appVersion: "1",
      client: "webmain",
      keyfrom: "webfanyi.webmain",
      keyid: TRANSLATE_KEY_ID,
      yduuid,
    },
  );

  const rawText = await fetchText(`${TRANS_BASE}/webtranslate/sse`, {
    method: "POST",
    headers: buildHeaders(
      {
        Accept: "*/*",
      },
      cookie,
    ),
    body: buildFormData(params),
  });

  return parseSseEvents(rawText);
}

function buildDictSignature(text, timestamp) {
  const keyfrom = "webfanyi.webmain";
  const client = "webmain";
  const suffix = (`${text}${keyfrom}`).length % 10;
  const t = `${timestamp}${suffix}`;
  const digest = md5Hex(`${text}${keyfrom}`);
  const sign = md5Hex(`${client}${text}${t}${JSON_API_SECRET}${digest}`);

  return {
    sign,
    t,
    client,
    keyfrom,
  };
}

async function getDictResult({ text, direction, cookie }) {
  const dict = direction === "en2zh-CHS" ? "ec" : "ce";
  const { sign, t, client, keyfrom } = buildDictSignature(text, Date.now());

  const body = new URLSearchParams({
    needTranslate: "false",
    dicts: JSON.stringify({ count: "1", dicts: [dict] }),
    q: text,
    t,
    client,
    sign,
    keyfrom,
  });

  return fetchJson(`${DICT_BASE}/jsonapi_s?doctype=json&jsonversion=4`, {
    method: "POST",
    headers: buildHeaders(
      {
        Accept: "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded",
      },
      cookie,
    ),
    body,
  });
}

async function getEnhanceResult({ text, translation, from, to, yduuid, cookie, token, secretKey }) {
  const signPayload = genParamV3(
    {
      signSecretKey: secretKey,
      keyId: TRANSLATE_KEY_ID,
      token,
      source: "webmain",
    },
    secretKey,
    {
      product: "webfanyi",
      appVersion: "12.0.0",
      client: "webmain",
      keyfrom: "webfanyi.webmain",
      keyid: TRANSLATE_KEY_ID,
      yduuid,
    },
  );

  const body = buildFormData({
    srcArticle: encodeURIComponent(text),
    tgtArticle: encodeURIComponent(translation),
    from,
    to,
    ...signPayload,
  });

  return fetchJson(`${TRANS_BASE}/translate/enhance`, {
    method: "POST",
    headers: buildHeaders(
      {
        Accept: "application/json, text/plain, */*",
      },
      cookie,
    ),
    body,
  });
}

function guessDirection(text) {
  return /[\u4e00-\u9fff]/.test(text) ? "zh-CHS2en" : "en2zh-CHS";
}

function shouldFetchDict(direction, text) {
  return ["en2zh-CHS", "zh-CHS2en"].includes(direction) && text.length <= 50;
}

function shouldFetchEnhance(direction) {
  return ["zh-CHS2en", "en2zh-CHS", "ja2zh-CHS", "ko2zh-CHS"].includes(direction);
}

function parseArgs(argv) {
  const args = {
    text: "",
    from: "",
    to: "",
    yduuid: process.env.YOUDAO_YDUUID || "",
    cookie: process.env.YOUDAO_COOKIE || "",
    ydtoken: process.env.YOUDAO_YDTOKEN || "",
    useTerm: false,
    withDict: true,
    withEnhance: true,
    help: false,
  };

  const positionals = [];
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const next = argv[index + 1];

    if (arg === "--help" || arg === "-h") {
      args.help = true;
      continue;
    }
    if (arg === "--from" && next) {
      args.from = next;
      index += 1;
      continue;
    }
    if (arg === "--to" && next) {
      args.to = next;
      index += 1;
      continue;
    }
    if (arg === "--yduuid" && next) {
      args.yduuid = next;
      index += 1;
      continue;
    }
    if (arg === "--cookie" && next) {
      args.cookie = next;
      index += 1;
      continue;
    }
    if (arg === "--ydtoken" && next) {
      args.ydtoken = next;
      index += 1;
      continue;
    }
    if (arg === "--use-term") {
      args.useTerm = true;
      continue;
    }
    if (arg === "--no-dict") {
      args.withDict = false;
      continue;
    }
    if (arg === "--no-enhance") {
      args.withEnhance = false;
      continue;
    }

    positionals.push(arg);
  }

  args.text = positionals.join(" ").trim();
  return args;
}

function printHelp() {
  const lines = [
    "Usage:",
    "  node main.js \"hello world\" [--from en] [--to zh-CHS]",
    "",
    "Options:",
    "  --from <lang>      Source language, e.g. en, zh-CHS, ja, ko, auto",
    "  --to <lang>        Target language, e.g. en, zh-CHS",
    "  --yduuid <value>   Override local yduuid",
    "  --cookie <value>   Optional Cookie header",
    "  --ydtoken <value>  Optional ydtoken for direction detection",
    "  --use-term         Enable terminology mode",
    "  --no-dict          Skip jsonapi_s dictionary supplement",
    "  --no-enhance       Skip translate/enhance request",
    "  -h, --help         Show this help",
  ];

  console.log(lines.join("\n"));
}

async function main() {
  const args = parseArgs(process.argv.slice(2));

  if (args.help || !args.text) {
    printHelp();
    process.exit(args.help ? 0 : 1);
  }

  const yduuid = args.yduuid || buildYduuid();
  let from = args.from;
  let to = args.to;
  let directionInfo = null;

  if (!from || !to) {
    try {
      directionInfo = await detectDirection({
        text: args.text,
        yduuid,
        cookie: args.cookie,
        ydtoken: args.ydtoken,
      });

      if (directionInfo?.code === 0 && directionInfo?.data?.translateDirection) {
        [from, to] = directionInfo.data.translateDirection.split("2");
      }
    } catch (error) {
      const guessed = guessDirection(args.text);
      [from, to] = guessed.split("2");
      directionInfo = {
        code: -1,
        fallback: true,
        guessedDirection: guessed,
        error: error.message,
      };
    }
  }

  if (!from || !to) {
    const guessed = guessDirection(args.text);
    [from, to] = guessed.split("2");
  }

  const keyResponse = await getTranslateKey({
    yduuid,
    cookie: args.cookie,
    cachedTextToken: "",
  });

  if (keyResponse.code !== 0 || !keyResponse.data?.secretKey || !keyResponse.data?.token) {
    throw new Error(`Failed to get translate key: ${JSON.stringify(keyResponse)}`);
  }

  const sseResult = await translateSse({
    text: args.text,
    from,
    to,
    yduuid,
    cookie: args.cookie,
    token: keyResponse.data.token,
    secretKey: keyResponse.data.secretKey,
    useTerm: args.useTerm,
  });

  const direction = sseResult.direction || `${from}2${to}`;
  const result = {
    input: args.text,
    from,
    to,
    direction,
    yduuid,
    key: {
      token: keyResponse.data.token,
      secretKey: keyResponse.data.secretKey,
    },
    sse: {
      requestId: sseResult.requestId,
      translation: sseResult.translation,
      events: sseResult.events,
    },
    directionInfo,
  };

  if (args.withEnhance && sseResult.translation && shouldFetchEnhance(direction)) {
    try {
      result.enhance = await getEnhanceResult({
        text: args.text,
        translation: sseResult.translation,
        from,
        to,
        yduuid,
        cookie: args.cookie,
        token: keyResponse.data.token,
        secretKey: keyResponse.data.secretKey,
      });
    } catch (error) {
      result.enhance = { error: error.message };
    }
  }

  if (args.withDict && shouldFetchDict(direction, args.text)) {
    try {
      result.dict = await getDictResult({
        text: args.text,
        direction,
        cookie: args.cookie,
      });
    } catch (error) {
      result.dict = { error: error.message };
    }
  }

  console.log(JSON.stringify(result, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
