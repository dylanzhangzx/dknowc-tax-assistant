# CHANGE_log · dknowc-tax-assistant

## v1.0.4 追加（2026-11-25，渲染内核继承上游「溯源核验报告生成器」1.0.2，未封版）

按上游发布通知整体继承（Dylan 指示：版本号不升；治理约定：不改上游源码目录、不在包内 fork 内核）。

- **内核 5 脚本整体拷贝**（不手改）：`render_trace_html.py`、`build_report_input.py`、`trust_digest.py`、`run_paths.py`、`chart_embed.py`；删除本包旧渲染实现与 `verification.py`（两轨/来源等级/材料类型退出等已由内核承担）。
- **配置**：新增 `reference/trace_report.config.json`（源自上游 config/examples/tax.json：品牌/通道/agent_track/official_host_allow）；渲染统一 `--config` 传入。
- **域内核验对齐 trust_digest 口径**：`verify_claims.py` 落盘 `{verdict, issues, record:{answer_digest, evidence_digest, verdict}}`；答案摘要用角标规范化口径，证据摘要复刻渲染器 renumber 后的 (编号, 源网址) 集合（`_renderer_evidence_items`），两侧同构避免“永远 stale”。
- **工作流**：渲染前先 `build_report_input.py` 转通用 JSON；run 内重跑覆盖同名（交付版本编号由 deliver_outputs 处理），交付文件名 8-20 字短名不带 `_v2`。
- **测试**：继承上游通用版 `tests/test_two_track.py`（62 项）；重写 `tests/test_run_and_verification.py`（运行目录 + trust_digest + record 契约）；`test_source_agency` 改走 build_report_input 管线断言机构口径；新增 `tests/test_pending_upstream_gaps.py` 记录 6 项待上游吸收的税务口径（徽标文案、来源性质四分、DW-0121 研究资料、段落裁剪、--external-data、未定位事实门），上游补齐后自动转断言。
- 全量回归：56 项 unittest（11 项按缺口 skip）+ 62 项内核两轨 + 22 项注册通道；e2e：通过案例「已核验 · AI 验收 5/5」，改答案后拦截“核验记录与当前答案不一致”不产出 HTML。

## v1.0.4 追加（2026-11-24，两轨验收 + 注册通行码，未封版）

按可信搜索 1.8.2 改造清单移植（Dylan 2026-11-24 移交），版本号不变（整改不升号）。

### 两轨自验收（口径层 + 渲染器）

- **不合格不出报告**：`render_trace_html.py` 两轨门禁——结构核验（脚本）∧ AI 验收（Agent）任一轨不过，打印失败原因后 `SystemExit(1)` 不写 HTML；交付物只有“已核验”一种形态。
- **selfCheck 结构化契约**：每项 `{verdict, basis, evidence}`（`agentCheck` 别名兼容，旧字符串写法兼容）；`CHECKABLE_PATTERNS` 识别材料编号/条款号/文号/日期/年份/文件名/GB 标准号，声明“通过”但证据无可回查要素 → `evidence_missing` 按结构违约拦截；`fail` 否决；`pending` 只待复核。Agent 提交了结构化自检时以它为准；未写时若有结论台账则由程序推导（证据指向 tax_verify.json）。
- **结构轨收紧**：正文依据无可展开摘录从软提醒改为硬错误 `missing_excerpt`（`verification.py` 分级表同步）；`only_unofficial` 硬错误按来源等级口径移除。
- **来源等级（香港 MPF 题后口径）**：新增 `is_official_external`（gov 域名正则 + 机构后缀正则，标题判据不用「局/厅/署」单字后缀、机构名带括号可命中）——外部官方信源可作正文依据标「公开网络·官方」，只有正文依据全部为第三方信源才出提醒（软项）。
- **材料类型退出报告**：来源卡去掉类型标签、核验单去掉“材料构成”行、类型不参与统计。
- **`user_facing_text` 改单遍替换**：修掉顺序 replace 级联问题（1.8.2 审核观察①同款）。
- 核验单分「结构核验 / AI 验收」两节，AI 验收明细展示逐项结论/依据/证据（可折叠）。
- SKILL 规则 4.1/4.2/4.3 重写（两轨验收、证据要素、角标要素分挂）；工作流第 6/7 步改结构化 selfCheck + 门禁口径；`answer-and-report.md` 写明 selfCheck 契约与示例；`capability-layer.md`/`troubleshooting.md` 同步。

