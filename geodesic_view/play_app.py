"""下一步按钮：跑 example_workflow 的下一步，并换上当时的图。"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nicegui import run, ui
from PIL import Image

from geodesic_view.step_walk import WorkflowPlayer



def _png(fig) -> Image.Image:
    """
    函数名: _png
    作用: 把当前这张图收成 PIL，交给页面显示
    输入:
        fig: matplotlib 图
    输出:
        PIL.Image.Image
    """
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    image = Image.open(buf)
    image.load()
    return image



@ui.page("/")
def page() -> None:
    """
    函数名: page
    作用: 一个按钮往前走 example_workflow，图区只保留当前这一步
    输入: 无
    输出: 无
    """
    player = WorkflowPlayer()
    with ui.column().classes("w-full q-pa-md"):
        with ui.row().classes("w-full items-center"):
            button = ui.button("下一步")
            status = ui.label("从读入样本表开始")
        picture = ui.image().classes("w-full")

        async def go() -> None:
            """
            函数名: go
            作用: 在后台线程跑下一步，再把新图换上
            输入: 无
            输出: 无
            """
            button.disable()
            button.props("loading")
            try:
                got = await run.io_bound(player.advance)
            except Exception as exc:
                status.set_text(type(exc).__name__ + ": " + str(exc))
                button.enable()
                button.props(remove="loading")
                return
            if got is None:
                status.set_text("已经走完")
                button.props(remove="loading")
                return
            title, fig = got
            status.set_text(title)
            picture.set_source(_png(fig))
            if player.finished:
                button.set_text("已经走完")
                button.props(remove="loading")
                return
            button.enable()
            button.props(remove="loading")

        button.on_click(go)



def main() -> None:
    """
    函数名: main
    作用: 在本机 8766 端口打开逐步演示
    输入: 无
    输出: 无
    """
    from nicegui_ui.asyncio_win import install_win_asyncio_reset_filter
    install_win_asyncio_reset_filter()
    ui.run(
        host="127.0.0.1",
        port=8766,
        title="workflow",
        reload=False,
        show=False,
        language="zh-CN",
    )



if __name__ in {"__main__", "__mp_main__"}:
    main()
