# Excel 模板可视化任务分解 (tasks_zh.md)

Speckit 风格分阶段任务清单。

---

## 阶段 1：规划文档

### [x] [任务 1.1] 发布 Speckit 文档
* **说明**：创建 `docs/plans/excel_template_viz/` 宪章、规格、方案、任务（含中文版）。
* **验收**：8 个文件齐全，涵盖 Streamlit 与 Google 测试页。

### [x] [任务 1.2] 分析 GIN LOT List 工作表
* **说明**：读取示例 xlsx，在 plan 中记录列与行布局。
* **验收**：工作表名为 `List`；12 列，标题行 0。

---

## 阶段 2：核心服务

### [x] [任务 2.1] 模板注册加载器
* **说明**：`registry.py` 加载 `config/templates.json`。
* **验收**：返回 TemplateConfig 列表；支持路径环境变量。

### [x] [任务 2.2] Excel 解析器
* **说明**：`excel_parser.py` 读写 List 工作表。
* **验收**：工作表名大小写不敏感；可导出 xlsx 字节。

### [x] [任务 2.3] Google Sheets 连接器
* **说明**：`google_sheets.py` 解析 ID 并拉取预览。
* **验收**：服务账号与 OAuth；异常信息清晰。

---

## 阶段 3：Streamlit UI

### [x] [任务 3.1] 主应用侧边栏导航
* **说明**：每个注册模板一项 + Google 测试页。
* **验收**：侧边栏动态生成。

### [x] [任务 3.2] 模板表单组件
* **说明**：data_editor + 下载按钮。
* **验收**：GIN LOT 列可编辑并可导出。

### [x] [任务 3.3] Google Sheet 测试页
* **说明**：URL、认证、预览表格。
* **验收**：成功绿色 / 失败红色及排查建议。

---

## 阶段 4：配置与文档

### [x] [任务 4.1] templates.json
* **说明**：注册 gin_lot 模板及路径元数据。
* **验收**：支持 `GIN_LOT_TEMPLATE_PATH`。

### [x] [任务 4.2] README 与 .gitignore
* **说明**：中文 README；凭证不入库。
* **验收**：文档完整。

---

## 阶段 5：测试与 GitHub

### [x] [任务 5.1] pytest 模块
* **说明**：Google ID 解析等离线测试。
* **验收**：无网络可通过。

### [x] [任务 5.2] GitHub 仓库
* **说明**：创建远程并推送初始脚手架。
* **验收**：返回仓库 URL。

---

## 阶段 6：后续（用户）

### [ ] [任务 6.1] 复制示例 xlsx 到 templates/
* **说明**：用户将 `GIN LOT TEMPLATE.xlsx` 复制为 `templates/gin_lot_template.xlsx`。

### [ ] [任务 6.2] 配置 Google 凭证
* **说明**：共享表格给服务账号或完成 OAuth。