### 注册通行码通道（对齐公文写作 3.9.9 / 可信搜索 1.8.2）

- `register_key.mjs`：`challenge` 默认走 `agent-registration-key-send` 固定通行码发码通道（一次请求即发码，`flow:"key"`）；原领题路径整体保留，通行码失效/停用自动回落（输出 `keyFallback`）；**限频、号码被拒、供应商失败、结果未确认一律停点不回落**；`--legacy` 显式跳过。
- 发码会话按手机号落盘 `~/.config/dknowc/maas_registration_session.json`（600、10 分钟时效），register 复用、成功清除；通行码通道地址只允许 `platform.dknowc.cn` + 本机回环（`PASSCODE_URL_REJECTED`）。
- **宿主弹窗整改（1.8.2 决策 8）**：`clearChallengeState`/`clearPendingKey`/`clearRegSessionState` 一律写占位覆盖、不再 `unlink`（宿主把删除判成“删除文件”并逐次弹确认）。
- `check_release.py` 新增登记门禁：`REGISTRATION_KEY_ALLOWED` 登记已分配通行码；未登记通行码与未登记高熵长串（字母+数字、≥40）一律拦下。
- `reference/onboarding_scripts.md` S3 改通行码流程；注册通道统一叫「注册通行码」。

### 测试

- 新增 `tests/test_two_track.py`（16 项：证据要素/新旧写法/fail/pending/别名/来源等级/单遍替换/面板/门禁退出）与 `tests/test_register_key_channel.py`（22 项，本地 mock 起服实测发码/限频/白名单/会话契约）。
- 更新 `tests/test_run_and_verification.py`（缺摘录改结构违约、第三方信源提醒、selfCheck 证据门禁等 6 项调整）。
- 全量 76 项单元 + 22 项注册通道实测通过；e2e：通过案例渲染“已核验（AI 验收 5/5 有据）”，证据不足/核验失败案例退出 1 不产出 HTML。

## v1.0.4（2026-11-20，运行目录隔离 + 报告两档核验，未封版）

移植深知可信多引擎搜索 1.0.1 已验收的两项改动，在本 Skill 全部入口落地。

### 运行目录隔离

- 新增 `scripts/run_dir.py`：`--out` 新建运行目录（已存在且非空即拒绝）、`--run` 打开已有运行目录、都不传时在当前工作目录 `runs/tax-<时间戳>/` 自动新建；任何输出拒绝落在 Skill 安装目录（含 `official-docs/`），`--output` 只收裸文件名，同名不覆盖。
- 全部写入入口接入：`tax_search.py`、`merge_search_results.py`、`websearch_convert.py`、`question_profile.py`、`source_cards.py`、`verify_claims.py`、`render_trace_html.py`、`deliver_outputs.py`。
- `path_guard.py` 改为「输入可读任意处、输出拒绝 Skill 目录」；删除默认创建 `official-docs/search-results`、`official-docs/output` 的行为。
- `render_trace_html.py` 去掉硬编码 skill-root IO：输入优先从 `--run` 目录取，输出写运行目录；同题重跑 `_v2` 另存。
- `deliver_outputs.py` 只从运行目录收 HTML，拒绝 Skill 目录内的源文件。
- 打包排除运行产物（`tests/`、`official-docs/`、`outputs/` 本就不入包）；`__pycache__` 打包忽略。

### 报告核验两档

