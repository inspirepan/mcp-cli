# mcp-cli 实现规划

Last Updated: 2025-11-24

## 1. 执行摘要（Executive Summary）

- 目标：实现一个名为 `mcp-tool` 的 Python 命令行工具，将多个 MCP server 的 tools 暴露为本地 CLI 子命令。每个 server 的每个 tool 在 CLI 中映射为一个子命令，例如 `filesystem__read_file`、`filesystem__write_file`。
- 配置：支持从当前目录 `mcp.json`、当前目录的 `.claude/mcp.json`、以及 home 目录下的 `~/.mcp.json` 加载配置，并进行合并，复用 MCP Python SDK 中已经实践的 `mcpServers` 配置格式。
- 体验：`mcp-tool --help` 或 `mcp-tool help` 能列出所有可用子命令（无需 desc）；对每个具体子命令（如 `mcp-tool filesystem__read_file --help`），展示对应 MCP tool 的原始描述（desc）和入参 JSON Schema，并提供尽可能友好的命令行参数映射。
- 技术选型：
  - 使用 Python + uv 管理项目和依赖。
  - 使用 `mcp` Python SDK 提供的 client 能力来连接 MCP servers、列出 tools、调用 tools。
  - CLI 框架优先选择 `click`（或在实现阶段可评估 `typer`，但本规划以 `click` 为基线），支持动态生成子命令。
- 参数传递方案：
  - 对于结构较简单的 object schema，将每个属性映射为一个命令行 flag，例如 `--path`、`--encoding`，required 属性在 CLI 层标记为必填。
  - 对于复杂 / 嵌套 schema，提供 `--json` / `--json-file` / `--json-stdin` 模式，以原始 JSON 传入，并允许与 flag 合并（flag 覆盖 JSON 中同名字段）。
  - 通过 `--dry-run` 或 `--print-input-schema` 等选项帮助用户理解 schema 与 flag 的映射关系。

## 2. 当前状态分析（Current State Analysis）

### 2.1 仓库与代码现状

- 目录：`/Users/bytedance/code/mcp-cli`
  - 当前仅有 `debug.log`，尚未初始化 Python 项目或任何源码。
- 相关 SDK 仓库：`~/code/GITHUB/modelcontextprotocol-python-sdk`
  - 包含 `src/mcp`、`examples`、`tests` 等完整实现和示例。
  - `examples/clients/simple-chatbot/mcp_simple_chatbot/servers_config.json` 使用了如下配置结构：

    ```json
    {
      "mcpServers": {
        "sqlite": {
          "command": "uvx",
          "args": ["mcp-server-sqlite", "--db-path", "./test.db"]
        }
      }
    }
    ```

  - `src/mcp/cli/claude.py` 中的 `update_claude_config` 也操作 `mcpServers` 字段，进一步印证了该配置格式在 SDK 内部的既有约定。

### 2.2 环境与约束

- Python 包管理：必须使用 `uv`，禁止使用 `pip`。
- Python 代码规范：
  - 所有函数必须有类型标注（type hints）。
  - 公共 API 需要 docstring。
  - 函数应保持小而聚焦，避免超长函数。
  - 单行长度不超过 120 字符。
- CLI 名称：最终命令名为 `mcp-tool`，与官方 `mcp[cli]` 提供的 `mcp` 命令区分开来，避免冲突。

### 2.3 业务需求小结

- 从多个配置文件自动聚合 MCP server 列表。
- 自动发现每个 server 提供的全部工具（tools）。
- 每个 tool 在 CLI 中成为一个子命令，命名形式：`<server-name>__<tool-name>`。
- 顶层 `mcp-tool --help` / `mcp-tool help`：列出全部子命令名称即可，不展示 desc。
- 每个子命令的 `--help`：
  - 展示原始 tool 描述（desc）。
  - 展示完整入参 JSON Schema（或格式化后的等价信息）。
  - 同时给出所有可用 flag 的说明（与 JSON 属性的对应关系）。

## 3. 目标状态设计（Proposed Future State）

### 3.1 整体架构

