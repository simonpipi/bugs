# RabbitMQ 3.8.26 延迟消息迁移工具

这套工具用于迁移 RabbitMQ `3.8.26` 上 `x-delayed-message` 插件内部尚未触发的延迟消息。

目录说明：

- `export_delayed.escript`
  在旧 RabbitMQ 服务器本机执行，直接读取 delayed 插件的 Mnesia 表，导出为 `JSONL`。
- `replay_delayed.py`
  在可访问新 RabbitMQ 的机器上执行，读取导出结果并重发到新 RabbitMQ。
- `send_delayed_messages.py`
  向现有 delayed exchange 批量发送测试延迟消息，默认延迟 2 到 3 小时。
- `convert_delayed_tsv.py`
  将 `rabbitmqctl eval` 导出的 TSV 转成 `replay_delayed.py` 可直接使用的 JSONL。
- `inspect_delayed_jsonl.py`
  读取 JSONL 并将 `payload_base64` 解码成人类可读内容。
- `requirements.txt`
  Python 侧依赖，仅包含 `pika`。

## 边界

- 仅覆盖 `x-delayed-message` 插件内部延迟消息。
- 不覆盖普通队列里的堆积消息。
- 不覆盖镜像队列、仲裁队列、流队列的数据级迁移。
- 不直接解析 Mnesia 文件；导出依赖旧 RabbitMQ 节点仍然运行且插件仍可用。

## 前置条件

旧集群：

- RabbitMQ `3.8.26`
- 已启用 `rabbitmq_delayed_message_exchange`
- 迁移窗口内生产者和消费者全部下线
- 具备旧机器主机权限

新集群：

- 已安装兼容版本的 `rabbitmq_delayed_message_exchange`
- 已导入与旧集群一致的 definitions
- 延迟交换机名称、`x-delayed-type`、binding 拓扑与旧集群一致

## 迁移顺序

1. 在旧节点确认 delayed 插件仍处于启用状态。
2. 在新节点安装 delayed 插件并导入 definitions。
3. 在旧节点导出延迟消息。
4. 先做小批量回放验证。
5. 全量回放。
6. 对账通过后再切换业务连接。
7. 保留旧节点只读观察窗口，再退役。

## 旧节点预检

建议先在旧节点执行：

```bash
rabbitmq-plugins list -e | grep delayed
rabbitmqctl status
rabbitmqctl eval 'rabbit_delayed_message:table_name().'
rabbitmqctl eval 'rabbit_delayed_message:index_table_name().'
```

预期：

- delayed 插件已启用
- `rabbit_delayed_message:*` 模块可调用
- 可以拿到两张本地 Mnesia 表名

## 导出命令

先给脚本加执行权限：

```bash
chmod +x export_delayed.escript
```

在旧节点导出单个 vhost：

```bash
./export_delayed.escript \
  --node rabbit@old-host \
  --cookie 'YOUR_ERLANG_COOKIE' \
  --output /tmp/delayed-export.jsonl \
  --vhost /your_vhost
```

导出全部 vhost：

```bash
./export_delayed.escript \
  --node rabbit@old-host \
  --cookie 'YOUR_ERLANG_COOKIE' \
  --output /tmp/delayed-export.jsonl \
  --vhost all
```

说明：

- 脚本按 delayed 插件的 index 表顺序导出，近似按 `due_at_ms` 升序输出。
- 导出结果为 UTF-8 `JSONL`，每行一条消息。
- `payload_base64` 保存消息体，防止二进制内容损坏。
- `msg_id` 是迁移去重主键，由稳定字段计算得出。

## 回放准备

安装 Python 依赖：

```bash
python3 -m pip install -r requirements.txt
```

建议先使用测试 vhost 或测试新节点做 10 到 100 条样本演练。

## 只读容器导出后的格式转换

如果你是在只读容器里通过 `rabbitmqctl eval` 导出了 TSV，可以先在容器外转换成 JSONL：