- 新增 `scripts/verification.py`：硬错误 / 软提醒分类、答案/证据/画像摘要、`build_verification_state`。
- 报告只保留 **已核验 / 核验未通过**：只有硬错误（无出处、核心结论无角标、仅非官方来源、金额/对象不一致、原文不支持、标准过时、措辞风险、关键数字缺失、废止/旧文号无依据、校验失败、记录过期、阻塞缺口、absence 断言）才判未通过；无摘录、缺链接、时效提示、无关候选、语义待复核等软提醒不改结论。
- `verify_claims.py` 写入 `answer_digest`/`evidence_digest`/`profile_digest`；答案、材料或画像改动后旧记录自动判 `stale_verification`，强制重核。
- `render_trace_html.py` 传 `--verify-file` 时五项自检由校验记录推导，不采信手写 selfcheck；不传按“核验未通过：未执行事实核验”处理。`claim_verified` 只在硬错误时 `False`；`no_excerpt` 显示“待补摘录”，不显示“引用未通过核验”。来源卡表格不截断。
- 交付红线：`outputs/` 只放 HTML；不复制 `answer.md`/`v1_report.md`；交付清单不含 `.md`。

### 报告样式对齐多引擎 1.0.1

- `render_trace_html.py` 整体套用可信多引擎搜索 1.0.1 的报告视觉：来源卡、段落分块、角标、知识专库（`lib-unused` 折叠未引用材料、单组检索隐藏重复 tab）。
- 正文引用改为 `sup.cite` 可点击编号，点击弹出「引用依据」弹层（`cite-modal`，含遮罩、Esc/点遮罩关闭、移动端底部弹出）；不再内联展开 jb 标题/摘录胶囊。表格单元格同一套角标。
- 知识专库未进入正文的召回材料收进「未进入正文的参考材料」折叠区；有外部材料时页脚改为来源性质提示。
- 新增回归：`tests/test_run_and_verification.py` 增加正文/表格角标样式 2 项（共 56 项）。

### 顺带修复

- `source_cards._infer_jurisdiction`：发布机关为中央部委/总局时直接判“全国”，修复中央公告被地方门户转载时误判地方来源、导致全国结论校验失败的问题。

### 测试与验证

- 新增 `tests/test_run_and_verification.py`（15 项）；`tests/test_capability_layer.py` 的 PathGuard 用例改为运行目录口径（16 项）。
- 全量 54 项通过：capability 16、test_fixes 14、initialize 4、source_agency 5、run_and_verification 15。
- 真实接口端到端（增值税小规模免征）：检索 → 画像 → 材料 → 校验 pass → 渲染“已核验”；改答案后渲染自动“核验记录已失效”；错误引文校验 fail → 渲染“核验未通过”，来源卡均标“引用未通过核验”；全部产物只落 `/tmp/tax_e2e/runs/*`，Skill 安装目录无新增文件。

## v1.0.3（2026-11-12/13，测试反馈修复 + 来源展示口径，未封版）

### 来源展示口径同步（2026-11-13）

按 Dylan 授权口径（与深知公文写作 3.9.7 对齐）：来源卡不再展示“数据源”，统一展示“发布或实施机构”。

- `render_trace_html.py`：`agency` 只取「发布或实施机构 → 发布机关」；删除 `unit`/`sourceElement`/`数据源`/`来源`/站点名回退，缺失留空，不从标题前缀推导。
- `source_cards.py`：`issuer` 只取「发布或实施机构 → 发布机关」，不再回退 `数据源`。
- `merge_search_results.py`：`_to_article` 透传 `发布或实施机构`（此前合并后会丢，渲染层只能拿到站点名）。
- `websearch_convert.py`：新增 `ISSUER_KEYS`，将 `publisher/issuer/organization` 原样透传为 `发布或实施机构`；`数据源` 仍保留站点名。
- `reference/answer-and-report.md`：引用模板明确“政策依据用「发文机构：XX」，数据支撑用「来源：XX」，不写「数据源：XX」”；`reference/capability-layer.md` 同步 issuer 口径。
- 新增 `tests/test_source_agency.py`（5 项）：渲染/材料画像不回退、merge 透传、WebSearch 转换透传。
- 版本号保持 1.0.3；**未封版时版本号不递增，仍正常出 zip 送审**；通过审核后再交 public 会话做渠道对齐。

### 测试反馈修复（2026-11-12）

修复杨艳慧《深知MaaS新接口测试报告 V1.0》§五 税务三条：

