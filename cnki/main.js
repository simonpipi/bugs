const crypto = require("crypto");
const { execFile } = require("child_process");

const BASE_HOST = "dict.cnki.net";
const AES_KEY = "4e87183cfd3a45fe";

function encryptWords(words) {
  const cipher = crypto.createCipheriv("aes-128-ecb", Buffer.from(AES_KEY, "utf8"), null);
  cipher.setAutoPadding(true);
  let encrypted = cipher.update(words, "utf8", "base64");
  encrypted += cipher.final("base64");
  return encrypted.replace(/\//g, "_").replace(/\+/g, "-");
}

function parseSetCookie(setCookieHeaders) {
  const lines = Array.isArray(setCookieHeaders)
    ? setCookieHeaders
    : setCookieHeaders
      ? [setCookieHeaders]
      : [];
  const jar = {};
  for (const line of lines) {
    const firstPart = line.split(";")[0];
    const eqIndex = firstPart.indexOf("=");
    if (eqIndex === -1) {
      continue;
    }
    const name = firstPart.slice(0, eqIndex).trim();
    const value = firstPart.slice(eqIndex + 1).trim();
    jar[name] = value;
  }
  return jar;
}

function buildCookieHeader(jar) {
  return Object.entries(jar)
    .map(([name, value]) => `${name}=${value}`)
    .join("; ");
}

function request({ method, path, headers = {}, body, retries = 2 }) {
  return new Promise((resolve, reject) => {
    const args = [
      "-sS",
      "-D",
      "-",
      "-X",
      method,
      `https://${BASE_HOST}${path}`,
      "-H",
      "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) Gecko/20100101 Firefox/135.0",
      "-H",
      "Accept: application/json, text/plain, */*",
      "-H",
      "Accept-Language: zh-CN,zh;q=0.5",
    ];

    for (const [key, value] of Object.entries(headers)) {
      args.push("-H", `${key}: ${value}`);
    }

    if (body) {
      args.push("--data", body);
    }

    execFile("/usr/bin/curl", args, { maxBuffer: 20 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error) {
        if (retries > 0) {
          resolve(request({ method, path, headers, body, retries: retries - 1 }));
          return;
        }
        reject(new Error(stderr || error.message));
        return;
      }

      const parts = stdout.split(/\r?\n\r?\n/);
      let headerBlock = "";
      let responseBody = "";

      for (let i = 0; i < parts.length; i += 1) {
        const chunk = parts[i];
        if (/^HTTP\/\d(?:\.\d)?\s+\d+/.test(chunk)) {
          headerBlock = chunk;
          responseBody = parts.slice(i + 1).join("\n\n");
        }
      }

      const headerLines = headerBlock.split(/\r?\n/);
      const statusLine = headerLines.shift() || "";
      const statusMatch = statusLine.match(/^HTTP\/\d(?:\.\d)?\s+(\d+)/);
      const parsedHeaders = {};

      for (const line of headerLines) {
        const idx = line.indexOf(":");
        if (idx === -1) {
          continue;
        }
        const key = line.slice(0, idx).trim().toLowerCase();
        const value = line.slice(idx + 1).trim();
        if (parsedHeaders[key]) {
          if (Array.isArray(parsedHeaders[key])) {
            parsedHeaders[key].push(value);
          } else {
            parsedHeaders[key] = [parsedHeaders[key], value];
          }
        } else {
          parsedHeaders[key] = value;
        }
      }

      resolve({
        statusCode: statusMatch ? Number(statusMatch[1]) : 0,
        headers: parsedHeaders,
        body: responseBody,
      });
    });
  });
}

async function bootstrapSession() {
  const homeRes = await request({
    method: "GET",
    path: "/index",
  });

  const jar = parseSetCookie(homeRes.headers["set-cookie"]);
  const homeCookie = buildCookieHeader(jar);

  const tokenRes = await request({
    method: "GET",
    path: "/fyzs-front-api/getToken",
    headers: {
      Referer: "https://dict.cnki.net/",
      Token: "undefined",
      Cookie: homeCookie,
    },
  });

  Object.assign(jar, parseSetCookie(tokenRes.headers["set-cookie"]));

  const tokenPayload = JSON.parse(tokenRes.body);
  if (!tokenPayload || tokenPayload.code !== 200 || !tokenPayload.data) {
    throw new Error(`bootstrap failed: invalid getToken response ${tokenRes.body}`);
  }

  jar.token = tokenPayload.data;
  return {
    jar,
    token: tokenPayload.data,
  };
}

async function literalTranslation(words, translateType = null, session = null) {
  const { jar, token } = session || await bootstrapSession();
  const cookie = buildCookieHeader(jar);
  const payload = JSON.stringify({
    words: encryptWords(words),
    translateType,
  });

  const res = await request({
    method: "POST",
    path: "/fyzs-front-api/translate/literaltranslation",
    headers: {
      "Content-Type": "application/json;charset=utf-8",
      "Content-Length": Buffer.byteLength(payload),
      Origin: "https://dict.cnki.net",
      Referer: "https://dict.cnki.net/index",
      Token: token,
      Cookie: cookie,
    },
    body: payload,
  });

  return JSON.parse(res.body);
}

async function queryTranslateData(words, session = null) {
  const { jar, token } = session || await bootstrapSession();
  const cookie = buildCookieHeader(jar);
  const payload = JSON.stringify({ words });

  const res = await request({
    method: "POST",
    path: "/fyzs-front-api/translate/querytranslatedate",
    headers: {
      "Content-Type": "application/json;charset=utf-8",
      "Content-Length": Buffer.byteLength(payload),
      Origin: "https://dict.cnki.net",
      Referer: "https://dict.cnki.net/index",
      Token: token,
      Cookie: cookie,
    },
    body: payload,
  });

  return JSON.parse(res.body);
}

async function main() {
  const words = process.argv[2] || "diabetes";
  const detail = process.argv.includes("--detail");
  const session = await bootstrapSession();

  const literal = await literalTranslation(words, null, session);
  console.log("literaltranslation:");
  console.log(JSON.stringify(literal, null, 2));

  if (detail) {
    const detailData = await queryTranslateData(words, session);
    console.log("\nquerytranslatedate:");
    console.log(JSON.stringify(detailData, null, 2));
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
