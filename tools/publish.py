#!/usr/bin/env python3
"""Publish an Obsidian article folder to Hugo content/post/."""

from __future__ import annotations

import argparse
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

CHINA_TZ = timezone(timedelta(hours=8))


def now_china_iso() -> str:
    now = datetime.now(CHINA_TZ)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + now.strftime("%z")[:3] + ":" + now.strftime("%z")[3:]

FRONTMATTER_RE = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", re.DOTALL)
WIKI_IMAGE_RE = re.compile(r"!\[\[([^\]|]+)(?:\|([^\]]*))?\]\]")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

CATEGORIES = [
    ("csharp", "C#"),
    ("cpp", "C++"),
    ("unity", "Unity"),
    ("ue", "UE"),
    ("opengl", "OpenGL"),
    ("math", "Math"),
    ("dsa", "DSA"),
    ("tools", "Tools"),
]

SUBCATEGORIES = [
    ("basic", "基础"),
    ("advanced", "进阶"),
]


@dataclass
class PublishOptions:
    source_dir: Path
    blog_root: Path
    title: str = ""
    slug: str = ""
    category: str = ""
    subcategory: str = ""
    tags: list[str] = field(default_factory=list)
    cover: str = ""
    post_date: str = ""


@dataclass
class PublishResult:
    slug: str
    dest_dir: Path
    message: str


def blog_root_from_here() -> Path:
    return Path(__file__).resolve().parent.parent


def find_markdown_file(source_dir: Path) -> Path:
    preferred = source_dir / "index.md"
    if preferred.is_file():
        return preferred

    md_files = sorted(source_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not md_files:
        raise FileNotFoundError(f"未找到 Markdown 文件: {source_dir}")

    return md_files[0]


def parse_simple_yaml(raw: str) -> dict:
    data: dict = {}
    current_list_key: str | None = None

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- ") and current_list_key:
            data.setdefault(current_list_key, []).append(stripped[2:].strip().strip('"').strip("'"))
            continue

        if ":" not in line:
            current_list_key = None
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if not value:
            current_list_key = key
            data[key] = []
            continue

        current_list_key = None
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            data[key] = [item.strip().strip('"').strip("'") for item in inner.split(",") if item.strip()]
        else:
            data[key] = value

    return data


def parse_frontmatter(text: str) -> tuple[dict, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    meta = parse_simple_yaml(match.group(1))
    body = text[match.end() :]
    return meta, body.lstrip("\r\n")


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug


def normalize_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,，]", value) if part.strip()]
    return [str(value).strip()]


def first_value(meta: dict, *keys, default="") -> str:
    for key in keys:
        value = meta.get(key)
        if isinstance(value, list):
            if value:
                return str(value[0]).strip()
        elif value:
            return str(value).strip()
    return default


def first_list(meta: dict, *keys) -> list[str]:
    for key in keys:
        if key in meta:
            return normalize_list(meta[key])
    return []


def detect_from_source(source_dir: Path) -> dict:
    md_path = find_markdown_file(source_dir)
    meta, _ = parse_frontmatter(md_path.read_text(encoding="utf-8"))

    title = first_value(meta, "title", default=md_path.stem)
    slug = first_value(meta, "slug", default=slugify(title) or slugify(source_dir.name) or source_dir.name.lower())
    category = first_value(meta, "category", "categories")
    subcategory = first_value(meta, "subcategory", "subcategories")
    cover = first_value(meta, "cover", "image")
    post_date = first_value(meta, "date", default=now_china_iso())
    tags = first_list(meta, "tags")

    return {
        "title": title,
        "slug": slug,
        "category": category,
        "subcategory": subcategory,
        "cover": cover,
        "date": post_date,
        "tags": tags,
        "markdown_file": str(md_path),
    }


def sanitize_image_name(filename: str) -> str:
    """把空格等不安全字符换成连字符 方便 Markdown 链接"""
    name = Path(filename).name.strip().strip('"').strip("'")
    if name.startswith("<") and name.endswith(">"):
        name = name[1:-1].strip()
    stem = Path(name).stem
    suffix = Path(name).suffix
    safe_stem = re.sub(r"[\s]+", "-", stem)
    safe_stem = re.sub(r"[^\w\-.]+", "-", safe_stem, flags=re.UNICODE)
    safe_stem = re.sub(r"-{2,}", "-", safe_stem).strip("-")
    return f"{safe_stem or 'image'}{suffix}"


def normalize_image_ref(raw: str) -> str:
    name = raw.strip().strip('"').strip("'")
    if name.startswith("<") and name.endswith(">"):
        name = name[1:-1].strip()
    return Path(name).name


def collect_note_image_refs(body: str) -> list[str]:
    """只从笔记原文收集图片名 以笔记侧为准"""
    refs: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        key = normalize_image_ref(name)
        if key and key not in seen:
            seen.add(key)
            refs.append(key)

    for match in WIKI_IMAGE_RE.finditer(body):
        add(match.group(1))

    for match in MARKDOWN_IMAGE_RE.finditer(body):
        add(match.group(1))

    return refs


def resolve_source_image(source_dir: Path, note_name: str) -> Path:
    """按笔记里的文件名找图 找不到再尝试去空格名"""
    direct = source_dir / note_name
    if direct.is_file():
        return direct

    safe_name = sanitize_image_name(note_name)
    fallback = source_dir / safe_name
    if fallback.is_file():
        return fallback

    raise FileNotFoundError(f"图片不存在: {direct}")


def convert_body_images(body: str, rename_map: dict[str, str]) -> str:
    """把笔记图片语法转成带宽度的 HTML 图 保留 Obsidian |宽度"""

    def replace_wiki(match: re.Match[str]) -> str:
        filename = normalize_image_ref(match.group(1))
        pipe_value = (match.group(2) or "").strip()
        safe_name = rename_map[filename]

        alt = Path(filename).stem
        width = ""
        if pipe_value.isdigit():
            width = pipe_value
        elif pipe_value:
            alt = pipe_value

        return render_image_tag(safe_name, alt, width)

    def replace_md(match: re.Match[str]) -> str:
        alt = match.group(1)
        filename = normalize_image_ref(match.group(2))
        safe_name = rename_map.get(filename, sanitize_image_name(filename))
        return render_image_tag(safe_name, alt, "")

    converted = WIKI_IMAGE_RE.sub(replace_wiki, body)
    converted = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)").sub(replace_md, converted)
    return converted


