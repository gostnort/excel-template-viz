# 真实脏数据流形对齐基准测试 (Dirty Data Geodesic Alignment Benchmark)

本目录包含针对 `geodesic_align` 规则还原流水线的端到端真实脏数据基准测试（包含 `datasets/`、`results/` 与驱动测试工具）。
覆盖 11 组正交业务领域与脏数据边缘场景（欧式小数、千分位、混杂日期、拓扑行序打散、字符形变、无源留白安全降级等）。

---

### 一、 通用测试脚本的使用方式 (`run_generic_align_test.py`)

#### 1. 默认无参运行（直接执行第 11 个经典范例）
```bash
python test/dirty_data_tests/run_generic_align_test.py
```
> **默认行为**：自动以 `11_real_estate_chart_source.xlsx`（Sheet: `ListingFeed`）为源，以 `11_real_estate_chart.xlsx`（Sheet: `11_real_estate_chart`）为模板输出，完成流形对齐、输出决策表、校验生成的 TOML 并记录格拉斯曼流形跃迁。

---

#### 2. 测试任意外部真实业务表（零门槛自定义测试）
开发者想测试两张新的 Excel 表，直接传路径即可（支持自动识别第一个工作表，也可显式指定 Sheet）：
```bash
python test/dirty_data_tests/run_generic_align_test.py \
    --source "path/to/my_source.xlsx" \
    --template "path/to/my_template.xlsx" \
    --output-toml "results/custom_mapping.toml"
```

---

#### 3. 运行或查看全部 11 个内置正交基准用例
```bash
# 查看 11 组正交基准清单及脏数据模式
python test/dirty_data_tests/run_generic_align_test.py --list-suites

# 指定跑任意一个内置测试集（比如跑 06 欧洲银行、或 11 房产）
python test/dirty_data_tests/run_generic_align_test.py --suite 06
python test/dirty_data_tests/run_generic_align_test.py --suite 11
```

---

### 二、 自动化 Pytest 回归测试套件

```bash
pytest test/dirty_data_tests/test_dirty_data_geodesic.py -v
```
自动化执行全部 11 组基准用例的断言校验，验证数值稳定性、拓扑对齐与无源留白降级（`input`）保护。
