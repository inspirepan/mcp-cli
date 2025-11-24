# mcp-cli 上下文与关键决策

Last Updated: 2025-11-24

## 1. 项目背景

- 目标：在本地开发环境中，通过一个统一的 `mcp-tool` CLI，将多个 MCP server 的 tools 暴露为可脚本化调用的子命令，以便在终端或 CI 中直接使用这些工具能力。
- 范围：
  - 不负责实现具体的 MCP server，只负责作为 client 连接既有 server；
  - 聚焦于 tools（resources / prompts 等能力可作为后续拓展）。

## 2. 目录与文件结构（目标）

- 仓库根目录：`/Users/bytedance/code/mcp-cli`
  - `pyproject.toml`：uv 管理的项目配置，注册 `mcp-tool` CLI 入口。
  - `mcp_cli/`：主 Python 包目录（命名可在实现时微调）。
    - `__init__.py`
    - `main.py`：CLI 入口，定义 `cli` 根命令。
    - `config.py`：配置加载与合并逻辑。
    - `client.py`：MCP server 封装与工具调用逻辑。
    - `commands.py`：动态子命令注册相关代码。
    - `schema.py`：JSON Schema 解析与 CLI 参数映射。
    - `output.py`：输出与错误处理辅助函数。
  - `tests/`：pytest 测试目录，按模块拆分。
  - `dev/active/mcp-cli/`：本任务的规划与跟踪文档所在目录。

> 注：以上结构为目标结构，用于指导后续开发；实际实现过程中可根据需要略作调整，但应保持模块职责清晰。

## 3. 外部依赖与参考项目

- MCP Python SDK
  - 本地路径：`~/code/GITHUB/modelcontextprotocol-python-sdk`
  - 用途：
    - 作为 MCP client 的核心实现提供方，包括 server 进程管理、消息协议处理等；
    - 提供配置示例（`servers_config.json`）和 client 示例（simple-chatbot）。

- `servers_config.json` 示例（来自 simple-chatbot）
  - 文件：`examples/clients/simple-chatbot/mcp_simple_chatbot/servers_config.json`
  - 关键结构：

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

  - 该结构将作为本项目 `mcp.json` 等配置文件的约定基础。

- `mcp.cli.claude` 配置逻辑
  - 文件：`src/mcp/cli/claude.py`
  - 作用：
    - 操作 Claude Desktop 的配置文件 `claude_desktop_config.json`；
    - 使用 `mcpServers` 字段存储各 server 配置。
  - 启示：
    - 本项目应尽量沿用 `mcpServers` 这一字段名称与整体结构，以便与已有生态保持兼容性。

## 4. 关键设计决策

### 4.1 CLI 命令命名与结构

- 根命令名：`mcp-tool`
  - 优点：避免与官方 `mcp` CLI 命令冲突，同时名称直观地表达 “MCP tools 的 CLI 包装”。
  - 风险：部分用户可能习惯直接使用 `mcp` 命令，需要在文档中解释两者的区别与定位。

- 子命令命名：`<server-name>__<tool-name>`
  - 采用双下划线 `__` 作为 server 与 tool 的分隔符。
  - 不对 server / tool 名做大小写或命名风格转换，直接使用原始 name。
  - 若存在不同 server 同名 tool，可以靠前缀区分。

### 4.2 配置文件与合并策略

- 支持的配置文件（按优先级从低到高）：
  1. `~/.mcp.json`
  2. `./.claude/mcp.json`
  3. `./mcp.json`

- 合并策略：
  - 顶层只认一个字段：`mcpServers`；
  - 所有配置文件中 `mcpServers` 合并到一个 dict：
    - 如果 server 名（key）不同：简单并集；
    - 如果 server 名相同：使用优先级更高（更近）的文件整体覆盖该 server 配置；
    - 某些子字段（如 `env`）采用浅合并，允许在更近配置中覆盖或新增环境变量。

- 无配置情形：
  - CLI 启动时报错，并打印：
    - 已尝试查找的路径；
    - 最小可用配置示例。

### 4.3 JSON Schema → CLI 参数映射

- 简单 schema：
  - 条件：顶层为 `type: "object"`，`properties` 仅包含标量属性（string / number / integer / boolean）及简单数组。
  - 映射：
    - `property name` → `--property-name` flag（直接使用属性名，无转换）。
    - required 属性 → 必须传入，否则 CLI 校验失败。
    - `enum` → 限定 choices。
    - `array` → 允许多次传入同名 flag，并聚合为列表。

- 复杂 schema：
  - 条件：存在嵌套 object、组合类型（`oneOf` 等），或顶层类型不是 `object`。
  - 处理：
    - 不尝试细化为多个 flag，只提供 JSON 直通；
    - 支持：`--json`、`--json-file`、`--json-stdin`；
    - 若仍有部分简单字段适合 flag，可在实现时按需补充，但不做强制要求。

### 4.4 CLI 入参与用户体验

- 入参策略：
  - 简单工具：优先通过 flag 传参，提升易用性；
  - 复杂工具：推荐通过 JSON 传参，保证表达能力；
  - flag 与 JSON 同时存在时：flag 覆盖 JSON 中同名字段。

- 帮助信息设计：
  - 顶层 `mcp-tool --help`：
    - 简要说明工具用途与配置位置；
    - 罗列全部可用子命令名。
  - 子命令 `--help`：
    - 展示 tool desc、JSON Schema（格式化）、flag 列表及示例；
    - 对复杂 schema 给出推荐用法（如 `--json-file`）。

### 4.5 运行模式与生命周期

- 每次 CLI 调用：
  - 解析配置 → 初始化目标 server → 列出 / 调用单个 tool → 清理资源；
  - 不设计长连接或交互式模式（可作为未来扩展）。

- 性能考虑：
  - 首版聚焦正确性与清晰错误信息；
  - 后续如有需要，可增加：
    - 本地缓存已发现的 server / tool 列表；
    - 交互式 session 模式（一次建立连接，多次调用）。

## 5. 已知开放问题（待确认）

- 是否需要在 v1 就兼容官方 `mcp` CLI 的某些命令格式或行为（例如 inspector 等），还是只聚焦 "tools → 子命令" 这一能力。
- 输出格式是否需要支持更丰富的模式（如 `--output table` / `--output yaml`），当前规划仅包含 text / json。
- 是否需要一开始就支持 prompts / resources 等 MCP 能力映射为 CLI 命令，或先专注 tools，后续再扩展。

## 6. 与规划文档的关系

- 本文件（context）用于记录：
  - 目录结构与外部依赖；
  - 重要设计决策与开放问题；
  - 便于在实现时快速了解项目边界与约束。

- 详细的实施步骤与任务拆解请参考：
  - `dev/active/mcp-cli/mcp-cli-plan.md`
  - `dev/active/mcp-cli/mcp-cli-tasks.md`
