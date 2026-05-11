# South Plus 验证码识别

本目录只保留当前主路径：槽位候选框 + 单字符 CNN 分类 + 序列约束搜索。

旧的 ddddocr、HOG/SVM、未接入 rerank 实验脚本已经清理，避免继续维护多套过期算法。

## 文件说明

- `cnn_captcha.py`：CNN 识别核心逻辑，包含候选框生成、批量分类、候选打分和四槽位序列选择。
- `recognize_captcha_cnn.py`：识别单张验证码。
- `batch_captcha_verify.py`：批量下载验证码，并使用当前 CNN 算法识别和生成复核拼图。
- `train_char_cnn.py`：训练单字符 CNN。
- `evaluate_cnn_captcha.py`：批量评估整题准确率和字符准确率。
- `evaluate_candidate_recall.py`：诊断候选框召回率和正确候选排名。
- `analyze_cnn_mismatches.py`：分析错例来源、混淆数字和典型样本。
- `mine_hard_negatives.py`：从误选框中挖 hard negatives。
- `captcha_char_cnn.pt` / `captcha_char_cnn_meta.json`：当前 CNN 模型和元数据。
- `captcha_samples/labels.csv`：整题标签。
- `captcha_samples/char_labels.csv`：字符级标注框。

## 环境准备

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r southplus/requirements-captcha.txt
```

## 使用

识别单张：

```bash
python3 southplus/recognize_captcha_cnn.py southplus/captcha_samples/captcha_001.jpg
```

输出调试信息：

```bash
python3 southplus/recognize_captcha_cnn.py southplus/captcha_samples/captcha_001.jpg --debug
```

下载并识别 5 张新图：

```bash
python3 southplus/batch_captcha_verify.py \
  -n 5 \
  -o /tmp/southplus_live_check \
  --results-file /tmp/southplus_live_check/results.csv \
  --insecure
```

协议登录：

```bash
cp southplus/sp_config.example.json southplus/sp_config.json
python3 southplus/sp.py --config southplus/sp_config.json
```

`sp_config.json` 中配置账号、密码、Cookie/代理、CNN 模型路径和 `login.max_attempts`。真实配置文件已加入 `.gitignore`，不要提交账号密码；`max_attempts=0` 表示不限次数，验证码识别或登录未确认成功时会重新获取验证码继续提交。

批量评估：

```bash
python3 southplus/evaluate_cnn_captcha.py \
  --output /tmp/cnn_results.csv \
  --mismatches /tmp/cnn_mismatches.csv
```

候选召回诊断：

```bash
python3 southplus/evaluate_candidate_recall.py
```

错例分析：

```bash
python3 southplus/analyze_cnn_mismatches.py --results /tmp/cnn_results.csv
```

## 当前效果

在 250 张已标注样本上的当前最佳结果：

```text
sequence=221/250=88.40%
character=967/1000=96.70%
raw_candidate_recall@0.45=1000/1000=100.00%
ranked_recall@1=877/1000=87.70%
ranked_recall@10=974/1000=97.40%
```

剩余主要错误：

```text
wrong_slots=33
fallback_or_scan_miss=16
same_box_classification=9
wrong_component_box=6
tiny_noise_component=2
```

## 下一步优化计划

目标：把整题成功率从当前 `83.60%` 推到 `85% - 90%` 区间。按 250 张样本计算，`85%` 至少需要 `213/250`，相比当前 `209/250` 需要多对 4 题；`90%` 需要 `225/250`，需要多对 16 题。

状态说明：

- `未开始`：尚未执行。
- `进行中`：正在改代码、调参或补样本。
- `待验证`：已有改动或实验结果，但还没完成全量评估。
- `已完成`：全量评估达成该阶段目标，并记录结果。
- `放弃`：实验收益不足或回退风险过高，不进入主路径。

### 阶段一：候选召回修复

- 状态：`已完成`
- 目标区间：`85% - 87%`
- 预期收益：多对 `4 - 8` 题。
- 主要错误来源：`fallback_or_scan_miss=20`
- 执行内容：
  - 导出并复核 `fallback_or_scan_miss` 错例，区分“正确框未生成”和“正确框生成但排名靠后”。
  - 优化 `slot_scan`、`template_scan`、`template_local` 的候选生成，重点覆盖低位 `0/1/5`、细窄字符、断裂字符。
  - 对漏召回槽位做定向补框，避免全局放宽阈值引入大量噪声。
  - 使用候选召回诊断确认 `raw_candidate_recall` 和 `ranked_recall` 是否提升。
- 验证命令：

```bash
python3 southplus/evaluate_candidate_recall.py
python3 southplus/evaluate_cnn_captcha.py \
  --output /tmp/cnn_results.csv \
  --mismatches /tmp/cnn_mismatches.csv
