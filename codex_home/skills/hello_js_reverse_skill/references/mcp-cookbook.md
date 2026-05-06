# MCP 工具使用手册

## 概述

本手册详细说明 `camoufox-reverse` MCP 服务器的使用方式，
提供常见逆向场景下的具体操作步骤。

## 工具速查表

### camoufox-reverse MCP（52 个工具）

| 类别 | 工具 | 核心用途 |
|------|------|---------|
| **浏览器** | `launch_browser` / `close_browser` | 启动/关闭反检测浏览器 |
| **导航** | `navigate` / `reload` / `go_back` | 页面导航 |
| **页面交互** | `click` / `type_text` / `wait_for` | 元素交互 |
| **截图** | `take_screenshot` / `take_snapshot` | 截图 / 无障碍树 |
| **页面信息** | `get_page_info` / `get_page_html` | 页面状态和 HTML |
| **源码搜索** | `search_code` | 在所有 JS 中搜索（结构化结果，默认 max_results=50） |
| **精确搜索** | `search_code_in_script` | 在指定脚本中搜索（前后 3 行上下文，适合大文件） |
| **源码获取** | `get_script_source` | 获取指定脚本的代码 |
| **源码保存** | `save_script` | 将脚本保存到本地文件 |
| **脚本列表** | `list_scripts` | 列出页面加载的所有脚本 |
| **执行 JS** | `evaluate_js` / `evaluate_js_handle` | 在页面执行任意 JS |
| **加载前注入** | `add_init_script` | 页面加载前注入脚本（支持 `persistent` 跨导航重注入） |
| **伪断点** | `set_breakpoint_via_hook` | 通过 Hook 设置伪断点（支持 `persistent` 持久化） |
| **断点数据** | `get_breakpoint_data` | 获取伪断点捕获的数据 |
| **函数追踪** | `trace_function` / `get_trace_data` | 追踪函数调用（支持 `persistent` 跨导航持久化） |
| **自定义 Hook** | `hook_function` | 注入自定义 Hook（before/after/replace，支持 `non_overridable` 防覆盖） |
| **预设 Hook** | `inject_hook_preset` | 一键 Hook（xhr/fetch/crypto/websocket/debugger_bypass，默认持久化） |
| **移除 Hook** | `remove_hooks` | 移除所有 Hook（支持 `keep_persistent` 保留持久化 Hook） |
| **冻结原型** | `freeze_prototype` | 冻结任意原型方法，防止页面 JS 覆盖 Hook |
| **属性追踪** | `trace_property_access` / `get_property_access_log` | Proxy 级别属性访问追踪 |
| **JSVMP 插桩** | `hook_jsvmp_interpreter` | 一键插桩 JSVMP（Function.prototype.apply + 30+ 敏感属性） |
| **JSVMP 日志** | `get_jsvmp_log` | 获取 JSVMP 日志（API 调用统计 + 属性读取摘要） |
| **JSVMP 字符串** | `dump_jsvmp_strings` | 提取字符串数组，识别 API 名称，检测混淆模式 |
| **环境采集** | `compare_env` | 全面收集浏览器环境（navigator/screen/canvas/WebGL/Audio/timing） |
| **网络捕获** | `start_network_capture` / `stop_network_capture` | 启停网络捕获（支持 `capture_body` 捕获响应体） |
| **网络请求** | `list_network_requests` | 列出捕获的请求 |
| **请求详情** | `get_network_request` | 获取请求完整信息（含响应体） |
| **请求来源** | `get_request_initiator` | 获取请求的 JS 调用栈（改进 URL 匹配 + 诊断信息） |
| **请求拦截** | `intercept_request` / `stop_intercept` | 拦截/修改/Mock 请求 |
| **Cookie** | `get_cookies` / `set_cookies` / `delete_cookies` | Cookie 管理 |
| **Storage** | `get_storage` / `set_storage` | localStorage / sessionStorage |
| **状态管理** | `export_state` / `import_state` | 保存/恢复浏览器状态 |
| **控制台** | `get_console_logs` | 读取控制台输出 |
| **指纹** | `get_fingerprint_info` | 检查浏览器指纹 |
| **反检测** | `check_detection` | 测试是否被反爬识别 |
| **反调试** | `bypass_debugger_trap` | 绕过 debugger 陷阱 |