- 顶层结构：
  - Python 包：`mcp_cli`（工作名，可在实际实现时微调）。
  - 入口点：通过 `pyproject.toml` 的 `project.scripts` 暴露 `mcp-tool = mcp_cli.main:cli`。
  - CLI 框架：`click`，根命令为 `@click.group()` 动态注册子命令。
  - 核心模块：
    - `config`: 负责加载与合并 `mcp.json`、`.claude/mcp.json`、`~/.mcp.json`。
    - `client`: 封装 MCP Python SDK 的 client 连接、server 生命周期管理、tool 调用。
    - `commands`: 根据已发现的 servers & tools 生成 click 子命令。
    - `schema`: 将 JSON Schema 映射到 CLI 参数，并负责在 `--help` 中展示。
    - `output`: 统一处理工具返回结果的打印格式（raw / JSON / pretty）。

### 3.2 配置系统目标行为

- 支持的配置路径：
  1. 当前工作目录：`./mcp.json`
  2. 当前工作目录下：`./.claude/mcp.json`
  3. 用户 home 目录：`~/.mcp.json`

- 配置格式（统一使用 `mcpServers` 结构）：

  ```json
  {
    "mcpServers": {
      "filesystem": {
        "command": "uvx",
        "args": ["mcp-server-fs", "--root", "/"]
      },
      "sqlite": {
        "command": "uvx",
        "args": ["mcp-server-sqlite", "--db-path", "./test.db"],
        "env": {"SQLITE_BUSY_TIMEOUT": "5000"}
      }
    }
  }
  ```

- 合并策略（由下而上覆盖）：
  - 解析顺序：`~/.mcp.json` → `./.claude/mcp.json` → `./mcp.json`。
  - 合并规则：
    - 顶层以 `mcpServers` 字段为主，将三个文件中的 `mcpServers` 进行字典合并。
    - server 名相同：后加载（更近路径）的配置整体覆盖先前的该 server 配置。
    - 某些子字段（如 `env`）可做浅层合并：更近路径下的键覆盖远处路径的同名键。
  - 若没有任何文件存在或无 `mcpServers` 字段：给出明确错误提示，并在 `mcp-tool --help` 中指引配置示例。

### 3.3 MCP client 层目标行为

- 复用 SDK：
  - 使用 `mcp` Python SDK 中的 client 能力，按照 `servers_config.json` 示例中的模式：
    - 为每个 server 实例化一个封装对象（类似 `Server(name, srv_config)`）。
    - 在调用具体 tool 前，负责初始化（handshake）和 capabilities 同步。

- Server 生命周期：
  - 每次 CLI 调用：
    - 读取配置，构建需要的 server 列表。
    - 按需启动 server（例如只为目标子命令关联的 server 建立连接）。
    - 调用工具后清理连接 / 进程。
  - 为 `mcp-tool --help` 和 `mcp-tool <subcommand> --help` 提供只做 "list tools"、不真正执行 tool 的模式。

### 3.4 CLI 子命令模型

- 子命令命名：
  - 形式：`<server-name>__<tool-name>`，两者均使用原始 name，不做额外转义（仅在实现层面做必要的合法性处理）。
  - 示例：
    - `filesystem__read_file`
    - `filesystem__write_file`
    - `sqlite__execute_query`

- 根命令 `mcp-tool`：
  - 动态列出所有可用子命令。
  - `mcp-tool --help` / `mcp-tool help` 输出：
    - 描述：整体介绍与配置说明（简短）。
    - 子命令列表：仅显示子命令名称，不要求 desc。
  - 额外内置子命令（可选）：
    - `mcp-tool servers`：列出所有 server 及其来源配置文件。
    - `mcp-tool tools`：按 server 分组列出所有 tools 名称。

### 3.5 参数映射与 UX 设计

- 基础规则：
  - 每个 MCP tool 拥有一个 JSON Schema（假定为 object 类型或其他合法 JSON Schema）。
  - 对于 `type: "object"` 且 `properties` 为简单字段的情况：
    - 每个 property → 一个 CLI flag：`--<property-name>`。
    - flag 名默认直接使用属性名（如 `file_path`、`encoding`），避免大小写转换带来的困惑。
    - required 属性在 CLI 中标记为 `required=True`，缺失时报错并打印对应 schema 片段。
    - `enum` 属性映射为有固定 choices 的 CLI 选项。
    - `type: "boolean"` 属性映射为 `--flag/--no-flag` 或 `--flag true/false`（实现阶段可权衡，但规划优先 `--flag/--no-flag`）。
    - `type: "array"` 且 items 为简单标量：支持多次传入 `--names foo --names bar`，内部合并为数组。

