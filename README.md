# 深知税务助手（skills.sh Public 版）

> 版本 v1.0.3（2026-11-13，测试反馈修复 + 来源展示口径，未封版）｜中国大陆税务领域的可信政策检索与问答 Skill

**入口**：`SKILL.md`（路由与底线规则）→ 按需读 `reference/` 下各文档。

## 安装

```bash
npx -y skills add dylanzhangzx/dknowc-tax-assistant -g --all
```

装好后在 Agent 中即可调用 `/dknowc-tax-assistant`（也可只装本项目：去掉 `-g --all`）。
按需指定要装的 skill：`--skill dknowc-tax-assistant`；更新到最新版：`npx skills update`。

## 快速开始

```bash
python3 scripts/initialize.py          # Key 与环境检查
python3 scripts/tax_search.py --query "增值税 小规模纳税人 免征增值税 月销售额 标准 2023" \
  --policy-labels "政策/主题标签/财政、金融、审计/税务" \
  -o official-docs/search-results/tax_demo.json
```

## 结构

```
SKILL.md                 路由 + 底线（约 100 行）
scripts/
  tax_client.py          五接口客户端（可信搜索 V2 主路 + 政策数据四接口）
  tax_search.py          检索：--query（V2 主路）/ --file（全文兜底，不切条）
  tag_catalog.py         标签短名→完整路径解析、返回标签校验
  question_profile.py    问题画像（地域/时点/税种/纳税人身份/优惠/申报期）
  source_cards.py        材料画像（地域/文件类型/来源性质/抓取状态）
  calc_tax.py            滞纳金/税额/价税分离/减免额计算
  calc_period.py         日期区间与利息计算
  verify_claims.py       结论图通用校验（交付前闸门）
  path_guard.py          能力层脚本读写路径白名单
  check_release.py       发布检查（Key/手机号/包外引用/非运行资产门禁）
  check_answer.py        措辞检查（税务版）
  merge_search_results.py / render_trace_html.py / deliver_outputs.py
  initialize.py / api_key.py / attribution.py / register_key.mjs
reference/               retrieval-v2（检索前必读）/ retrieval-policy / tags /
                         answer-and-report / capability-layer / troubleshooting /
                         onboarding_scripts / policy_tags.json / tax_claims.example.json
official-docs/           search-results/（检索落盘，运行期生成）output/（报告，运行期生成）

评测工具（run_tax_eval.py）与测试集（12 题 questions.jsonl、逐题结果）由维护仓库保存，不入 skill 包。
```

## 硬约束（详见 SKILL.md）

- 第一次检索必须是 V2 `--query`；没读过 `reference/retrieval-v2.md` 不得调用任何检索。
- 标签传完整路径；带标签 0 条不静默降级。
- 答案写适用年度；引用按"文件全称+文号+发布日期"锁定版本。
- 仅中国大陆税务；社保为相邻领域、单独标签族。
- Key 不进对话与日志；注册链路写盘范围（均 0600）：Key 配置文件、客户端实例标识 `maas_client_instance`、题目状态文件（完成即清理）、写盘失败时的临时保管文件（persist 恢复后即删）。

## 测试证据

测试记录与原始证据由维护仓库保存（不入 skill 包）：最小验证记录、12 题 A/B 测试报告、WorkBuddy 10 题实测记录与 74 份原始检索 JSON。
