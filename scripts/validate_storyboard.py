#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


V_RE = re.compile(
    r"^## V(?P<id>\d{2})｜(?P<duration>\d+(?:\.\d+)?)秒｜(?P<start>\d+(?:\.\d+)?)—(?P<end>\d+(?:\.\d+)?)秒.*?$",
    re.MULTILINE,
)
S_RE = re.compile(
    r"S(?P<id>\d{2}) (?P<start>\d+(?:\.\d+)?)—(?P<end>\d+(?:\.\d+)?)秒"
)


def fail(messages: list[str]) -> int:
    for message in messages:
        print(f"ERROR: {message}")
    return 1


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_storyboard.py <storyboard.md>")
        return 2

    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8-sig")
    matches = list(V_RE.finditer(text))
    if not matches:
        return fail(["未找到形如 ## V01｜12秒｜0—12秒 的V标题"])

    errors: list[str] = []
    shot_ids: list[int] = []
    previous_global_end: float | None = None
    long_reactions = 0

    if "耐心消耗曲线" not in text and "失控递进" not in text:
        errors.append("缺少正常角色的耐心消耗或失控递进总表")
    total_v = len(matches)
    for level in range(1, total_v + 1):
        if f"|V{level:02d}|{level}/{total_v}|" not in text:
            errors.append(
                f"导演总表缺少V{level:02d}的{level}/{total_v}累计等级"
            )

    for index, match in enumerate(matches):
        vid = match.group("id")
        duration = float(match.group("duration"))
        global_start = float(match.group("start"))
        global_end = float(match.group("end"))
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():body_end]

        code_blocks = re.findall(r"```text\s*(.*?)```", body, re.DOTALL)
        if len(code_blocks) != 1:
            errors.append(f"V{vid}需要1个可复制text代码块，实际{len(code_blocks)}个")
            code = ""
        else:
            code = code_blocks[0]
            forbidden_cross_v = (
                r"\bV\d{2}\b",
                r"上一V",
                r"前一V",
                r"其他V",
                r"延续全片",
                r"上一条视频",
            )
            for pattern in forbidden_cross_v:
                if re.search(pattern, code):
                    errors.append(f"V{vid}提示词包含跨V依赖表达：{pattern}")
            if "本V上传并绑定：" in code:
                errors.append(f"V{vid}仍有重复的独立资产绑定清单，应改为首次描述时直接@资产")
            if "字幕后期加" in code or "后期再做字幕" in code:
                errors.append(f"V{vid}提示词混入面向制作人员的字幕后期备注")
            if "无字幕" not in code:
                errors.append(f"V{vid}提示词缺少“无字幕”")
            if "五官怼脸超近景" in code:
                if "眼中心" not in code:
                    errors.append(f"V{vid}有五官超近景但缺少眼睛纵向高度锚点")
                if "焦外" not in code:
                    errors.append(f"V{vid}有五官超近景但缺少焦外环境锚点")
                if "回切" not in code and "切回" not in code:
                    errors.append(f"V{vid}有五官超近景但缺少回切近景连续性")

        if previous_global_end is not None and abs(global_start - previous_global_end) > 1e-6:
            errors.append(f"V{vid}全片起点{global_start}不承接上一V终点{previous_global_end}")
        if abs((global_end - global_start) - duration) > 1e-6:
            errors.append(f"V{vid}标题时长与全片区间不一致")
        previous_global_end = global_end

        base_a = len(re.findall(r"^本V基础画面A｜[^\n]+", code, re.MULTILINE))
        base_b = len(re.findall(r"^本V基础画面B｜[^\n]+", code, re.MULTILINE))
        if base_a != 1 or base_b != 1:
            errors.append(
                f"V{vid}代码块应各有且仅有1套A/B基础画面，实际A={base_a}、B={base_b}"
            )
        base_headers = re.findall(r"^本V基础画面[AB]｜([^\n]+)", code, re.MULTILINE)
        if len(base_headers) == 2 and any("@" not in header for header in base_headers):
            errors.append(f"V{vid}的A/B基础画面标题必须直接绑定对应环境资产")
        if "**V级" in body and "基础画面：**" in body:
            errors.append(f"V{vid}代码块外仍有重复的旧版基础画面")
        for field in ("①背景：", "②环境：", "③人物：", "④构图：", "⑤镜头参数："):
            count = code.count(field)
            if count != 2:
                errors.append(f"V{vid}字段{field}应出现2次，实际{count}次")

        shots = list(S_RE.finditer(body))
        if not shots:
            errors.append(f"V{vid}没有S镜头")
            continue
        previous_end = 0.0
        for shot in shots:
            sid = int(shot.group("id"))
            start = float(shot.group("start"))
            end = float(shot.group("end"))
            shot_ids.append(sid)
            if abs(start - previous_end) > 1e-6:
                errors.append(f"V{vid}的S{sid:02d}从{start}开始，前一镜结束于{previous_end}")
            if end <= start:
                errors.append(f"V{vid}的S{sid:02d}时长非正数")
            previous_end = end
        if abs(previous_end - duration) > 1e-6:
            errors.append(f"V{vid}的S时间轴结束于{previous_end}，V时长为{duration}")

        reaction_matches = list(re.finditer(
            r"S\d{2} (?P<a>\d+(?:\.\d+)?)—(?P<b>\d+(?:\.\d+)?)秒[^\n]*3秒长反应",
            body,
        ))
        for reaction in reaction_matches:
            reaction_duration = float(reaction.group("b")) - float(reaction.group("a"))
            long_reactions += 1
            if reaction_duration < 3.0 - 1e-6:
                errors.append(f"V{vid}存在不足3秒的正常角色长反应：{reaction_duration}秒")

    if shot_ids != list(range(shot_ids[0], shot_ids[-1] + 1)):
        errors.append("S编号不连续")
    if long_reactions < len(matches):
        errors.append(f"共{len(matches)}个V，但只找到{long_reactions}个正常角色3秒长反应")

    if errors:
        return fail(errors)
    print(
        f"OK: {len(matches)}个V，S{shot_ids[0]:02d}—S{shot_ids[-1]:02d}连续，"
        f"{long_reactions}个正常角色长反应均不少于3秒，全片{previous_global_end:g}秒"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
