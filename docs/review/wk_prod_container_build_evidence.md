# prod 容器镜像构建记录

## 2026-11-03 重新构建结果

代码基线 `cfe263f`，纳入当前工作区的行业法规标准分类、资产中心/治理审核顺序和资产计数性能优化。使用现有 DaoCloud 基础镜像、清华 PyPI（含镜像内锁文件包地址）和 npmmirror npm。本机 Docker daemon mirrors 为 DaoCloud、阿里云、USTC。两个构建均 exit 0，复用未变化依赖缓存；仓库锁文件未改写。

| 镜像 | 平台 | 最终镜像 ID | 本地镜像大小 |
| --- | --- | --- | --- |
| `nexus-api:prod` | linux/amd64 | `sha256:530102b5510ee69b2bcac4573b8117c3864be86817a6273db4baedf1e64258e5` | 500,126,131 bytes |
| `nexus-console:prod` | linux/amd64 | `sha256:fe88386486590ef54f10de01e8af14aab06ab9b695deb35eb6f831a018876faf` | 1,337,558,850 bytes |

构建日志：`/tmp/nexus-api-prod-rebuild-20261103.log`、`/tmp/nexus-console-prod-rebuild-20261103.log`。

本轮检查与修复：

- API 最初构建通过，但额外无网络检查发现默认 `uv run` 会尝试安装 dev 组中的 pytest/pygments。修正 Dockerfile 的 CMD 为 `uv run --no-sync uvicorn ...`，直接使用构建时冻结安装的生产依赖；最终重建复用原依赖层，标签指向上表 ID。
- API 无网络临时容器成功导入应用并生成 256 个 OpenAPI path，包含法规标准列表和资产中心计数。缓存类、每应用缓存实例、行业法规标准迁移文件均存在；引擎实际池大小为 10+20。Python 3.11.18、FastAPI 0.136.1。
- API 进一步以实际最终 CMD 在无网络临时容器内启动 uvicorn，使用隔离 SQLite、关闭 Worker 并允许缺省注册表，仅在容器内部请求 `/v1/health`，返回 200。没有使用开发库或生产依赖连接。
- API 镜像内两个锁文件使用清华源，检查的 `.env*` 和私有 Provider 配置未进入镜像。
- Console Next.js 16.4.1 生产编译、TypeScript、15 个静态页面生成与生产依赖裁剪通过。Node v24.22.2，BUILD_ID `Z7Z8-Z-Dqaub858yXSRgp`。
- Console 无网络临时容器启动 Next.js 生产服务，容器内部 `/login` 返回 200 且含 NEXUS；锁文件使用 npmmirror，vitest、`.next/cache` 与 `.env*` 不存在。
- API/Console 分别暴露 8000/3000；隔离验证没有宿主机端口映射，验证进程正常结束，`--rm` 容器自动清理。仅重建本地镜像，未推送或替换运行服务，未执行迁移。外部数据库、MinIO、LiteLLM 的业务验收不在本轮隔离验证范围。
- Console 出现已有 middleware → proxy 迁移提示，未阻断构建。`git diff --check` 通过。

日期：2026-10-23。任务包：`docs/task-packages/wk_prod_container_build_task_package.md`。

代码基线：`4609358`；另含本次 `docker/Dockerfile` 国内源正确性修复，尚未提交。

## 构建结果

| 镜像 | 平台 | 镜像 ID | 本地镜像大小 |
| --- | --- | --- | --- |
| `nexus-api:prod` | linux/amd64 | `sha256:a8973f362f0e2956d47356ab7c64aff882186912da3b603bd22a41188923a483` | 498,413,073 bytes |
| `nexus-console:prod` | linux/amd64 | `sha256:06d65279e3b6b0bca217ef1d51edf0681837a7ac1c3e33cb86ce0dc76b365d73` | 1,336,305,551 bytes |

基础镜像及 Dockerfile frontend 均使用 `docker.m.daocloud.io`；PyPI 使用 `https://pypi.tuna.tsinghua.edu.cn/simple`，下载包地址使用同站点 `/packages/`；npm 使用 `https://registry.npmmirror.com`。

```bash
docker build --progress=plain \
  --build-arg DOCKERHUB_MIRROR=docker.m.daocloud.io/library \
  --build-arg PYPI_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  --build-arg PYPI_PACKAGE_BASE_URL=https://pypi.tuna.tsinghua.edu.cn/packages/ \
  --target nexus-api -t nexus-api:prod -f docker/Dockerfile .

docker build --progress=plain \
  --build-arg DOCKERHUB_MIRROR=docker.m.daocloud.io/library \
  --build-arg NPM_REGISTRY=https://registry.npmmirror.com \
  --target nexus-console -t nexus-console:prod -f docker/Dockerfile .
```