```bash
python3 convert_delayed_tsv.py \
  --input delayed-node1.tsv \
  --output delayed-node1.jsonl
```

如果是多个节点，分别转换后再合并：

```bash
python3 convert_delayed_tsv.py --input delayed-node0.tsv --output delayed-node0.jsonl
python3 convert_delayed_tsv.py --input delayed-node1.tsv --output delayed-node1.jsonl
python3 convert_delayed_tsv.py --input delayed-node2.tsv --output delayed-node2.jsonl

cat delayed-node0.jsonl delayed-node1.jsonl delayed-node2.jsonl > delayed-all.jsonl
```

## 查看 JSONL 中的消息体

如果你想直接把 `payload_base64` 解码出来看内容：

```bash
python3 inspect_delayed_jsonl.py \
  --input delayed-node1.jsonl \
  --limit 5
```

如果只想按原始 UTF-8 文本输出，不做 JSON 美化：

```bash
python3 inspect_delayed_jsonl.py \
  --input delayed-node1.jsonl \
  --limit 5 \
  --raw
```

## 回放命令

```bash
python3 replay_delayed.py \
  --input /tmp/delayed-export.jsonl \
  --amqp-url 'amqp://user:password@new-host:5672/%2F' \
  --checkpoint /tmp/delayed-replay.sqlite3 \
  --vhost /your_vhost \
  --skew-guard-ms 2000
```

说明：

- `remaining_delay_ms = max(0, due_at_ms - now_ms - skew_guard_ms)`
- 回放时保持原 `exchange` 和 `routing_key`
- 保留原消息属性和业务 headers
- 覆盖 `x-delay` 为新的剩余延迟
- 开启 publisher confirms
- checkpoint 使用 SQLite，可断点续跑

如果导出文件中包含多个 vhost，`replay_delayed.py` 会根据每条记录的 `vhost` 自动重建连接 URL 的 vhost 路径。

## 生成测试延迟消息

如果你需要先造一批 2 到 3 小时的延迟消息，可以使用：

```bash
python3 send_delayed_messages.py \
  --host 127.0.0.1 \
  --port 5672 \
  --username guest \
  --password guest \
  --vhost kuke_test \
  --exchange kukecrms.exchange.business.delay \
  --routing-key kukecrms.key.business.customer_delay \
  --count 20
```

可选参数：

- `--min-delay-ms` 默认 `7200000`，即 2 小时
- `--max-delay-ms` 默认 `10800000`，即 3 小时
- `--seed` 可固定随机种子，便于复现
- 不建议对 `x-delayed-message` 的延迟发布使用 `--mandatory`，因为 broker 在延迟消息入库当下不会返回立即路由结果，客户端可能收到 `UnroutableError`

## 校验建议

小批量演练时：

- 抽样核对 `exchange`、`routing_key`、`headers`、`properties`、`payload_base64`
- 对比 `due_at_ms` 是否合理
- 验证新集群是否在接近目标时间时把消息路由到目标队列

全量迁移时：

- 导出总数 = `JSONL` 行数
- `JSONL` 行数 = publisher confirm 成功数 + checkpoint 中已确认总数
- checkpoint 中失败数必须为 `0`

可用 SQL 快速检查 checkpoint：

```sql
SELECT status, COUNT(*) FROM replay_checkpoint GROUP BY status;
```

## 回退与风险

- 不要在导出完成前禁用 delayed 插件。
- 不要在迁移窗口中恢复旧集群生产流量。
- 如果新集群 exchange 或 binding 不一致，`mandatory + publisher confirms` 会让回放脚本失败退出，不会静默吞掉不可路由消息。
- 如果脚本报 `unsupported delayed message shape`，说明现场 RabbitMQ/插件内部结构和 3.8.26 预期不一致，需要根据报出的 term 片段微调 `export_delayed.escript`。
