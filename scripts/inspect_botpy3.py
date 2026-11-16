"""第三次探测 botpy：InboundMessage 结构、事件分发链路与源码片段。

只读探测：不读取 .env，不发起网络请求。每项独立 try/except，
失败打印 ``SKIP: <原因>`` 后继续。
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect


def _skip(reason: object) -> None:
    print(f"SKIP: {reason}")


def _signature(obj: object) -> str:
    try:
        return str(inspect.signature(obj))
    except Exception as exc:
        return f" -> SKIP: {exc}"


def _type_text(annotation: object) -> str:
    if isinstance(annotation, str):
        return annotation
    return getattr(annotation, "__name__", repr(annotation))


def _print_source(obj: object, limit: int) -> None:
    try:
        source = inspect.getsource(obj)
    except Exception as exc:
        _skip(f"getsource: {exc}")
        return
    lines = source.splitlines()
    print("\n".join(lines[:limit]))
    if len(lines) > limit:
        print(f"... truncated: 共 {len(lines)} 行，仅打印前 {limit} 行")


def _dump_structure(class_ref: str) -> None:
    module_name, _, class_name = class_ref.rpartition(".")
    print(f"\n===== {class_ref} 结构 =====")
    try:
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
    except Exception as exc:
        _skip(f"定位 {class_ref}: {exc}")
        return

    try:
        if dataclasses.is_dataclass(cls):
            print("is_dataclass: True")
            for field in dataclasses.fields(cls):
                print(f"{field.name}: {_type_text(field.type)}")
            return
        print("is_dataclass: False")
    except Exception as exc:
        _skip(f"is_dataclass/fields: {exc}")

    try:
        slots = getattr(cls, "__slots__", "<无 __slots__>")
        print(f"__slots__: {slots!r}")
    except Exception as exc:
        _skip(f"__slots__: {exc}")

    try:
        annotations = getattr(cls, "__annotations__", None)
        print(f"__annotations__: {annotations!r}")
    except Exception as exc:
        _skip(f"__annotations__: {exc}")

    try:
        names = [name for name in dir(cls) if not name.startswith("_")]
        print("公开属性名: " + ", ".join(names))
    except Exception as exc:
        _skip(f"dir: {exc}")


def _dump_relation() -> None:
    print("\n===== InboundMessage 与 GroupMessage 的关系 =====")
    try:
        models = importlib.import_module("botpy.protocol.models")
        inbound_cls = models.InboundMessage
        group_cls = importlib.import_module("botpy.message").GroupMessage
    except Exception as exc:
        _skip(f"定位类: {exc}")
        return

    try:
        for base in inbound_cls.__mro__:
            print(f"mro: {base!r}")
    except Exception as exc:
        _skip(f"__mro__: {exc}")

    try:
        names = [name for name in dir(inbound_cls) if not name.startswith("_")]
        print("InboundMessage 公开名字: " + ", ".join(names))
    except Exception as exc:
        _skip(f"dir(InboundMessage): {exc}")

    try:
        print(f"issubclass(GroupMessage, InboundMessage): {issubclass(group_cls, inbound_cls)}")
    except Exception as exc:
        _skip(f"issubclass: {exc}")

    for attr in ("raw", "data", "payload", "message"):
        try:
            if hasattr(inbound_cls, attr):
                member = getattr(inbound_cls, attr)
                print(f"InboundMessage.{attr}: {type(member).__name__}")
            else:
                print(f"InboundMessage.{attr}: <不存在>")
        except Exception as exc:
            _skip(f"InboundMessage.{attr}: {exc}")


def _dump_normalize() -> None:
    print("\n===== botpy.normalize_inbound_message =====")
    try:
        botpy_module = importlib.import_module("botpy")
        func = botpy_module.normalize_inbound_message
    except Exception as exc:
        _skip(f"定位 normalize_inbound_message: {exc}")
        return

    print(f"signature{_signature(func)}")
    print("--- source 前 40 行 ---")
    _print_source(func, 40)


def _dump_group_reply() -> None:
    print("\n===== botpy.message.GroupMessage.reply 源码 =====")
    try:
        group_cls = importlib.import_module("botpy.message").GroupMessage
        func = group_cls.reply
    except Exception as exc:
        _skip(f"定位 GroupMessage.reply: {exc}")
        return
    _print_source(func, 80)


def _dump_policy_classes() -> None:
    print("\n===== ReplyLimiter / MessageSendPolicy 构造签名 =====")
    try:
        reply_module = importlib.import_module("botpy.protocol.reply")
        print(f"ReplyLimiter.__init__{_signature(reply_module.ReplyLimiter.__init__)}")
    except Exception as exc:
        _skip(f"ReplyLimiter: {exc}")

    try:
        policy_module = importlib.import_module("botpy.protocol.send_policy")
        print(
            "MessageSendPolicy.__init__"
            f"{_signature(policy_module.MessageSendPolicy.__init__)}"
        )
    except Exception as exc:
        _skip(f"MessageSendPolicy: {exc}")


def _dump_client_use() -> None:
    print("\n===== botpy.Client.use 签名 =====")
    try:
        client_cls = importlib.import_module("botpy").Client
        print(f"use{_signature(client_cls.use)}")
    except Exception as exc:
        _skip(f"Client.use: {exc}")


def _dump_ws_dispatch() -> None:
    print("\n===== botpy.Client.ws_dispatch 源码前 60 行 =====")
    try:
        client_cls = importlib.import_module("botpy").Client
        func = client_cls.ws_dispatch
    except Exception as exc:
        _skip(f"定位 ws_dispatch: {exc}")
        return
    _print_source(func, 60)


def main() -> None:
    _dump_structure("botpy.protocol.models.InboundMessage")
    _dump_structure("botpy.protocol.models.RawEvent")
    _dump_relation()
    _dump_normalize()
    _dump_group_reply()
    _dump_policy_classes()
    _dump_client_use()
    _dump_ws_dispatch()


if __name__ == "__main__":
    main()
