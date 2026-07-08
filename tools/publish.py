#!/usr/bin/env python3
"""Publish an Obsidian article folder to Hugo content/post/."""

from __future__ import annotations

import argparse
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

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
    post_date = first_value(meta, "date", default=date.today().isoformat())
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


def convert_obsidian_images(body: str) -> tuple[str, set[str]]:
    referenced: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        filename = match.group(1).strip()
        pipe_value = (match.group(2) or "").strip()
        referenced.add(filename)

        alt = Path(filename).stem
        if pipe_value and not pipe_value.isdigit():
            alt = pipe_value

        return f"![{alt}]({filename})"

    converted = WIKI_IMAGE_RE.sub(replace, body)
    return converted, referenced


def collect_markdown_images(body: str) -> set[str]:
    return {match.group(1).strip() for match in MARKDOWN_IMAGE_RE.finditer(body)}


def render_hugo_frontmatter(options: PublishOptions) -> str:
    tags_block = ""
    if options.tags:
        tag_lines = "\n".join(f"    - {tag}" for tag in options.tags)
        tags_block = f"tags:\n{tag_lines}\n"

    image_line = f"image: {options.cover}\n" if options.cover else ""

    return (
        "---\n"
        f"title: {options.title}\n"
        f"date: {options.post_date or date.today().isoformat()}\n"
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

    converted_body, wiki_images = convert_obsidian_images(body)
    markdown_images = collect_markdown_images(converted_body)
    image_names = sorted(wiki_images | markdown_images)

    dest_dir = options.blog_root / "content" / "post" / options.slug
    dest_dir.mkdir(parents=True, exist_ok=True)

    copied_images: list[str] = []
    for image_name in image_names:
        src_image = options.source_dir / image_name
        if not src_image.is_file():
            raise FileNotFoundError(f"图片不存在: {src_image}")

        dest_image = dest_dir / image_name
        shutil.copy2(src_image, dest_image)
        copied_images.append(image_name)

    if options.cover and options.cover not in copied_images:
        cover_src = options.source_dir / options.cover
        if cover_src.is_file():
            shutil.copy2(cover_src, dest_dir / options.cover)
            copied_images.append(options.cover)

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
