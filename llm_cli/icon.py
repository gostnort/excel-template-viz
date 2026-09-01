"""从 icon_source.png 裁切并缩成 512x512 图标（Lanczos/双线性，不限色）。"""

from __future__ import annotations

import ctypes
import struct
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

SIZE = 512
TINY_SIDE = 16  # CLI 网格及更小边长用双线性；512 主图仍 Lanczos
_PKG = Path(__file__).resolve().parent
SOURCE_PATH = _PKG / "icon_source.png"
ICON_PATH = _PKG / "icon_512.png"
ICON_256_PATH = _PKG / "icon_256.png"
ICO_PATH = _PKG / "icon.ico"

BLACK = (0, 0, 0)
MARGIN_RATIO = 0.06
MIN_MARGIN = 2


def _flatten_rgb(image: Image.Image) -> Image.Image:
    """
    函数名: _flatten_rgb
    作用: 把源图铺到黑底 RGB，去掉透明通道
    输入:
        image (Image.Image): 任意模式的源图
    输出:
        Image.Image: RGB 图
    """
    if image.mode in ("RGBA", "LA"):
        rgba = image.convert("RGBA")
        bg = Image.new("RGB", rgba.size, BLACK)
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    if image.mode == "P" and "transparency" in image.info:
        rgba = image.convert("RGBA")
        bg = Image.new("RGB", rgba.size, BLACK)
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return image.convert("RGB")


def _ink_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    """
    函数名: _ink_bbox
    作用: 非纯黑像素包络；右/下为开区间，含最后一行一列
    输入:
        image (Image.Image): RGB 图
    输出:
        tuple[int, int, int, int]: (left, top, right, bottom)，right/bottom 不含
    """
    width, height = image.size
    pixels = image.load()
    min_x = width
    min_y = height
    max_x = -1
    max_y = -1
    for y in range(height):
        for x in range(width):
            pixel = pixels[x, y]
            rgb = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
            # 任意非纯黑视为内容，不按品牌色名单裁切
            if rgb != BLACK:
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y
    if max_x < 0:
        return (0, 0, width, height)
    # 外扩 1 像素，避免抗锯齿边被贴边裁掉
    min_x = max(0, min_x - 1)
    min_y = max(0, min_y - 1)
    max_x = min(width - 1, max_x + 1)
    max_y = min(height - 1, max_y + 1)
    return (min_x, min_y, max_x + 1, max_y + 1)  # 开区间，含最后一行一列


