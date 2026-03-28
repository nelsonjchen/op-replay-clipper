"""Styled text helpers for pyray-based overlays.

This module includes a small Python/pyray port of ideas from
`DrawTextStyle.h` in NathanGuilhot/Raylib_DrawTextStyle:
https://github.com/NathanGuilhot/Raylib_DrawTextStyle/tree/main

Upstream is MIT-licensed. Copyright (c) 2021 Nighten.
See the upstream repository LICENSE file for the original terms.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class StyledTextFonts:
    regular: Any
    bold: Any
    italic: Any | None = None
    bold_italic: Any | None = None
    code: Any | None = None


@dataclass(frozen=True)
class StyledTextState:
    bold: bool = False
    italic: bool = False
    underline: bool = False
    crossed: bool = False
    code: bool = False


@dataclass(frozen=True)
class StyledTextRun:
    text: str
    state: StyledTextState
    color: Any | None = None


@dataclass(frozen=True)
class StyledTextPaint:
    color: Any
    code_text_color: Any | None = None
    code_fill_color: Any | None = None
    code_border_color: Any | None = None


@dataclass(frozen=True)
class StyledTextMetrics:
    width: float
    height: float


def parse_inline_text(text: str, *, initial_state: StyledTextState | None = None) -> list[StyledTextRun]:
    state = initial_state or StyledTextState()
    runs: list[StyledTextRun] = []
    buffer: list[str] = []
    idx = 0

    def flush_buffer() -> None:
        if buffer:
            runs.append(StyledTextRun("".join(buffer), state))
            buffer.clear()

    while idx < len(text):
        if text.startswith("**", idx):
            flush_buffer()
            state = replace(state, bold=not state.bold)
            idx += 2
            continue
        if text.startswith("__", idx):
            flush_buffer()
            state = replace(state, underline=not state.underline)
            idx += 2
            continue
        if text.startswith("~~", idx):
            flush_buffer()
            state = replace(state, crossed=not state.crossed)
            idx += 2
            continue
        ch = text[idx]
        if ch == "*":
            flush_buffer()
            state = replace(state, italic=not state.italic)
            idx += 1
            continue
        if ch == "`":
            flush_buffer()
            state = replace(state, code=not state.code)
            idx += 1
            continue
        buffer.append(ch)
        idx += 1

    flush_buffer()
    return runs


def _split_runs_on_newlines(runs: list[StyledTextRun]) -> list[list[StyledTextRun]]:
    lines: list[list[StyledTextRun]] = [[]]
    for run in runs:
        pieces = run.text.split("\n")
        for piece_idx, piece in enumerate(pieces):
            if piece:
                lines[-1].append(StyledTextRun(piece, run.state, run.color))
            if piece_idx < len(pieces) - 1:
                lines.append([])
    return lines


def _font_base_size(font) -> float:
    return max(1.0, float(getattr(font, "baseSize", 1.0) or 1.0))


def _glyph_advance(font, codepoint: int, *, font_size: float = 24.0) -> float:
    import pyray as rl

    scale = font_size / _font_base_size(font)
    get_glyph_info = getattr(rl, "get_glyph_info", None)
    if callable(get_glyph_info):
        try:
            glyph = get_glyph_info(font, codepoint)
        except Exception:
            glyph = None
        if glyph is not None:
            advance = float(getattr(glyph, "advanceX", 0.0) or 0.0)
            if advance <= 0.0:
                get_glyph_atlas_rec = getattr(rl, "get_glyph_atlas_rec", None)
                if callable(get_glyph_atlas_rec):
                    try:
                        glyph_rect = get_glyph_atlas_rec(font, codepoint)
                    except Exception:
                        glyph_rect = None
                    if glyph_rect is not None:
                        advance = float(getattr(glyph_rect, "width", 0.0) or 0.0)
            if advance > 0.0:
                return advance * scale

    try:
        text_size = rl.measure_text_ex(font, chr(codepoint), font_size, 0)
        return float(getattr(text_size, "x", 0.0) or 0.0)
    except Exception:
        return 0.0


def _select_font(fonts: StyledTextFonts, state: StyledTextState):
    if state.code and fonts.code is not None:
        return fonts.code
    if state.bold and state.italic and fonts.bold_italic is not None:
        return fonts.bold_italic
    if state.bold:
        return fonts.bold
    if state.italic and fonts.italic is not None:
        return fonts.italic
    return fonts.regular


def measure_inline_text(
    fonts: StyledTextFonts,
    text: str | list[StyledTextRun],
    *,
    font_size: float,
    spacing: float = 0.0,
    line_spacing: float = 1.0,
) -> tuple[float, float]:
    import pyray as rl

    runs = parse_inline_text(text) if isinstance(text, str) else text
    lines = _split_runs_on_newlines(runs)
    if not lines:
        return 0.0, 0.0

    line_widths: list[float] = []
    for line in lines:
        line_width = 0.0
        for run in line:
            font = _select_font(fonts, run.state)
            codepoints = [ord(ch) for ch in run.text]
            for char_idx, codepoint in enumerate(codepoints):
                line_width += _glyph_advance(font, codepoint, font_size=font_size)
                if char_idx < len(codepoints) - 1:
                    line_width += spacing
        line_widths.append(line_width)

    line_height = font_size * line_spacing
    return max(line_widths), line_height * len(lines)


def _measure_run_layout(
    fonts: StyledTextFonts,
    run: StyledTextRun,
    *,
    font_size: float,
    spacing: float,
    code_padding_x: float,
    code_padding_y: float,
) -> tuple[float, float]:
    font = _select_font(fonts, run.state)
    text_width = 0.0
    codepoints = [ord(ch) for ch in run.text]
    for char_idx, codepoint in enumerate(codepoints):
        text_width += _glyph_advance(font, codepoint, font_size=font_size)
        if char_idx < len(codepoints) - 1:
            text_width += spacing

    width = text_width
    height = font_size
    if run.state.code:
        width += code_padding_x * 2
        height = max(height, font_size + (code_padding_y * 2))
    return width, height


def measure_styled_text_line(
    *,
    fonts: StyledTextFonts,
    text: str | list[StyledTextRun],
    font_size: float,
    spacing: float = 0.0,
    code_padding_x: float = 0.0,
    code_padding_y: float = 0.0,
) -> StyledTextMetrics:
    runs = parse_inline_text(text) if isinstance(text, str) else text
    lines = _split_runs_on_newlines(runs)
    if not lines:
        return StyledTextMetrics(width=0.0, height=0.0)

    line_widths: list[float] = []
    line_heights: list[float] = []
    for line in lines:
        width = 0.0
        height = font_size
        for run in line:
            run_width, run_height = _measure_run_layout(
                fonts,
                run,
                font_size=font_size,
                spacing=spacing,
                code_padding_x=code_padding_x,
                code_padding_y=code_padding_y,
            )
            width += run_width
            height = max(height, run_height)
        line_widths.append(width)
        line_heights.append(height)

    return StyledTextMetrics(width=max(line_widths), height=sum(line_heights))


def draw_inline_text(
    fonts: StyledTextFonts,
    text: str | list[StyledTextRun],
    *,
    position,
    font_size: float,
    default_color,
    spacing: float = 0.0,
    line_spacing: float = 1.0,
    align: str = "left",
    width: float | None = None,
    code_color=None,
) -> tuple[float, float]:
    import pyray as rl

    runs = parse_inline_text(text) if isinstance(text, str) else text
    lines = _split_runs_on_newlines(runs)
    if not lines:
        return 0.0, 0.0

    line_metrics = [measure_inline_text(fonts, line, font_size=font_size, spacing=spacing, line_spacing=line_spacing) for line in lines]
    max_line_width = max(width for width, _ in line_metrics)
    line_height = font_size * line_spacing
    total_height = line_height * len(lines)
    block_width = width if width is not None else max_line_width
    start_y = float(position.y)

    def _line_x(line_width: float) -> float:
        if align == "center":
            return float(position.x) + max(0.0, (block_width - line_width) / 2)
        if align == "right":
            return float(position.x) + max(0.0, block_width - line_width)
        return float(position.x)

    for line_idx, line in enumerate(lines):
        line_width, _ = line_metrics[line_idx]
        cursor_x = _line_x(line_width)
        cursor_y = start_y + (line_idx * line_height)
        for run in line:
            font = _select_font(fonts, run.state)
            color = run.color or (code_color if run.state.code and code_color is not None else default_color)
            run_start_x = cursor_x
            for char_idx, ch in enumerate(run.text):
                codepoint = ord(ch)
                draw_text_codepoint = getattr(rl, "draw_text_codepoint", None)
                if callable(draw_text_codepoint):
                    draw_text_codepoint(font, codepoint, rl.Vector2(cursor_x, cursor_y), font_size, color)
                else:
                    rl.draw_text_ex(font, ch, rl.Vector2(cursor_x, cursor_y), font_size, 0, color)
                cursor_x += _glyph_advance(font, codepoint, font_size=font_size)
                if char_idx < len(run.text) - 1:
                    cursor_x += spacing

            run_width = cursor_x - run_start_x
            if run.state.underline:
                underline_y = cursor_y + max(1.0, font_size * 0.92)
                rl.draw_line(run_start_x, underline_y, run_start_x + run_width, underline_y, color)
            if run.state.crossed:
                strike_y = cursor_y + max(1.0, font_size * 0.52)
                rl.draw_line(run_start_x, strike_y, run_start_x + run_width, strike_y, color)

    return max_line_width, total_height


def draw_styled_text_line(
    *,
    fonts: StyledTextFonts,
    text: str | list[StyledTextRun],
    position,
    font_size: float,
    spacing: float = 0.0,
    paint: StyledTextPaint,
    code_padding_x: float = 0.0,
    code_padding_y: float = 0.0,
) -> StyledTextMetrics:
    import pyray as rl

    runs = parse_inline_text(text) if isinstance(text, str) else text
    metrics = measure_styled_text_line(
        fonts=fonts,
        text=runs,
        font_size=font_size,
        spacing=spacing,
        code_padding_x=code_padding_x,
        code_padding_y=code_padding_y,
    )
    cursor_x = float(position.x)
    cursor_y = float(position.y)
    code_text_color = paint.code_text_color or paint.color

    for run in runs:
        font = _select_font(fonts, run.state)
        text_color = run.color or (code_text_color if run.state.code and code_text_color is not None else paint.color)
        run_width, run_height = _measure_run_layout(
            fonts,
            run,
            font_size=font_size,
            spacing=spacing,
            code_padding_x=code_padding_x,
            code_padding_y=code_padding_y,
        )
        run_start_x = cursor_x + (code_padding_x if run.state.code else 0.0)
        if run.state.code and paint.code_fill_color is not None:
            rect_y = cursor_y - code_padding_y
            rl.draw_rectangle_rounded(
                rl.Rectangle(cursor_x, rect_y, run_width, run_height),
                0.24,
                12,
                paint.code_fill_color,
            )
            if paint.code_border_color is not None:
                rl.draw_rectangle_rounded_lines_ex(
                    rl.Rectangle(cursor_x, rect_y, run_width, run_height),
                    0.24,
                    12,
                    2,
                    paint.code_border_color,
                )

        text_x = run_start_x
        for char_idx, ch in enumerate(run.text):
            codepoint = ord(ch)
            draw_text_codepoint = getattr(rl, "draw_text_codepoint", None)
            if callable(draw_text_codepoint):
                draw_text_codepoint(font, codepoint, rl.Vector2(text_x, cursor_y), font_size, text_color)
            else:
                rl.draw_text_ex(font, ch, rl.Vector2(text_x, cursor_y), font_size, 0, text_color)
            text_x += _glyph_advance(font, codepoint, font_size=font_size)
            if char_idx < len(run.text) - 1:
                text_x += spacing

        if run.state.underline:
            underline_y = cursor_y + max(1.0, font_size * 0.92)
            rl.draw_line(run_start_x, underline_y, text_x, underline_y, text_color)
        if run.state.crossed:
            strike_y = cursor_y + max(1.0, font_size * 0.52)
            rl.draw_line(run_start_x, strike_y, text_x, strike_y, text_color)
        cursor_x += run_width

    return metrics