完整本地日志：`/tmp/nexus-api-prod-build.log`、`/tmp/nexus-console-prod-build.log`。

## 修复与验证

- API 原 Dockerfile 对锁文件改写国内源后，又用完整源码 COPY 覆盖锁文件。现将 COPY 前移，再改写镜像内锁文件，仓库锁文件及完整性哈希不变。
- npm 安装和生产裁剪显式使用指定国内 registry，关闭非必要 audit 请求；npm 锁文件下载地址替换使用 registry 构建参数。
- API 构建通过 `uv sync --frozen --no-dev`；无网络临时容器成功导入 `nexus_api.main.app`（265条路由，FastAPI 0.136.1）。检查两个镜像内 Python 锁文件，均不再包含官方 PyPI 索引和包下载地址；`/app/.env` 未进入镜像。
- Console 的 Next.js 16.4.1 生产编译、TypeScript 检查和页面生成通过；生产依赖裁剪成功。构建仍提示既有 `middleware` 文件约定迁移到 `proxy` 的非阻断警告，本任务未扩展到路由迁移。
- Console 无网络临时容器在自身回环地址启动生产服务，`GET /login` 返回200，正文包含 NEXUS；生产 BUILD_ID 为 `eIKy9_9QoepN7lsOV7Xob`。确认开发依赖 vitest 已移除、`.env` 未进入镜像。
- 临时验证容器无宿主机端口映射，结束时正常停止并自动删除。未执行连接数据库、MinIO、LiteLLM 等外部服务的业务验收；未推送镜像仓库或部署服务。
- `git diff --check` 通过。


## 2026-10-26 重新构建结果

代码基线：`78ce093`；使用现有工作区 Dockerfile 国内源修复，并补充 `.dockerignore` 排除本地私有 `nexus-app/config/data_sync_providers.local.json`。未改仓库锁文件。

| 镜像 | 平台 | 镜像 ID | 本地镜像大小 |
| --- | --- | --- | --- |
| `nexus-api:prod` | linux/amd64 | `sha256:5378c1b39fe0aaf2321b0612326919055007e2c845f81d04b72b49f998249677` | 499,985,271 bytes |
| `nexus-console:prod` | linux/amd64 | `sha256:12ee160237e71e52e581b8c898dd03cbe428bf885fdf2f47d72a86b25472ec91` | 1,336,628,754 bytes |

使用上述同款构建命令和国内源：DaoCloud Dockerfile frontend 与 Python/Node 基础镜像、清华 PyPI（含锁文件包 URL）、npmmirror npm；本机 Docker daemon 另配置 DaoCloud、阿里云和 USTC mirrors。两个 build 命令均 exit 0，最终标签与 image inspect 一致。复用未变化依赖缓存，API 源码层和 Console 生产编译重新执行。

本轮日志：`/tmp/nexus-api-prod-rebuild-20261026.log`、`/tmp/nexus-console-prod-rebuild-20261026.log`。

验证结果：

- API 无网络临时容器导入通过：Python 3.11.17、FastAPI 0.136.1；检查 OpenAPI 的 253 个 path，确认岗位 list/aggregate 的 `region` 及教学标准 `occupation` 参数已包含。
- API 两个镜像内锁文件仅使用国内 PyPI URL；本地私有 Provider 配置和 `.env*` 未进入镜像。
- Console 生产编译、TypeScript 和静态页面生成通过，生产依赖裁剪成功；Node v24.22.1、Next.js 16.4.1，BUILD_ID `8TDacJF-GN754_4nIyxXp`。
- Console 无网络临时容器在容器自身回环地址启动，`GET /login` 返回 200 且含 NEXUS；vitest 开发依赖和 `.env`/`.env.dev` 不存在。
- 所有验证容器使用 `--rm --network none`，无宿主机端口映射，检查完成自动退出；未替换本地运行服务、未推送镜像、未连接数据库或执行迁移。
- `git diff --check` 通过；本轮构建配置和证据修改未提交。

## 2026-10-28 重新构建结果

代码基线：`81823a1`，基于当前工作区构建。沿用已有 Dockerfile 和 `.dockerignore`，本轮补充 Console 源码 COPY 后重新改写构建副本锁文件的 npm 下载地址；仓库锁文件、版本和完整性哈希未改动。

| 镜像 | 平台 | 镜像 ID | 本地镜像大小 |
| --- | --- | --- | --- |
| `nexus-api:prod` | linux/amd64 | `sha256:384bbd75b578fbacb6b79e55cd49f7b742b2d386a0352464134d9759b2547b4f` | 500,046,610 bytes |
| `nexus-console:prod` | linux/amd64 | `sha256:ce1200a5a7ae83f93caa086205410c0d4c9ce85960cbf19cf00e32ef7211af9a` | 1,336,742,946 bytes |

