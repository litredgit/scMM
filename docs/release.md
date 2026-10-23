# 发布运维与来源管理

[任务导航](README.md) · [架构职责](development.md)

## 数据与 Git

- 不提交原始 mzML/mzXML、处理矩阵、H5AD 或大体积执行输出，除非仓库策略明确允许。
- 测试数据应尽量使用代码构造的小型合成谱和矩阵。
- 不在 notebook 或源码中写个人绝对路径。
- 提交信息建议使用项目现有风格，例如 `docs: ...`、`refactor: ...`、`test: ...`。
- 提交前查看 `git status` 和 `git diff --check`，避免把无关本地修改带入提交。

## 发布前检查

完成相关开发检查后，更新 5007 开发服务供用户验收，保留工作区修改。用户明确验收通过后，
再提交、推送并部署生产；执行顺序见 [发布、更新与回滚](installation.md#发布更新与回滚)。

先完成本次改动涉及的[分块验证](testing.md#完整验证)；包输入改变时构建发行包，再用本次 wheel 检查独立安装入口。
核对 dist 中选中的文件确为本次产物：

```bash
uv run --isolated --no-project \
  --with "$(find dist -maxdepth 1 -name '*.whl' -print -quit)" \
  scmm-process --help
```

提取/读取链改变时，还应在受支持的 Python 版本和代表性 mzML/mzXML 文件上完成相关端到端验证。

## 上游源码快照

外部交付单独保存在 `.upstream-snapshots.git/` 裸仓库的 `snapshots` 分支及 `snapshot/<名称>` 标签，
主仓库 `vendor/snapshots` 同步对象。交付提交只代表接收顺序，不伪造作者开发历史。
已收录 `scMM-new`（`bdce317`，2026-09-21）和 `SCMM-GUI-0.2.0-source`（`f961809`，2026-09-22）。

从仓库根目录导入，重复使用目录时指定新名称：

```sh
uv run --locked python scripts/import_upstream_snapshot.py 新交付目录 --name 新版本名称 --received-date YYYY-MM-DD
git log --oneline vendor/snapshots
git diff dev vendor/snapshots -- scMM/
git --git-dir=.upstream-snapshots.git show snapshots:.snapshot.json
```

脚本保留交付源码、PDF、配置及可执行位，跳过 Git/缓存目录，拒绝软链接；`.snapshot.json`
记录来源、排除项与 SHA-256。同名同内容不重复导入，同名异内容拒绝；新交付删除的文件仍可从旧标签找回。
只含包源码的交付统一映射到 `scMM/`，完整项目保留布局。原目录不自动随修改更新快照。
脚本不执行交付代码、不切换当前分支或改暂存区，但需要 Git 对象/引用与 `.git/info/exclude` 写权限。
按功能审阅移植，不直接整体合并快照分支。

快照标签留在本地裸仓库，普通推送 dev 不会备份它们。使用新的文件名导出并另存到其他磁盘：

```sh
git --git-dir=.upstream-snapshots.git bundle create /tmp/scmm-upstream-备份日期.bundle --all
git clone --bare /tmp/scmm-upstream-备份日期.bundle /tmp/scmm-upstream-restored.git
```

## 开源敏感信息检查与历史清理计划

当前文件检查：`python scripts/check_sensitive.py`；全部本地可达历史审计：
`python scripts/check_sensitive.py --history --report /tmp/scmm-security-audit.json`。
检查代码、文档、CHANGELOG、Notebook 输出、验证报告，以及 `dist/`、`build/` 和服务静态资源；
zip/wheel/sdist 在内存中检查，不解压到工作区。规则覆盖个人目录、内网地址、常见凭据格式、私钥、带凭据 URL、
字面量密码/密钥赋值及凭据文件名；超过扫描上限的压缩包报未完成检查，不当作通过。
输出只有类别、文件、行号和历史对象摘要，不输出命中值。模式扫描无法证明不存在未知格式的敏感信息，发布前仍须审阅。
CI 检查本次变更源码和按需构建的产物；历史单独记录，不能把既有历史问题隐藏成当前源码通过。

本轮按用户确认只审计历史并准备计划，不改写提交、不更新远端；脱敏摘要见
[开源审计报告](validation/open-source-audit.json)。历史仍含个人路径、内网地址及带输出的旧 Notebook。
当前文件脱敏不会移除这些 Git 对象；GitHub 旧提交、引用、克隆和缓存也不会因此消失。
当前未命中所扫描的凭据模式，不能扩展为不存在凭据的结论；未来发现真实凭据必须先撤销或轮换，再处理历史。

后续历史处理需单独审阅以下范围：

1. 冻结协作写入，核对远端分支/标签、本地旧分支、备份 refs 和所有 worktree，创建仓库外私有备份及隔离 mirror。
2. 对拟公开引用执行路径/地址替换，清空历史 Notebook 输出及执行计数，审阅代码单元中的真实路径。
   保留科学定义和数值报告；旧源码快照及归档逐项核对。
3. 在隔离镜像重新扫描全部可达对象，执行文档/Notebook/构建检查，产出旧新提交映射和受影响引用清单。
4. 审阅并另行授权后协调远端引用更新和必要强推，按 GitHub 要求处理旧 PR/缓存引用，通知协作者重新克隆。
   重写本地分支不能清除远端、备份、reflog 或第三方克隆，不承诺彻底删除已公开数据。
5. 用户确认迁移可用后再评估本地旧 refs、reflog、备份和对象回收，不自动删除恢复材料。

依据 [GitHub 敏感数据移除说明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)。
认证参考 [Argon2-cffi](https://argon2-cffi.readthedocs.io/en/stable/howto.html) 及
[OWASP 会话管理](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)。
