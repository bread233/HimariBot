"""容错版 MCP stdio 客户端包装。

MCP stdio 协议规定 stdout 仅可承载 JSON-RPC 消息，所有日志/状态/调试输出
必须写到 stderr（参见 https://modelcontextprotocol.io/specification/server/transports#stdio）。

但部分第三方 MCP 服务器（典型如 ``moegirl-wiki-mcp`` 等 npm 包）会把启动横幅
直接打印到 stdout，污染协议流。``mcp.client.stdio.stdio_client`` 遇到这类
非 JSON 行时会把 ``Exception`` 对象写回 read_stream，使 ``ClientSession``
将其视为致命错误并终止 ``initialize`` 协商。

本模块提供 :func:`tolerant_stdio_client`：行为与官方 ``stdio_client`` 完全一致，
唯一差异在于在解析层先按 JSON 起始符做廉价预筛、解析失败的行只记录告警后丢弃，
不向上层流注入异常。这样违规服务器仍可正常握手，合规服务器行为不变。

注意：本模块仅依赖 ``mcp`` SDK 的公开 API（``StdioServerParameters``、
``types.JSONRPCMessage``、``SessionMessage``），不再依赖任何私有符号。
"""

from __future__ import annotations

import asyncio
import codecs
import logging
import os
import shutil
import sys
from contextlib import asynccontextmanager
from typing import TextIO

from mcp import types
from mcp.client.stdio import StdioServerParameters
from mcp.shared.message import SessionMessage

import anyio
import anyio.lowlevel

logger = logging.getLogger(__name__)

_MAX_GARBAGE_PREVIEW = 200
_PROCESS_TERMINATION_TIMEOUT = 5.0


def _resolve_executable_command(command: str) -> str:
    """解析 command 为可执行路径。

    对于绝对路径直接返回；否则通过 ``shutil.which`` 查找可执行文件。
    找不到时返回原始 command，后续 ``create_subprocess_exec`` 会抛出 OSError。

    Args:
        command: 命令名称或路径。

    Returns:
        str: 解析后的可执行路径。
    """
    if os.path.isabs(command):
        return command
    resolved = shutil.which(command)
    if resolved is not None:
        return resolved
    return command


def _build_default_environment() -> dict[str, str]:
    """获取默认环境变量（过滤 None 值）。

    Returns:
        dict[str, str]: 过滤后的环境变量字典。
    """
    return {k: v for k, v in os.environ.items() if v is not None}


async def _create_stdio_process(
    command: str,
    args: list[str],
    env: dict[str, str],
    errlog: TextIO,
    cwd: str | None,
) -> asyncio.subprocess.Process:
    """创建 stdio 子进程。

    Args:
        command: 可执行文件路径。
        args: 命令行参数。
        env: 环境变量。
        errlog: stderr 透传目标。
        cwd: 工作目录。

    Returns:
        asyncio.subprocess.Process: 创建的子进程。
    """
    return await asyncio.create_subprocess_exec(
        command,
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=errlog,
        env=env,
        cwd=cwd,
    )


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    """优雅终止进程。

    先尝试 terminate，等待超时后 kill。

    Args:
        process: 待终止的子进程。
    """
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=_PROCESS_TERMINATION_TIMEOUT)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.wait()


def _process_stdout_lines(
    buffer: str,
    text: str,
    decoder: codecs.IncrementalDecoder,
    read_stream_writer: anyio.abc.ObjectSendStream,
) -> tuple[str, asyncio.Task]:
    """解码 stdout 数据并尝试发送 JSON-RPC 消息。

    返回更新后的 buffer。消息通过 read_stream_writer 发送（由调用方 await）。
    """
    lines = (buffer + text).split("\n")
    return lines