## 场景化操作手册

### 场景 1：分析数据接口的加密参数

**目标**：找到接口中加密参数的生成逻辑

```
步骤 1：启动反检测浏览器
  [camoufox-reverse] launch_browser()

步骤 2：导航到目标页面
  [camoufox-reverse] navigate(url="https://target.com")

步骤 3：确认页面加载
  [camoufox-reverse] take_screenshot() → 确认页面正常

步骤 4：开始网络捕获
  [camoufox-reverse] start_network_capture()

步骤 5：触发数据请求（如翻页）
  [camoufox-reverse] click(selector=".next-page")
  或
  [camoufox-reverse] evaluate_js(expression="document.querySelector('.next').click()")

步骤 6：查看网络请求
  [camoufox-reverse] list_network_requests

步骤 7：获取目标请求详情
  [camoufox-reverse] get_network_request(request_id=N)
  → 记录 URL、Headers、Params、Response

步骤 8：获取请求调用栈（黄金路径）
  [camoufox-reverse] get_request_initiator(request_id=N)
  → 直接定位发起请求的 JS 函数

步骤 9：搜索加密参数
  [camoufox-reverse] search_code(keyword="参数名=")
  [camoufox-reverse] search_code(keyword="参数名")

步骤 10：读取相关源码
  [camoufox-reverse] get_script_source(script_url="包含加密逻辑的脚本URL")

步骤 11：设置伪断点验证
  [camoufox-reverse] set_breakpoint_via_hook(target_function="加密函数路径")
  触发请求 →
  [camoufox-reverse] get_breakpoint_data
  → 查看捕获的参数和返回值
```

### 场景 2：动态 Cookie 逆向

**目标**：找到 Cookie 的生成逻辑

```
步骤 1：注入 Cookie Hook
  [camoufox-reverse] hook_function(
    function_path="Document.prototype.cookie",
    hook_code="console.log('[Cookie Set]', arguments[0]); console.trace('Cookie Stack');",
    position="before"
  )
  或使用预设 Hook：
  [camoufox-reverse] inject_hook_preset(preset="crypto")

步骤 2：刷新页面触发 Cookie 生成
  [camoufox-reverse] reload()

步骤 3：读取 Hook 输出
  [camoufox-reverse] get_console_logs
  → 找到 Cookie 设置记录和调用栈

步骤 4：根据调用栈定位生成函数
  [camoufox-reverse] search_code(keyword="目标函数名")
  [camoufox-reverse] get_script_source(script_url="...")

步骤 5：分析生成逻辑
  [camoufox-reverse] set_breakpoint_via_hook(target_function="cookie生成函数")
  刷新页面 →
  [camoufox-reverse] get_breakpoint_data → 查看入参和返回值
  [camoufox-reverse] trace_function(function_path="加密函数", log_args=true, log_return=true, log_stack=true)
  [camoufox-reverse] get_trace_data → 查看中间值
```

### 场景 3：混淆代码分析

**目标**：还原混淆的 JS 代码

```
步骤 1：列出所有脚本
  [camoufox-reverse] list_scripts
  → 找到可疑的混淆脚本（通常文件名无意义或体积很大）

步骤 2：保存混淆脚本到本地
  [camoufox-reverse] save_script(script_url="混淆脚本URL", save_path="./project/obfuscated.js")

步骤 3：搜索关键特征
  [camoufox-reverse] search_code(keyword="_0x")
  → 确认混淆类型（OB混淆）
  
  [camoufox-reverse] search_code(keyword="switch|while.*true")
  → 检查是否有控制流平坦化

步骤 4：在浏览器中还原字符串
  [camoufox-reverse] evaluate_js(expression="返回字符串数组的代码")
  → 获取解密后的字符串映射

步骤 5：定位关键函数
  [camoufox-reverse] search_code(keyword="encrypt|sign|md5|aes")
  → 找到加密相关代码的大致位置
  [camoufox-reverse] get_script_source → 获取上下文
```

