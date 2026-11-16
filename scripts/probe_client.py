"""探针：确认 Client 实例属性、Intents 取值与 start 的协程语义。

只读探测：不读取 .env，不发起网络请求。每项独立 try/except，
失败打印 ``SKIP: <原因>`` 后继续。
"""

from __future__ import annotations

import dataclasses
import inspect


def _skip(reason: object) -> None:
    print(f"SKIP: {reason}")


def probe_client_attrs() -> None:
    print("===== 1. Client 实例属性 =====")
    try:
        import botpy
    except Exception as exc:
        _skip(f"import botpy: {exc}")
        return

    try:
        client = botpy.Client(intents=botpy.Intents.none())
    except Exception as exc:
        _skip(f"实例化 Client: {exc}")
        return

    try:
        print(f"vars(client) keys: {sorted(vars(client).keys())}")
    except Exception as exc:
        _skip(f"vars: {exc}")

    for name in ("api", "http", "token", "robot"):
        try:
            if hasattr(client, name):
                print(f"client.{name}: {type(getattr(client, name)).__name__}")
            else:
                print(f"client.{name}: <不存在>")
        except Exception as exc:
            _skip(f"client.{name}: {exc}")


def probe_intents() -> None:
    print("\n===== 2. Intents(public_messages=True).value =====")
    try:
        import botpy

        print(int(botpy.Intents(public_messages=True).value))
    except Exception as exc:
        _skip(exc)


def probe_message_scopes() -> None:
    print("\n===== 3. botpy.protocol.models._MESSAGE_SCOPES keys =====")
    try:
        from botpy.protocol import models

        scopes = models._MESSAGE_SCOPES
        print(sorted(scopes.keys()))
    except Exception as exc:
        _skip(exc)


def probe_client_start_source() -> None:
    print("\n===== 4. botpy.Client.start 源码前 40 行 =====")
    try:
        import botpy

        source = inspect.getsource(botpy.Client.start)
    except Exception as exc:
        _skip(exc)
        return
    lines = source.splitlines()
    print("\n".join(lines[:40]))
    if len(lines) > 40:
        print(f"... truncated: 共 {len(lines)} 行，仅打印前 40 行")


def probe_reply_target() -> None:
    print("\n===== 5. ReplyTarget 字段 =====")
    try:
        from botpy.protocol import models

        for field in dataclasses.fields(models.ReplyTarget):
            annotation = field.type
            if not isinstance(annotation, str):
                annotation = getattr(annotation, "__name__", repr(annotation))
            print(f"{field.name}: {annotation}")
    except Exception as exc:
        _skip(exc)


def main() -> None:
    probe_client_attrs()
    probe_intents()
    probe_message_scopes()
    probe_client_start_source()
    probe_reply_target()


if __name__ == "__main__":
    main()
