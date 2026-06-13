"""
Gradio Application Entry Point

Main entry point for launching the Gradio web UI.
"""
import gradio as gr
import logging

from app.gradio_main import build_app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    logger.info("Building Gradio application...")
    app = build_app()
    
    logger.info("Launching Gradio server...")
    app.launch(
        server_port=8501,
        share=False,
        inbrowser=True,
        server_name="127.0.0.1"
    )
