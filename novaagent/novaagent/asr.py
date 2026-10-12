"""DashScope 录音文件转写客户端(会议纪要的录音入口)。

链路(四步,全部走原生 REST,不走 SDK —— 本项目的 LLM 层也是裸 httpx):
  1. `GET /api/v1/uploads?action=getUploadPolicy&model=<ASR_MODEL>` 取上传凭证
  2. 表单 POST 上传到凭证里的 `upload_host`,得到 `oss://<key>` 临时 URL
  3. `POST /api/v1/services/audio/asr/transcription`(`X-DashScope-Async: enable`)提交任务 → task_id
  4. `GET /api/v1/tasks/<task_id>` 轮询到 SUCCEEDED → 下载 `transcription_url` 指向的结果 JSON

【为什么音频必须上传到远端】
  录音文件识别的异步任务**只吃公网可访问的 URL**,不吃本地文件路径;能同步传本地 Base64
  的 `qwen3-asr-flash` 限制是 ≤10MB / ≤5 分钟,真实班会录音(30~60 分钟)直接超标。
  百炼自带的免费临时存储是这条链路唯一不需要自备 OSS 的做法。

【隐私:这一步会出网】
  会议音频原文(含师生姓名、讨论内容)会离开本机。这是**用户主动上传**才发生的动作,
  调用方必须在 UI 上显式确认;本模块**不落盘**音频(内存直传),转写完成后本地不留副本。
  与既有「联网检索只发问题文本」是两条不同的出网通道,别混为一谈。

⚠ **本模块未经真机联调**:字段名以官方文档为准做了容错(见 `_pick`),
  首次真跑若报错,错误信息会直接打印响应里实际存在的键名清单(不含值),便于定位。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx

from . import config


class AsrError(RuntimeError):
    """转写失败。message 面向用户可读,不泄露 key、不打印音频内容。"""


# ---------------------------------------------------------------- 纯函数层

def check_audio(filename: str, size: int) -> str:
    """上传前置校验,返回小写后缀。不合法直接抛 AsrError(不烧一次网络往返)。"""
    ext = Path(filename or "").suffix.lower()
    if ext not in config.ASR_AUDIO_EXTS:
        raise AsrError(
            f"不支持的音频格式 {ext or '(无后缀)'};支持 " + "、".join(sorted(config.ASR_AUDIO_EXTS))
        )
    max_bytes = config.ASR_MAX_MB * 1024 * 1024
    if size <= 0:
        raise AsrError("音频文件为空")
    if size > max_bytes:
        raise AsrError(f"音频超过 {config.ASR_MAX_MB}MB 上限({size // 1024 // 1024}MB)")
    return ext


def _pick(d: dict, *names: str) -> Any:
    """按键名优先级取值(不同文档版本对凭证字段命名不一致,故容错而不是写死一个)。"""
    for n in names:
        if n in d and d[n] not in (None, ""):
            return d[n]
    return None


def _keys_of(d: Any) -> str:
    try:
        return ",".join(sorted(str(k) for k in d.keys())) or "(无)"
    except Exception:
        return type(d).__name__


def parse_transcription(payload: Any) -> str:
    """识别结果 JSON → 纯文本。

    优先级:逐句 `sentences[].text`(带时间轴、按说话人分行)> `transcripts[].text`
    > 顶层 `text`。**取不到任何文本 → 抛错**,不返回空串假装成功。
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return payload.strip()
    if not isinstance(payload, dict):
        raise AsrError(f"识别结果结构无法解析(顶层 {_keys_of(payload)})")

    lines: list[str] = []
    transcripts = payload.get("transcripts")
    if isinstance(transcripts, list):
        for tr in transcripts:
            if not isinstance(tr, dict):
                continue
            sents = tr.get("sentences")
            if isinstance(sents, list) and sents:
                for s in sents:
                    text = str((s or {}).get("text") or "").strip()
                    if not text:
                        continue
                    spk = (s or {}).get("speaker_id")
                    lines.append(f"[说话人{int(spk) + 1}] {text}"
                                 if isinstance(spk, int) and spk >= 0 else text)
            else:
                text = str(tr.get("text") or "").strip()
                if text:
                    lines.append(text)
    if not lines:
        text = str(payload.get("text") or "").strip()
        if text:
            lines.append(text)
    if not lines:
        raise AsrError(f"识别结果里没有可用文本(键 {_keys_of(payload)})")
    return "\n".join(lines).strip()


