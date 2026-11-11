# 答案与报告规范（answer-and-report）

## 答案结构（固定五段）

1. **结论**：一两句话直接回答；写明适用纳税年度（如"2023 年 1 月 1 日至 2027 年 12 月 31 日期间…"）。
2. **适用条件**：身份（小规模/一般纳税人/居民个人）、金额标准、行业、期限、例外；逐条列。
3. **政策依据**：文件全称 + 文号 + 发布日期 + 条款/段落，每条挂角标 `[n]`；文号缺失的镜像副本降级标注（只写标题+日期+源网址）或换带文号副本。
4. **算例**（如涉计算）：逐项写出公式与数字；税率表/速算扣除数标年度与文件依据；提交前重算一遍。
5. **需要你确认**：用户没给但影响结论的事实（收入构成、扣除项目、是否预缴、纳税年度、所在地）。

## 措辞红线

- 原文与解释分开：条文没有的推论必须标"按通常口径"或删除；
- 绝对化表述（只能/唯一/一定/全部/一律/一旦…）要么有封闭列举依据，要么改写；
- 0 条写"本次未召回"，不写"无相关政策"；
- 版本措辞不进交付：不写"版本待复核""库内标记失效"，用"该文件发布于 X 年 X 月，适用以最新公告为准"这类用户语言；
- 地方口径：没有当地文件时写"以当地税务机关/社保经办口径为准"，不把某地做法推广到全国。

## 生成前强制检查

```bash
python3 scripts/check_answer.py \
  --answer official-docs/search-results/tax_<任务>_answer.txt \
  --selfcheck official-docs/search-results/tax_<任务>_selfcheck.json
```

退出码 0 才继续；命中项改写，或在 selfcheck 的 `absolute_review` 按行号逐条说明（对象，键=行号）。注意管道会吞退出码，直接跑、别接 `| tail; echo $?`。

## 自检五项（写入 selfcheck JSON）

`fact_basis`（每个结论有材料依据）/ `binding`（引用绑定到载有该依据的材料）/ `consistency`（结论间无矛盾）/ `freshness`（年度/时效已核对，引用的是目标年度口径）/ `no_gap`（用户问题无遗漏子问题）。

外部材料（阶段二联网/阶段三宿主 WebSearch）相关自检：
- 外部材料不得单独支撑核心结论；核心结论仅有外部公开材料时，`fact_basis` 记"未通过：核心结论仅有外部公开材料"，答案写"未检索到直接依据，待核验"；
- 正文每个外部引用必须有 `外部公开材料 · 政府网站/官方媒体/次级媒体/未知` 徽标与源网址；报告正文页出现"本页部分材料为外部公开材料"提示条；
- 自检说明与用户可见文本不出现"阶段二/三""可信联网""宿主 WebSearch"等内部词。

自检说明里的日期一律写"YYYY年M月D日"（如 2023年1月1日），不写连写数字——2026-11-06 实测出现过"2023001起执行"笔误；提交前把 selfcheck JSON 的说明字段扫一遍再渲染。

## 角标与引用契约

- `[n]` = 合并产物里的材料 `编号` 字段（`merge_search_results.py` 输出），不要按数组位置数；
- 角标挂在**直接载有该依据**的材料上；找不到就补搜或写"未检索到直接依据"；
- 引用块逐字；允许省略号，不得改条件、数字、主体、期限；同条但书/例外一并纳入；
- 引用块前把前 10 个字在检索 JSON 里 grep 到再写（防凭记忆写"很熟"的条文）。

## 渲染与交付

```bash
python3 scripts/merge_search_results.py \
  --input official-docs/search-results/tax_<任务>_label.json --search-key "带标签检索" \
  --input official-docs/search-results/tax_<任务>_nolabel.json --search-key "无标签对照" \
  --output official-docs/search-results/tax_<任务>_merged.json

python3 scripts/render_trace_html.py official-docs/search-results/tax_<任务>_merged.json \
  --answer-file official-docs/search-results/tax_<任务>_answer.txt \
  --self-check-file official-docs/search-results/tax_<任务>_selfcheck.json \
  --question-file official-docs/search-results/tax_<任务>_question.txt

python3 scripts/deliver_outputs.py official-docs/output/<报告>.html
```

- 单文件三页：正文（去角标干净版）／溯源核验报告（默认落点）／知识专库；
- 自检不写死计数（材料数/引用数由报告统计）；不写材料编号（渲染器会重编号，用"《文件名》第X条挂在载有该条的材料"描述）；
- 文件名用短标识 `tax_<任务>_question.txt` / `_answer.txt` / `_selfcheck.json`，避免固定文件名写入失败；同题重跑自动 `_v2` 另存。

## 带标签 0 条时的答案写法

> 本次带「税务」标签检索未召回到结果（已重试一次）。以下结果来自不带标签的独立检索，两次检索记录都附在溯源报告中。