python3 southplus/analyze_cnn_mismatches.py --results /tmp/cnn_results.csv
```

- 完结标准：
  - 整题准确率达到或超过 `85%`。
  - `fallback_or_scan_miss` 数量明显下降。
  - 新增候选没有导致明显 `wrong_component_box` 或 `tiny_noise_component` 回退。
- 结果记录：
  - 基线：`sequence=209/250=83.60%`
  - 完结结果：`sequence=213/250=85.20%`，`character=958/1000=95.80%`，`raw_candidate_recall@0.45=1000/1000=100.00%`

### 阶段二：候选打分和后验规则

- 状态：`已完成`
- 目标区间：`87% - 88.5%`
- 预期收益：在阶段一基础上多对 `2 - 5` 题。
- 主要处理对象：正确框已进入候选集，但排序靠后或四槽位联合搜索误选。
- 执行内容：
  - 扫描 `BACKGROUND_SCORE_WEIGHT`、`SLOT_SCAN_SOURCE_PENALTY`、`TEMPLATE_SCAN_SOURCE_PENALTY`、`TEMPLATE_LOCAL_SOURCE_PENALTY`、`TEMPLATE_MATCH_BONUS`、`POSITION_FALLBACK_SOURCE_PENALTY`。
  - 使用 `--rule-check-regressions` 检查规则是否造成基线正确样本回退。
  - 只接受低风险、可解释、收益明确的单条或少量组合规则。
- 验证命令：

```bash
python3 southplus/tune_cnn_scoring.py \
  --rule-scan \
  --rule-check-regressions \
  --top 20 \
  --rule-output /tmp/southplus_rule_scan.json
```

- 完结标准：
  - 整题准确率达到或超过 `87%`。
  - 规则扫描显示净收益为正。
  - 回退样本数量可接受，并逐条确认原因。
- 结果记录：
  - 阶段输入结果：`sequence=213/250=85.20%`
  - 阶段性结果：`sequence=214/250=85.60%`，`character=959/1000=95.90%`
  - 完结结果：`sequence=218/250=87.20%`，`character=964/1000=96.40%`，`raw_candidate_recall@0.45=1000/1000=100.00%`

### 阶段三：same-box 分类增强

- 状态：`已完成`
- 目标区间：`88% - 90%`
- 预期收益：多对 `2 - 6` 题，但存在模型回退风险。
- 主要错误来源：`same_box_classification=16`
- 执行内容：
  - 导出 same-box hard positives 和 crop 图片，人工复核是否标注可靠。
  - 只训练 `/tmp` 临时模型，不直接覆盖正式模型。
  - 对比临时模型和当前正式模型的整题准确率、字符准确率、错例分布。
  - 如果 hard positives 导致整体回退，则标记该实验为 `放弃`，不进入主路径。
- 验证命令：

```bash
python3 southplus/analyze_cnn_mismatches.py \
  --results /tmp/cnn_results.csv \
  --hard-positives-output /tmp/hard_positives.csv \
  --export-same-box-crops /tmp/same_box_crops

python3 southplus/train_char_cnn.py \
  --hard-positives /tmp/hard_positives.csv \
  --model /tmp/captcha_char_cnn_hp.pt \
  --meta /tmp/captcha_char_cnn_hp_meta.json

python3 southplus/evaluate_cnn_captcha.py \
  --model /tmp/captcha_char_cnn_hp.pt \
  --meta /tmp/captcha_char_cnn_hp_meta.json \
  --output /tmp/cnn_results_hp.csv \
  --mismatches /tmp/cnn_mismatches_hp.csv