def build_task_body(file_url: str, model: str = "") -> dict:
    """异步转写任务的请求体(纯函数,便于离线断言参数拼装)。"""
    parameters: dict[str, Any] = {}
    if config.ASR_DIARIZATION:
        parameters["diarization_enabled"] = True
        if config.ASR_SPEAKER_COUNT > 0:
            parameters["speaker_count"] = config.ASR_SPEAKER_COUNT
    return {
        "model": model or config.ASR_MODEL,
        "input": {"file_urls": [file_url]},
        "parameters": parameters,
    }


def task_status(output: dict) -> str:
    return str((output or {}).get("task_status") or "").upper()


# ---------------------------------------------------------------- 网络层

def _api_key(api_key: str) -> str:
    key = api_key or config.LLM_API_KEY
    if not key:
        raise AsrError("未配置 LLM_API_KEY,无法调用录音转写")
    return key


def _base() -> str:
    return config.DASHSCOPE_BASE_URL


async def _get_upload_policy(client: httpx.AsyncClient, key: str, model: str) -> dict:
    resp = await client.get(
        f"{_base()}/api/v1/uploads",
        params={"action": "getUploadPolicy", "model": model},
        headers={"Authorization": f"Bearer {key}"},
    )
    if resp.status_code != 200:
        raise AsrError(f"获取上传凭证失败 HTTP {resp.status_code}")
    try:
        data = resp.json()
    except json.JSONDecodeError:
        raise AsrError("上传凭证响应不是 JSON")
    policy = data.get("data") if isinstance(data.get("data"), dict) else data
    if not _pick(policy, "upload_host", "uploadHost"):
        raise AsrError(f"上传凭证缺少 upload_host(实际键:{_keys_of(policy)})")
    return policy


async def _upload(client: httpx.AsyncClient, policy: dict, filename: str,
                  data: bytes, model: str) -> str:
    """表单直传 OSS,返回 `oss://<key>` 临时 URL。"""
    host = str(_pick(policy, "upload_host", "uploadHost"))
    upload_dir = str(_pick(policy, "upload_dir", "uploadDir") or "").strip("/")
    key = _pick(policy, "key", "oss_key", "ossKey") or f"{upload_dir}/{filename}"
    fields = {
        "key": key,
        "policy": str(_pick(policy, "policy") or ""),
        "signature": str(_pick(policy, "signature") or ""),
        "x-oss-object-acl": str(_pick(policy, "x_oss_object_acl", "xOssObjectAcl") or "private"),
        "x-oss-forbid-overwrite": str(
            _pick(policy, "x_oss_forbid_overwrite", "xOssForbidOverwrite") or "true"),
        "success_action_status": "200",
    }
    ak = _pick(policy, "oss_access_key_id", "ossAccessKeyId", "access_key_id", "OSSAccessKeyId")
    if ak:
        fields["OSSAccessKeyId"] = str(ak)
    if not fields["policy"] or not fields["signature"]:
        raise AsrError(f"上传凭证缺少 policy/signature(实际键:{_keys_of(policy)})")
    resp = await client.post(host, data=fields,
                             files={"file": (filename, data, "application/octet-stream")})
    if resp.status_code not in (200, 204):
        raise AsrError(f"音频上传失败 HTTP {resp.status_code}(模型 {model} 与凭证须一致)")
    return f"oss://{key}"