- 复杂 schema 支持：
  - 当满足以下任一条件时，认为 schema 复杂：
    - 顶层类型不是 `object`；
    - `properties` 中存在嵌套 `object` 或 `array` 的复杂结构；
    - 使用了 `oneOf` / `anyOf` / `allOf` 等组合类型；
  - 在复杂场景下，提供通用 JSON 传参：
    - `--json '{"path": "...", "options": {...}}'`
    - `--json-file path/to/args.json`
    - `--json-stdin`：从 stdin 读取完整 JSON（如 `cat args.json | mcp-tool filesystem__read_file --json-stdin`）。
  - 若同时提供 flag 与 JSON：
    - 以 JSON 为基础对象；
    - 同名字段被 CLI flag 覆盖，保证 flag 优先权。

- 帮助与可发现性：
  - 每个子命令 `--help` 输出：
    - Tool 名称与隶属 server 名；
    - 原始 desc（从 MCP server 的 tool 描述字段读取）；
    - 格式化后的 JSON Schema（pretty-printed JSON 或等价结构）；
    - CLI flag 列表及其与 schema 属性的对应关系（包括 required / optional、默认值、枚举等）；
    - 提示复杂 schema 时推荐使用 `--json` / `--json-file` / `--json-stdin`。

### 3.6 输出与错误处理

- 输出格式：
  - 默认：对常见文本结果直接打印文本（如 tool 返回单一字符串）。
  - 提供 `--output json` 选项，将 MCP tool 返回的内容（包括多段 content）以 JSON 格式原样输出，便于脚本消费。
  - 可选 `--output pretty`：对 JSON 做缩进与简化展示。

- 错误处理：
  - 配置错误：清晰区分 "未找到配置文件"、"JSON 解析错误"、"缺少 mcpServers"、"server 未配置 command" 等典型问题，并给出修正建议。
  - 连接 / 启动错误：展示退出码、stderr 片段，并提示用户单独运行 server 以调试。
  - Tool 调用错误：展示来自 MCP server 的错误 message，同时保留非零退出码。
  - 参数错误：显示对应子命令的 schema 片段和示例用法。

## 4. 实施阶段划分（Implementation Phases）

### Phase 0：项目引导与基础设施

- 使用 `uv init` 初始化项目结构，配置 `pyproject.toml`。
- 添加依赖：`mcp`（Python SDK）、`click`、`typing-extensions`（如需要）、`pytest` 等。
- 设置基础代码结构：`mcp_cli/` 目录与最小入口 `main.py`。

### Phase 1：配置加载与合并

- 实现 `config` 模块：负责按顺序查找三个配置路径并解析 JSON。
- 定义轻量数据模型（如 `ServerConfig` dataclass）来表达 `command`、`args`、`env` 等信息。
- 完成三层配置合并逻辑和清晰错误消息。

### Phase 2：MCP client 封装

- 基于 SDK 示例（如 simple-chatbot）设计 `ServerClient` 封装，统一：
  - 初始化 / handshake；
  - 列出 tools；
  - 调用指定 tool 并返回结果；
  - 正确清理资源（进程 / 连接）。
- 根据 CLI 调用生命周期决定是一次调用只连接一个 server，还是允许多 server 并行。

### Phase 3：动态 CLI 子命令生成

- 在 `commands` 模块中：
  - 根命令负责加载配置与 server 列表；
  - 遍历所有 server 和 tools，基于 `<server>__<tool>` 命名规则创建子命令；
  - 为 `--help` / `help` 子命令提供完整子命令列表。

### Phase 4：参数映射与 JSON Schema 解释

- 实现 `schema` 模块：
  - 将 tool 的 JSON Schema 转为一组 click 参数定义；
  - 标记 required / optional，处理默认值与枚举；
  - 在复杂场景下自动启用 JSON 模式选项。
- 明确 flag 与 JSON 传参冲突时的合并逻辑。

### Phase 5：输出处理与错误体验

- 提供统一的结果打印函数，支持原始文本与 JSON 两种模式。
- 统一错误码与错误信息格式，使 CLI 便于脚本化调用。

### Phase 6：测试、验证与迭代

- 使用 pytest 为关键模块（config、schema、commands、client）添加单元测试与集成测试。
- 在实际环境中对典型 MCP server（如 filesystem、sqlite）验证 CLI 行为。
- 根据使用反馈迭代 UX（如默认输出格式、参数命名等）。

## 5. 详细任务拆解（Detailed Tasks）

以下任务按逻辑分组，包含优先级、依赖关系、预估工作量（S/M/L/XL）与验收标准。

### 5.1 Phase 0：项目引导

