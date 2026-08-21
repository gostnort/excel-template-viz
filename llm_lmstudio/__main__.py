"""python -m llm_lmstudio  底座 CLI：models / load / unload / health / ask / vision。"""

from __future__ import annotations

import argparse
import json
import sys

from llm_lmstudio.config import load_user_config, save_user_config
from llm_lmstudio.facade import conversation_once, pic2str
from llm_lmstudio.models import get_model, has_vision, is_model_loaded, list_models, load_model, unload_model



def _apply_overrides(args: argparse.Namespace) -> None:
    """
    函数名: _apply_overrides
    作用: 把 --url / --model / --token 写进配置
    输入:
        args (Namespace): 可选覆盖项
    输出: 无
    """
    kwargs: dict = {}
    if getattr(args, "url", None):
        kwargs["api_url"] = args.url
    if getattr(args, "token", None) is not None:
        kwargs["api_token"] = args.token
    if getattr(args, "model", None):
        kwargs["model"] = args.model
    if kwargs:
        save_user_config(**kwargs)



def cmd_models(_args: argparse.Namespace) -> int:
    """
    函数名: cmd_models
    作用: 列出本机 LM Studio 模型与加载状态
    输入:
        _args: 未使用
    输出:
        int: 退出码
    """
    items = list_models()
    for item in items:
        key = item.get("key") or item.get("id")
        instances = item.get("loaded_instances") or []
        n = len(instances) if isinstance(instances, list) else 0
        caps = item.get("capabilities") or {}
        vision = bool(caps.get("vision")) if isinstance(caps, dict) else False
        print(f"{key}\tloaded={n}\tvision={vision}")
    if not items:
        print("(no models)")
    return 0



def cmd_load(args: argparse.Namespace) -> int:
    """
    函数名: cmd_load
    作用: 加载模型权重
    输入:
        args: model 可选位置参数
    输出:
        int: 退出码
    """
    key = args.model_name or load_user_config().get("model")
    result = load_model(key, remember=True)
    print(json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else result)
    return 0



def cmd_unload(args: argparse.Namespace) -> int:
    """
    函数名: cmd_unload
    作用: 卸载模型权重
    输入:
        args: model 可选
    输出:
        int: 退出码
    """
    key = args.model_name or None
    ids = unload_model(key)
    print("unloaded: " + (", ".join(ids) if ids else "(none)"))
    return 0



def cmd_health(_args: argparse.Namespace) -> int:
    """
    函数名: cmd_health
    作用: 打印配置、是否加载、是否 vision
    输入:
        _args: 未使用
    输出:
        int: 退出码
    """
    cfg = load_user_config()
    key = str(cfg.get("model") or "")
    info = get_model(key) if key else None
    loaded = is_model_loaded(key) if key else False
    vision = has_vision(key) if key else False
    print(f"api_url={cfg['api_url']}")
    print(f"model={key!r}")
    print(f"loaded={loaded}")
    print(f"vision={vision}")
    if info:
        print(f"display_name={info.get('display_name')!r}")
    return 0 if cfg.get("api_url") else 1



def cmd_ask(args: argparse.Namespace) -> int:
    """
    函数名: cmd_ask
    作用: 一次性文本问答
    输入:
        args: text / system / thinking / release
    输出:
        int: 退出码
    """
    print(conversation_once(args.text, system=args.system, thinking=bool(args.thinking)))
    if args.release:
        unload_model()
    return 0



def cmd_vision(args: argparse.Namespace) -> int:
    """
    函数名: cmd_vision
    作用: 读图问答；无 vision 能力则退出 2
    输入:
        args: image / prompt / system / release
    输出:
        int: 退出码
    """
    cfg = load_user_config()
    key = str(cfg.get("model") or "")
    if not has_vision(key):
        print("current model has capabilities.vision=false", file=sys.stderr)
        return 2
    print(pic2str(args.image, args.prompt, system=args.system))
    if args.release:
        unload_model()
    return 0



def _build_parser() -> argparse.ArgumentParser:
    """
    函数名: _build_parser
    作用: 组装 llm_lmstudio 子命令
    输入: 无
    输出:
        argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog="python -m llm_lmstudio",
        description="LM Studio native REST client (load / unload / chat).",
    )
    parser.add_argument("--url", default=None, help="override api_url and save")
    parser.add_argument("--token", default=None, help="override api_token and save")
    parser.add_argument("--model", default=None, help="override current model key and save")
    root = parser.add_subparsers(dest="command", required=True)
    models = root.add_parser("models", help="list downloaded/loaded models")
    models.set_defaults(func=cmd_models)
    load = root.add_parser("load", help="load model weights")
    load.add_argument("model_name", nargs="?", default=None)
    load.set_defaults(func=cmd_load)
    unload = root.add_parser("unload", help="unload model weights")
    unload.add_argument("model_name", nargs="?", default=None)
    unload.set_defaults(func=cmd_unload)
    health = root.add_parser("health", help="config + loaded + vision")
    health.set_defaults(func=cmd_health)
    ask = root.add_parser("ask", help="stateless text chat")
    ask.add_argument("text")
    ask.add_argument("--system", default=None)
    ask.add_argument("--thinking", action="store_true")
    ask.add_argument("--release", action="store_true")
    ask.set_defaults(func=cmd_ask)
    vision = root.add_parser("vision", help="image + prompt")
    vision.add_argument("image")
    vision.add_argument("--prompt", default="Describe this image.")
    vision.add_argument("--system", default=None)
    vision.add_argument("--release", action="store_true")
    vision.set_defaults(func=cmd_vision)
    return parser



def main(argv: list[str] | None = None) -> int:
    """
    函数名: main
    作用: CLI 入口
    输入:
        argv (list[str] | None): 参数
    输出:
        int: 退出码
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    _apply_overrides(args)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 1
    return int(func(args) or 0)



if __name__ == "__main__":
    raise SystemExit(main())
