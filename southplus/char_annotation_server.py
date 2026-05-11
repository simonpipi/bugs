#!/usr/bin/env python3
import csv
import json
import mimetypes
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


BASE_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = BASE_DIR / "captcha_samples"
LABELS_CSV = SAMPLES_DIR / "labels.csv"
CHAR_LABELS_CSV = SAMPLES_DIR / "char_labels.csv"


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Captcha Char Annotation</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #161616; background: #f5f5f3; }
    main { display: grid; grid-template-columns: 280px 1fr; min-height: 100vh; }
    aside { border-right: 1px solid #d7d7d2; background: #fff; padding: 12px; overflow: auto; max-height: 100vh; }
    .toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
    .toolbar input { width: 100%; padding: 8px; border: 1px solid #bbb; border-radius: 6px; }
    .list { display: grid; gap: 4px; }
    .item { display: grid; grid-template-columns: 56px 1fr 28px; align-items: center; gap: 8px; padding: 7px 8px; border-radius: 6px; cursor: pointer; }
    .item:hover { background: #f0f0ec; }
    .item.active { background: #dfe9ff; }
    .item.done .status { color: #157347; }
    .item .file { font-variant-numeric: tabular-nums; }
    section { padding: 20px; overflow: auto; }
    .top { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 14px; }
    .title { font-size: 22px; font-weight: 700; margin-right: 12px; }
    .label-input { width: 120px; font-size: 20px; font-weight: 700; letter-spacing: 4px; padding: 5px 10px; background: #fff; border: 1px solid #d0d0ca; border-radius: 6px; }
    button { padding: 8px 12px; border: 1px solid #aaa; border-radius: 6px; background: #fff; cursor: pointer; }
    button:hover { background: #f1f1ed; }
    button.primary { color: #fff; border-color: #1761d1; background: #1761d1; }
    button.primary:hover { background: #0f55bf; }
    .stage-wrap { display: inline-block; background: #fff; border: 1px solid #ccc; padding: 12px; border-radius: 8px; }
    canvas { display: block; width: 750px; height: 300px; image-rendering: pixelated; cursor: crosshair; }
    .boxes { display: grid; grid-template-columns: repeat(4, minmax(130px, 1fr)); gap: 8px; margin-top: 12px; max-width: 750px; }
    .box-card { background: #fff; border: 1px solid #d0d0ca; border-radius: 6px; padding: 8px; cursor: pointer; }
    .box-card.active { outline: 2px solid #1761d1; }
    .digit { font-size: 18px; font-weight: 700; }
    .coords { color: #666; font-size: 12px; margin-top: 4px; font-variant-numeric: tabular-nums; }
    .hint { margin-top: 12px; color: #555; line-height: 1.6; max-width: 760px; }
    .warn { color: #b00020; }
  </style>
</head>
<body>
<main>
  <aside>
    <div class="toolbar"><input id="filter" placeholder="过滤编号或文件名"></div>
    <div id="summary"></div>
    <div id="list" class="list"></div>
  </aside>
  <section>
    <div class="top">
      <div class="title" id="title">加载中</div>
      <input id="labelInput" class="label-input" maxlength="4" inputmode="numeric" pattern="[0-9]*" placeholder="4位">
      <button id="prev">上一张</button>
      <button id="next">下一张</button>
      <button id="clear">清空本张</button>
      <button id="save" class="primary">保存并下一张</button>
    </div>
    <div class="stage-wrap">
      <canvas id="canvas" width="750" height="300"></canvas>
    </div>
    <div class="boxes" id="boxes"></div>
    <div class="hint">
      拖拽画框，按 <b>1-4</b> 切换当前字符位，<b>Enter</b> 保存并下一张，<b>Backspace</b> 删除当前框。
      框尽量贴住真实数字笔画，包含干扰线没关系，但不要把相邻数字圈进去。
    </div>
  </section>
</main>
<script>
const scale = 5;
const colors = ["#e53935", "#1e88e5", "#43a047", "#8e24aa"];
let images = [];
let current = 0;
let currentPos = 0;
let img = new Image();
let boxes = [null, null, null, null];
let drag = null;
let dirty = false;
let saveTimer = null;
let loading = false;
let currentFile = "";

const $ = (id) => document.getElementById(id);
const canvas = $("canvas");
const ctx = canvas.getContext("2d");

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}

function naturalPoint(evt) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(150, (evt.clientX - rect.left) / rect.width * 150)),
    y: Math.max(0, Math.min(60, (evt.clientY - rect.top) / rect.height * 60)),
  };
}

function normalizeBox(a, b) {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  const w = Math.abs(a.x - b.x);
  const h = Math.abs(a.y - b.y);
  if (w < 1 || h < 1) return null;
  return { x: Math.round(x), y: Math.round(y), w: Math.round(w), h: Math.round(h) };
}

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (img.complete && img.naturalWidth) ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  boxes.forEach((box, i) => {
    if (!box) return;
    ctx.strokeStyle = colors[i];
    ctx.lineWidth = i === currentPos ? 4 : 2;
    ctx.strokeRect(box.x * scale, box.y * scale, box.w * scale, box.h * scale);
    ctx.fillStyle = colors[i];
    ctx.fillRect(box.x * scale, box.y * scale - 20, 28, 20);
    ctx.fillStyle = "#fff";
    ctx.font = "14px monospace";
    ctx.fillText(`${i + 1}:${digitFor(i)}`, box.x * scale + 4, box.y * scale - 5);
  });
  if (drag) {
    const box = normalizeBox(drag.start, drag.end);
    if (box) {
      ctx.setLineDash([8, 5]);
      ctx.strokeStyle = colors[currentPos];
      ctx.lineWidth = 2;
      ctx.strokeRect(box.x * scale, box.y * scale, box.w * scale, box.h * scale);
      ctx.setLineDash([]);
    }
  }
  renderBoxCards();
}

function digitFor(pos) {
  const label = currentLabel();
  return label[pos] || "";
}

function currentLabel() {
  return ($("labelInput").value || "").replace(/\D+/g, "").slice(0, 4);
}

function renderBoxCards() {
  $("boxes").innerHTML = boxes.map((box, i) => {
    const text = box ? `x=${box.x}, y=${box.y}, w=${box.w}, h=${box.h}` : "未标注";
    return `<div class="box-card ${i === currentPos ? "active" : ""}" data-pos="${i}">
      <div class="digit">${i + 1}: ${digitFor(i) || "?"}</div>
      <div class="coords">${text}</div>
    </div>`;
  }).join("");
  document.querySelectorAll(".box-card").forEach(el => {
    el.onclick = () => { currentPos = Number(el.dataset.pos); draw(); };
  });
}

function renderList() {
  const query = $("filter").value.trim();
  const done = images.filter(item => item.done).length;
  $("summary").innerHTML = `<p>已标注 ${done}/${images.length}</p>`;
  $("list").innerHTML = images.map((item, idx) => {
    if (query && !item.file.includes(query) && !String(item.index).includes(query)) return "";
    return `<div class="item ${idx === current ? "active" : ""} ${item.done ? "done" : ""}" data-idx="${idx}">
      <span class="file">${String(item.index).padStart(3, "0")}</span>
      <span>${item.label || "<span class='warn'>无 label</span>"}</span>
      <span class="status">${item.done ? "ok" : ""}</span>
    </div>`;
  }).join("");
  document.querySelectorAll(".item").forEach(el => {
    el.onclick = () => loadImage(Number(el.dataset.idx));
  });
}

async function loadImage(idx) {
  if (loading) return;
  if (dirty) await saveSnapshot(currentFile, boxes);
  loading = true;
  current = Math.max(0, Math.min(images.length - 1, idx));
  const item = images[current];
  currentFile = item.file;
  $("title").textContent = `${String(item.index).padStart(3, "0")} ${item.file}`;
  $("labelInput").value = item.label || "";
  boxes = [null, null, null, null];
  const ann = await api(`/api/annotation?file=${encodeURIComponent(item.file)}`);
  ann.boxes.forEach(b => { boxes[b.pos] = { x: b.x, y: b.y, w: b.w, h: b.h }; });
  currentPos = boxes.findIndex(b => !b);
  if (currentPos < 0) currentPos = 0;
  img = new Image();
  img.onload = () => { draw(); loading = false; };
  img.src = `/images/${encodeURIComponent(item.file)}?t=${Date.now()}`;
  renderList();
}

async function saveCurrent(goNext = true) {
  if (!images[current]) return;
  const item = images[current];
  await saveSnapshot(item.file, boxes);
  if (goNext) loadImage(current + 1);
}

async function saveSnapshot(file, snapshotBoxes) {
  if (!file) return;
  const item = images.find(row => row.file === file);
  const label = file === currentFile ? currentLabel() : (item?.label || "");
  const payload = {
    file,
    label,
    boxes: snapshotBoxes.map((box, pos) => box ? ({ ...box, pos, digit: label[pos] || "" }) : null).filter(Boolean),
  };
  const result = await api("/api/annotation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (item) {
    item.label = result.label || label;
    item.done = payload.boxes.length === 4 && item.label.length === 4;
  }
  if (file === currentFile) dirty = false;
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  renderList();
}

function markDirty() {
  dirty = true;
  const file = currentFile;
  const snapshot = boxes.map(box => box ? ({ ...box }) : null);
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => saveSnapshot(file, snapshot), 150);
}

canvas.addEventListener("mousedown", evt => {
  drag = { start: naturalPoint(evt), end: naturalPoint(evt) };
  draw();
});
canvas.addEventListener("mousemove", evt => {
  if (!drag) return;
  drag.end = naturalPoint(evt);
  draw();
});
window.addEventListener("mouseup", () => {
  if (!drag) return;
  const box = normalizeBox(drag.start, drag.end);
  if (box) {
    boxes[currentPos] = box;
    currentPos = Math.min(3, currentPos + 1);
    markDirty();
    saveSnapshot(currentFile, boxes.map(box => box ? ({ ...box }) : null));
  }
  drag = null;
  draw();
});

window.addEventListener("keydown", evt => {
  if (evt.target && evt.target.tagName === "INPUT") {
    if (evt.key === "Enter") {
      evt.preventDefault();
      saveCurrent(true);
    }
    return;
  }
  if (evt.key >= "1" && evt.key <= "4") {
    currentPos = Number(evt.key) - 1;
    draw();
  } else if (evt.key === "Enter") {
    evt.preventDefault();
    saveCurrent(true);
  } else if (evt.key === "Backspace") {
    evt.preventDefault();
    boxes[currentPos] = null;
    markDirty();
    saveSnapshot(currentFile, boxes.map(box => box ? ({ ...box }) : null));
    draw();
  } else if (evt.key === "ArrowRight") {
    loadImage(current + 1);
  } else if (evt.key === "ArrowLeft") {
    loadImage(current - 1);
  }
});

$("prev").onclick = () => loadImage(current - 1);
$("next").onclick = () => loadImage(current + 1);
$("clear").onclick = () => {
  boxes = [null, null, null, null];
  currentPos = 0;
  markDirty();
  saveSnapshot(currentFile, boxes.map(box => box ? ({ ...box }) : null));
  draw();
};
$("save").onclick = () => saveCurrent(true);
$("filter").oninput = renderList;
$("labelInput").addEventListener("input", () => {
  const normalized = currentLabel();
  if ($("labelInput").value !== normalized) $("labelInput").value = normalized;
  if (images[current]) images[current].label = normalized;
  markDirty();
  draw();
});

window.addEventListener("beforeunload", () => {
  if (!dirty || !currentFile) return;
  const item = images.find(row => row.file === currentFile);
  const label = currentLabel() || item?.label || "";
  const payload = JSON.stringify({
    file: currentFile,
    label,
    boxes: boxes.map((box, pos) => box ? ({ ...box, pos, digit: label[pos] || "" }) : null).filter(Boolean),
  });
  navigator.sendBeacon("/api/annotation", new Blob([payload], { type: "application/json" }));
});

api("/api/images").then(data => {
  images = data.images;
  renderList();
  loadImage(0);
}).catch(err => {
  $("title").textContent = "加载失败";
  $("labelInput").value = "";
  alert(err.message);
});
</script>
</body>
</html>
"""


def clean_digit(value):
    return re.sub(r"\D+", "", (value or "").strip())


def read_labels():
    labels = {}
    if not LABELS_CSV.exists():
        return labels
    with LABELS_CSV.open(newline="", encoding="utf-8-sig") as fp:
        for row in csv.DictReader(fp):
            file_name = row.get("file", "")
            if file_name:
                labels[file_name] = clean_digit(row.get("label"))
    return labels


def read_label_rows():
    default_fieldnames = [
        "index",
        "file",
        "result",
        "whole",
        "segment",
        "raw",
        "boxes",
        "ok",
        "content_type",
        "size",
        "url",
        "error",
        "label",
    ]
    if not LABELS_CSV.exists():
        return default_fieldnames, []
    with LABELS_CSV.open(newline="", encoding="utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        return reader.fieldnames or default_fieldnames, list(reader)


def write_label(file_name, label):
    label = clean_digit(label)[:4]
    fieldnames, rows = read_label_rows()
    if "label" not in fieldnames:
        fieldnames.append("label")
    if "file" not in fieldnames:
        fieldnames.insert(0, "file")
    if "index" not in fieldnames:
        fieldnames.insert(0, "index")

    target = None
    for row in rows:
        if row.get("file") == file_name:
            target = row
            break
    if target is None:
        match = re.search(r"(\d+)", Path(file_name).stem)
        target = {key: "" for key in fieldnames}
        target["index"] = str(int(match.group(1))) if match else ""
        target["file"] = file_name
        rows.append(target)
    target["label"] = label

    rows.sort(key=lambda row: int(row.get("index") or 0))
    if LABELS_CSV.exists():
        backup_path = LABELS_CSV.with_suffix(".csv.bak")
        backup_path.write_text(LABELS_CSV.read_text(encoding="utf-8"), encoding="utf-8")
    with LABELS_CSV.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return label


def read_char_labels():
    annotations = {}
    if not CHAR_LABELS_CSV.exists():
        return annotations
    with CHAR_LABELS_CSV.open(newline="", encoding="utf-8-sig") as fp:
        for row in csv.DictReader(fp):
            file_name = row.get("file", "")
            if not file_name or not re.fullmatch(r"captcha_\d{3}\.jpg", file_name):
                continue
            annotations.setdefault(file_name, [])
            annotations[file_name].append(
                {
                    "file": file_name,
                    "pos": int(row.get("pos", 0)),
                    "x": int(row.get("x", 0)),
                    "y": int(row.get("y", 0)),
                    "w": int(row.get("w", 0)),
                    "h": int(row.get("h", 0)),
                    "digit": clean_digit(row.get("digit"))[:1],
                }
            )
    for boxes in annotations.values():
        boxes.sort(key=lambda item: item["pos"])
    return annotations


def write_char_labels(annotations):
    fieldnames = ["file", "pos", "x", "y", "w", "h", "digit"]
    if CHAR_LABELS_CSV.exists():
        backup_path = CHAR_LABELS_CSV.with_suffix(".csv.bak")
        backup_path.write_text(CHAR_LABELS_CSV.read_text(encoding="utf-8"), encoding="utf-8")
    with CHAR_LABELS_CSV.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for file_name in sorted(annotations):
            for row in sorted(annotations[file_name], key=lambda item: item["pos"]):
                output = dict(row)
                output["file"] = file_name
                writer.writerow(output)


class Handler(BaseHTTPRequestHandler):
    server_version = "CaptchaAnnotator/1.0"

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, status=200, content_type="text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_text(INDEX_HTML, content_type="text/html; charset=utf-8")
            return
        if parsed.path == "/api/images":
            labels = read_labels()
            annotations = read_char_labels()
            images = []
            for image_path in sorted(SAMPLES_DIR.glob("captcha_*.jpg")):
                match = re.search(r"(\d+)", image_path.stem)
                index = int(match.group(1)) if match else 0
                boxes = annotations.get(image_path.name, [])
                images.append(
                    {
                        "index": index,
                        "file": image_path.name,
                        "label": labels.get(image_path.name, ""),
                        "done": len(boxes) == 4 and len(labels.get(image_path.name, "")) == 4,
                    }
                )
            self.send_json({"images": images})
            return
        if parsed.path == "/api/annotation":
            file_name = parse_qs(parsed.query).get("file", [""])[0]
            annotations = read_char_labels()
            self.send_json({"boxes": annotations.get(file_name, [])})
            return
        if parsed.path.startswith("/images/"):
            file_name = unquote(parsed.path[len("/images/") :])
            image_path = (SAMPLES_DIR / file_name).resolve()
            if image_path.parent != SAMPLES_DIR.resolve() or not image_path.exists():
                self.send_error(404)
                return
            content_type = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
            data = image_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/annotation":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        file_name = payload.get("file", "")
        if not re.fullmatch(r"captcha_\d{3}\.jpg", file_name):
            self.send_json({"error": "文件名无效"}, status=400)
            return
        image_path = (SAMPLES_DIR / file_name).resolve()
        if image_path.parent != SAMPLES_DIR.resolve() or not image_path.exists():
            self.send_json({"error": "图片不存在"}, status=400)
            return
        labels = read_labels()
        payload_label = clean_digit(payload.get("label"))[:4]
        label = write_label(file_name, payload_label) if "label" in payload else labels.get(file_name, "")
        rows = []
        for item in payload.get("boxes", []):
            pos = int(item.get("pos", 0))
            if pos < 0 or pos > 3:
                continue
            digit = clean_digit(item.get("digit"))[:1] or (label[pos : pos + 1] if pos < len(label) else "")
            rows.append(
                {
                    "file": file_name,
                    "pos": pos,
                    "x": int(round(float(item.get("x", 0)))),
                    "y": int(round(float(item.get("y", 0)))),
                    "w": int(round(float(item.get("w", 0)))),
                    "h": int(round(float(item.get("h", 0)))),
                    "digit": digit,
                }
            )
        rows.sort(key=lambda row: row["pos"])
        annotations = read_char_labels()
        annotations[file_name] = rows
        write_char_labels(annotations)
        self.send_json({"ok": True, "saved": len(rows), "label": label})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    if not SAMPLES_DIR.exists():
        print(f"样本目录不存在: {SAMPLES_DIR}", file=sys.stderr)
        return 2
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"标注工具: http://127.0.0.1:{port}")
    print(f"输出文件: {CHAR_LABELS_CSV}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
