# 安装与部署

[返回文档索引](README.md)

本页负责环境安装、启动配置与服务更新；网页操作见 [工作流程](workflow.md)，
参数含义见 [参数参考](parameters.md)，reader 构建与协议见 [RAW 技术说明](thermo-raw.md)。

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

日常拉取代码后重复上述同步命令，严格复用锁文件。
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
uv run --locked python -m pytest -q
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

网页面向实验室内网使用。项目根目录默认为 `~/data/results`，可用 `--project-root` 指定，必须存在且可写。
`--storage` 可重复指定已挂载的服务器目录，Linux 上 `~/data` 存在时会另加入“云盘”。
读取前解析真实路径，拒绝逃逸根目录的路径或符号链接；浏览器电脑的本地路径不能直接使用。
导入旧结果时含 pickle 的目录须明确信任。`--output` 只保留旧任务兼容，不改变项目根目录。

本机生产服务为 5006 的 `scmm-ui.service`，开发服务为 5007 的 `scmm-dev.service`。
两者使用独立 worktree、`.venv` 和运行目录；日常操作见下节。以下命令展示通用启动参数。

本地访问配置：

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

## 开发与生产分离

本机保留原仓库作为开发 worktree，新增相邻的生产 worktree，共享 Git 对象和原始输入。
`develop` 已更名为 `dev`，`refined` 等历史分支保留。两套虚拟环境分别按同一份 `uv.lock`
同步；生产使用 `--all-extras --no-dev`，开发使用 `--all-extras --dev`。

| 配置 | 生产 | 开发 |
|---|---|---|
| 分支 / 目录 | `main` / `~/scMM-prod` | `dev` / `~/scMM` |
| Python 环境 | `~/scMM-prod/.venv` | `~/scMM/.venv` |
| 端口 / 用户级服务 | 5006 / `scmm-ui.service` | 5007 / `scmm-dev.service` |
| 原始输入（仅引用） | `~/data` | 同左 |
| 项目、分析结果及旧任务输出 | `~/data/results`（保留已有项目） | `~/.local/state/scmm/dev/results` |
| 缓存 / 临时文件 | `~/.local/state/scmm/prod/cache` / `prod/tmp` | `~/.local/state/scmm/dev/cache` / `dev/tmp` |
| 全局预设 | `~/data/results/.scmm-preferences.json` | `~/.local/state/scmm/dev/preferences.json` |

项目内的预览缓存、批次状态和快照随各自的项目根隔离。启动器另行设置 `XDG_CACHE_HOME`、
`UV_CACHE_DIR`、`NUMBA_CACHE_DIR`、`MPLCONFIGDIR` 和 `TMPDIR`，后台 worker 继承这些配置。
原始数据根沿用现有挂载，其中的生产结果子目录仍可被浏览，但开发保存和任务输出固定写入开发根；
不自动复制、迁移或清理已有结果。直接调用 Python API/Notebook 时仍应明确指定开发结果路径。
.NET/Thermo helper 是独立的共享外部依赖，不由分支切换或回滚管理。

