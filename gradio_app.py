"""
Gradio Application Entry Point

Main entry point for launching the Gradio web UI.
"""
import warnings
import logging

# Filter out deprecation warnings from third-party libraries
warnings.filterwarnings('ignore', category=DeprecationWarning)
warnings.filterwarnings('ignore', message='.*HTTP_422_UNPROCESSABLE_ENTITY.*')
warnings.filterwarnings('ignore', module='starlette')
warnings.filterwarnings('ignore', module='gradio')

import gradio as gr
from app.gradio_main import build_app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Suppress verbose logging from third-party libraries
logging.getLogger('gradio').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

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
