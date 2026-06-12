import asyncio
import os
import time
from dataclasses import dataclass
from nonebot import logger

@dataclass
class CodexResult:
    ok: bool
    text: str
    score: int = 0
    reason: str = ""

async def ask_codex(config, prompt: str, image_paths: list[str] | None = None) -> CodexResult:
    image_args: list[str] = []
    if image_paths:
        for p in image_paths:
            if p:
                image_args.extend(["--image", str(p)])

    image_log_info = ""
    if image_paths:
        basenames = [os.path.basename(str(p)) for p in image_paths if p]
        image_log_info = f" image_count={len(basenames)} image_basenames={basenames}"

    logger.info(
        f"codex_chat request=1 model={config.codex_chat_model} "
        f"timeout={config.codex_chat_timeout}{image_log_info}"
    )
    started = time.perf_counter()
    try:
        process = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            "-i",
            config.codex_chat_docker_container,
            "codex",
            "--search",
            "exec",
            "-m",
            config.codex_chat_model,
            "-s",
            "read-only",
            "-C",
            config.codex_chat_workdir,
            "--skip-git-repo-check",
            *image_args,
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.warning("codex_chat success=0 error_type=docker_not_found")
        return CodexResult(ok=False, text="", reason="docker_not_found")
    except Exception:
        logger.exception("codex_chat success=0 error_type=process_start_error")
        return CodexResult(ok=False, text="", reason="process_start_error")
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=prompt.encode("utf-8")),
            timeout=config.codex_chat_timeout,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        logger.warning("codex_chat success=0 error_type=timeout")
        return CodexResult(ok=False, text="", reason="timeout")
    except Exception:
        process.kill()
        await process.wait()
        logger.exception("codex_chat success=0 error_type=process_error")
        return CodexResult(ok=False, text="", reason="process_error")

    out_text = stdout.decode("utf-8", errors="ignore").strip()
    err_text = stderr.decode("utf-8", errors="ignore").strip()
    if process.returncode != 0 or not out_text:
        logger.warning(f"codex_chat success=0 returncode={process.returncode} stderr_len={len(err_text)}")
        return CodexResult(ok=False, text="", reason="process_error" if process.returncode != 0 else "empty_output")

    elapsed = time.perf_counter() - started
    logger.info(f"codex_chat success=1 elapsed={elapsed:.3f}s output_len={len(out_text)}")
    return CodexResult(ok=True, text=out_text)
