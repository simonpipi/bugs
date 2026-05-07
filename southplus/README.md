# South Plus 验证码识别说明

本目录包含 South Plus 数字验证码的本地识别、训练、评估和错例诊断脚本。当前主力方案是“槽位候选框 + 单字符 CNN 分类 + 序列约束搜索”，不依赖在线 OCR 服务。

## 目录结构

- `cnn_captcha.py`：CNN 识别核心逻辑，包含候选框生成、批量分类、几何 rerank、四槽位序列选择。
- `recognize_captcha_cnn.py`：识别单张验证码图片。
- `train_char_cnn.py`：用 `char_labels.csv` 训练单字符 CNN。
- `evaluate_cnn_captcha.py`：批量评估验证码整体准确率和字符准确率。
- `evaluate_candidate_recall.py`：诊断候选框召回率和正确候选排名。
- `analyze_cnn_mismatches.py`：分析最终错例来源、混淆数字和典型样本。
- `mine_hard_negatives.py`：从误选框中挖 hard negatives，作为背景类重训样本。
- `captcha_samples/labels.csv`：验证码整题标签。
- `captcha_samples/char_labels.csv`：字符级标注框。
- `captcha_char_cnn.pt` / `captcha_char_cnn_meta.json`：当前 CNN 模型和元数据。

## 环境准备

建议在虚拟环境中安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r southplus/requirements-captcha.txt
pip install opencv-python numpy
```

如果本机已有 `torch`、`cv2`、`numpy`，可以直接运行脚本。

## 快速使用

识别单张验证码：

```bash
python3 southplus/recognize_captcha_cnn.py southplus/captcha_samples/captcha_001.jpg
```

输出调试信息：

```bash
python3 southplus/recognize_captcha_cnn.py southplus/captcha_samples/captcha_001.jpg --debug
```

批量评估当前模型，推荐输出到 `/tmp`，避免覆盖工作区已有结果：

```bash
python3 southplus/evaluate_cnn_captcha.py \
  --output /tmp/cnn_results.csv \
  --mismatches /tmp/cnn_mismatches.csv
