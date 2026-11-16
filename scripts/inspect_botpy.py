"""事实性 dump 已安装 qq-botpy-sdk 的公开 API。

只做只读探测：不读取 .env，不发起网络请求，不推断字段含义。
每一项独立 try/except，失败只打印 ``SKIP: <原因>``，不中断脚本。
"""

from __future__ import annotations

import importlib
import importlib.metadata
import inspect


def _skip(reason: object) -> None:
    print(f"SKIP: {reason}")


def _signature(obj: object) -> str:
    """返回签名文本；取不到时返回 SKIP 标记而不抛错。"""
    try:
        return str(inspect.signature(obj))
    except Exception as exc:
        return f"SKIP: {exc}"


def _dump_version() -> None:
    print("===== 1. 版本与路径 =====")
    try:
        print(f"importlib.metadata.version('qq-botpy-sdk'): {importlib.metadata.version('qq-botpy-sdk')}")
    except Exception as exc:
        _skip(exc)
    try:
        import botpy

        print(f"botpy.__file__: {botpy.__file__}")
    except Exception as exc:
        _skip(exc)


def _import_botpy() -> object | None:
    try:
        return importlib.import_module("botpy")
    except Exception as exc:
        _skip(f"import botpy: {exc}")
        return None


def _dump_public_names(botpy_module: object) -> None:
    print("\n===== 2. dir(botpy) 公开名字 =====")
    try:
        names = sorted(name for name in dir(botpy_module) if not name.startswith("_"))
        for name in names:
            print(name)
    except Exception as exc:
        _skip(exc)


def _dump_client_init(botpy_module: object) -> None:
    print("\n===== 3. botpy.Client.__init__ 签名 =====")
    try:
        client_cls = getattr(botpy_module, "Client")
        print(_signature(client_cls.__init__))
    except Exception as exc:
        _skip(exc)


def _dump_client_methods(botpy_module: object) -> None:
    print("\n===== 4. botpy.Client 上以 on_ 开头的方法 =====")
    try:
        client_cls = getattr(botpy_module, "Client")
        for name in sorted(dir(client_cls)):
            if name.startswith("on_"):
                print(name)
    except Exception as exc:
        _skip(exc)

    print("\n===== 5. botpy.Client 上非下划线、非 on_ 开头的方法 =====")
    try:
        client_cls = getattr(botpy_module, "Client")
        for name in sorted(dir(client_cls)):
            if name.startswith("_"):
                continue
            if name.startswith("on_"):
                continue
            try:
                member = getattr(client_cls, name)
            except Exception as exc:
                _skip(f"{name}: {exc}")
                continue
            if callable(member):
                print(name)
    except Exception as exc:
        _skip(exc)


def _dump_message_classes() -> None:
    print("\n===== 6. botpy.message 下的类 =====")
    try:
        module = importlib.import_module("botpy.message")
    except Exception as exc:
        _skip(f"import botpy.message: {exc}")
        return

    try:
        classes = [
            (name, obj)
            for name, obj in inspect.getmembers(module, inspect.isclass)
            if not name.startswith("_")
        ]
    except Exception as exc:
        _skip(exc)
        return

    for name, obj in classes:
        print(f"--- {name} ---")
        try:
            print(_signature(obj.__init__))
        except Exception as exc:
            _skip(f"{name}.__init__: {exc}")


def _dump_api_functions() -> None:
    print("\n===== 7. botpy.api 下的公开函数 =====")
    try:
        module = importlib.import_module("botpy.api")
    except Exception as exc:
        _skip(f"import botpy.api: {exc}")
        return

    try:
        functions = [
            (name, obj)
            for name, obj in inspect.getmembers(module, inspect.isfunction)
            if not name.startswith("_")
        ]
    except Exception as exc:
        _skip(exc)
        return

    for name, obj in functions:
        print(f"{name}{_signature(obj)}")


def _dump_intents(botpy_module: object) -> None:
    print("\n===== 8. botpy.Intents =====")
    try:
        intents_cls = getattr(botpy_module, "Intents")
    except Exception as exc:
        _skip(exc)
        return

    print("--- Intents.__init__ ---")
    try:
        print(_signature(intents_cls.__init__))
    except Exception as exc:
        _skip(exc)

    print("--- Intents 属性名 ---")
    try:
        for name in sorted(dir(intents_cls)):
            if not name.startswith("_"):
                print(name)
    except Exception as exc:
        _skip(exc)


def main() -> None:
    _dump_version()
    botpy_module = _import_botpy()
    if botpy_module is None:
        return
    _dump_public_names(botpy_module)
    _dump_client_init(botpy_module)
    _dump_client_methods(botpy_module)
    _dump_message_classes()
    _dump_api_functions()
    _dump_intents(botpy_module)


if __name__ == "__main__":
    main()