- **DW-0118** `check_answer.py`：「税率/征收率/速算扣除/扣除标准/起征点」不再按关键词触发；改为命中具体数字（`%`、百分之、个点、元金额）且同一行没有年度（`20xx年`）或文号（`〔20xx〕`/`第x号`/`公告x年第x号`/`财税〔`）才拦。假设句「取决于所适用的税率档」不再误报；无出处的具体税率仍会被拦。
- **DW-0119** `tax_search.py`：`--search-channel webSearch` 阶段二无条件写 `数据权威性=非权威`，不再依赖接口 dataAuthority（可能返回“权威”）。`source_cards.py` 增加 `data_authority`（外部材料强制非权威）、`source_nature_status=explicit/inferred`、`library_material`，并在“外部材料被接口标权威”或“来源性质无法判定”时输出 warnings。
- **DW-0121** `render_trace_html.py`：研究资料解析支持三级及以下小标题下的表格、`-/*` 列表；二级标题才重置当前节；解析 0 项时返回 `parsed=false` 与 warnings，CLI 打 warning，过程条显示“研究资料未解析”，不再静默输出 0。
- **DW-0122** `initialize.py`：Key 校验从 format-only 改为“格式检查 + 轻量真实检索校验”（`policies/filter`，limit=1，8 秒超时）。401/403 → `ready=false`、`blocking_issues=["api_key_invalid"]`；网络超时/5xx → 降级放行、`key_validated=false`；新增 `--no-verify-key` 跳过。`tax_client.filter_policies` 增加 `timeout` 参数（默认仍 60 秒）。实测正常网络校验约 0.9–1.0 秒，失效 Key 约 70–120 毫秒返回 403。
- **DW-0125** SKILL.md 删除对 `CHANGE_log.md` 的引用；目录说明不再把 `check_release` 列为包内脚本，改为“评测工具与测试集、发布检查脚本与变更记录由维护仓库保存，不入 skill 包”。`check_release.py` 新增包内文档自洽检查：SKILL/reference 中指向 `scripts/`、`reference/`、`resources/` 的文件必须存在；出现 `CHANGE_log.md`/`README.md` 引用直接失败。全量扫描确认其余显式引用均在包内。
- **审核建议修复（2026-11-13）**：① 税率类数值规则不再把年份当出处——仅 `20xx年` 仍会告警，需文号或《文件全称》；② 研究资料空表（只有表头+分隔行）不再计 1 项，`parsed=false` 并告警；③ 含具体数字的假设句（假设/若/如果/试算/举例等）不再按“断言税率”告警。
- 新增 `tests/test_test_fixes_20261112.py`（14 项）与 `tests/test_initialize_key.py`（4 项）；原能力层 15 项回归仍通过。
- 版本号按 Dylan 指示升至 1.0.3；**本轮不封版、不打包、不发布**。

## v1.0.2（2026-11-11）

### 渠道包整改（A 轨 9 渠道 + skillhub 基线）

- 按 skill审核 2026-11-11 渠道包审核报告整改，版本号由 1.0.1 升至 1.0.2（2026-11-11 决策）。
- 移除公开包内真实人名表述（`reference/websearch-fallback.md`、`scripts/render_trace_html.py` 共 2 处），改为「口径确认」。
- 修正 `scripts/attribution.py` 声明示例：由另一产品/旧版本/主渠道改为 `agentSource=dknowc-tax-assistant;version=<版本>;channel=<渠道>`。
- onboarding 隐私话术对齐同系列产品：统一为「验证后只在本机保存一个访问凭证」，删除原有矛盾表述；初始化引导同步为「注册检索账号 + 发送注册验证码」口径。
- 渠道命名对齐深知可信搜索 public 版：WorkBuddy slug 去后缀（frontmatter name 保留 `-workbuddy`）；modelscope/scnet/skills-sh/xiaohongshu 的 zip 顶层目录去后缀。
- 构建器新增大小写不敏感的 `skillhub` 字样检查；清理包内跨产品施工痕迹。
- 9 个渠道包与 skillhub 基线统一重建为 v1.0.2；包结构、渠道码、注册契约不变。

## v1.0.1（2026-11-10）

### 能力层接入（同日补充，版本号不升）

对齐深知法律助手的四层能力链路，接入税务检索→答案→报告流程：

