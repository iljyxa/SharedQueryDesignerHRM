#!/usr/bin/env python3
"""
Сборка справки внешней обработки КонструкторПредставленийЗарплатаКадры из Markdown.

Источники и результаты:
  README.md                         -> src/.../Help/ru.html                               (справка обработки)
  docs/КонструкторПредставлений.md  -> src/.../Forms/КонструкторПредставлений/Help/ru.html (справка формы)
  docs/ТекстЗапроса.md              -> src/.../Forms/ТекстЗапроса/Help/ru.html            (справка формы)

Что делает:
  - убирает из Markdown блоки между HTML-комментариями help:skip-begin ... help:skip-end
    (разделы, имеющие смысл только в репозитории) и остальные HTML-комментарии;
  - преобразует Markdown в HTML (python-markdown: fenced_code, tables, toc, sane_lists);
  - убирает изображения по внешним ссылкам (справка 1С не имеет доступа в интернет)
    и разворачивает ссылки на локальные .md-файлы в обычный текст;
  - оборачивает результат в HTML-каркас справки 1С со стилем v8help://service_book/service_style;
  - регистрирует справку в .mdo обработки и форм, если она ещё не зарегистрирована.

Запуск:
  python scripts/build_help.py          # пересобрать файлы справки
  python scripts/build_help.py --check  # только проверить актуальность, код возврата 1 при расхождении

Зависимости: pip install -r requirements.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import markdown
    from markdown.extensions.toc import slugify_unicode
except ImportError:  # pragma: no cover
    sys.exit("Не установлен пакет markdown: pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
PROCESSOR_DIR = ROOT / "src" / "ExternalDataProcessors" / "КонструкторПредставленийЗарплатаКадры"
MDO_PATH = PROCESSOR_DIR / "КонструкторПредставленийЗарплатаКадры.mdo"

# (исходный Markdown, каталог Help, имя формы в .mdo или None для самой обработки)
TARGETS = [
    (ROOT / "README.md", PROCESSOR_DIR / "Help", None),
    (ROOT / "docs" / "КонструкторПредставлений.md", PROCESSOR_DIR / "Forms" / "КонструкторПредставлений" / "Help", "КонструкторПредставлений"),
    (ROOT / "docs" / "ТекстЗапроса.md", PROCESSOR_DIR / "Forms" / "ТекстЗапроса" / "Help", "ТекстЗапроса"),
]

HELP_LANG = "ru"

HTML_TEMPLATE = """<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<link rel="stylesheet" type="text/css" href="v8help://service_book/service_style"></link>
<style>
pre {{ font-family: Consolas, "Courier New", monospace; font-size: 90%; background: #f4f4f4; border: 1px solid #ddd; padding: 6px 8px; white-space: pre-wrap; }}
code {{ font-family: Consolas, "Courier New", monospace; font-size: 95%; }}
table {{ border-collapse: collapse; margin: 8px 0; }}
th, td {{ border: 1px solid #bbb; padding: 3px 8px; vertical-align: top; text-align: left; }}
th {{ background: #eee; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""

SKIP_BLOCK_RE = re.compile(r"<!--\s*help:skip-begin\s*-->.*?<!--\s*help:skip-end\s*-->\s*", re.S)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->\s*", re.S)
REMOTE_IMG_RE = re.compile(r"<p>\s*<img[^>]+src=\"https?://[^\"]*\"[^>]*>\s*</p>\s*|<img[^>]+src=\"https?://[^\"]*\"[^>]*>", re.S)
LOCAL_MD_LINK_RE = re.compile(r"<a href=\"(?!https?://|#)[^\"]*\.md(?:#[^\"]*)?\">(.*?)</a>", re.S)


def preprocess_markdown(text: str) -> str:
    text = SKIP_BLOCK_RE.sub("", text)
    text = HTML_COMMENT_RE.sub("", text)
    return text


def markdown_to_html(text: str) -> str:
    md = markdown.Markdown(
        extensions=["fenced_code", "tables", "sane_lists", "toc"],
        extension_configs={"toc": {"slugify": slugify_unicode, "separator": "-"}},
        output_format="html",
    )
    return md.convert(text)


def postprocess_html(html: str) -> str:
    html = REMOTE_IMG_RE.sub("", html)
    html = LOCAL_MD_LINK_RE.sub(r"\1", html)
    # Пункты оглавления, ведущие на удаленные (пропущенные) разделы.
    ids = set(re.findall(r' id="([^"]+)"', html))
    html = re.sub(r"<li><a href=\"#([^\"]+)\">[^<]*</a></li>\n", lambda m: "" if m.group(1) not in ids else m.group(0), html)
    return html


def build_help_html(md_path: Path) -> str:
    text = md_path.read_text(encoding="utf-8")
    body = postprocess_html(markdown_to_html(preprocess_markdown(text)))
    return HTML_TEMPLATE.format(body=body)


def register_help_in_mdo(mdo_text: str, form_name: str | None) -> str:
    """Добавляет блок <help> в .mdo для обработки (form_name=None) или формы, если его нет."""
    help_block = f"<help>\n{{i}}  <pages>\n{{i}}    <lang>{HELP_LANG}</lang>\n{{i}}  </pages>\n{{i}}</help>"
    if form_name is None:
        # Блок справки обработки идет сразу после <containedObjects .../>.
        head_end = mdo_text.find("<forms uuid=")
        if "<help>" in mdo_text[:head_end]:
            return mdo_text
        return re.sub(
            r"(  <containedObjects [^>]*/>\n)",
            lambda m: m.group(1) + "  " + help_block.format(i="  ") + "\n",
            mdo_text,
            count=1,
        )

    form_re = re.compile(rf"(  <forms uuid=\"[^\"]+\">\n    <name>{re.escape(form_name)}</name>\n.*?)(  </forms>)", re.S)
    match = form_re.search(mdo_text)
    if match is None:
        sys.exit(f"В .mdo не найдена форма {form_name}")
    if "<help>" in match.group(1):
        return mdo_text
    # Блок справки формы идет после </synonym>, перед <usePurposes>.
    form_block = match.group(1).replace("    </synonym>\n", "    </synonym>\n    " + help_block.format(i="    ") + "\n", 1)
    return mdo_text[: match.start(1)] + form_block + mdo_text[match.end(1):]


def main() -> int:
    parser = argparse.ArgumentParser(description="Сборка справки обработки из Markdown")
    parser.add_argument("--check", action="store_true", help="только проверить актуальность справки")
    args = parser.parse_args()

    outputs: dict[Path, str] = {}
    for md_path, help_dir, _ in TARGETS:
        outputs[help_dir / f"{HELP_LANG}.html"] = build_help_html(md_path)

    mdo_text = MDO_PATH.read_text(encoding="utf-8")
    for _, _, form_name in TARGETS:
        mdo_text = register_help_in_mdo(mdo_text, form_name)
    outputs[MDO_PATH] = mdo_text

    stale = [p for p, content in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != content]

    if args.check:
        if stale:
            print("Справка устарела, выполните python scripts/build_help.py:")
            for p in stale:
                print("  ", p.relative_to(ROOT))
            return 1
        print("Справка актуальна")
        return 0

    for p in stale:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(outputs[p], encoding="utf-8", newline="\n")
        print("записан", p.relative_to(ROOT))
    if not stale:
        print("Изменений нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())