async def _submit(client: httpx.AsyncClient, key: str, file_url: str, model: str) -> str:
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
        # oss:// 协议必须显式声明才会在服务端被解析为内部 OSS 资源
        "X-DashScope-OssResourceResolve": "enable",
    }
    resp = await client.post(f"{_base()}/api/v1/services/audio/asr/transcription",
                             headers=headers, json=build_task_body(file_url, model))
    if resp.status_code != 200:
        raise AsrError(f"转写任务提交失败 HTTP {resp.status_code}")
    data = resp.json()
    task_id = _pick(data.get("output") or {}, "task_id")
    if not task_id:
        raise AsrError(f"提交响应没有 task_id(实际键:{_keys_of(data.get('output'))})")
    return str(task_id)


async def _poll(client: httpx.AsyncClient, key: str, task_id: str) -> dict:
    """轮询到 SUCCEEDED 返回 output;FAILED/CANCELED 或未知终态抛错。"""
    deadline = config.ASR_TOTAL_TIMEOUT_S
    waited = 0.0
    while True:
        resp = await client.get(f"{_base()}/api/v1/tasks/{task_id}",
                                headers={"Authorization": f"Bearer {key}"})
        if resp.status_code != 200:
            raise AsrError(f"任务状态查询失败 HTTP {resp.status_code}")
        output = (resp.json() or {}).get("output") or {}
        st = task_status(output)
        if st == "SUCCEEDED":
            return output
        if st in ("FAILED", "CANCELED", "CANCELLED", "UNKNOWN"):
            code = _pick(output, "code", "message") or ""
            raise AsrError(f"转写任务{st} {str(code)[:120]}".strip())
        if waited >= deadline:
            raise AsrError(f"转写超时(已等待 {int(waited)}s,上限 {int(deadline)}s)")
        await asyncio.sleep(config.ASR_POLL_INTERVAL_S)
        waited += config.ASR_POLL_INTERVAL_S


async def _fetch_result(client: httpx.AsyncClient, output: dict) -> str:
    results = output.get("results")
    if not isinstance(results, list) or not results:
        raise AsrError(f"任务成功但没有结果条目(实际键:{_keys_of(output)})")
    texts: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url = _pick(item, "transcription_url", "url")
        if not url:
            continue
        r = await client.get(str(url))
        if r.status_code != 200:
            raise AsrError(f"下载识别结果失败 HTTP {r.status_code}")
        try:
            texts.append(parse_transcription(r.json()))
        except json.JSONDecodeError:
            texts.append(parse_transcription(r.text))
    if not texts:
        raise AsrError(f"结果条目里没有 transcription_url(实际键:{_keys_of(results[0])})")
    return "\n\n".join(t for t in texts if t).strip()


async def transcribe(filename: str, data: bytes, model: str = "",
                     api_key: str = "") -> str:
    """音频字节 → 转写文本。全程内存直传,**不在本地落盘音频**。"""
    if not config.ASR_ENABLED:
        raise AsrError("录音转写已在配置中关闭(NOVA_ASR_ENABLED=0)")
    key = _api_key(api_key)
    mdl = model or config.ASR_MODEL
    check_audio(filename, len(data))
    timeout = httpx.Timeout(config.ASR_TOTAL_TIMEOUT_S, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        policy = await _get_upload_policy(client, key, mdl)
        file_url = await _upload(client, policy, filename, data, mdl)
        task_id = await _submit(client, key, file_url, mdl)
        output = await _poll(client, key, task_id)
        return await _fetch_result(client, output)


def describe_config() -> dict:
    """给 /api/health 用的**只读**配置读数(不含 key 值,只含来源标签 —— 同 config.key_source 纪律)。"""
    return {
        "asr_enabled": config.ASR_ENABLED,
        "asr_model": config.ASR_MODEL,
        "asr_diarization": config.ASR_DIARIZATION,
        "asr_max_mb": config.ASR_MAX_MB,
        "asr_total_timeout_s": config.ASR_TOTAL_TIMEOUT_S,
        "asr_key_source": config.key_source("LLM_API_KEY"),
        "asr_base_url": config.DASHSCOPE_BASE_URL,
    }