- 新增 `scripts/question_profile.py`：地域/时点/领域 + 税务维度（税种、纳税人身份、优惠事项、申报期、政策年度、文件类型、用户诉求），输出 `tax_question_profile.json`；
- 新增 `scripts/source_cards.py`：材料画像（地域、机关、文件类型、来源性质、来源通道、抓取状态、税种），输出 `tax_source_cards.json`；
- 新增 `scripts/calc_tax.py`：滞纳金（含首尾/算头不算尾）、不含税计税、含税价税分离、减免额四种口径，金额 Decimal 四舍五入到分；通用日期/利息仍用 `calc_period.py`；
- 新增 `scripts/verify_claims.py`：结论图通用校验（地域/税种/时点/来源等级/逐字引文/枚举数/计算重算/否定截止日/推断限定词/外部来源性质/争议两解/答案锚点），`verdict` 非 `pass` 不得出报告；新增 `path_guard.py` 限定读写路径；
- 新增 `reference/capability-layer.md` 与 `reference/tax_claims.example.json`（direct/calculation/negative/external/inference/interpretation 六类示例）；
- SKILL.md 新增规则 4.2（交付前过结论图校验）与工作流画像/材料/结论/校验步骤；
- 来源标签语义对齐（与深知法律助手一致）：内部 `非官方来源=true` 仅表示库外材料，不等于网站不官方；用户可见标签改为 `外部公开材料 · 政府网站/官方媒体/次级媒体/未知`（渲染器按发布机构/域名判定），正文提示条、核验结论、自检词表同步；
- 新增 `tests/test_capability_layer.py`（15 项：画像、材料、校验正反例、路径白名单）。
- 审核整改（同日）：① `direct` 增加来源地域校验，全国 claim 引用地方来源直接失败；② `calculation` 必须写回工具结果（滞纳金 `days/amount`、不含税 `tax`、含税 `base/tax`、减免 `relief`），只写输入不通过；③ `source_cards` 显式来源性质优先，`来源性质=次级媒体` 即使漏标 `非官方来源` 也不再判为官方库/official；④ SKILL.md 规则 4.2 改为所有交付报告任务强制走结论图校验，消除与步骤 6 的适用条件冲突。
- 版本号保持 1.0.1；SkillHub 包与 public 源同步重建。
- 能力层终验（2026-11-10）：**通过，可发布**（0 阻塞 / 0 重要 / 0 建议；15/15 测试、包体 SHA256、33 文件逐字节一致、编译/node/check_release/路径白名单/敏感信息扫描均通过）。

### 联网降级同步

- 联网前确认（2026-11-10，对齐深知法律助手）：用 `tax_search.py --file "文件全名"` 走 001 全文兜底做库内确认——命中取全文，找不到或只命中旧版才联网；新增"最新/2026/现行"版本敏感规则（库内旧版不能当现行，须联网核新文并写明版本差异）。取消早期 `--confirm` 方案。

同步深知可信搜索 1.7.2 的三阶段联网降级机制（口径确认：可使用 WebSearch，但溯源核验报告必须做好标记）：

- `tax_client.semantic_search` 新增 `search_channel` 参数（searchChannel 单值 webSearch/govSearch/wxSearch）；
- `tax_search.py` 新增 `--search-channel`（阶段二入口），联网路自动补 `非官方来源=true`、`检索通道=深知税务检索·联网`，且不使用 policyLabels（联网页无库内标签）；
- 新增 `scripts/websearch_convert.py`（宿主 WebSearch 原始结果 → 通用材料形态，标 `非官方来源/非权威/宿主 WebSearch`）；
- SKILL.md 新增规则 4.1（库内不足才联网、外部材料标注、法定要素红线、用户可见词禁令）与工作流阶段二/三；
- 新增 `reference/websearch-fallback.md`（三阶段细则、税务红线三档、标注规范、禁止事项）；更新 retrieval-v2（0 条→降级）、answer-and-report（外部材料自检）、troubleshooting（联网异常）；
- 报告标记沿用同源渲染层：`非官方来源` 徽标 + `数据权威性=非权威` 双口径 + 正文页"本页部分材料来自公开网络"提示条。



