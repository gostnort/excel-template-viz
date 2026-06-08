# 模板自动发现技术方案（plan_zh.md）

## 1. 架构背景

```
templates/                         app/services/
├── gin_lot.xlsx                   ├── registry.py
├── gin_lot.config.json            └── data_source.py
```

### 1.1 模板注册流程
* 扫描 `templates/` 下的 `*.xlsx`。
* 对每个模板解析同名配置文件：
  * 优先 `<name>.config.json`，否则 `<name>.json`。
  * 缺失配置时生成默认配置并写入。
* 由配置生成 `TemplateConfig` 列表。

### 1.2 数据源流程
* 数据源保存在配置文件的 `data_source` 字段。
* `load_template_data_source()` 从配置读取。
* `save_template_data_source()` 写回同一配置文件。

---

## 2. 目录结构

```
excel-template-viz/
├── app/
├── templates/
│   ├── *.xlsx
│   ├── *.json
│   └── *.config.json
├── plans/
│   └── template_auto_discovery/
└── tests/
```

---

## 3. 实施阶段

1. **规划** — 新增 `plans/` 目录下的 Speckit 文档。
2. **注册表改造** — 自动扫描模板并生成默认配置。
3. **数据源改造** — 数据源写入模板同名配置。
4. **UI/文档更新** — 更新提示文案与 README。
5. **测试更新** — 调整数据源单测为配置文件模式。

---

## 4. 已知约束

* 同名配置文件是模板配置的唯一来源。
* 缺失字段时使用默认值。
