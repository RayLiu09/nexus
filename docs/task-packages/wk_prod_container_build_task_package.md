# prod 容器镜像构建任务包

## 2026-11-19 重新构建

用户要求使用国内镜像源重新构建 `nexus-api:prod`、`nexus-console:prod`。代码基线为 `57cac43`，包含 pgvector collection 路由、metadata 瘦身回填和 migration `20261118_0133`。沿用现有 Dockerfile，显式指定 DaoCloud 基础镜像、清华 PyPI 索引及包地址、npmmirror npm；单 Agent 顺序构建，允许复用未变化缓存。镜像记录源码 revision label，检查架构、入口、端口，并通过无网络、无宿主机端口映射的临时容器验证 API 新模块、健康检查及 Console 生产登录页。日志单独保存 `/tmp/nexus-{api,console}-prod-{rebuild,verify}-20261119.log`。本轮范围限本地镜像构建、隔离验证和证据记录；不推送镜像、不替换运行服务、不执行迁移，不修改业务源码或仓库锁文件。保留已有构建记录及其他工作区修改。

## 2026-11-17 再次构建（r2）

用户再次要求使用国内镜像源重新构建两个 `prod` 镜像。基于当前工作区（HEAD `939ec0b`），沿用下述范围、禁止项和验收要求，单 Agent 顺序构建，显式使用 DaoCloud、清华 PyPI 与 npmmirror。构建日志另存 `/tmp/nexus-{api,console}-prod-rebuild-20261117-r2.log`，避免覆盖同日已有记录；使用无网络临时容器验证，结果追加到 review evidence。仅构建本地镜像，不推送或替换服务，不修改业务代码及仓库锁文件。

## 2026-11-17 重新构建

用户要求使用国内镜像源重新构建 `nexus-api:prod` 和 `nexus-console:prod`。代码基线 `79d5d16`，使用当前工作区与已有 Dockerfile 的 DaoCloud 基础镜像、清华 PyPI 和 npmmirror npm。沿用本任务包范围和禁止项，单 Agent 顺序构建，允许复用未变化缓存；检查镜像 ID、平台、大小、入口、端口，通过无网络临时容器验证 API 导入、健康检查及 Console 生产登录页启动。仅本地镜像构建和隔离验证，不推送、不替换运行服务、不执行迁移，不改业务代码或仓库锁文件。构建与验证日志保存在 `/tmp/nexus-{api,console}-prod-{rebuild,verify}-20261117.log`，结果记录在对应 review evidence。

## 2026-11-05 重新构建

用户要求使用国内镜像源重建 `nexus-api:prod` 和 `nexus-console:prod`。基于当前工作区（HEAD `e5750b3`，包含已有未提交源码），沿用 DaoCloud 基础镜像、清华 PyPI 和 npmmirror npm。单 Agent 顺序构建，允许复用未变化依赖缓存；检查镜像 ID、平台、大小、入口和端口，并通过无网络临时容器验证 API 导入、Console 生产产物及登录页启动。日志保存 `/tmp/nexus-api-prod-rebuild-20261105.log`、`/tmp/nexus-console-prod-rebuild-20261105.log`。范围限本地构建和临时验证，不推送、不替换运行服务、不执行迁移，不修改业务代码、依赖版本或仓库锁文件。

## 2026-11-03 重新构建

用户要求使用本地镜像源重建 `nexus-api:prod`、`nexus-console:prod`。基于当前工作区，包含行业法规标准、入口顺序与资产计数性能优化。沿用 Dockerfile 已配置的 DaoCloud 基础镜像、清华 PyPI 和 npmmirror npm，允许复用依赖缓存，重建变化源码和生产产物。单 Agent 顺序构建并记录镜像 ID、平台、大小；在无网络临时容器内检查 API 导入及新模块、Console 生产产物和登录页启动。日志保存 `/tmp/nexus-api-prod-rebuild-20261103.log`、`/tmp/nexus-console-prod-rebuild-20261103.log`。仅本地构建和临时验证，不推送、不替换运行服务、不执行迁移，不改依赖版本或仓库锁文件。