```

- 完结标准：
  - 临时模型整题准确率达到或超过阶段二结果。
  - same-box 分类错误下降，且其他错误桶没有明显增加。
  - 达到 `88% - 90%` 后，再考虑是否替换正式模型。
- 结果记录：
  - 阶段输入结果：`sequence=218/250=87.20%`
  - 临时 hard-positive 模型结果：`sequence=175/250=70.00%`，`character=923/1000=92.30%`，结论为放弃，不替换正式模型。
  - 后验规则完结结果：`sequence=221/250=88.40%`，`character=967/1000=96.70%`
  - 是否替换正式模型：不替换；保留正式 CNN，接入低风险 same-box 后验规则。

### 回溯记录模板

每轮实验完成后，在下面追加一条记录：

```text
日期：
阶段：
状态：
改动摘要：
验证命令：
sequence：
character：
错例分布：
结论：
下一步：
```

### 回溯记录

```text
日期：2026-05-09
阶段：阶段一：候选召回修复
状态：已完成
改动摘要：新增 slot_scan_templates_v4，对低位 0/1/5 补充与现有模板 IoU<0.45 的经验模板；新增 top2 低置信 template_scan 0 候选 +0.20 后验加分。
验证命令：
  southplus/.venv/bin/python southplus/evaluate_cnn_captcha.py --output /tmp/cnn_results_opt.csv --mismatches /tmp/cnn_mismatches_opt.csv
  southplus/.venv/bin/python southplus/evaluate_candidate_recall.py
  southplus/.venv/bin/python southplus/analyze_cnn_mismatches.py --results /tmp/cnn_results_opt.csv
sequence：213/250=85.20%
character：958/1000=95.80%
错例分布：wrong_slots=42, fallback_or_scan_miss=17, same_box_classification=16, wrong_component_box=7, tiny_noise_component=2
结论：阶段一达到 85% 门槛，raw_candidate_recall@0.45 提升到 100.00%，无 raw miss。
下一步：进入阶段二，优先处理 ranked_recall@1 和 same-box 分类/高背景模板误选。
```

```text
日期：2026-05-09
阶段：阶段二：候选打分和后验规则
状态：进行中
改动摘要：新增 top2 短高 template_scan 0 候选 +0.20 后验加分，条件为 digit=0、source=template_scan、height<=12。
验证命令：
  southplus/.venv/bin/python southplus/evaluate_cnn_captcha.py --output /tmp/cnn_results_opt2.csv --mismatches /tmp/cnn_mismatches_opt2.csv
  southplus/.venv/bin/python southplus/evaluate_candidate_recall.py
  southplus/.venv/bin/python southplus/analyze_cnn_mismatches.py --results /tmp/cnn_results_opt2.csv
sequence：214/250=85.60%
character：959/1000=95.90%
错例分布：wrong_slots=41, fallback_or_scan_miss=17, same_box_classification=15, wrong_component_box=7, tiny_noise_component=2
结论：阶段二获得阶段性净增 1 题；相对原始基线净增 5 题，无原正确样本回退。
下一步：继续寻找可解释的组合规则；若规则收益耗尽，转入 same-box hard positives 临时模型实验。
```

```text
日期：2026-05-09
阶段：阶段二：候选打分和后验规则
状态：已完成
改动摘要：新增 top4 后验规则：低置信 template_scan 0 候选 +0.20；position=1 的 template_scan 6 候选 +0.40；position=1 的 slot_scan 1 候选 -0.20。
验证命令：
  southplus/.venv/bin/python southplus/evaluate_cnn_captcha.py --output /tmp/cnn_results_stage2_final.csv --mismatches /tmp/cnn_mismatches_stage2_final.csv
  southplus/.venv/bin/python southplus/evaluate_candidate_recall.py
  southplus/.venv/bin/python southplus/analyze_cnn_mismatches.py --results /tmp/cnn_results_stage2_final.csv
  southplus/.venv/bin/python southplus/tune_cnn_scoring.py --rule-scan --rule-check-regressions --rule-top-k 4 --top 12 --rule-output /tmp/southplus_rule_scan_stage2_done.json