@asynccontextmanager
async def tolerant_stdio_client(
    server: StdioServerParameters,
    errlog: TextIO = sys.stderr,
):
    """官方 ``stdio_client`` 的容错替代实现。

    Args:
        server: stdio 子进程启动参数。
        errlog: 子进程 stderr 透传目标，默认 ``sys.stderr``。

    Yields:
        tuple[Any, Any]: ``(read_stream, write_stream)``，与官方实现接口一致。

    实现差异：
        - 仅对以 ``{`` 或 ``[`` 开头的非空行尝试 JSON-RPC 解析。
        - 预筛失败或 pydantic 校验失败的行通过 ``logger.warning`` 记录后直接丢弃，
          不会以 ``Exception`` 对象的形式注入 read_stream。
        - 进程生命周期、stdin 关闭流程与官方实现完全一致。
    """

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    try:
        command = _resolve_executable_command(server.command)
        env = (
            {**_build_default_environment(), **server.env}
            if server.env is not None
            else _build_default_environment()
        )
        process = await _create_stdio_process(
            command=command,
            args=server.args,
            env=env,
            errlog=errlog,
            cwd=server.cwd,
        )
    except OSError:
        await read_stream.aclose()
        await write_stream.aclose()
        await read_stream_writer.aclose()
        await write_stream_reader.aclose()
        raise

    decoder = codecs.getincrementaldecoder(server.encoding)(
        errors=server.encoding_error_handler,
    )

    async def stdout_reader() -> None:
        assert process.stdout, "Opened process is missing stdout"
        try:
            async with read_stream_writer:
                buffer = ""
                while True:
                    chunk = await process.stdout.read(4096)
                    if not chunk:
                        break
                    text = decoder.decode(chunk)
                    if not text:
                        continue
                    lines = (buffer + text).split("\n")
                    buffer = lines.pop()
                    for line in lines:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        # JSON-RPC 2.0 消息总是 JSON 对象（'{'）或批量数组（'['）；
                        # 任何其他起始字符都可以无歧义判定为协议违规噪声。
                        if stripped[0] not in ("{", "["):
                            logger.warning(
                                "Dropped non-JSON line from MCP stdio server "
                                "(violates MCP spec — stdout must carry JSON-RPC only): %r",
                                line[:_MAX_GARBAGE_PREVIEW],
                            )
                            continue
                        try:
                            message = types.JSONRPCMessage.model_validate_json(line)
                        except Exception:
                            logger.warning(
                                "Dropped malformed JSON-RPC line from MCP stdio server: %r",
                                line[:_MAX_GARBAGE_PREVIEW],
                            )
                            continue
                        await read_stream_writer.send(SessionMessage(message))
                # flush remaining bytes
                remaining = decoder.decode(b"", final=True)
                if remaining.strip():
                    lines = (buffer + remaining).split("\n")
                    for line in lines:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        if stripped[0] not in ("{", "["):
                            logger.warning(
                                "Dropped non-JSON line from MCP stdio server "
                                "(violates MCP spec — stdout must carry JSON-RPC only): %r",
                                line[:_MAX_GARBAGE_PREVIEW],
                            )
                            continue
                        try:
                            message = types.JSONRPCMessage.model_validate_json(line)
                        except Exception:
                            logger.warning(
                                "Dropped malformed JSON-RPC line from MCP stdio server: %r",
                                line[:_MAX_GARBAGE_PREVIEW],
                            )
                            continue
                        await read_stream_writer.send(SessionMessage(message))
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async def stdin_writer() -> None:
        assert process.stdin, "Opened process is missing stdin"
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    json_payload = session_message.message.model_dump_json(
                        by_alias=True, exclude_none=True
                    )
                    data = (json_payload + "\n").encode(
                        encoding=server.encoding,
                        errors=server.encoding_error_handler,
                    )
                    process.stdin.write(data)
                    await process.stdin.drain()
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdout_reader)
        tg.start_soon(stdin_writer)
        try:
            yield read_stream, write_stream
        finally:
            if process.stdin:
                try:
                    process.stdin.close()
                except Exception:
                    pass
            await _terminate_process(process)
            await read_stream.aclose()
            await write_stream.aclose()
            await read_stream_writer.aclose()
            await write_stream_reader.aclose()
