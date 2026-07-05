# Google OAuth 客户端配置

---

## 1. 创建 Google Cloud 项目

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)。
2. 顶部项目下拉 → **新建项目**（或选择已有项目）。
3. 记下项目名称；后续所有操作均在该项目下进行。

---

## 2. 启用 Google Sheets API

1. 左侧菜单 → **Enabled APIs & services**
0. 顶部 **+ Enable APIs & Services**
0. 在 **API Library** 搜索 `Google Sheets API`。
0. 点击进入，输入新的程序名称，例如`Excel Template Viz`，**启用**。

---

## 3. 创建 OAuth 2.0 客户端 ID（桌面应用）

1. **APIs & Services** → **Credentials** 
0. 顶部 **+ Create credentials** → **OAuth Client ID**。
0. **Application type** 必须选 **Desktop app**。
3. **Name**随意，例如 `Excel Template Viz Desktop`。
4. 点击 **创建** → **下载 JSON**。

下载的文件名通常为 `client_secret_*.json` 或类似名称。

## 4. 放入本项目

任选一种方式：

### 方式 A：应用内上传（推荐）

1. 启动应用，打开 **Google 连接** 标签页。
2. 点击 **选择授权文件**，在文件对话框中选择下载的 JSON。
3. 成功后会提示「授权文件已保存」，并写入 `credentials/oauth_client.json`。
4. 点击 **连接**；首次会打开浏览器完成 Google 账号授权，之后 token 保存在 `credentials/authorized_user.json`。

### 方式 B：手动复制

```text
credentials/
  oauth_client.json      ← 将下载的 JSON 复制并重命名为此文件名
  authorized_user.json   ← 首次「连接」成功后自动生成，勿手动编辑
```

在项目根目录创建 `credentials` 文件夹（若不存在），将 JSON 保存为 `oauth_client.json`。

---

## 5. 相关文档

- 实现契约：`docs/connect_google.md`
- TOML 数据源配置：各模板目录下 `{id}.toml` 的 `[[sources]]` / `[[fields]]`
