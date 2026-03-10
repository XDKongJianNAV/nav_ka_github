# 开发环境与协作约定

## 1. 统一约定

本项目统一使用以下工具与文件：

- `Python 3.14`
- `uv`（环境与依赖管理）
- 项目根目录下的 `.venv/`（虚拟环境目录）
- `pyproject.toml`（项目配置）
- `uv.lock`（依赖锁文件）

同一仓库内不要混用 `pip install -r requirements.txt`、conda、系统 Python 手动装包等方式。协作统一采用 `uv` 工作流。

## 2. 获取与同步代码

### 首次克隆

```bash
git clone <repo_url>
cd <project_name>
```

建议目录示例：

- Windows: `D:\dev\<project_name>`
- WSL/Linux: `~/src/<project_name>`

### 日常同步

```bash
git pull
```

### 提交修改

```bash
git status
git add .
git commit -m "your message"
git push
```

## 3. 安装前提

确保本机已安装：

- Git
- Python 3.14
- uv

检查版本：

```bash
git --version
python --version
uv --version
```

要求 Python 版本为 `3.14.x`。

## 4. 创建虚拟环境

在项目根目录执行：

```bash
uv venv --python 3.14
```

该命令会创建：

```text
<project_name>/.venv/
```

如已有旧 `.venv/` 且 Python 版本不一致，删除后重新创建。

## 5. 激活环境（可选）

推荐直接使用 `uv run <command>`，通常无需手动激活。

如需手动激活：

- Windows CMD:
  ```bat
  .venv\Scripts\activate.bat
  ```
- Windows PowerShell:
  ```powershell
  .venv\Scripts\Activate.ps1
  ```
- WSL/Linux/macOS:
  ```bash
  source .venv/bin/activate
  ```

## 6. 安装依赖

在项目根目录执行：

```bash
uv sync
```

作用：

- 按 `pyproject.toml` + `uv.lock` 同步依赖
- 将依赖安装到当前项目的 `.venv/`

## 7. 运行命令

统一使用：

```bash
uv run python <script_path>
```

示例：

```bash
uv run python src/<package_name>/main.py
uv run python notebooks/<script_name>.py
```

若项目已定义 CLI，可直接执行：

```bash
uv run <command>
```

## 8. 配置文件说明

### `pyproject.toml`

用于维护项目元数据、依赖、Python 版本约束及开发工具配置。

### `uv.lock`

记录依赖解析后的精确版本，保证不同机器安装结果尽量一致。

依赖变更时通常需要同时更新并提交这两个文件。

## 9. 依赖管理

### 添加依赖

```bash
uv add <package>
```

示例：

```bash
uv add numpy
```

### 删除依赖

```bash
uv remove <package>
```

示例：

```bash
uv remove numpy
```

以上操作都会更新 `pyproject.toml` 与 `uv.lock`。

## 10. 依赖变更提交流程

```bash
uv add <package>
git add pyproject.toml uv.lock
git commit -m "add <package>"
git push
```

不要只提交代码而不提交 `uv.lock`。

## 11. 路径约定

README 与脚本说明统一使用项目根目录相对路径，避免写死本机绝对路径。

推荐：

- `src/<package_name>/`
- `notebooks/`
- `data/`
- `output/`
- `tests/`

示例：

```bash
uv run python notebooks/nb_example.py
```

仅在说明路径模式时给出绝对路径示例：

- 项目根目录（Windows）: `D:\dev\<project_name>`
- 项目根目录（WSL/Linux）: `~/src/<project_name>`
- 虚拟环境目录: `<project_name>/.venv/`

## 12. 常用工作流

首次拉取项目：

```bash
git clone <repo_url>
cd <project_name>
uv venv --python 3.14
uv sync
```

运行脚本：

```bash
uv run python <script_path>
```

日常更新代码：

```bash
git pull
uv sync
```

新增依赖后的提交流程见第 10 节。

## 13. 代码组织约定

- 先在 `notebooks/` 完成探索、验证与流程打通。
- 稳定后的可复用逻辑迁移到 `src/`。
- `notebooks/` 保留分析过程，`src/` 保留正式实现。
