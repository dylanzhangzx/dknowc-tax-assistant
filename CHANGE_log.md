# CHANGE_log · dknowc-tax-assistant

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
