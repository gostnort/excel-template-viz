# Python Coding Style Rules

Please adhere to the following strict code layout and documentation style rules for all Python code in this repository:

## 1. Code Formatting & Spacing
- **Class Spacing**: Use exactly **3 empty lines** between top-level class declarations.
- **Function Spacing**: Use exactly **2 empty lines** between functions or methods.
- **No Internal Empty Lines**: Do **NOT** use empty lines inside functions or methods.
- **Imports**: All `import` statements must be placed at the very top of the file, unless it is a local import inside a function (e.g. to avoid circular imports or for testing/lazy loading).

## 2. Comments & Paragraphs inside Functions
- Use Chinese comments (`# 中文注释`) to segment logic paragraphs inside a function/method and explain what the following block of code does.
- Since empty lines are forbidden inside functions, comments serve as the visual separators.

## 3. Function & Method Docstrings
- Every function/method must include a Chinese docstring containing:
  - `函数名`: Name of the function.
  - `作用`: Brief description of what the function does.
  - `输入`: Detailed input parameters, types, and descriptions.
  - `输出`: Return value types and descriptions.

- Format template:
  ```python
  """
  函数名: example_function
  作用: 这是一个示例函数说明
  输入: 
      param1 (str): 描述1
      param2 (int): 描述2
  输出: 
      dict: 返回一个包含处理结果的字典
  """
  ```
