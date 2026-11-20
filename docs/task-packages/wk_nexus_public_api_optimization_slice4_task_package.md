# nexus-public-api 优化单元4：岗位查询 SQL 与分布分析

日期：2026-11-19；单 Agent。继承前三单元未提交工作。用户授权本地实施、真实库只读分析；薪酬选择高薪岗位 TOP 与统一月薪区间分布。

## 目标与边界

依据 ARCHITECT/SPEC 的 raw_jobs 独立业务事实、WORKFLOWS API Contract / Permission And Audit Gate。核对实际字段及执行计划后优化公开岗位查询与聚合，补齐学历×经验、原始行业、采集区域和薪酬分析。保持过滤、分页 total、sample_count、missing_counts、received_to、NULL 组、稳定采集时间排序、原始薪酬与按需来源读取兼容。

允许改动 nexus-api 岗位业务查询/DTO/测试、必要公共 SQL helper、生成工具及 skill 路由/说明、API/架构/需求说明与本单元验证产物。真实 nexus_dev 仅使用强制只读事务与超时；不得启动真实库 lifespan/worker/seed。薪酬规则从实际文本形态确定并在实施前记入下方合同。

禁止修改业务数据、执行迁移、提交/推送/部署、构建或重启服务、处理 embedding、扩大 Console/UI/治理/采集范围、引入基础设施或推断行业标准分类与实际工作城市。禁止绕过认证/返回前 caller 复查/脱敏审计。无企业 IAM、自研 gateway、反向指针或其他架构越界。

## 交付及验证

1. 保存实际库字段分布、索引/约束和 SQL EXPLAIN ANALYZE BUFFERS；使用固定 received_to 比较等价结果与优化前后查询成本，区分 SQL 与 HTTP 延迟。
2. 冻结新增统计合同后实现小范围 SQL 优化及薪酬只读能力，公开 raw 文本与换算/排除口径；不默认带完整溯源。
3. 回归已有过滤、字面通配符、时间窗口、分页/排序、样本/缺失值、空值分组；覆盖薪酬单位/周期/面议/畸形文本/边界及排名稳定性、认证撤销与审计。
4. 同步 OpenAPI 生成工具、skill，隔离数据通过原 skill 执行器验证维度与答案元数据，保存可复核证据。更新 readme/ARCHITECT/SPEC/API 合同和 Review 报告。
5. API Contract 与 Permission And Audit 提供自查证据，人工 Gate 在合并前完成；不以本地测试冒充远端部署验收。

## 冻结统计合同

- 保持 list 默认响应、采集时间 DESC NULLS LAST/id DESC、过滤字面 AND 与来源详情兼容。事实查询缩窄投影，非时间过滤统计省去一对一 provenance join；分页后读取完整行。分组 CTE 一次过滤统计，由分组计数推导分组总数、记录数和各维缺失数，保留 NULL/空字符串的不同组。
- aggregate.group_by 增加 region，已有 education/experience/industry 保留原值，最多三维交叉。region 是采集范围；industry 是企业原始行业文本，不拆分/归并为标准产业，经验字段中的学历等异常值不改写。
- 新增 GET `/open/v1/market-jobs/salary-analysis` / `analyze_market_job_salaries`，同一 JobFilters，top_n=10（1–100）。仅返回轻量 top 岗位事实/ID、固定月薪桶及统计口径，详细来源通过 get_market_job 按需获取。
- 仅解析明确人民币元/k/千/万的正数、闭合区间或单值；显式月薪原值、年薪除12；多薪后缀保留但不摊进月度基础报价。日/时/周/次及无单位、上下开放区间、面议、非法格式等排除并给原因数量。assume_monthly 默认 false；显式 true 才将未标周期文本视作月薪，返回假设影响记录数；不推断工时、天数或币种。
- TOP 按换算后月薪下限 DESC、上限 DESC、id DESC（保守报价排序，非实发/保证收入）；桶按未舍入中点 [0,3000)、[3000,5000)、[5000,8000)、[8000,10000)、[10000,15000)、[15000,20000)、[20000,30000)、[30000,+∞)，边界左闭右开。金额展示两位小数，分组/排序使用 Decimal 未舍入值。matched=eligible+excluded；桶和=eligible；缺失与原因明确，仅已入库记录，不代表招聘人数或全市场。
- 薪酬先 SQL 分组读取不同报价与频次（实际当前1312种），Python纯规则解析；只将 TOP 候选报价回查轻量岗位，不全量下载岗位正文，不新增表/索引/迁移。

## 交付状态

实现与自动验证完成，见[Review证据](../review/nexus_public_api_optimization_slice4_2026-11-19.md)。108项API回归、26项skill测试通过，生成59个工具且分发无漂移。真实库三类查询在固定received_to、同一只读事务中验证结果等价，聚合SQL耗时中位数降低65.70%–79.16%；列表下降2.79%–6.93%，不作为线上HTTP承诺。实际18,308条必要字段复制到隔离SQLite后，原skill执行器21/21次成功；保存完整分组分页和薪酬严格/假设模式证据。

默认薪酬不猜测周期，真实样本全部缺少显式月/年周期；显式月薪假设可纳入17,745条、排除563条，均披露假设影响。原始源值/详情和权限审计合同兼容。无提交/推送/部署/迁移或真实业务数据改动；API Contract、Permission And Audit人工Gate留待合并前。