- 对外版本统一 1.0.0（SKILL.md / 包名 / 本文件一致）；仅出 SkillHub 包。
- SKILL.md 标题改为"深知税务助手（SkillHub Public 版）"；description_zh 按"面向谁→能查/能算/能核→凭什么可信→交付形态→提供方"结构与知识库文章对齐。
- 注册脚本新增敏感参数 `--phone-file` / `--vcode-file` / `DKNOWC_PHONE` / `DKNOWC_VCODE`（避免手机号、验证码明文进 argv）；initialize.py 增加 register_key.mjs 存在性检查与 register_ready 判定。
- 包结构对齐深知可信搜索/法律助手：源码在 public/skillhub/dknowc-tax-assistant/，成品 package/dknowc-tax-assistant-skillhub-v1.0.0.zip，zip 顶层 dknowc-tax-assistant/，仅含 SKILL.md、attribution.json、scripts/、reference/、resources/；不含 README、CHANGE_log、check_release、eval、official-docs、__pycache__、.DS_Store。
- 发布审核整改（同版本 1.0.0）：① 新增 `resources/THIRD_PARTY_NOTICES.md`（Apache ECharts / Apache-2.0 归属声明）；② 产品文档《Skill 介绍》正式版与知识库文章、description_zh 三点统一（575 字符逐字一致）；③ `--phone-file`/`--vcode-file` 文件不可读或为空时回退环境变量（DKNOWC_PHONE / DKNOWC_VCODE），修复环境变量被忽略的问题。

## v0.1.3（2026-11-06，复核对齐轮）

第二轮复核"有条件通过"（4 条件全关），新发现 2 处文档与实现不符并修复：SKILL.md 规则 10 与 README 安全约束不再声称"注册链路只写 Key 配置文件"，改为列全实际写盘范围（Key 配置文件、maas_client_instance、maas_agent_challenge.json、失败时的临时保管文件，均 0600 及各生命周期）。

## v0.1.2（2026-11-06，复审 4 条件修复轮）

复审"有条件通过"后修复 4 项条件：① persist 恢复路径打通——register 写盘失败时 Key 落 0600 临时保管文件（30 分钟有效），persist 自动从保管文件恢复落盘、成功即删（pendingKeySaved/recoveredFromPending 字段 + 文档指引同步）；② frontmatter 权限声明补齐 attach.dknowc.cn（网络）与 maas_client_instance、题目状态文件、临时保管文件（本地读写）；③ 下载白名单收紧为 exact-host（仅 open/attach.dknowc.cn + 443 + 拒绝 userinfo，与法律助手 0.3.9 同口径）；④ 手机号口径如实化（argv 传递 + 题目状态文件临时保存 0600、完成即清理，文档不再声称"不写入任何文件"）。另：check_release 外部目录规则补 04/07/99 前缀；产出提交包 dknowc-tax-assistant-skillhub-v0.1.2.zip。

## v0.1.1（2026-11-06，skill审核整改轮）

首轮外部审核驳回（6 阻断 + 10 重要）后逐项修复：

- **阻断**：① frontmatter 补齐 name/slug/display_name/description×3/category/permissions（network/local_read/local_write）/secrets，对齐同仓库 SkillHub 包规范；② register_key.mjs 换用 2026-11-04 平台口径版（register 不再传 type:"11"），适配本 skill 身份与 SkillHub 注册渠道码；③ 注册输出任何情况不再输出明文 Key（原来写入失败时回退明文），成功话术与实际持久化状态一致；④ 全文下载地址白名单校验（https + *.dknowc.cn 才携带 api-key 请求）；⑤ 开通文档注册命令改为脚本实际签名（challenge --phone / answer --phone --answer / register --phone --vcode / persist）；⑥ tag_catalog.py 去除内部人名。
- **重要**：initialize Key 校验口径如实标注 format-only + 长度检查、node 版本检查（≥18）；api_key.py 支持 DKNOWC_CONFIG_DIR（与注册脚本对齐）；Key 落盘改临时文件+原子替换+强制 0600；onboarding 手机号口径如实（argv 传递、对话脱敏）；清除包外路径引用与内部实测编号；全量标签清单/eval/运行落盘移回维护仓库；check_release 加固（eval 目录、包外路径引用、CHANGE_log 不再跳过扫描）；各处 dnowc→dknowc 笔误修正。