1.1 初始化 uv 项目结构
- 描述：在 `mcp-cli` 目录中使用 `uv init` 创建项目，并设置合适的包名（如 `mcp_cli`）。
- Effort：S
- 依赖：无
- 验收标准：
  - 存在 `pyproject.toml`，且被 uv 管理。
  - 可以执行 `uv run python -c "print('ok')"` 正常运行。

1.2 配置基础依赖
- 描述：通过 `uv add` 添加 `mcp`（含 CLI 支持）、`click`、`pytest` 等依赖。
- Effort：S
- 依赖：任务 1.1
- 验收标准：
  - `uv run python -c "import mcp, click"` 不报错。

1.3 建立最小 CLI 入口
- 描述：创建 `mcp_cli/main.py`，实现一个最小的 `click.group()`，并在 `pyproject.toml` 中注册 `mcp-tool` 脚本入口。
- Effort：S
- 依赖：任务 1.1、1.2
- 验收标准：
  - 在项目根执行 `uv run mcp-tool --help` 能正常输出基础帮助信息。

### 5.2 Phase 1：配置加载与合并

2.1 设计配置数据模型
- 描述：定义 `ServerConfig` 等数据结构，涵盖 `command`、`args`、`env` 等字段。
- Effort：S
- 依赖：任务 1.3
- 验收标准：
  - 类型有完整 type hints。
  - 能从示例 JSON（servers_config.json）构造对应对象。

2.2 实现配置文件查找顺序
- 描述：实现函数查找并返回存在的配置文件路径列表：`~/.mcp.json`、`./.claude/mcp.json`、`./mcp.json`。
- Effort：S
- 依赖：任务 2.1
- 验收标准：
  - 在不同当前工作目录下能正确发现存在的文件。
  - 对不存在文件不报错，只跳过。

2.3 实现配置解析与合并
- 描述：依次加载可用配置文件，解析 JSON，按 `mcpServers` 规则进行合并，并处理 env 浅合并逻辑。
- Effort：M
- 依赖：任务 2.1、2.2
- 验收标准：
  - 支持三个来源的 server 列表合并；
  - 同名 server 优先使用更近路径配置；
  - env 中同名键被更近路径覆盖；
  - 错误 JSON 会抛出带文件路径的清晰异常。

2.4 无配置时的错误提示与示例
- 描述：当合并结果为空时，在 CLI 中提供清晰提示，并展示最小配置示例片段。
- Effort：S
- 依赖：任务 2.3
- 验收标准：
  - `uv run mcp-tool` 在无配置环境下输出明确错误与示例 JSON。

### 5.3 Phase 2：MCP client 封装

3.1 参考 SDK 示例定义 ServerClient 抽象
- 描述：对 SDK 中 simple-chatbot 的 `Server` 类进行抽象，定义本项目的 `ServerClient`（或类似命名），负责对单个 server 的所有交互。
- Effort：M
- 依赖：任务 2.3
- 验收标准：
  - 提供 `initialize()`、`list_tools()`、`call_tool(name, args)`、`cleanup()` 等方法；
  - 有完整类型标注与 docstring。

3.2 支持基于 `command` + `args` 启动 server
- 描述：使用 Python SDK 提供的 stdio / 进程封装方式，根据 `ServerConfig` 启动 MCP server 并建立连接。
- Effort：M
- 依赖：任务 3.1
- 验收标准：
  - 在本地配置如 sqlite server 后，能够成功握手并列出 tools。

3.3 设计 CLI 生命周期内的 server 复用策略
- 描述：决定一次 CLI 调用是否只连接目标 server，还是可同时连接多个 server（例如为将来扩展多工具调用留接口）。
- Effort：S
- 依赖：任务 3.1
- 验收标准：
  - 文档中明确当前版本策略（建议：一次调用只连接一个 server）。

3.4 错误与超时处理
- 描述：为 server 启动失败、握手失败、tool 调用超时等场景设计错误信息与退出码策略。
- Effort：M
- 依赖：任务 3.2
- 验收标准：
  - 有单元测试或集成测试覆盖典型失败场景；
  - CLI 对这些失败返回非零退出码，并打印可读错误信息。

### 5.4 Phase 3：动态 CLI 子命令生成

4.1 根命令加载全部 servers 与 tools
- 描述：在 CLI 启动时加载合并后的配置，初始化（或惰性初始化）所有 server，并获取所有 tools 列表。
- Effort：M
- 依赖：任务 2.3、3.1
- 验收标准：
  - `mcp-tool` 在存在配置时能够列出全部 `<server>__<tool>` 子命令名称；
  - 不执行任何 tool，只做 capabilities 查询。

