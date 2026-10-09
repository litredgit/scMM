# 安装与部署

[返回文档索引](README.md)

## 推荐方式：uv

先按 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/) 安装 uv，然后在仓库
根目录同步完整环境：

```bash
uv sync --locked --all-extras --dev
```

uv 会读取 `.python-version`，在需要时安装 Python 3.12，并根据 `uv.lock` 创建项目专用 `.venv`。
项目会以可编辑模式安装，修改本地 `scMM/` 后无需重新安装。不要再用 pip 向 `.venv` 手工添加
长期依赖；发布依赖通过 `uv add` 管理，开发工具通过 `uv add --dev` 管理。

当前正式支持 Python 3.11–3.12。项目把 PyOpenMS 和核心数值栈限制在本机及 CI 已验证的兼容
范围；PyOpenMS 3.3 没有 CPython 3.13 wheel，因此在新 PyOpenMS 版本通过部署机器的 CPU、原始谱
读写和完整测试前，不应只为追新版本移除这些上限。

日常拉取代码后严格复用锁文件：

```bash
uv sync --locked --all-extras --dev
```

只有明确升级依赖时才运行 `uv lock --upgrade`，并将 `pyproject.toml` 与 `uv.lock` 的变更一起审阅、
测试和提交。`uv sync` 默认精确同步，会移除未声明的包，因此临时工具优先使用 `uvx` 或
`uv run --with <package>`。

## Thermo RAW 额外依赖

mzML/mzXML 使用 Python 环境中的 PyOpenMS。直接读取 Thermo profile RAW 还需要
.NET 8 和已部署的 Thermo RawFileReader helper；`uv sync` 不安装这些外部组件。
当前真实验收在 Linux，其他厂商 RAW 和 Windows 实机未验收；centroid scan 会报错。

reader 默认查找用户目录中的部署文件，也可用 `SCMM_THERMO_READER`（DLL 路径）和
`SCMM_DOTNET`（运行程序路径）指定。采集时区默认 `Asia/Shanghai`，可通过
`raw_timezone` / `SCMM_RAW_TIMEZONE` 覆盖。依赖版本、构建步骤、部署路径和验证证据见
[Thermo RAW 技术说明](thermo-raw.md)。不会在直接读取失败时自动转换 mzML；
旧 `--msconvert` 参数非空时会提示迁移错误。

## 使用 Notebook

完整同步已经包含 `notebook` extra。启动项目内的 JupyterLab：

```bash
uv run --locked python -m ipykernel install --user --name scmm --display-name scMM
uv run --locked jupyter lab
```

打开项目根目录的 `scMM_workflow.ipynb`，选择显示名为 `scMM`、内部名称为 `scmm` 的内核。
VS Code 也可直接选择仓库内的 `.venv/bin/python`。Notebook 的功能和参数见
[参数化 Notebook 工作流](workflow.md)。

## 依赖分组

| 分组 | 主要用途 |
|---|---|
| 核心依赖 | 原始谱读取、矩阵处理、保存、归一化、基础统计 |
| `plot` | Matplotlib/Seaborn、UMAP、Palantir 和轨迹图 |
| `cluster` | Leiden 与 Louvain 聚类 |
| `supervised` | 监督学习、SMOTE 和 SHAP |
| `ui` | Panel 引导式网页、Plotly 原始谱/质量图和 UMAP 质量检查 |
| `notebook` | JupyterLab 与项目内核 |
| `dev` 依赖组 | pytest、Ruff、构建与覆盖率；不进入发布包依赖 |

仅运行核心处理可使用：

```bash
uv sync --locked --no-dev
```

按需启用功能，例如：

```bash
uv sync --locked --extra plot --extra cluster
uv sync --locked --extra ui
```

仓库开发和 PR 验证统一使用 `uv sync --locked --all-extras --dev`，确保 notebook、分析和网页
入口共享同一份锁文件。

## 验证安装

```bash
uv run --locked python -c "import scMM, pyopenms, anndata; print('scMM environment ready')"
uv run --locked scmm-process --help
uv run --locked scmm-ui --help
uv run --locked pytest -q
```

如果入口不存在，先运行 `uv sync --locked --all-extras --dev`，并确认命令从包含 `pyproject.toml`
的仓库目录执行。

## 系统资源建议

原始目录处理会构建公共 m/z 网格，并可能并行读取多个谱文件。建议：

- 先用单个文件和 `N_JOBS=1` 验证参数。
- 再把 `N_JOBS` 增大；`-1` 会使用所有可用 CPU。
- 内存不足时减少并发，而不是优先降低质量分辨率。
- 将结果写到本地高速磁盘，完成后再归档到网络存储。

## 网页服务部署

网页面向实验室内网使用。项目根目录固定为 `/home/crs/data/results`，必须存在且可写。
`--storage` 可重复指定已挂载的服务器目录，Linux 上 `/home/crs/data` 存在时会另加入“云盘”。
读取前解析真实路径，拒绝逃逸根目录的路径或符号链接；浏览器电脑的本地路径不能直接使用。
导入旧结果时含 pickle 的目录须明确信任。`--output` 只保留旧任务兼容，不改变项目根目录。

本机启动：

```bash
uv run --locked scmm-ui --storage "原始数据=/mnt/ms-data" --port 5006 --show
```

局域网或 Tailscale 访问（将 `scmm-node:5006` 换为实际访问的主机名或 IP 与端口）：

```bash
uv run --locked scmm-ui \
  --storage "原始数据=/mnt/ms-data" \
  --address 0.0.0.0 --port 5006 \
  --allow-websocket-origin scmm-node:5006
```

从客户端打开 `http://scmm-node:5006`。允许的 origin 可重复指定；防火墙及 Tailscale 路由由部署环境管理。
外部默认参数用 `--config workbench.json` 或 `SCMM_UI_CONFIG` 配置，格式见[参数参考](parameters.md#网页默认参数)。
Windows 完整安装和后台任务未验收，当前项目网页使用 Linux；缺少 fcntl 的最小兼容不代表完整 Windows 支持。

## 独立端口检验

使用独立的项目目录与存储根，不需要重启现有服务：

```bash
mkdir -p /tmp/scmm-review/projects
SCMM_PREFERENCES=/tmp/scmm-review/preferences.json uv run --locked scmm-ui \
  --storage "检验数据=/tmp/scmm-review" --isolated-storage \
  --project-root /tmp/scmm-review/projects --port 5007
```

`--isolated-storage` 禁用自动加入云盘根目录，只开放明确配置的存储根。局域网访问时，
增加 `--address 0.0.0.0`，并为实际使用的主机名/IP 配置对应端口的 `--allow-websocket-origin`。

## 更新常驻服务

更新代码不会自动替换运行中的 Python 进程。采用用户级 `scmm-ui.service` 的部署可先检查：

```sh
systemctl --user status scmm-ui.service --no-pager
systemctl --user show scmm-ui.service -p ExecStart -p WorkingDirectory -p MainPID -p ActiveEnterTimestamp
journalctl --user -u scmm-ui.service -n 30 --no-pager
```

确认实际工作目录与环境，保存会话修改并检查进行中的任务后，再重启：

```sh
systemctl --user restart scmm-ui.service
systemctl --user status scmm-ui.service --no-pager
```

只改 Python 代码不需 daemon-reload；修改 service 文件后才需先执行 `systemctl --user daemon-reload`。
重启会断开网页并清空未保存会话，不删除已保存文件。重开页面，核对“scMM 实验项目”及六步导航；
HTTP 200 不能单独证明新版已加载。实际操作见[工作流程](workflow.md)。