```

诊断候选框召回：

```bash
python3 southplus/evaluate_candidate_recall.py
```

分析错例：

```bash
python3 southplus/analyze_cnn_mismatches.py --results /tmp/cnn_results.csv
```

## 当前最终效果

在 200 张已标注样本上，当前版本验证结果：

```text
sequence: 137/200 = 68.50%
character: 729/800 = 91.12%
```

候选框诊断结果：

```text
raw_candidate_recall@0.45: 755/800 = 94.38%
ranked_recall@1:        672/800 = 84.00%
ranked_recall@3:        726/800 = 90.75%
ranked_recall@10:       737/800 = 92.12%
```

## 优化版本记录

### V0：早期传统方案

入口主要是 `recognize_captcha.py`、`recognize_captcha_svm.py` 和 SVM 相关脚本。

特点：

- 使用图像预处理、连通域和 HOG/SVM 单字符分类。
- 对粘连、噪声、小字符、位置漂移比较敏感。
- 更适合做基线和样本导出，不再是当前推荐主路径。

### V1：槽位 CNN 基线

核心改动：

- 使用 `SlotCharCNN` 做单字符分类。
- 每个验证码拆成 4 个槽位，各槽位生成候选框。
- 候选来源包括 `component`、`slot_scan`、`position_fallback`。
- 通过 `select_best_sequence` 做四槽位单调位置约束，避免选到重叠框或乱序框。

主要问题：

- 正确框经常没有进入候选集。
- 小 `1`、低位 `0/5`、大框误选较多。
- 单纯调 `slot_scan` 惩罚或给 `component` 加分没有稳定收益。

参数验证结论：

```text
baseline: 102/200 = 51.00%, character 676/800 = 84.50%
提高 slot_scan penalty: 无稳定提升，通常下降
component 小加分: 最多只提升 1 个字符，不提升整题
```

### V2：多模板候选增强

当前主版本。

核心改动在 `cnn_captcha.py`：

- 新增 `compute_slot_scan_templates_v2`。
- 对每个 `position + digit` 从字符标注分布中取多个代表框，而不是只取一个中位模板。
- 模板按 `y/x` 排序后取首位、中位、末位，样本足够时再取四分位点。
- 加载旧 `captcha_char_cnn_meta.json` 时，如果缺少 `slot_scan_templates_v2`，会从 `char_labels.csv` 即时计算，不需要重训模型。
- 识别时优先使用 `slot_scan_templates_v2`，旧字段 `slot_scan_templates` 作为 fallback。

收益：

```text
raw_candidate_recall@0.45: 83.25% -> 94.38%
ranked_recall@1:          73.12% -> 84.00%
sequence:                 102/200 -> 137/200
character:                676/800 -> 729/800
```

### V2.1：模板源打分微调

在 v2 候选增强后，重新验证模板源参数：

```python
TEMPLATE_SCAN_SOURCE_PENALTY = 0.30
TEMPLATE_MATCH_BONUS = 0.10
TEMPLATE_MISMATCH_PENALTY = 0.05
```

对比 v2 初始参数：

```text
v2 初始: sequence 136/200, character 727/800
v2.1:    sequence 137/200, character 729/800
```

这个收益不大，但没有观察到回退样本，因此保留。

## 当前识别流程

1. 读取图片。
2. 用 `component_candidates` 生成连通域候选。
3. 用槽位中心范围过滤跨槽候选。
4. 加入 `position_fallback` 和若干 `slot_scan` 扫描框。
5. 加入 `slot_scan_templates_v2` 模板候选。
6. 用 CNN 对所有候选框批量分类。
7. 对每个候选按以下因素打分：
   - 数字概率
   - 背景类概率惩罚
   - 槽位中心距离惩罚
   - 来源优先级惩罚
   - 模板数字匹配加分或不匹配惩罚
   - 数字框宽高几何先验
8. 四个槽位联合搜索，要求位置单调且候选框不严重冲突。

## 训练流程

重新训练 CNN：

```bash
python3 southplus/train_char_cnn.py
```

常用参数：

```bash
python3 southplus/train_char_cnn.py \
  --epochs 35 \
  --batch-size 64 \
  --lr 1e-3 \
  --negative-per-file 8
```

训练会写入：

- `southplus/captcha_char_cnn.pt`
- `southplus/captcha_char_cnn_meta.json`

如需加入 hard negatives：

```bash
python3 southplus/mine_hard_negatives.py
python3 southplus/train_char_cnn.py --hard-negatives southplus/captcha_samples/hard_negatives.csv
```

## 错例分析

当前最终版剩余错位：

```text
wrong_slots: 71
fallback_or_scan_miss: 38
same_box_classification: 26
tiny_noise_component: 5
wrong_component_box: 2
```

高频混淆：

```text
3 -> 9: 10
5 -> 0: 8
5 -> 1: 6
1 -> 9: 6
0 -> 9: 5
5 -> 9: 5
7 -> 9: 5
```

这说明候选框问题已经明显减少，下一步收益主要来自两类方向：

- 继续提高模板候选精度，减少 `template_scan` 大框/错位框。
- 针对 `3/5/0/1/7/9` 做 hard example 重训或更细的后验校正。

## 建议的下一步优化

1. 导出最终错例中的 `same_box_classification` crop，补充到训练集或单独做 hard example 微调。
2. 对 `template_scan` 增加更细的局部搜索，而不是直接复用标注代表框。
3. 对 `1` 类加入更强的窄框先验，避免被大模板或背景小竖线干扰。
4. 把 `evaluate_candidate_recall.py` 作为每次候选改动后的第一道验证，先确认候选召回和排名，再跑整题评估。