4.2 动态注册子命令
- 描述：使用 click 的动态命令注册能力，将每个 tool 包装为一个子命令函数，并绑定到根 group。
- Effort：L
- 依赖：任务 4.1
- 验收标准：
  - `mcp-tool filesystem__read_file --help` 能进入对应子命令帮助页面；
  - 未配置的命令名会给出标准的 "No such command" 提示。

4.3 实现 help/--help 输出所有子命令
- 描述：实现 `mcp-tool --help` 与 `mcp-tool help`，只列出全部子命令名称，不展示 desc。
- Effort：S
- 依赖：任务 4.2
- 验收标准：
  - 输出中包含所有 `<server>__<tool>` 名称，且格式清晰。

### 5.5 Phase 4：参数映射与 JSON Schema

5.1 解析 tool JSON Schema
- 描述：从 MCP server 获取的 tool 描述中提取 `inputSchema`，并转为内部表示。
- Effort：M
- 依赖：任务 3.1
- 验收标准：
  - 对简单 object schema 能正确识别属性、required、默认值、枚举等。

5.2 将 schema 转为 CLI flag
- 描述：根据 3.5 中的规则，将简单属性映射为 click 参数（options），并在 help 中展示。
- Effort：L
- 依赖：任务 5.1、4.2
- 验收标准：
  - 用户可以通过 `--path` 等 flag 正确传入参数并成功调用工具；
  - 缺失 required 字段会有明确报错信息。

5.3 复杂 schema 的 JSON 直通模式
- 描述：为复杂 schema 场景提供 `--json`、`--json-file`、`--json-stdin` 三种传参方式，并定义 flag 与 JSON 合并逻辑。
- Effort：M
- 依赖：任务 5.1
- 验收标准：
  - 可以从文件或 stdin 读取完整 JSON 作为 tool 入参；
  - 同名字段被 CLI flag 覆盖的行为经过测试验证。

5.4 在子命令 `--help` 中展示 schema 与映射
- 描述：在子命令帮助信息中展示原始 desc、格式化 JSON Schema，以及 flag ↔ 属性映射说明。
- Effort：M
- 依赖：任务 5.2、5.3
- 验收标准：
  - `mcp-tool filesystem__read_file --help` 能完整展示 desc、schema 与参数说明；
  - 对复杂 schema 子命令会提示优先使用 `--json` / `--json-file` 等方式。

### 5.6 Phase 5：输出与错误处理

6.1 统一结果输出格式
- 描述：实现统一的 `print_result` 工具函数，支持 `--output text`（默认）与 `--output json`。
- Effort：S
- 依赖：任务 3.2
- 验收标准：
  - 默认模式下打印文本结果友好；
  - JSON 模式下输出合法 JSON，便于下游脚本处理。

6.2 错误码与异常映射
- 描述：将不同错误类型映射为合适的退出码，并在文档中说明（如 1：通用错误，2：配置错误，3：连接错误等）。
- Effort：S
- 依赖：任务 3.4、6.1
- 验收标准：
  - 在常见错误场景下 CLI 返回预期退出码；
  - 错误消息中包含必要上下文信息（server 名、tool 名等）。

### 5.7 Phase 6：测试与迭代

7.1 单元测试覆盖关键模块
- 描述：为 `config`、`schema`、`client`、`commands` 编写单元测试。
- Effort：M
- 依赖：前述功能模块基本可用
- 验收标准：
  - 关键逻辑有测试覆盖，测试可通过 `uv run pytest` 执行；
  - 核心分支（如配置合并、参数映射）均有正 / 反向用例。

7.2 集成测试：真实 server 调用
- 描述：在本地引入至少一个 MCP server（如 filesystem 或 sqlite），通过 CLI 实际调用 tools 验证端到端行为。
- Effort：M
- 依赖：任务 3.2、4.2、5.2
- 验收标准：
  - 能通过 CLI 读写文件或执行 SQL 并得到正确结果；
  - 在 server 未运行 / 命令错误时有清晰报错。

7.3 文档与示例（可选）
- 描述：在项目中添加 README 片段或 docs（仅在你确认需要时创建，避免多余文档），展示常见使用场景与配置示例。
- Effort：S
- 依赖：主功能可用
- 验收标准：
  - 新用户按照文档示例即可完成一次配置并运行一个 tool。

