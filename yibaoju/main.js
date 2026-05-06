const crypto = require("crypto");
const { sm2, sm4 } = require("sm-crypto");

const CONFIG = {
  baseURL: "https://fuwu.nhsa.gov.cn/ebus/fuwu/api",
  hallURL: "https://fuwu.nhsa.gov.cn/nationalHallSt/",
  endpoint: "/nthl/api/CommQuery/queryFixedHospital",
  appCode: "T98HPCGN5ZVVQBS8LZQNOAEXVI9GYHKQ",
  appSecret: "NMVFVILMKT13GEMD3BKPKCTBOQBPZR2P",
  privateKeyBase64: "AJxKNdmspMaPGj+onJNoQ0cgWk2E3CYFWKBJhpcJrAtC",
  userAgent:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) Gecko/20100101 Firefox/135.0",
  nonceCharset: "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678",
};

function base64ToHex(value) {
  return Buffer.from(value, "base64").toString("hex");
}

function utf8Bytes(input) {
  const bytes = [];
  for (let i = 0; i < input.length; i += 1) {
    const code = input.charCodeAt(i);
    if (code >= 65536 && code <= 1114111) {
      bytes.push((code >> 18) & 7 | 240);
      bytes.push((code >> 12) & 63 | 128);
      bytes.push((code >> 6) & 63 | 128);
      bytes.push((code & 63) | 128);
    } else if (code >= 2048 && code <= 65535) {
      bytes.push((code >> 12) & 15 | 224);
      bytes.push((code >> 6) & 63 | 128);
      bytes.push((code & 63) | 128);
    } else if (code >= 128 && code <= 2047) {
      bytes.push((code >> 6) & 31 | 192);
      bytes.push((code & 63) | 128);
    } else {
      bytes.push(code & 255);
    }
  }
  return bytes;
}

function toUnicodeEscapedJson(input) {
  let out = "";
  for (const char of input) {
    const code = char.charCodeAt(0);
    out += code > 127 ? `\\u${code.toString(16).padStart(4, "0")}` : char;
  }
  return out;
}

function sortObject(obj) {
  const keys = Object.keys(obj).sort();
  const out = {};
  for (const key of keys) {
    out[key] = obj[key];
  }
  return out;
}

function pickSignFields(obj) {
  const out = {};
  for (const [key, value] of Object.entries(obj)) {
    if (!Object.prototype.hasOwnProperty.call(obj, key)) {
      continue;
    }
    if (["signData", "encData", "extra"].includes(key)) {
      continue;
    }
    if (value == null) {
      continue;
    }
    out[key] = value;
  }
  return out;
}

function normalizeDataForSign(data) {
  const clone = { ...data };
  for (const key of Object.keys(clone)) {
    const value = clone[key];
    if (typeof value === "number" || typeof value === "boolean") {
      clone[key] = String(value);
      continue;
    }
    if (Array.isArray(value) && value.length === 0) {
      delete clone[key];
      continue;
    }
    if (Array.isArray(value) && value.length > 0) {
      clone[key] = value.map((item) => (item && typeof item === "object" && !Array.isArray(item) ? sortObject(item) : item));
      continue;
    }
    if (!value) {
      delete clone[key];
    }
  }
  return sortObject(clone);
}

function buildSignPlaintext(payload) {
  const parts = [];
  for (const [key, value] of Object.entries(payload)) {
    if (!Object.prototype.hasOwnProperty.call(payload, key)) {
      continue;
    }
    if (value == null || String(value) === "") {
      continue;
    }
    if (key === "data") {
      const normalized = normalizeDataForSign({ ...value });
      parts.push(`${key}=${JSON.stringify(normalized)}`);
      continue;
    }
    parts.push(`${key}=${value}`);
  }
  parts.push(`key=${CONFIG.appSecret}`);
  return parts.join("&");
}

function sm4EncryptHex(keyBytes, plainBytes) {
  const padding = 16 - (plainBytes.length % 16);
  const padded = plainBytes.concat(new Array(padding).fill(padding));
  const cipherBytes = sm4.encrypt(padded, keyBytes, {
    padding: "none",
    output: "array",
  });
  return Buffer.from(cipherBytes).toString("hex").toUpperCase();
}

function sm4DecryptHex(keyBytes, cipherHex) {
  const cipherBytes = Array.from(Buffer.from(cipherHex, "hex"));
  const plainBytes = sm4.decrypt(cipherBytes, keyBytes, {
    padding: "none",
    output: "array",
  });
  const pad = plainBytes[plainBytes.length - 1];
  const unpadded = plainBytes.slice(0, plainBytes.length - pad);
  return Buffer.from(unpadded).toString("utf8");
}