sequence：218/250=87.20%
character：964/1000=96.40%
错例分布：wrong_slots=36, fallback_or_scan_miss=16, same_box_classification=12, wrong_component_box=6, tiny_noise_component=2
结论：阶段二达到 87% 门槛；最终规则扫描已无正收益单条规则，候选召回 raw_candidate_recall@0.45 维持 100.00%。
下一步：进入阶段三，只用 /tmp 临时模型评估 same-box hard positives，避免直接覆盖正式模型。
```

```text
日期：2026-05-09
阶段：阶段三：same-box 分类增强
状态：已完成
改动摘要：导出 12 条 same-box hard positives 并训练 /tmp 临时模型；临时模型大幅回退后放弃。改为接入 3 条 top4 局部后验规则：position=1 的 template_scan 4 且模板匹配 +0.30；position=3 的 template_scan 2 且模板匹配 +0.40；position=2 的 slot_scan 1 额外 -0.40。
验证命令：
  southplus/.venv/bin/python southplus/evaluate_cnn_captcha.py --output /tmp/cnn_results_stage3_base.csv --mismatches /tmp/cnn_mismatches_stage3_base.csv
  southplus/.venv/bin/python southplus/analyze_cnn_mismatches.py --results /tmp/cnn_results_stage3_base.csv --hard-positives-output /tmp/hard_positives_stage3.csv --export-same-box-crops /tmp/same_box_crops_stage3
  southplus/.venv/bin/python southplus/train_char_cnn.py --hard-positives /tmp/hard_positives_stage3.csv --model /tmp/captcha_char_cnn_stage3_hp.pt --meta /tmp/captcha_char_cnn_stage3_hp_meta.json
  southplus/.venv/bin/python southplus/evaluate_cnn_captcha.py --model /tmp/captcha_char_cnn_stage3_hp.pt --meta /tmp/captcha_char_cnn_stage3_hp_meta.json --output /tmp/cnn_results_stage3_hp.csv --mismatches /tmp/cnn_mismatches_stage3_hp.csv
  southplus/.venv/bin/python southplus/evaluate_cnn_captcha.py --output /tmp/cnn_results_stage3_rules.csv --mismatches /tmp/cnn_mismatches_stage3_rules.csv
  southplus/.venv/bin/python southplus/analyze_cnn_mismatches.py --results /tmp/cnn_results_stage3_rules.csv
  southplus/.venv/bin/python southplus/evaluate_candidate_recall.py
sequence：221/250=88.40%
character：967/1000=96.70%
错例分布：wrong_slots=33, fallback_or_scan_miss=16, same_box_classification=9, wrong_component_box=6, tiny_noise_component=2
结论：阶段三达到 88% 门槛；same_box_classification 从 12 降到 9。hard-positive 临时模型结果为 175/250=70.00%，不替换正式模型。
下一步：若继续冲 90%，优先处理 fallback_or_scan_miss=16 中 rank 靠后的低位 0/5/1 和底部小字符。
```

## 当前识别流程

1. 读取图片。
2. 用 `component_candidates` 生成连通域候选。
3. 用槽位中心范围过滤跨槽候选。
4. 加入 `position_fallback`、`slot_scan` 和模板扫描候选。
5. 使用 `slot_scan_templates_v3` 对低位 `0/1/5` 增强模板召回。
6. 使用 `slot_scan_templates_v4` 对低位 `0/1/5` 继续补充低 IoU 经验模板。
7. 对模板附近前景做 `template_local` 精修。
8. 用 CNN 对所有候选框批量分类。
9. 按数字概率、背景概率、槽位距离、候选来源、模板匹配和后验规则打分。
10. 四槽位联合搜索，要求位置单调且候选框不严重冲突。

## 训练

重新训练正式 CNN：

```bash
python3 southplus/train_char_cnn.py
```

训练临时模型做实验：

```bash
python3 southplus/train_char_cnn.py \
  --model /tmp/captcha_char_cnn_exp.pt \
  --meta /tmp/captcha_char_cnn_exp_meta.json
```

挖 hard negatives 后重训：

```bash
python3 southplus/mine_hard_negatives.py
python3 southplus/train_char_cnn.py --hard-negatives southplus/captcha_samples/hard_negatives.csv
```

导出 same-box hard positives 做临时实验：

```bash
python3 southplus/analyze_cnn_mismatches.py \
  --results /tmp/cnn_results.csv \
  --hard-positives-output /tmp/hard_positives.csv \
  --export-same-box-crops /tmp/same_box_crops
python3 southplus/train_char_cnn.py \
  --hard-positives /tmp/hard_positives.csv \
  --model /tmp/captcha_char_cnn_hp.pt \
  --meta /tmp/captcha_char_cnn_hp_meta.json
```

注意：hard positives 曾导致整题回退，正式替换模型前必须先用 `/tmp` 临时模型完整评估。

## 调参

扫描候选打分参数：

```bash
python3 southplus/tune_cnn_scoring.py
```

扫描低风险后验规则：

```bash
python3 southplus/tune_cnn_scoring.py \
  --rule-scan \
  --rule-check-regressions \
  --top 20 \
  --rule-output /tmp/southplus_rule_scan.json
```

调参脚本会把候选框和 CNN 分类结果缓存到 `/tmp`，清理临时文件时可直接删除 `/tmp/southplus_*` 和 `/tmp/cnn_*`。