隔离检查发现默认 `uv run` 会同步 dev 组并尝试下载 pytest 间接依赖。修正 API CMD 加 `--no-sync`，直接使用构建时已安装的生产依赖；不更改依赖清单或版本。重新构建并验证无网络启动。

- 来源：用户要求构建 nexus-api、nexus-console，tag 使用 prod，并使用国内镜像源。
- 目标：基于当前代码生成本地 `nexus-api:prod`、`nexus-console:prod`，记录镜像 ID、构建配置及验证结果。
- 范围：现有 `docker/Dockerfile` 的国内源构建正确性修复、构建命令、镜像检查、必要的隔离验证和记录；单 Agent 顺序实施。
- 约束：DaoCloud 基础镜像、清华 PyPI、npmmirror npm；锁定版本和完整性哈希不变，仓库锁文件不改写。排除本地环境文件及凭据。
- 禁止：推送镜像仓库、部署或启动常驻服务、数据库迁移或业务数据写入、修改业务合同、改动无关电商样例文件。
- 验收：两个 prod tag 均成功构建；检查镜像架构、入口、端口及生产构建输出；验证镜像内 API 导入、Console 生产产物与依赖；不将隔离构建检查作为连接外部依赖的生产验收。

构建前发现 API 锁文件国内源改写位于完整源码 COPY 之前，会被覆盖；改为 COPY 完成后再改写镜像内锁文件。npm 安装和裁剪显式沿用国内 registry，关闭非必要 audit 网络请求。


## 2026-10-26 重新构建

用户要求按当前代码重新构建两项服务，tag 使用 `prod`。代码基线 `78ce093`，沿用现有工作区 Dockerfile 的国内源修复。Docker daemon 已配置 DaoCloud、阿里云和 USTC mirrors；Dockerfile 明确使用 DaoCloud 基础镜像、清华 PyPI 和 npmmirror。按现有构建方案执行，验证最终镜像的入口、依赖、公开 API schema 和 Console 生产页面。本轮不推送镜像或替换运行服务。构建前补充 `.dockerignore`，排除 gitignore 中已有的私有 `nexus-app/config/data_sync_providers.local.json`；不读取其凭据内容，不改动仓库锁文件。

## 2026-10-28 重新构建

用户再次要求基于当前工作区重建 `nexus-api:prod` 和 `nexus-console:prod`，代码基线 `81823a1`。沿用已有 Dockerfile 和国内源配置：DaoCloud 基础镜像、清华 PyPI（含锁文件下载地址）以及 npmmirror npm。顺序执行两个构建，允许复用未变化依赖缓存；检查镜像标签、平台、入口、API 导入、Console 生产产物和隔离启动。日志保存到 `/tmp/nexus-api-prod-rebuild-20261028.log` 和 `/tmp/nexus-console-prod-rebuild-20261028.log`。本轮范围仍为本地构建和临时隔离验证，不推送、不替换运行容器、不执行迁移。

本轮 Console 镜像检查发现：`COPY nexus-console ./` 会恢复仓库锁文件的官方 npm tarball 地址。补充在源码 COPY 后重新改写构建副本，再执行生产编译，使运行镜像中的锁文件与 npm prune 同样使用 npmmirror；不改仓库锁文件、依赖版本或完整性哈希。

## 2026-10-30 重新构建

用户要求使用本地镜像源重新构建两个服务，tag 使用 `prod`。代码基线 `cfe263f`，包含当前工作区未提交源码；沿用已有 DaoCloud 基础镜像源、清华 PyPI 和 npmmirror npm 配置。单 Agent 顺序构建 `nexus-api:prod`、`nexus-console:prod`，保留依赖缓存，检查镜像平台、入口、API 导入和 Console 生产产物及隔离启动。日志为 `/tmp/nexus-api-prod-rebuild-20261030.log`、`/tmp/nexus-console-prod-rebuild-20261030.log`。范围限本地镜像构建和临时验证，不推送、不替换运行服务、不执行迁移，不改业务代码或依赖锁文件。
