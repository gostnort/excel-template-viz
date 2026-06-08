# Excel 模板可视化技术方案 (plan_zh.md)

## 1. 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│  Streamlit 应用 (app/app.py)                                │
│  ┌──────────────┐  ┌──────────────────────────────────────┐ │
│  │ 侧边栏导航   │  │ 主面板                               │ │
│  │ - 模板 A     │  │  template_form.render_template()     │ │
│  │ - 模板 B     │  │  或 google_sheet 测试页              │ │
│  │ - Google测试 │  └──────────────────────────────────────┘ │
│  └──────────────┘                                           │
└─────────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
  config/templates.json          services/
                                 ├── registry.py
                                 ├── excel_parser.py
                                 └── google_sheets.py
```

### 1.1 导航模型
* 单一入口 `app.py`；侧边栏 radio 驱动 `st.session_state["page"]`。
* 每个注册模板一项，另加固定项「Google Sheet 连通性测试」。
* 不依赖 Streamlit 多页文件夹，模板数量由 JSON 动态决定。

### 1.2 GIN LOT 模板（List 工作表）
来源：`GIN LOT TEMPLATE.xlsx`，工作表 `List`（大小写不敏感）。

| 行 | 角色 | 内容 |
|----|------|------|
| 0 | 标题 | order, YY, MM, DD, P.O. No., … Truck Line |
| 1+ | 数据 | 示例行（YY=26, MM=04, Product=FRESH GINGER 等） |

### 1.3 Excel 解析器
* 读取/写回指定工作表；工作表名大小写不敏感匹配。
* 下载时生成 xlsx 字节流。

### 1.4 Google Sheets 连接器
* 解析 spreadsheet ID；服务账号或 OAuth 两种认证。
* 返回前几行 DataFrame 供展示。

### 1.5 终端用户测试页
* 粘贴 URL、选择认证、运行测试；成功/失败消息与排查建议（中文）。

---

## 2. 目录结构

见 `plan.md` §2（与英文版一致）。

---

## 3. 依赖

streamlit、pandas、openpyxl、gspread、google-auth、google-auth-oauthlib、pytest。

---

## 4. 实施阶段

1. 规划 — Speckit 文档。
2. 核心服务 — registry、excel_parser、google_sheets。
3. UI — 侧边栏 + 模板表单 + Google 测试。
4. 配置 — templates.json。
5. 测试 — ID 解析、工作表匹配。
6. GitHub — 创建仓库并推送。

---

## 5. 已知约束

* 开发者可能无 Google 表格权限；在线 Google 测试仅通过 UI 由终端用户执行。
* 示例 xlsx 在仓库外（微信路径）；可通过环境变量 `GIN_LOT_TEMPLATE_PATH` 或复制到 `templates/`。