### 场景 4：WASM 逆向

**目标**：分析 WASM 加密函数的输入输出

```
步骤 1：搜索 WASM 加载代码
  [camoufox-reverse] search_code(keyword="WebAssembly|.wasm|instantiate")

步骤 2：找到 WASM 文件
  [camoufox-reverse] list_network_requests
  → 找到 .wasm 文件的请求

步骤 3：分析 WASM 调用
  [camoufox-reverse] search_code(keyword="exports.|instance.exports")
  → 找到导出函数的调用代码

步骤 4：追踪输入输出
  [camoufox-reverse] set_breakpoint_via_hook(target_function="wasm导出函数调用路径")
  触发请求 →
  [camoufox-reverse] get_breakpoint_data → 查看入参和返回值

步骤 5：在浏览器中测试
  [camoufox-reverse] evaluate_js(expression="调用wasm函数并返回结果")
  → 验证 I/O 关系
```

### 场景 5：WebSocket 通信分析

**目标**：分析 WebSocket 消息格式和加密

```
步骤 1：注入 WebSocket Hook
  [camoufox-reverse] inject_hook_preset(preset="websocket")

步骤 2：读取 WS 消息日志
  [camoufox-reverse] get_console_logs
  → 获取 WS 发送/接收消息

步骤 3：搜索 WS 相关代码
  [camoufox-reverse] search_code(keyword="WebSocket|ws.send|onmessage")

步骤 4：手动发送 WS 消息
  [camoufox-reverse] evaluate_js(expression="ws.send(JSON.stringify({...}))")
```

## 高级技巧

### 使用 trace_function 自动记录函数调用

```
[camoufox-reverse] trace_function(
    function_path="window.encrypt",
    log_args=true,
    log_return=true,
    log_stack=true,
    max_captures=50,
    persistent=True          → 跨导航持久化，页面刷新/跳转后自动重注入
)
```
→ 每次 `encrypt` 被调用时自动记录参数、返回值和调用栈，不暂停执行
→ `get_trace_data` 会自动合并页面数据和 Python 端持久化数据

### 使用 inject_hook_preset 一键 Hook

```
默认 persistent=True（持久化，跨导航自动重注入）：

[camoufox-reverse] inject_hook_preset(preset="xhr")              → Hook 所有 XHR 请求
[camoufox-reverse] inject_hook_preset(preset="fetch")             → Hook 所有 fetch 请求
[camoufox-reverse] inject_hook_preset(preset="crypto")            → Hook btoa/atob/JSON.stringify
[camoufox-reverse] inject_hook_preset(preset="websocket")         → Hook WebSocket 消息
[camoufox-reverse] inject_hook_preset(preset="debugger_bypass")   → 绕过反调试
```

### 使用 hook_function 自定义 Hook

```
[camoufox-reverse] hook_function(
    function_path="XMLHttpRequest.prototype.open",
    hook_code="console.log('[XHR]', arguments[0], arguments[1])",
    position="before",
    non_overridable=True     → 防覆盖：Object.defineProperty 冻结 + toString 伪装 native code
)
```
→ 在 XHR.open 调用前输出请求方法和 URL，即使页面 JS 尝试覆盖也不会丢失

### 使用 freeze_prototype 防止 Hook 被覆盖

```
[camoufox-reverse] freeze_prototype(className="XMLHttpRequest", methodName="send")
```
→ 冻结原型方法（configurable:false + writable:false），防止 JSVMP 等覆盖你的 Hook

### 使用 JSVMP 专项工具

```
[camoufox-reverse] hook_jsvmp_interpreter        → 一键插桩 Function.prototype.apply + 30+ 敏感属性
[camoufox-reverse] dump_jsvmp_strings             → 提取字符串数组，识别 API 名称
  触发操作...
[camoufox-reverse] get_jsvmp_log                  → 获取 API 调用统计 + 属性读取摘要
[camoufox-reverse] compare_env                    → 收集完整浏览器环境（补环境基准线）
```

