# mcp-tool

将 MCP servers 工具映射为 CLI 子命令，用于给 Agent 提供渐进式披露 MCP 工具

## 简介

`mcp-tool` 连接配置好的 MCP servers，将它们暴露的 **tools** 转换成标准的 CLI 子命令。
例如，server `filesystem` tool `read_file` → `mcp-tool filesystem__read_file`


## 快速开始

### 1. 查看可用工具

```bash
# 列出所有已加载 server 的 tools
mcp-tool
```

### 2. 查看工具参数

```bash
# 查看具体工具的用法和参数
mcp-tool fetch__fetch --help
```

### 3. 运行工具

支持两种传参方式：**Flags** (推荐) 和 **JSON**。

```bash
# 方式一：使用 Flags (自动从 schema 生成)
mcp-tool fetch__fetch --url "https://example.com"

# 方式二：使用 JSON
mcp-tool fetch__fetch --json '{"url": "https://example.com"}'
```

## 配置

`mcp-tool` 会按顺序加载并合并以下位置的配置：
1. `~/.mcp.json`
2. `./.claude/mcp.json`
3. `./mcp.json`

格式与标准 MCP 相同：

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "uvx",
      "args": ["mcp-server-fs", "--root", "."]
    }
  }
}
```

## 进阶用法

### 参数传递
除了 `--json`，还支持从文件或管道读取：

- `--json-file args.json`: 读取文件
- `--json-stdin`: 从 stdin 读取 (如 `echo '...' | mcp-tool ... --json-stdin`)

> 注意：Flag 参数优先级高于 JSON 里的同名字段。

### 输出控制
默认输出文本格式，适合人类阅读。如需脚本处理，可强制 JSON 输出：

```bash
mcp-tool <cmd> --output json
```

## 安装

本项目使用 [uv](https://docs.astral.sh/uv/) 管理，需要 Python >= 3.10。

```bash
# 开发模式运行
mcp-tool --help
```