def render_image_tag(src: str, alt: str, width: str) -> str:
    """生成图片标签 有宽度用 HTML 无宽度用 Markdown"""
    safe_alt = alt.replace('"', "&quot;")
    if width:
        return f'<img src="{src}" alt="{safe_alt}" width="{width}">'
    return f"![{alt}]({src})"


def render_hugo_frontmatter(options: PublishOptions) -> str:
    tags_block = ""
    if options.tags:
        tag_lines = "\n".join(f"    - {tag}" for tag in options.tags)
        tags_block = f"tags:\n{tag_lines}\n"

    image_line = f"image: {options.cover}\n" if options.cover else ""

    return (
        "---\n"
        f"title: {options.title}\n"
        f"date: {options.post_date or now_china_iso()}\n"
        f"slug: {options.slug}\n"
        "categories:\n"
        f"    - {options.category}\n"
        "subcategories:\n"
        f"    - {options.subcategory}\n"
        f"{tags_block}"
        f"{image_line}"
        "---\n"
    )


def validate_options(options: PublishOptions) -> None:
    if not options.source_dir.is_dir():
        raise FileNotFoundError(f"源文件夹不存在: {options.source_dir}")

    if not options.title.strip():
        raise ValueError("请填写标题")

    if not options.slug.strip():
        raise ValueError("请填写 slug")

    if not options.category:
        raise ValueError("请选择栏目")

    if not options.subcategory:
        raise ValueError("请选择子栏目")


def publish_article(options: PublishOptions) -> PublishResult:
    validate_options(options)

    md_path = find_markdown_file(options.source_dir)
    raw_text = md_path.read_text(encoding="utf-8")
    _, body = parse_frontmatter(raw_text)

    # 先按笔记原文收集图片名 再映射到博客安全名
    note_images = collect_note_image_refs(body)
    rename_map = {name: sanitize_image_name(name) for name in note_images}
    converted_body = convert_body_images(body, rename_map)

    dest_dir = options.blog_root / "content" / "post" / options.slug
    dest_dir.mkdir(parents=True, exist_ok=True)

    copied_images: list[str] = []
    for note_name, safe_name in rename_map.items():
        src_image = resolve_source_image(options.source_dir, note_name)
        dest_image = dest_dir / safe_name
        shutil.copy2(src_image, dest_image)
        copied_images.append(safe_name)

    cover_name = options.cover
    if cover_name:
        note_cover = normalize_image_ref(cover_name)
        safe_cover = sanitize_image_name(note_cover)
        if safe_cover not in copied_images:
            cover_src = resolve_source_image(options.source_dir, note_cover)
            shutil.copy2(cover_src, dest_dir / safe_cover)
            copied_images.append(safe_cover)
        options.cover = safe_cover

    output = render_hugo_frontmatter(options) + "\n" + converted_body.strip() + "\n"
    (dest_dir / "index.md").write_text(output, encoding="utf-8")

    message = (
        f"发布成功\n"
        f"目标: {dest_dir}\n"
        f"文章: index.md\n"
        f"图片: {len(copied_images)} 张"
    )
    return PublishResult(slug=options.slug, dest_dir=dest_dir, message=message)


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish Obsidian folder to Hugo blog")
    parser.add_argument("--source", required=True, help="Obsidian article folder")
    parser.add_argument("--blog-root", default=str(blog_root_from_here()), help="Blog repository root")
    parser.add_argument("--title", default="", help="Article title")
    parser.add_argument("--slug", default="", help="URL slug")
    parser.add_argument("--category", default="", help="Category slug")
    parser.add_argument("--subcategory", default="", help="Subcategory slug")
    parser.add_argument("--tags", default="", help="Comma separated tags")
    parser.add_argument("--cover", default="", help="Cover image filename")
    parser.add_argument("--date", default="", help="Publish date YYYY-MM-DD")
    return parser


def main() -> int:
    parser = build_cli_parser()
    args = parser.parse_args()

    source_dir = Path(args.source).expanduser().resolve()
    detected = detect_from_source(source_dir)

    options = PublishOptions(
        source_dir=source_dir,
        blog_root=Path(args.blog_root).resolve(),
        title=args.title or detected["title"],
        slug=args.slug or detected["slug"],
        category=args.category or detected["category"],
        subcategory=args.subcategory or detected["subcategory"],
        tags=[tag.strip() for tag in args.tags.split(",") if tag.strip()] or detected["tags"],
        cover=args.cover or detected["cover"],
        post_date=args.date or detected["date"],
    )

    result = publish_article(options)
    print(result.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