国内源：

- Dockerfile frontend：`docker.m.daocloud.io/docker/dockerfile:1.7`；
- 基础镜像：`docker.m.daocloud.io/library/python:3.11-slim`、`docker.m.daocloud.io/library/node:24-bookworm-slim`；
- Python 索引及包下载：`https://pypi.tuna.tsinghua.edu.cn/simple` 和同站点 `/packages/`；
- npm 安装、生产裁剪及镜像内锁文件：`https://registry.npmmirror.com`。

两个最终 build 命令均 exit 0。API 安装 60 个锁定依赖；Console 的依赖安装、生产编译、TypeScript 检查、15 个静态页面生成和生产依赖裁剪通过。

本轮日志：`/tmp/nexus-api-prod-rebuild-20261028.log`、`/tmp/nexus-console-prod-rebuild-20261028.log`。

验证结果：

- API 无网络临时容器导入 FastAPI 应用并生成 OpenAPI，包含 253 个 path 和 `/v1/health`；Python 3.11.18、FastAPI 0.136.1。
- API 镜像内两个锁文件都使用清华源，不含官方 PyPI 索引和包下载地址；检查的 `.env` 和私有 Provider 本地配置不存在。
- Console 最终镜像的 npm 锁文件包含 npmmirror，不含 `https://registry.npmjs.org/`；vitest、`.next/cache` 及检查的 `.env*` 文件不存在。
- Console Node v24.22.1、Next.js 16.4.1，BUILD_ID 为 `dg8w-ZChWjXCgxVOk-_Ar`。
- Console 最终镜像在 `--rm --network none` 临时容器内启动生产服务，内部 `GET /login` 返回 200 且正文包含 NEXUS；无宿主机端口映射，校验结束停止进程并自动删除容器。
- 已有的 `middleware` 到 `proxy` 迁移提示为非阻断警告。未执行数据库、MinIO、LiteLLM 等外部依赖的业务验收。
- 本轮仅重建本地镜像和隔离验证，未推送仓库、未替换现有运行容器、未执行数据库迁移。

## 2026-10-30 重新构建结果

代码基线：`cfe263f`，包含当前工作区未提交源码。沿用现有 Dockerfile 和 `.dockerignore`，本轮未改构建配置、业务源码或仓库锁文件。

| 镜像 | 平台 | 镜像 ID | 本地镜像大小 |
| --- | --- | --- | --- |
| `nexus-api:prod` | linux/amd64 | `sha256:2ae9b08a776d3104347ac7dbbdd1cc7aa9a8c29217be82a2c60dc548f5fd443b` | 500,088,133 bytes |
| `nexus-console:prod` | linux/amd64 | `sha256:12280544217b364cc364e4ffd787b9b1d1955e34677eb72ec1b7f9d59c22f4c6` | 1,337,540,747 bytes |

构建沿用本文的 `docker build --progress=plain` 命令，显式指定 DaoCloud 基础镜像源、清华 PyPI 索引和包地址、npmmirror npm；两个构建均 exit 0。日志：`/tmp/nexus-api-prod-rebuild-20261030.log`、`/tmp/nexus-console-prod-rebuild-20261030.log`。

验证结果：

- API 镜像平台、8000 端口和 uvicorn 入口正确；无网络临时容器成功导入应用并生成含 `/v1/health` 的 255 个 OpenAPI path。Python 3.11.18、FastAPI 0.136.1。
- API 镜像内两个锁文件使用清华源，不含官方 PyPI 索引和包下载地址；`/app` 下没有 `.env*` 文件，私有 Provider 本地配置未进入镜像。
- Console 生产编译、TypeScript 检查、15 个静态页面生成和生产依赖裁剪通过；3000 端口和 Next.js 生产入口正确。Node v24.22.2、Next.js 16.4.1，BUILD_ID `b1fcttayhDfj7AyUbWY2n`。
- Console 最终锁文件使用 npmmirror，不含官方 npm 下载地址；vitest、`.next/cache` 和检查的 `.env*` 文件不存在。
- Console 无网络临时容器在容器自身回环地址启动，`GET /login` 返回 200 且正文包含 NEXUS；验证结束停止进程，容器自动删除，无宿主机端口映射。
- 构建出现既有 middleware 迁移提示以及 npm 对 msw、unrs-resolver 安装脚本的提示，均未阻断构建或隔离启动验证。
- 本轮仅构建本地镜像及隔离验证，未推送、未替换运行容器、未执行迁移或连接外部依赖的业务验收。
