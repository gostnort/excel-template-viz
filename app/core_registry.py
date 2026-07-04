import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = PROJECT_ROOT / "templates"


class SortTemplates:
    """
    json文件用于模版的显示名称，并根据使用的顺序展示在导航栏上。
    文件不存在时，按文件创建时间降序作为默认时间线。
    文件存在时，按最新打开的模版降序作为时间线。
    json应该包含所有模版的文件。
    """

    JSON_FILE_NAME: str = "sort_templates.json"

    @property
    def LastUseTemplate(self) -> Path | None:
        """
        调用范例：
        registry.last_use_template = Path("templates/foo.xlsx")
        """
        return self._last_use_template

    @LastUseTemplate.setter
    def LastUseTemplate(self, value: Path | None) -> None:
        if value is None:
            self._last_use_template = None
            return
        # 检查 value 是否是 templates 文件夹下存在的 .xlsx 文件
        if not (
            isinstance(value, Path)
            and value.suffix == ".xlsx"
            and value.parent == TEMPLATES_DIR
            and value.exists()
        ):
            raise ValueError(
                "last_use_template 必须是 templates 文件夹内存在的 xlsx 文件"
            )
        if value == self._last_use_template:
            return  # 相同值可跳过，避免重复写盘
        self._last_use_template = value
        self._modify_json(last_use_template=value)

    def __init__(self):
        self.JSON_PATH = TEMPLATES_DIR / self.JSON_FILE_NAME
        self._last_use_template = None
        self.SortTemplatesJsonPayload = {}
        self.UpdateJson()
        """
        API还包括：
        LastUseTemplate变量
        """

    def _is_excel_lock_name(self, name: str) -> bool:
        """
        Excel 打开工作簿时会创建 ~$*.xlsx 临时锁文件
        return: 是否是临时锁文件
        example:
            name: "~$template1.xlsx"
              - return: True
            name: "template1.xlsx"
              - return: False
        """
        return name.startswith("~")

    def _iter_templates(self) -> list[Path]:
        """
        扫描 templates/*.xlsx，跳过 Excel 锁文件 ~$*.xlsx
        return: 模板文件路径列表
        example:
        [
            Path("templates/template1.xlsx"),
            Path("templates/template2.xlsx"),
            Path("templates/template3.xlsx"),
        ]
        """
        if not TEMPLATES_DIR.exists():
            return []
        return [
            template_path
            for template_path in TEMPLATES_DIR.glob("*.xlsx")
            if not self._is_excel_lock_name(template_path.name)
        ]

    def _derive_display_name(self, template_file_path: Path) -> str:
        """
        生成导航栏显示名称;
        template_file_path: 模板文件路径
        return: 导航栏显示名称。首字母大写，下划线代替空格和“-”。
        示例：
        template_file_path: Path("template-file name.xlsx")
        return: "Template_File_Name"
        """
        no_extension_name = template_file_path.stem
        no_extension_name = no_extension_name.replace("-", "_").replace("_", " ")
        no_extension_name = " ".join(no_extension_name.split())
        no_extension_name = no_extension_name.title()
        return no_extension_name.replace(" ", "_")

    def _generate_json(self) -> dict:
        """生成 JSON 数据，用于JSON文件不存在的时候生成默认数据。
        根据文件的创建时间生成默认的排序。文件名使用UI显示名称。
        return: JSON格式如下：
        {
            sort_templates_timeline:[
                template_file_most_recent_open,template_file_second_most_recent_open,template_file_third_most_recent_open, ...
            ]}
        """
        template_paths = self._iter_templates()
        # 无 JSON 时尚无打开记录，按文件创建时间降序作为默认时间线
        ordered_paths = sorted(
            template_paths,
            key=lambda path: getattr(path.stat(), "st_birthtime", path.stat().st_ctime),
            reverse=True,
        )
        timeline = [self._derive_display_name(path) for path in ordered_paths]
        payload = {"sort_templates_timeline": timeline}
        self.JSON_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._generate_json_template_section()
        return self.JSON_PATH.read_text(encoding="utf-8")

    def _modify_json(
        self, JSON_PATH: Path = None, last_use_template: Path = None
    ) -> None:
        """
        修改 JSON 数据。最近打开的模版将会移动到时间线的最前面。
        JSON_PATH: JSON 文件路径
        last_use_template: 最近打开的模板路径
        return: None
        """
        # 如果没有提供 JSON 文件路径，则调用_generate_json生成默认数据。
        if not JSON_PATH.exists():
            self._generate_json()
        # 根据last_use_template，将最近打开的模板移动到时间线的最前面。
        if last_use_template is not None:
            display_name = self._derive_display_name(last_use_template)
            # 加载已有的 JSON 数据
            json_data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
            timeline = json_data.get("sort_templates_timeline", [])
            # 删除已存在的同名 display_name
            timeline = [name for name in timeline if name != display_name]
            # 添加到最前面
            timeline.insert(0, display_name)
            json_data["sort_templates_timeline"] = timeline
            # 保存回文件
            with open(JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(json_data, f, ensure_ascii=False, indent=2)
        return

    def UpdateJson(self) -> None:
        """
        更新 JSON 数据。
        确保启动时 sort_templates.json 存在，包含所有当前模板，
        移除已删除模板，同步 id / file_name / display_name，并核对时间线。
        template.id 写入内存（self.template_ids）。
        return: None
        """
        # 1. 获取当前所有 templates
        template_paths = self._iter_templates()
        # 2. 生成 templates 的 IDs
        id_by_path = {path: self._assign_ID(path) for path in template_paths}
        # 3. 获得所有 templates 的 display_name
        display_by_id: dict[str, str] = {}
        file_name_by_id: dict[str, str] = {}
        for path in template_paths:
            template_id = id_by_path[path]
            display_by_id[template_id] = self._derive_display_name(path)
            file_name_by_id[template_id] = path.name
        valid_display_names = set(display_by_id.values())
        current_ids = set(display_by_id.keys())
        # 4. 核对 sort_templates.json 中的 templates（id / file_name / display_name）
        if not self.JSON_PATH.exists():
            self._generate_json()
        payload = json.loads(self.JSON_PATH.read_text(encoding="utf-8"))
        raw_templates = payload.get("templates")
        #  核对 templates[]：字段不存在时由 _generate_json_template_section 整段创建
        if raw_templates is None or not isinstance(raw_templates, list):
            self._generate_json_template_section()
            payload = json.loads(self.JSON_PATH.read_text(encoding="utf-8"))
            raw_templates = payload.get("templates", [])
        templates_list: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for entry in raw_templates:
            if not isinstance(entry, dict):
                continue
            entry_id = str(entry.get("id", "")).strip()
            if entry_id not in current_ids:
                continue  # 磁盘已删，从列表移除
            seen_ids.add(entry_id)
            templates_list.append(
                {
                    "id": entry_id,
                    "file_name": file_name_by_id[entry_id],
                    "display_name": display_by_id[entry_id],
                }
            )
        # 已有 templates 时：仅把磁盘上新出现的 id 追加到列表末尾（不重复 _generate_json_template_section）
        new_ids = sorted(current_ids - seen_ids)
        for template_id in new_ids:
            templates_list.append(
                {
                    "id": template_id,
                    "file_name": file_name_by_id[template_id],
                    "display_name": display_by_id[template_id],
                }
            )
        # 5. 核对 sort_templates_timeline：去掉已删项，新模板 display_name 追加到时间线末尾
        timeline = payload.get("sort_templates_timeline", [])
        if not isinstance(timeline, list):
            timeline = []
        timeline = [name for name in timeline if name in valid_display_names]
        known_displays = set(timeline)
        for entry in templates_list:
            display_name = entry["display_name"]
            if display_name not in known_displays:
                timeline.append(display_name)
                known_displays.add(display_name)
        payload["templates"] = templates_list
        payload["sort_templates_timeline"] = timeline
        self.JSON_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # 6. SortTemplatesJsonPayload 常驻内存（与磁盘 sort_templates.json 一致）
        self.SortTemplatesJsonPayload = payload
        self.TemplateIDs = {
            entry["id"]: TEMPLATES_DIR / entry["file_name"]
            for entry in payload.get("templates", [])
            if isinstance(entry, dict) and entry.get("id") and entry.get("file_name")
        }
        self.template_display_names = {
            entry["id"]: entry["display_name"]
            for entry in payload.get("templates", [])
            if isinstance(entry, dict) and entry.get("id")
        }
        self.sort_templates_timeline = list(payload.get("sort_templates_timeline", []))

    def _assign_ID(self, template_file_path: Path) -> str:
        """
        为模板文件赋予稳定 ID（全小写 + 下划线，见 templates/{id}/{id}.toml）。
        规则：ID是全小写，只用下划线，且去掉扩展名
        input: template_file_path: templates/sales-order template.xlsx
        output: ID: "sales_order_template"
        """
        id = template_file_path.stem.lower().replace("-", " ")
        id = " ".join(id.split())
        id = id.replace(" ", "_")
        return id

    def _generate_json_template_section(self) -> dict:
        """
        用于生成sort_templates.json如下片段templates[] 每项字段：
        "templates": [
            {
            "id": "sales_order",
            "file_name": "sales_order.xlsx",
            "display_name": "Sales_Order"
            }
        ]
        """
        if self.JSON_PATH.exists():
            payload = json.loads(self.JSON_PATH.read_text(encoding="utf-8"))
        # 如果template字段不存在：
        if payload.get("templates") is None:
            # 1. 获取所有模版
            template_paths = self._iter_templates()
            # 2. 获取所有模版ID，显示名，文件名
            templates_list: list[dict[str, str]] = []
            for path in template_paths:
                template_id = self._assign_ID(path)
                templates_list.append(
                    {
                        "id": template_id,
                        "file_name": path.name,
                        "display_name": self._derive_display_name(path),
                    }
                )
            templates_list.sort(key=lambda entry: entry["id"])
            # 3. 生成templates[] 每项字段
            payload["templates"] = templates_list
            # 4. 写入json文件
            self.JSON_PATH.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return {"templates": payload.get("templates", [])}


class ArrageInputView:
    def __init__(self):
        pass