def _fit_square(image: Image.Image, size: int) -> Image.Image:
    """
    函数名: _fit_square
    作用: 黑边居中铺成方图再缩到 size；空间用 Lanczos/双线性，不限色
    输入:
        image (Image.Image): RGB 内容图
        size (int): 目标边长
    输出:
        Image.Image: size×size RGB
    """
    width, height = image.size
    if width < 1 or height < 1:
        return Image.new("RGB", (size, size), BLACK)
    longest = max(width, height)
    margin = max(MIN_MARGIN, int(round(longest * MARGIN_RATIO)))
    side = max(width + margin * 2, height + margin * 2)
    canvas = Image.new("RGB", (side, side), BLACK)
    canvas.paste(image, ((side - width) // 2, (side - height) // 2))
    if side == size:
        return canvas
    return _spatial_resize(canvas, size, size)


def _resample_filter(width: int, height: int) -> Image.Resampling:
    """
    函数名: _resample_filter
    作用: 选空间缩小滤波器：512 主图用 Lanczos，CLI 小网格用双线性
    输入:
        width (int): 目标宽
        height (int): 目标高
    输出:
        Image.Resampling: LANCZOS 或 BILINEAR
    """
    # 极小边长 Lanczos 易振铃，双线性更稳；大图仍用 Lanczos
    if min(width, height) <= TINY_SIDE:
        return Image.Resampling.BILINEAR
    return Image.Resampling.LANCZOS


def _spatial_resize(image: Image.Image, width: int, height: int) -> Image.Image:
    """
    函数名: _spatial_resize
    作用: Pillow 空间缩小，插值结果原样保留
    输入:
        image (Image.Image): RGB 图
        width (int): 目标列数
        height (int): 目标行数
    输出:
        Image.Image: width×height RGB
    """
    src = image.convert("RGB")
    out = Image.new("RGB", (width, height), BLACK)
    if src.size[0] < 1 or src.size[1] < 1 or width < 1 or height < 1:
        return out
    if src.size == (width, height):
        return src
    return src.resize((width, height), _resample_filter(width, height))


def _fit_contain(image: Image.Image, width: int, height: int) -> Image.Image:
    """
    函数名: _fit_contain
    作用: 保持源宽高比缩进目标框并黑边居中，绝不分别拉伸
    输入:
        image (Image.Image): RGB 内容
        width (int): 目标宽
        height (int): 目标高
    输出:
        Image.Image: width×height RGB
    """
    src = image.convert("RGB")
    sw, sh = src.size
    out = Image.new("RGB", (width, height), BLACK)
    if sw < 1 or sh < 1 or width < 1 or height < 1:
        return out
    # 以较短边为限做等比 contain，不分别拉 X/Y
    if sw * height >= sh * width:
        nw = width
        nh = max(1, sh * width // sw)
        if nh > height:
            nh = height
            nw = max(1, sw * height // sh)
    else:
        nh = height
        nw = max(1, sw * height // sh)
        if nw > width:
            nw = width
            nh = max(1, sh * width // sw)
    nw = max(1, min(nw, width))
    nh = max(1, min(nh, height))
    scaled = _spatial_resize(src, nw, nh)
    out.paste(scaled, ((width - nw) // 2, (height - nh) // 2))
    return out


def load_source(path: Path | None = None) -> Image.Image:
    """
    函数名: load_source
    作用: 读取主源 PNG 并铺到黑底
    输入:
        path (Path | None): 源路径；空则用包内 icon_source.png
    输出:
        Image.Image: RGB 源图
    """
    src = path if path is not None else SOURCE_PATH
    if not src.is_file():
        raise FileNotFoundError(src)
    return _flatten_rgb(Image.open(src))


def render_icon() -> Image.Image:
    """
    函数名: render_icon
    作用: 按非黑包络裁切后居中缩到 512x512
    输入: 无
    输出:
        Image.Image: RGB 图
    """
    source = load_source()
    # 按非黑框裁切后再等比铺方，避免整幅黑边把内容挤出网格
    cropped = source.crop(_ink_bbox(source))
    return _fit_square(cropped, SIZE)


def render_grid(
    width: int,
    height: int,
    image: Image.Image | None = None,
) -> Image.Image:
    """
    函数名: render_grid
    作用: 把 512 图标缩到终端网格，保持等比 contain
    输入:
        width (int): 列像素（CLI 默认 16）
        height (int): 行像素（与列相同则不变形）
        image (Image.Image | None): 源图；空则读 icon_512 或现场生成
    输出:
        Image.Image: width×height RGB
    """
    if image is None:
        if ICON_PATH.is_file():
            src = Image.open(ICON_PATH).convert("RGB")
        else:
            src = render_icon()
    else:
        src = image.convert("RGB")
    # 按非黑框裁切后等比 contain 铺进整格；CLI 侧 N×N（默认 16），不分别拉 X/Y
    cropped = src.crop(_ink_bbox(src))
    return _fit_contain(cropped, width, height)


def write_icon(path: Path | None = None) -> Path:
    """
    函数名: write_icon
    作用: 写出 512 PNG，并派生 256 PNG 与多尺寸 ICO
    输入:
        path (Path | None): 目标 PNG；空则用包内 icon_512.png
    输出:
        Path: 写出的 512 PNG
    """
    dest = path if path is not None else ICON_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    image = render_icon()
    image.save(dest, format="PNG")
    # 从 512 按通用滤波器再写 256，旧路径仍可用
    if dest.resolve() == ICON_PATH.resolve():
        preview = _spatial_resize(image, 256, 256)
        preview.save(ICON_256_PATH, format="PNG")
    # 同步写出多尺寸 ICO（含 256 层），供控制台 WM_SETICON
    write_ico(ICO_PATH, image.convert("RGBA"))
    return dest


def write_ico(path: Path | None = None, image: Image.Image | None = None) -> Path:
    """
    函数名: write_ico
    作用: 从 512 源缩小写成多尺寸 ICO（16/32/48/256）
    输入:
        path (Path | None): 目标 .ico；空则用包内 icon.ico
        image (Image.Image | None): 源图；空则读 icon_512.png 或现场生成
    输出:
        Path: 写出的 ICO 路径
    """
    dest = path if path is not None else ICO_PATH
    if image is None:
        if ICON_PATH.is_file():
            src = Image.open(ICON_PATH).convert("RGBA")
        else:
            src = render_icon().convert("RGBA")
    else:
        src = image.convert("RGBA")
    sizes = (16, 32, 48, 256)
    blobs: list[bytes] = []
    for size in sizes:
        resized = _spatial_resize(src, size, size).convert("RGBA")
        buf = BytesIO()
        resized.save(buf, format="PNG")
        blobs.append(buf.getvalue())
    # ICO 头 + 每档 PNG 载荷（Vista+ 支持）
    count = len(blobs)
    offset = 6 + 16 * count
    header = struct.pack("<HHH", 0, 1, count)
    entries = bytearray()
    payload = bytearray()
    for size, blob in zip(sizes, blobs):
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(blob), offset)
        payload += blob
        offset += len(blob)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(header + entries + payload)
    return dest


def ensure_ico() -> Path:
    """
    函数名: ensure_ico
    作用: 若 ICO 缺失或比 PNG 旧则重写
    输入: 无
    输出:
        Path: 可用的 icon.ico
    """
    if ICO_PATH.is_file() and ICON_PATH.is_file():
        if ICO_PATH.stat().st_mtime >= ICON_PATH.stat().st_mtime:
            return ICO_PATH
    return write_ico()


def enable_vt() -> None:
    """
    函数名: enable_vt
    作用: 控制台改 UTF-8 并打开 VT/ANSI，避免 GBK 无法打印半块
    输入: 无
    输出: 无
    """
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.platform != "win32":
        return
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleOutputCP(65001)
    kernel32.SetConsoleCP(65001)
    handle = kernel32.GetStdHandle(-11)
    mode = ctypes.c_uint32()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return
    kernel32.SetConsoleMode(handle, mode.value | 0x0004)


def _console_hwnds() -> list[int]:
    """
    函数名: _console_hwnds
    作用: 收集控制台窗、根窗与 owner，供设图标
    输入: 无
    输出:
        list[int]: HWND 列表
    """
    if sys.platform != "win32":
        return []
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    kernel32.GetConsoleWindow.restype = ctypes.c_void_p
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetWindow.restype = ctypes.c_void_p
    hwnd = kernel32.GetConsoleWindow()
    found: list[int] = []
    if not hwnd:
        return found
    found.append(int(hwnd))
    root = user32.GetAncestor(hwnd, 2)
    if root and int(root) not in found:
        found.append(int(root))
    owner = user32.GetWindow(hwnd, 4)
    if owner and int(owner) not in found:
        found.append(int(owner))
    return found


def _load_icon_handles(ico: Path) -> tuple[int, int]:
    """
    函数名: _load_icon_handles
    作用: LoadImageW 载入大/小图标句柄
    输入:
        ico (Path): .ico 文件
    输出:
        tuple[int, int]: (大图标, 小图标) 句柄，失败为 0
    """
    user32 = ctypes.windll.user32
    user32.LoadImageW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.LoadImageW.restype = ctypes.c_void_p
    path = str(ico.resolve())
    big = user32.LoadImageW(None, path, 1, 32, 32, 0x0010)
    small = user32.LoadImageW(None, path, 1, 16, 16, 0x0010)
    big_i = int(big or 0)
    small_i = int(small or 0)
    if not big_i:
        big_i = small_i
    if not small_i:
        small_i = big_i
    return big_i, small_i


def _set_hwnd_icon(hwnd: int, big: int, small: int) -> None:
    """
    函数名: _set_hwnd_icon
    作用: 对单个 HWND 发送 WM_SETICON 并改窗口类图标
    输入:
        hwnd (int): 窗口句柄
        big (int): 32px 图标
        small (int): 16px 图标
    输出: 无
    """
    user32 = ctypes.windll.user32
    user32.SendMessageW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    user32.SendMessageW.restype = ctypes.c_void_p
    if small:
        user32.SendMessageW(hwnd, 0x0080, 0, small)
    if big:
        user32.SendMessageW(hwnd, 0x0080, 1, big)
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        setter = user32.SetClassLongPtrW
    else:
        setter = user32.SetClassLongW
    setter.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    setter.restype = ctypes.c_void_p
    if big:
        setter(hwnd, -14, big)
    if small:
        setter(hwnd, -34, small)


def apply_console_icon() -> None:
    """
    函数名: apply_console_icon
    作用: Windows 下把像素图标设到控制台/任务栏，并打开 VT
    输入: 无
    输出: 无
    """
    enable_vt()
    if sys.platform != "win32":
        return
    try:
        # 等同 $Host.UI.RawUI.WindowTitle
        ctypes.windll.kernel32.SetConsoleTitleW("llm_cli")
        ico = ensure_ico()
        big, small = _load_icon_handles(ico)
        if not big and not small:
            return
        for hwnd in _console_hwnds():
            try:
                _set_hwnd_icon(hwnd, big, small)
            except Exception:
                continue
        setter = getattr(ctypes.windll.kernel32, "SetConsoleIcon", None)
        if setter is not None and big:
            setter(big)
    except Exception:
        return


def main() -> int:
    """
    函数名: main
    作用: 从源图再生 512 PNG、256 派生图与 ICO 并打印路径
    输入: 无
    输出:
        int: 退出码
    """
    dest = write_icon()
    print(str(dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
