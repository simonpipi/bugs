# GIF 验证码识别使用说明

## 1. 生成预处理预览

```bash
python3 ' moxing/captcha_recognizer.py' preprocess
```

默认读取 ` moxing/captchas/*.gif`，输出到 ` moxing/captcha_preprocessed/*.png`。

可切换融合方式：

```bash
python3 ' moxing/captcha_recognizer.py' preprocess --method darkest
python3 ' moxing/captcha_recognizer.py' preprocess --method vote --binary
```

## 2. 标注验证码

```bash
python3 ' moxing/captcha_recognizer.py' init-labels --overwrite
```

编辑 ` moxing/labels.csv`，格式：

```csv
filename,label
captcha_001.gif,a7k2
captcha_002.gif,9m3x
```

默认字符集为数字和小写字母：

```text
0123456789abcdefghijklmnopqrstuvwxyz
```

也可以先生成放大的标注辅助图：

```bash
python3 ' moxing/captcha_recognizer.py' label-sheet
```

默认输出：

```text
 moxing/captcha_label_sheet.png
```

## 3. 训练模型

```bash
python3 ' moxing/captcha_recognizer.py' train --epochs 30 --batch-size 32
```

训练完成后默认保存模型到：

```text
 moxing/captcha_model.pt
```

如果验证码区分大小写，训练时传完整字符集：

```bash
python3 ' moxing/captcha_recognizer.py' train \
  --charset 0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ \
  --case-sensitive
```

样本较少时，可以先用全部标注样本拟合一个基线模型：

```bash
python3 ' moxing/captcha_recognizer.py' train --epochs 80 --batch-size 16 --val-ratio 0 --device cpu
```

## 4. 识别验证码

```bash
python3 ' moxing/captcha_recognizer.py' predict ' moxing/captchas/captcha_001.gif'
```

代码调用：

```python
from captcha_recognizer import predict_captcha

code = predict_captcha("captchas/captcha_001.gif")
print(code)
```

## 5. 评估模型

```bash
python3 ' moxing/captcha_recognizer.py' eval
```

错误样本会保存到：

```text
 moxing/captcha_errors.csv
```

## 6. 维护识别结果

启动本地维护页：

```bash
python3 ' moxing/captcha_recognizer.py' review
```

浏览器打开：

```text
http://127.0.0.1:8765/
```

页面里可以逐条修改验证码结果，勾选“识别错误”，并把修正内容保存到：

```text
 moxing/captcha_reviews.csv
```

导出可继续训练的标签文件：

```bash
python3 ' moxing/captcha_recognizer.py' export-reviewed-labels
```

默认输出到：

```text
 moxing/labels_reviewed.csv
```
