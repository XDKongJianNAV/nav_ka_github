统一 Python 版本，为3.14
uv venv --python 3.14
3. 激活环境
.venv\Scripts\activate.bat

pyproject.toml 可以理解成这个 Python 项目的“总配置文件”
安装依赖
uv sync
用 uv 往项目里添加依赖，最常用就是这条：

uv add 包名

例如加 numpy：

uv add numpy

这会同时更新项目的 pyproject.toml，并解析/更新锁文

删除依赖怎么做
uv remove 包名