## 6. 风险评估与缓解策略（Risk Assessment）

-1. 与官方 `mcp` CLI 命令的关系
- 风险：目前命令名为 `mcp-tool`，与官方 `mcp` CLI 不再直接命名冲突，但用户可能在理解两者职责上产生混淆。
- 缓解：
  - 开发阶段建议在 uv 虚拟环境中通过 `uv run mcp-tool` 使用本工具，避免与其他全局命令混淆；
  - 在文档中说明该风险，并保留未来改名为 `mcp-cli` 的可能性。

2. JSON Schema 复杂度
- 风险：部分 MCP tool 的 schema 可能非常复杂，简单 flag 映射难以覆盖所有情况。
- 缓解：
  - 实现通用的 `--json` / `--json-file` / `--json-stdin` 模式，保证功能完备性；
  - 在 help 中标记哪些字段采用了简化映射，推荐高阶用户直接传 JSON。

3. server 启动与性能问题
- 风险：每次 CLI 调用动态启动 server 可能导致性能较差，且错误信息难以调试。
- 缓解：
  - 首版优先保证正确性，接受一定启动成本；
  - 通过清晰的日志与错误输出帮助用户诊断 server 侧问题；
  - 预留未来持久化连接或长驻模式的扩展点。

4. 跨平台行为差异
- 风险：不同操作系统上进程管理、路径、环境变量等存在差异。
- 缓解：
  - 充分复用 MCP SDK 中已经处理好的进程 / transport 封装；
  - 在测试阶段覆盖至少 macOS + Linux 两种环境的基本场景。

5. 配置格式演进
- 风险：未来 MCP 规范或 Claude 配置格式可能演进，当前采用的 `mcpServers` 结构需要跟进。
- 缓解：
  - 在 `config` 模块中集中处理格式解析，避免格式散落在各处；
  - 通过 feature flag 或版本字段兼容旧配置。

## 7. 成功指标（Success Metrics）

- 功能性：
  - 至少支持 N≥2 个独立 MCP server（如 filesystem、sqlite）。
  - 对每个 server 至少成功调用 2 个以上 tool。
- 可用性：
  - 从零开始配置一个简单 server 并成功调用工具的操作步骤不超过 5 步。
  - 对于入参为简单 object schema 的工具，用户无需阅读原始 JSON Schema 即能通过 `--help` 完成调用。
- 稳定性：
  - 在典型使用场景下无资源泄漏（server 进程被正确回收）。
  - 错误场景下返回非零退出码并打印可读错误信息。

## 8. 资源与依赖（Required Resources & Dependencies）

- 技术依赖：
  - Python ≥ 3.8（具体版本按照 uv 默认或项目需求确定）。
  - `mcp` Python SDK（本地路径：`~/code/GITHUB/modelcontextprotocol-python-sdk`，发布包名称为 `mcp`）。
  - CLI 框架：`click`。
  - 测试框架：`pytest`。

- 运行时依赖：
  - 已安装并在 PATH 中可用的 `uv` 可执行文件（用于启动部分 server）。
  - 各类 MCP server 自身依赖（如 `mcp-server-sqlite`、`mcp-server-fs` 等），由用户在本地环境中安装。

## 9. 时间与里程碑预估（Timeline Estimates）

以下以 1 名熟悉 Python 与 MCP 的开发者为基准，仅供估算：

- Phase 0：项目引导与基础设施（0.5 天）
  - 完成 uv 初始化、依赖添加与最小 CLI 入口。

- Phase 1：配置加载与合并（0.5–1 天）
  - 完成配置模型、文件发现、合并逻辑与基本测试。

- Phase 2：MCP client 封装（1–1.5 天）
  - 集成 SDK，支持 server 启动、tool 列表、tool 调用与错误处理。

- Phase 3：动态 CLI 子命令生成（0.5–1 天）
  - 动态注册全部 `<server>__<tool>` 子命令，完成基础 help 行为。

- Phase 4：参数映射与 JSON Schema（1–1.5 天）
  - 完成简单 schema → flag 映射与复杂 schema 的 JSON 模式。

- Phase 5：输出与错误处理（0.5 天）
  - 统一输出格式与错误码策略。

- Phase 6：测试与迭代（1–2 天）
  - 单元测试、集成测试与基于真实 server 的端到端验证。

- 总体预估：约 5–7 个工作日，可根据实际复杂度与变更情况微调。
