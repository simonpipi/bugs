# RabbitMQ 延迟消息迁移使用文档

本文档说明如何把旧 RabbitMQ `x-delayed-message` 插件中的未触发延迟消息导出、转换、检查，并重放到新的 RabbitMQ 服务器。

适用场景：

- 旧 RabbitMQ 使用 `x-delayed-message`
- 旧环境是容器，且容器文件系统只读
- 只能通过 `rabbitmqctl eval` 读取 delayed 插件内部表
- 需要把消息迁移到另一个 RabbitMQ 服务器

## 目录

- [前提条件](#前提条件)
- [整体流程](#整体流程)
- [步骤 1：确认旧节点 delayed 表可读](#步骤-1确认旧节点-delayed-表可读)
- [步骤 2：从旧节点导出 TSV](#步骤-2从旧节点导出-tsv)
- [步骤 3：将 TSV 转换成 JSONL](#步骤-3将-tsv-转换成-jsonl)
- [步骤 4：检查 JSONL 中的消息体](#步骤-4检查-jsonl-中的消息体)
- [步骤 5：重放到新的 RabbitMQ](#步骤-5重放到新的-rabbitmq)
- [集群场景调用顺序](#集群场景调用顺序)
- [常见问题](#常见问题)

## 前提条件

旧集群：

- RabbitMQ 使用 `x-delayed-message`
- 旧环境中生产者和消费者已经下线
- 可以执行 `rabbitmqctl eval`
- 可以通过 `kubectl exec` 或等价方式进入每个 RabbitMQ Pod/容器

新集群：

- 已安装 `rabbitmq_delayed_message_exchange`
- 已创建目标 `vhost`
- 已导入正确的 `exchange / queue / binding`
- 延迟交换机和绑定关系与旧集群兼容

本地或跳板机：

- 有 Python 3
- 安装了 `pika`

安装依赖：

```bash
cd /Users/chenmingbo/Desktop/bugs/rabbitmq_delay_migration
python3 -m pip install -r requirements.txt
```

## 整体流程

建议固定按以下顺序执行：

1. 在旧集群每个节点上确认 delayed 表是否可读
2. 使用 `rabbitmqctl eval` 从每个节点导出 TSV
3. 将每个节点的 TSV 转成 JSONL
4. 抽样检查 JSONL 中的消息体
5. 将 JSONL 重放到新 RabbitMQ
6. 校验 checkpoint 和重放结果

如果是 RabbitMQ 集群，不要只导一个节点。`x-delayed-message` 的内部存储是节点本地的，必须逐节点导出。

## 步骤 1：确认旧节点 delayed 表可读

进入旧 RabbitMQ Pod/容器后先执行：

```bash
rabbitmqctl eval '
N = node(),
T = list_to_atom(atom_to_list(rabbit_delayed_message) ++ atom_to_list(N)),
io:format("table=~p size=~p~n", [T, mnesia:table_info(T, size)]).
'
```

示例输出：

```text
table='rabbit_delayed_messagerabbit@kuke-rabbitmq-server-1.kuke-rabbitmq-nodes.software' size=10
ok
```

说明：

- `size=0` 表示该节点没有待触发 delayed 消息
- `size>0` 表示该节点有可导出的 delayed 消息

## 步骤 2：从旧节点导出 TSV

推荐导出完整格式 TSV，保留消息体、完整 headers 和完整 properties。

先在本地终端准备导出表达式：

```bash
CMD=$(cat <<'EOF'
N = node(),
T = list_to_atom(atom_to_list(rabbit_delayed_message) ++ atom_to_list(N)),
I = list_to_atom(atom_to_list(rabbit_delayed_message) ++ atom_to_list(N) ++ "_index"),
Keys = mnesia:dirty_all_keys(I),
lists:foreach(
  fun(Key) ->
    lists:foreach(
      fun({delay_entry,
            {delay_key, DueAtMs,
              {exchange,{resource,VHost,exchange,Exchange},_,_,_,_,_,_,_,_,_,_}},
            {delivery,_,_,_,
              {basic_message,_,RoutingKeys,
                {content,_,
                  Props = {'P_basic', _, _, Headers, _, _, _, _, _, MessageId, Timestamp, _, _, _, _},
                  _,_, PayloadRev},
                _,_},
              _,_},
            _Ref}) ->
              RoutingKey = case RoutingKeys of [RK | _] -> RK; [] -> <<>> end,
              Payload = iolist_to_binary(lists:reverse(PayloadRev)),
              HeadersBin = term_to_binary(Headers),
              PropsBin = term_to_binary(Props),
              io:format("~B\t~ts\t~ts\t~ts\t~ts\t~p\t~ts\t~ts\t~ts~n",
                [DueAtMs,
                 VHost,
                 Exchange,
                 RoutingKey,
                 MessageId,
                 Timestamp,
                 base64:encode(Payload),
                 base64:encode(HeadersBin),
                 base64:encode(PropsBin)]);
         (_) ->
              ok
      end,
      mnesia:dirty_read(T, Key))
  end,
  Keys
).
EOF
)
```

然后对单个节点导出：

```bash
kubectl exec -n software kuke-rabbitmq-server-1 -- rabbitmqctl eval "$CMD" | sed '/^ok$/d' > delayed-node1-full.tsv
```

字段顺序如下：

1. `due_at_ms`
2. `vhost`
3. `exchange`
4. `routing_key`
5. `message_id`
6. `timestamp`
7. `payload_base64`
8. `headers_term_base64`
9. `properties_term_base64`

检查导出条数：

```bash
wc -l delayed-node1-full.tsv
```

## 步骤 3：将 TSV 转换成 JSONL

使用 [convert_delayed_tsv.py](/Users/chenmingbo/Desktop/bugs/rabbitmq_delay_migration/convert_delayed_tsv.py)：

```bash
cd /Users/chenmingbo/Desktop/bugs/rabbitmq_delay_migration

python3 convert_delayed_tsv.py \
  --input delayed-node1-full.tsv \
  --output delayed-node1.jsonl
```

说明：

- 脚本同时支持 8 列和 9 列 TSV
- 9 列 TSV 会保留完整的 `headers_term_base64` 和 `properties_term_base64`
- 输出结果可直接交给 `replay_delayed.py`

如果是多节点：

```bash
python3 convert_delayed_tsv.py --input delayed-node0-full.tsv --output delayed-node0.jsonl
python3 convert_delayed_tsv.py --input delayed-node1-full.tsv --output delayed-node1.jsonl
python3 convert_delayed_tsv.py --input delayed-node2-full.tsv --output delayed-node2.jsonl
```

合并：

```bash
cat delayed-node0.jsonl delayed-node1.jsonl delayed-node2.jsonl > delayed-all.jsonl
```

## 步骤 4：检查 JSONL 中的消息体

使用 [inspect_delayed_jsonl.py](/Users/chenmingbo/Desktop/bugs/rabbitmq_delay_migration/inspect_delayed_jsonl.py)：

```bash
python3 inspect_delayed_jsonl.py \
  --input delayed-node1.jsonl \
  --limit 5
```

如果只看原始 UTF-8 文本：

```bash
python3 inspect_delayed_jsonl.py \
  --input delayed-node1.jsonl \
  --limit 5 \
  --raw
```

这一步的目的：

- 验证 `payload_base64` 可以正常解码
- 确认消息体内容和业务预期一致
- 在真正回放前抽样核对消息

## 步骤 5：重放到新的 RabbitMQ

使用 [replay_delayed.py](/Users/chenmingbo/Desktop/bugs/rabbitmq_delay_migration/replay_delayed.py)：

```bash
python3 replay_delayed.py \
  --input delayed-node1.jsonl \
  --amqp-url 'amqp://用户名:密码@新RabbitMQ地址:5672/kuke_test' \
  --checkpoint /tmp/delayed-replay.sqlite3 \
  --vhost kuke_test \
  --skew-guard-ms 2000
```

如果是多节点合并后的文件：

```bash
python3 replay_delayed.py \
  --input delayed-all.jsonl \
  --amqp-url 'amqp://用户名:密码@新RabbitMQ地址:5672/%2F' \
  --checkpoint /tmp/delayed-replay.sqlite3 \
  --vhost all \
  --skew-guard-ms 2000
```

参数说明：

- `--input`
  要回放的 JSONL 文件
- `--amqp-url`
  新 RabbitMQ 连接地址
- `--checkpoint`
  SQLite 进度文件，用于断点续跑和防重复发送
- `--vhost`
  指定只回放某个 vhost，或者使用 `all`
- `--skew-guard-ms`
  用于时钟保护，默认 `2000`

重放逻辑：

- 脚本读取 `due_at_ms`
- 重新计算剩余延迟：
  `remaining_delay_ms = max(0, due_at_ms - now_ms - skew_guard_ms)`
- 使用原 `exchange`、原 `routing_key`、原 `payload`
- 恢复 headers / properties 后重发到新 RabbitMQ

注意：

- 默认不要加 `--mandatory`
- 对 `x-delayed-message` 的延迟重放，`mandatory` 往往会导致误报 `UnroutableError`

## 集群场景调用顺序

RabbitMQ 集群的推荐顺序如下：

1. 对 `server-0` 导出 TSV
2. 对 `server-1` 导出 TSV
3. 对 `server-2` 导出 TSV
4. 分别转换成 JSONL
5. 合并所有 JSONL
6. 抽样检查消息体
7. 回放到新集群
8. 查看 checkpoint

示例：

```bash
kubectl exec -n software kuke-rabbitmq-server-0 -- rabbitmqctl eval "$CMD" | sed '/^ok$/d' > delayed-node0-full.tsv
kubectl exec -n software kuke-rabbitmq-server-1 -- rabbitmqctl eval "$CMD" | sed '/^ok$/d' > delayed-node1-full.tsv
kubectl exec -n software kuke-rabbitmq-server-2 -- rabbitmqctl eval "$CMD" | sed '/^ok$/d' > delayed-node2-full.tsv

python3 convert_delayed_tsv.py --input delayed-node0-full.tsv --output delayed-node0.jsonl
python3 convert_delayed_tsv.py --input delayed-node1-full.tsv --output delayed-node1.jsonl
python3 convert_delayed_tsv.py --input delayed-node2-full.tsv --output delayed-node2.jsonl

cat delayed-node0.jsonl delayed-node1.jsonl delayed-node2.jsonl > delayed-all.jsonl

python3 inspect_delayed_jsonl.py --input delayed-all.jsonl --limit 5

python3 replay_delayed.py \
  --input delayed-all.jsonl \
  --amqp-url 'amqp://用户名:密码@新RabbitMQ地址:5672/%2F' \
  --checkpoint /tmp/delayed-replay.sqlite3 \
  --vhost all \
  --skew-guard-ms 2000
```

## 常见问题

### 1. `rabbitmqctl eval` 报 `undef`

如果执行 `rabbit_delayed_message:table_name()` 报 `undef`，是因为当前插件版本没有导出这个函数。  
本流程已经改为根据 `node()` 自己拼接 delayed 表名，不依赖 `table_name/0`。

### 2. 容器是只读的，能不能导出

可以。本文档的导出方式只打印到标准输出，不在容器内写文件。  
文件通过本地 shell 的 `>` 重定向保存到容器外。

### 3. `payload_base64` 怎么看明文

使用：

```bash
python3 inspect_delayed_jsonl.py --input delayed-node1.jsonl --limit 5
```

### 4. `checkpoint` 是干什么的

`checkpoint` 是重放进度记录文件，用来：

- 断点续跑
- 避免重复发送
- 留下失败记录

查看进度：

```bash
sqlite3 /tmp/delayed-replay.sqlite3 "SELECT status, COUNT(*) FROM replay_checkpoint GROUP BY status;"
```

### 5. full TSV 和简版 TSV 的区别

简版 8 列：

- 只能保留基础字段
- 自定义 headers / 完整 properties 可能丢失

完整 9 列：

- 保留完整 headers
- 保留完整 `P_basic` properties
- 推荐真实迁移时使用