function deriveKeyBytes(appCode, appSecret) {
  const firstBlock = appCode.slice(0, 16);
  const seedHex = sm4EncryptHex(utf8Bytes(firstBlock), utf8Bytes(appSecret));
  return utf8Bytes(seedHex.slice(0, 16).toUpperCase());
}

function randomNonce(length = 8) {
  const bytes = crypto.randomBytes(length);
  let out = "";
  for (let i = 0; i < length; i += 1) {
    out += CONFIG.nonceCharset[bytes[i] % CONFIG.nonceCharset.length];
  }
  return out;
}

function buildRequestBody(query, timestamp) {
  const payload = {
    data: query,
    appCode: CONFIG.appCode,
    version: "1.0.0",
    encType: "SM4",
    signType: "SM2",
    timestamp,
  };

  const signInput = pickSignFields(payload);
  signInput.data = sortObject(signInput.data);
  const signPlain = buildSignPlaintext(signInput);
  const privateKeyHex = base64ToHex(CONFIG.privateKeyBase64);
  const signHex = sm2.doSignature(signPlain, privateKeyHex, { hash: true });
  const signData = Buffer.from(signHex, "hex").toString("base64");

  const escaped = toUnicodeEscapedJson(JSON.stringify(query));
  const keyBytes = deriveKeyBytes(CONFIG.appCode, CONFIG.appSecret);
  const encData = sm4EncryptHex(keyBytes, utf8Bytes(escaped));

  return JSON.stringify({
    data: {
      appCode: CONFIG.appCode,
      version: "1.0.0",
      encType: "SM4",
      signType: "SM2",
      timestamp,
      signData,
      data: {
        encData,
      },
    },
  });
}

function decryptResponseEnvelope(envelope) {
  if (!envelope || !envelope.appCode || !envelope.data || !envelope.data.encData) {
    return envelope;
  }
  const keyBytes = deriveKeyBytes(CONFIG.appCode, CONFIG.appSecret);
  const plaintext = sm4DecryptHex(keyBytes, envelope.data.encData);
  return JSON.parse(plaintext);
}

async function warmupCookie() {
  const response = await fetch(CONFIG.hallURL, {
    headers: {
      "user-agent": CONFIG.userAgent,
      accept:
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
      "accept-language": "zh-CN,zh;q=0.9",
    },
  });
  const raw = response.headers.get("set-cookie");
  const base = [];
  if (raw) {
    base.push(raw.split(";", 1)[0]);
  }
  base.push("yb_header_active=-1");
  return base.join("; ");
}

async function queryFixedHospital(options) {
  const timestamp = Math.ceil(Date.now() / 1000);
  const nonce = randomNonce(8);
  const signature = crypto
    .createHash("sha256")
    .update(`${timestamp}${nonce}${timestamp}`, "utf8")
    .digest("hex");

  const cookie = await warmupCookie();
  const body = buildRequestBody(options, timestamp);

  const response = await fetch(`${CONFIG.baseURL}${CONFIG.endpoint}`, {
    method: "POST",
    headers: {
      accept: "application/json",
      "accept-language": "zh-CN,zh;q=0.9",
      "content-type": "application/json",
      channel: "web",
      "x-tif-paasid": "undefined",
      "x-tif-signature": signature,
      "x-tif-timestamp": String(timestamp),
      "x-tif-nonce": nonce,
      contenttype: "application/x-www-form-urlencoded",
      origin: "https://fuwu.nhsa.gov.cn",
      referer: "https://fuwu.nhsa.gov.cn/nationalHallSt/",
      "user-agent": CONFIG.userAgent,
      cookie,
    },
    body,
  });

  const json = await response.json();
  if (json && json.data && json.data.appCode) {
    json.data = decryptResponseEnvelope(json.data);
  }
  return {
    status: response.status,
    json,
  };
}

function buildQueryFromArgs() {
  const args = process.argv.slice(2);
  const get = (flag, fallback = "") => {
    const index = args.indexOf(flag);
    return index >= 0 && index + 1 < args.length ? args[index + 1] : fallback;
  };
  return {
    addr: get("--addr"),
    regnCode: get("--regnCode", "110000"),
    medinsName: get("--medinsName"),
    medinsLvCode: get("--medinsLvCode"),
    medinsTypeCode: get("--medinsTypeCode"),
    outMedOpenFlag: get("--outMedOpenFlag"),
    pageNum: Number(get("--pageNum", "1")),
    pageSize: Number(get("--pageSize", "10")),
    queryDataSource: "es",
  };
}

async function main() {
  const query = buildQueryFromArgs();
  const result = await queryFixedHospital(query);
  const payload = result.json;

  console.log(JSON.stringify({
    request: query,
    status: result.status,
    code: payload.code,
    message: payload.message,
    total: payload.data && payload.data.total,
    first: payload.data && payload.data.list && payload.data.list[0],
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