### 使用属性访问追踪

```
[camoufox-reverse] trace_property_access(target_expression="navigator")
  触发操作...
[camoufox-reverse] get_property_access_log        → 查看 navigator 的哪些属性被读取
```
→ 精确发现 JSVMP 或签名逻辑读取了哪些环境属性

### 使用 search_code_in_script 精确搜索大文件

```
[camoufox-reverse] search_code_in_script(script_id=3, keyword="sign|token|encrypt")
```
→ 在指定脚本中搜索，返回前后 3 行上下文，适合 200KB+ 的 JSVMP 文件

### 使用 add_init_script 进行预分析

```
[camoufox-reverse] add_init_script(script=`
    const knownGlobals = new Set(Object.keys(window));
    setInterval(() => {
        const newGlobals = Object.keys(window).filter(k => !knownGlobals.has(k));
        if (newGlobals.length > 0) {
            console.log('[Monitor] 新全局变量:', newGlobals);
            newGlobals.forEach(k => knownGlobals.add(k));
        }
    }, 1000);
`, persistent=True)         → 跨导航持久化
```

### 使用 evaluate_js 提取运行时数据

```
[camoufox-reverse] evaluate_js(expression=`
    JSON.stringify(document.cookie.split('; ').reduce((obj, pair) => {
        const [k, v] = pair.split('=');
        obj[k] = v;
        return obj;
    }, {}))
`)
```

### 使用 intercept_request 拦截/修改请求

```
[camoufox-reverse] intercept_request(url_pattern="**/api/data*", action="log")     → 仅记录
[camoufox-reverse] intercept_request(url_pattern="**/ads/*", action="block")       → 屏蔽广告
[camoufox-reverse] intercept_request(url_pattern="**/api/*", action="modify", modify_headers={"X-Custom": "test"})
[camoufox-reverse] intercept_request(url_pattern="**/api/*", action="mock", mock_response={"status": 200, "body": "{\"ok\":1}"})
```

## camoufox-reverse MCP 工具分类总览（52 个）

| 类别 | 工具 | 说明 |
|------|------|------|
| 浏览器生命周期 | `launch_browser` `close_browser` | 启动/关闭 Camoufox |
| 页面导航 | `navigate` `reload` `go_back` | 导航控制 |
| 页面交互 | `click` `type_text` `wait_for` | UI 自动化 |
| 页面状态 | `get_page_info` `take_screenshot` `take_snapshot` `get_page_html` | 页面信息 |
| 源码分析 | `list_scripts` `get_script_source` `search_code` `search_code_in_script` `save_script` | JS 逆向核心 |
| JS 执行 | `evaluate_js` `evaluate_js_handle` `add_init_script` | 代码执行（支持持久化） |
| 调试 | `set_breakpoint_via_hook` `get_breakpoint_data` `get_console_logs` | 伪断点调试（支持持久化） |
| Hook | `trace_function` `get_trace_data` `hook_function` `inject_hook_preset` `remove_hooks` `freeze_prototype` | 函数 Hook（支持持久化 + 防覆盖） |
| 属性追踪 | `trace_property_access` `get_property_access_log` | Proxy 级别属性访问监控 |
| JSVMP 专项 | `hook_jsvmp_interpreter` `get_jsvmp_log` `dump_jsvmp_strings` `compare_env` | JSVMP 虚拟机保护分析 |
| 网络 | `start_network_capture` `stop_network_capture` `list_network_requests` `get_network_request` `get_request_initiator` `intercept_request` `stop_intercept` | 网络分析（支持响应体捕获） |
| 存储 | `get_cookies` `set_cookies` `delete_cookies` `get_storage` `set_storage` `export_state` `import_state` | 状态管理 |
| 反检测 | `get_fingerprint_info` `check_detection` `bypass_debugger_trap` | 指纹与反检测 |
