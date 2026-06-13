"""
Excel Template Visualization - Gradio Version
Main application entry point
"""
import gradio as gr

def build_placeholder_app():
    """
    Temporary placeholder app for Phase 1 testing
    
    This will be replaced by the full app in Phase 4
    """
    with gr.Blocks(title="Excel 模板可视化 - Gradio") as app:
        gr.Markdown("# Excel 模板可视化")
        gr.Markdown("## Gradio 版本 - 开发中")
        gr.Markdown("""
        ### Phase 1 完成
        - ✓ 创建 gradio-ui 分支
        - ✓ 更新依赖配置
        - ✓ 创建批处理文件
        - ✓ Speckit 文档结构
        
        ### 下一步：Phase 2 - 数据层和 LLM 集成
        """)
        
        gr.Button("测试按钮", variant="primary")
    
    return app

if __name__ == "__main__":
    app = build_placeholder_app()
    app.launch(
        server_port=8501,
        share=False,
        inbrowser=True
    )