统一入口为 [scripts/scmm_env.py](../scripts/scmm_env.py)，仅依赖 Linux 的 Python 3.10+ 标准库、
Git、uv、systemd 和 `ss`；scMM 本身仍使用 `.venv` 中的 Python 3.12。
配置默认由上述路径推导；可在 `~/.config/scmm/environments.json` 覆盖
`dev`、`prod`、`raw`、`prod_results`、`state`、`address`、`origins`，或用 `--config` 指定文件。
现有访问配置沿用 `0.0.0.0` 和 origin `*`；网络访问策略仍见 [NET-01](roadmap.md#工程改进待设计与实现)。
配置与运行数据不提交到 Git。不同用户/机器先创建对应 worktree，再安装服务：

```sh
# 当前仓库为 dev；生产 worktree 尚未创建时执行
# git worktree add -b main ../scMM-prod dev
python3 scripts/scmm_env.py install
```

`install` 备份原 service 文件，安装两个用户级 unit，并启用生产服务随用户管理器启动；
开发服务按需启动，不默认启用。稳定启动器复制到 `~/.local/share/scmm/scmm_env.py`，
因此回滚到还没有管理脚本的旧提交也能启动网页。管理脚本变化后重新执行 `install`。
安装 unit 不自动重启现有进程。

## 日常开发与调试

```sh
cd ~/scMM
python3 scripts/scmm_env.py sync dev
systemctl --user start scmm-dev.service
# 访问 http://服务器地址:5007
journalctl --user -u scmm-dev.service -f
```

修改代码后执行 `systemctl --user restart scmm-dev.service`。需要终端日志、断点或临时调试时，
先停止开发 service，再前台启动；Ctrl+C 停止，修改后重新运行：

```sh
systemctl --user stop scmm-dev.service
python3 scripts/scmm_env.py serve dev
```

调试器选择 `~/scMM/.venv/bin/python`。需要 Python 断点时运行
`python3 scripts/scmm_env.py serve dev --debug`，再用 IDE 连接本机 `127.0.0.1:5678`；
它在调试器接入后才启动网页，远程开发可通过 SSH 转发该调试端口。
开发同步/更新要求 5007 已停止，避免运行期间替换依赖。其他进程手工指定生产结果路径不受启动器约束。
历史合成项目与浏览器证据保留原目录，见 [CHANGELOG 检验记录](../CHANGELOG.md#历史独立环境与检验步骤)；
若需要在 5007 复用，须显式导入或复制到开发根，不把真实生产项目作为调试写入目标。

## 发布、更新与回滚

任务完成并通过相关检查后，更新 5007 开发服务供用户验收，保留修改且不自动提交。
用户明确确认本任务或里程碑验收通过后，再提交、推送并部署生产；协作授权约定见
[代理工作指南](../AGENTS.md#协作约定)。

在开发目录中使用同一个脚本：

```sh
# 发布：先完成开发验证及用户验收，再提交、推送 dev，发布到 main / 5006
# git add <本任务文件>
# git commit -m "feat: ..."
git push origin dev
python3 scripts/scmm_env.py release

# 更新开发：先停止 5007；拉取 origin/dev 并锁定同步，不自动启动
systemctl --user stop scmm-dev.service
python3 scripts/scmm_env.py update dev

# 更新生产：拉取 origin/main、同步依赖、重启及检查 5006
python3 scripts/scmm_env.py update prod

# 回滚到上次部署前的代码；也可指定一个已知提交或标签
python3 scripts/scmm_env.py rollback
# python3 scripts/scmm_env.py rollback <提交或标签>

python3 scripts/scmm_env.py status
```

发布/更新只接受干净 worktree，并用 fast-forward 更新 `main`；分支分叉须先在开发环境处理。
发布前执行 [开发验证](development.md#完整验证)。脚本串行锁定环境操作，检查生产浏览器连接、
未结束任务和 worker，然后停止服务再变更代码及依赖。新进程通过 systemd 状态和首页 HTTP 检查后，
`release` 才推送远端 `main`；网络推送失败时，本地新服务已生效，修复网络后补推即可。
依赖同步或健康检查失败时，脚本尝试恢复原提交、锁定依赖和服务；若恢复本身失败，按错误和日志处置，
原提交仍保存在 `refs/scmm/recovery`。脚本不会替用户完成科学验收，也不替代发布前测试。

回滚将本地 `main` 指针恢复到指定版本，并在 `refs/scmm/previous` 保存切换前版本；
不强推远端，不删除或恢复项目结果。再次 `rollback` 可切回刚才的版本，
`update prod` 会重新部署远端 `main`。回滚后的新版本发布仍须包含远端 main 的历史，避免非快进推送；
永久撤销应在 `dev` 中提交修复后正常发布。保存格式若已变化，须另外评估旧代码读取新项目的兼容性。

重启会断开网页并清空未保存会话。先保存并关闭生产页面，再检查任务；
脚本能检测连接与持久任务，不能证明已关闭页面的会话内容已保存。
HTTP 200 不能代替六步流程或真实实验验收。可查看服务及具体运行目录：

```sh
systemctl --user status scmm-ui.service scmm-dev.service --no-pager
systemctl --user show scmm-ui.service -p ExecStart -p WorkingDirectory -p MainPID
journalctl --user -u scmm-ui.service -n 30 --no-pager
```

仅修改 Python 代码不需 daemon-reload；重新安装 unit 时脚本会执行 daemon-reload。
