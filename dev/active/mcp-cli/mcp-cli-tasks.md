# mcp-cli 任务清单

Last Updated: 2025-11-24

> 本文件是 `mcp-cli` 规划的具体执行清单，对应 `mcp-cli-plan.md` 中的任务编号，可用于跟踪进度。

## Phase 0：项目引导与基础设施

- [x] 1.1 初始化 `mcp-cli` 项目结构（包含 `pyproject.toml` 与 `mcp_cli` 包，满足 uv 管理要求）。
- [x] 1.2 在 `pyproject.toml` 中添加依赖：`mcp`、`click`、`pytest`，并验证可通过 `uv run` 运行。
- [x] 1.3 创建 `mcp_cli/main.py`，实现最小 CLI 入口，并在 `pyproject.toml` 注册 `mcp-tool` 脚本入口；验证 `uv run mcp-tool --help` 正常。

## Phase 1：配置加载与合并

- [x] 2.1 在 `mcp_cli/config.py` 中定义 `ServerConfig`、`MergedConfig` 等数据结构，带完整 type hints。
- [x] 2.2 实现配置文件查找函数 `get_default_config_paths`，按顺序检查：`~/.mcp.json`、`./.claude/mcp.json`、`./mcp.json`。
- [x] 2.3 实现 `mcpServers` 合并逻辑与结构校验（包括 `env` 浅合并），并通过 `load_merged_config` 输出合并结果。
- [ ] 2.4 在 CLI 层（而不仅是函数异常）无配置时给出清晰错误与最小配置示例文案。

## Phase 2：MCP client 封装

- [x] 3.1 参考 SDK simple-chatbot 示例，在 `mcp_cli/client.py` 定义 `McpServerClient` 抽象（含 `initialize` / `list_tools` / `call_tool` / `cleanup`）。
- [x] 3.2 支持基于 `ServerConfig` 的 `command` + `args` 启动 MCP server，并通过 stdio 建立 MCP client session。
- [ ] 3.3 明确并记录一次 CLI 调用的 server 连接策略（当前实现为：发现阶段遍历所有 server，执行阶段按需只连接目标 server）。
- [ ] 3.4 为 server 启动失败、握手失败、调用超时等场景设计并实现更精细的错误分类与退出码策略，并增加针对性测试。

## Phase 3：动态 CLI 子命令生成

- [x] 4.1 在 `mcp_cli/main.py` 中基于 `click.MultiCommand` 实现根命令逻辑，加载合并后的配置并通过 `discover_tools` 获取所有 server / tools。
- [x] 4.2 为每个 `<server>__<tool>` 生成一个动态子命令（使用 `McpToolCLI.get_command` + `_build_tool_command`），并绑定到根命令。
- [x] 4.3 实现 `mcp-tool --help` / `mcp-tool help` 输出全部子命令名称（在存在有效配置时），当前在无配置时会显示空列表并通过错误信息引导配置。

## Phase 4：参数映射与 JSON Schema

- [x] 5.1 在 `mcp_cli/schema.py` 中实现 JSON Schema 解析逻辑，识别简单 object schema 的属性 / required / enum 等（当前暂未处理默认值）。
- [x] 5.2 将简单 schema 属性映射为 CLI flag，支持标量、枚举和布尔值；在子命令中解析并组装为 tool 入参，flags 会覆盖 JSON 同名字段。
- [x] 5.3 为复杂 schema 提供 `--json`、`--json-file`、`--json-stdin` 三种传参方式，并实现 flags 覆盖 JSON 的合并逻辑。
- [x] 5.4 在子命令 `--help` 中展示工具原始 desc、完整输入 JSON Schema，以及关于 flag / JSON 传参方式的说明。

## Phase 5：输出与错误处理

- [ ] 6.1 在 `mcp_cli/output.py` 中实现统一的结果输出函数，支持 `--output text`（默认）与 `--output json`。
- [ ] 6.2 设计并实现错误码映射策略（如 1：通用错误，2：配置错误，3：连接错误等），并确保典型场景返回合适退出码。

## Phase 6：测试与迭代

- [ ] 7.1 在 `tests/` 目录为 `config`、`schema`、`client`、`commands` 编写单元测试；确保可通过 `uv run pytest` 运行。
- [ ] 7.2 使用至少一个真实 MCP server（如 filesystem 或 sqlite）进行端到端集成测试，验证 CLI 从配置到 tool 调用的完整链路。
- [ ] 7.3 视需要补充 README / 使用示例（遵循不额外创建无关文档的约束，仅在确有价值时添加）。
