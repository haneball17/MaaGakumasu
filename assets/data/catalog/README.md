# 统一游戏数据目录 v2

本目录按 `raw → assertions → canonical → derived` 管理游戏资料。HIF 是首个验收切片；现有运行时仍通过旧 JSON 接口读取，消费者迁移（M6）不在本里程碑范围内。

## 数据层

- `manifests/`：来源 URL、观察时间、内容哈希和解析器版本。
- `assertions/`：字段级来源断言；冲突不会静默覆盖。
- `canonical/`：经过显式裁决的实体、效果版本、术语和别名。
- `overlays/hif.json`：由当前代码和配置扫描得到的 HIF 必需语义及支持状态。
- `decisions/`：首次迁移晋升记录，以及来源刷新延期/拒绝记录。
- `reports/`：覆盖、冲突、新鲜度、解析、翻译、OCR、HIF 支持和兼容差分报告。

完整网页快照只保存在 `.cache/gakumas-data/raw/`，不提交到 Git。

## 离线发布门槛

```powershell
python tools/data_catalog.py validate --profile ingest
python tools/data_catalog.py validate --profile hif-release
python tools/data_catalog.py derive --check
python tools/data_catalog.py report
python tools/data_catalog.py all --offline
```

`derive --check` 会在 `.cache/gakumas-data/derived/` 生成确定性预览，并对动态时间字段做白名单后比较旧运行时语义。禁止直接编辑旧派生产物来绕过晋升记录。

## 当前边界

- 2026-07-15 刷新发现 143 张 P 偶像卡：136 张与基线精确匹配，7 张为新增候选。
- 页面没有稳定条目 ID，新增项也缺稀有度上下文，因此本次刷新仅保存断言并延期晋升。
- 122 张 Wiki 技能卡中有 121 条简中翻译；`ハイテンション` 不虚构翻译。
- 非 HIF 必需效果允许 `partial/unknown/unsupported`；未知效果不得进入可执行白名单。
- 本目录不扩大 HIF 自动点击、连续执行或发布权限。