## v0.1.0（2026-11-06）

首个版本，基于深知法律助手 v0.3.3 脚本资产改造 + 税务场景重写：

- **接口层**：`tax_client.py`（从 legal_client.py 改名，TaxApiError、`_tax_label_zero`；五接口路径与参数不动）。
- **检索层**：`tax_search.py` 重写——V2 `--query` 主路（标签短名自动解析、发文字号→文号映射、label_zero 不降级）；`--file` 全文兜底（条件筛选→副本挑选→正文→下载，超长截断如实标注）；**删除法条切分逻辑**（税务不需要）。
- **评测**：`eval/questions.jsonl` 12 题测试集（个税×2/增值税×2/企税×2/征管×2/优惠×2/社保×2）；`run_tax_eval.py` A/B×3 评测。结果：B 臂 12/12 目标命中、186/186 文章带所传标签；标签过滤波动复现 1 次（冒烟 0→5）；年度混排实测（单次最多 8 个年份）。
- **措辞检查**：`check_answer.py` 税务版（税率/征收率/速算扣除/扣除标准年度检查、滞纳金口径、社保基数上下限、小型微利三条件、免征限定词）。
- **reference/**：retrieval-v2（检索前必读）、retrieval-policy（全文兜底）、tags（围栏不是分类）、answer-and-report、troubleshooting、onboarding_scripts。
- **渲染/交付**：render_trace_html.py 品牌改税务（复用法律助手渲染层，无法条切分依赖）；merge/deliver/initialize/attribution/api_key 直接复用，initialize 话术改税务口径。

## v1.0.4 追加（2026-11-25，全面接受内核 1.0.2 口径，Dylan 决策）

继承上游内核后遗留的 6 项税务侧差异，按 Dylan 指示**全部接受 1.0.2 标准**落地（对齐法律助手 1.0.4 同款处理），不再挂"待上游缺口"：

- **来源徽标**：采用内核默认文案——官方信源（gov 域名/官方机构）标「公开网络·官方」，其余外部标「非官方来源」（含义：非深知库内材料）；正文提示条为内核自带（"本页部分材料来自公开网络第三方信源…"）。SKILL 4.1 与 reference 各文档撤下「外部公开材料 · 四分」与"非官方来源"禁词（该词现为正式徽标用语）；禁词保留"阶段一/二/三""可信联网""宿主 WebSearch"。
- **来源性质四分**：`source_nature`（政府网站/官方媒体/次级媒体/未知）降为内部画像字段（verify_claims 判级与提醒用），不再要求用户可见。
- **引用块弃用**（对齐法律 1.0.4 决策）：答案正文不写 Markdown `>` 引用块（内核无此分支，会渲染出字面 `>`）；原文由角标「引用依据」弹窗/材料卡回看；claim 的 `quote` 逐字校验保留在 verify_claims。
- **段落裁剪退出**：材料卡展示召回的全部段落（内核无裁剪）。
- **--external-data 退出**：税务从未使用；如需 LPR/汇率类数据，写进正文并角标挂来源材料。
- **研究资料**：按内核 1.0.2 解析器口径（「事实/口径」关键词二级标题分节 + 表格行统计）；写法约束写入 troubleshooting（表格直接放二级标题下、不用列表、不套三级小标题）。
- 删除 `tests/test_pending_upstream_gaps.py`；`test_test_fixes_20261112` 研究资料用例改按 1.0.2 行为断言；全量回归 47 项 unittest + 62 项内核两轨 + 22 项注册通道通过。

## v1.0.4 追加（2026-11-25，审核阻断 X15 修复，未封版）

- **X15（审核阻断）**：`register_key.mjs` 的 `genPassword()` 从 `Math.random()` 改为 `crypto.randomInt`（CSPRNG），与可信搜索/法律/咨询/PPT 五产品同款；选字符与洗牌两处均改。`tests/test_register_key_channel.py` 新增静态回归（代码行不得出现 Math.random、必须用 randomInt），防止回潮。
