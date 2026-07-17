#!/usr/bin/env python3
"""Publish an Obsidian article folder to Hugo content/post/."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

CHINA_TZ = timezone(timedelta(hours=8))


def now_china_iso() -> str:
    now = datetime.now(CHINA_TZ)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + now.strftime("%z")[:3] + ":" + now.strftime("%z")[3:]

FRONTMATTER_RE = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", re.DOTALL)
WIKI_IMAGE_RE = re.compile(r"!\[\[([^\]|]+)(?:\|([^\]]*))?\]\]")
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"([^\"]*)\")?\)")

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

# Obsidian 库顶层文件夹名 -> 栏目 slug
FOLDER_TO_CATEGORY = {
    "Cpp": "cpp",
    "C++": "cpp",
    "CSharp": "csharp",
    "C#": "csharp",
    "CS": "csharp",
    "Unity": "unity",
    "UE": "ue",
    "Unreal": "ue",
    "OpenGL": "opengl",
    "Math": "math",
    "DSA": "dsa",
    "Tools": "tools",
}

FOLDER_TO_SUBCATEGORY = {
    "基础": "basic",
    "basic": "basic",
    "Basic": "basic",
    "进阶": "advanced",
    "advanced": "advanced",
    "Advanced": "advanced",
}

IMAGE_DIR_NAMES = {"图片", "attachments", "assets", "imgs", "images", "media"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


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


@dataclass
class PostInfo:
    title: str
    slug: str
    category: str
    subcategory: str
    date: str
    path: Path


@dataclass
class NoteScanItem:
    source_dir: Path
    title: str
    slug: str
    category: str
    subcategory: str
    fingerprint: str
    status: str  # new / changed / unchanged / skipped
    rel_path: str


def category_label(slug: str) -> str:
    for item_slug, label in CATEGORIES:
        if item_slug == slug:
            return label
    return slug or "(未设置)"


def subcategory_label(slug: str) -> str:
    for item_slug, label in SUBCATEGORIES:
        if item_slug == slug:
            return label
    return slug or "(未设置)"


def posts_root(blog_root: Path) -> Path:
    return blog_root / "content" / "post"


def list_posts(blog_root: Path) -> list[PostInfo]:
    """扫描 content/post 下全部文章"""
    root = posts_root(blog_root)
    if not root.is_dir():
        return []

    posts: list[PostInfo] = []
    for index_path in sorted(root.glob("*/index.md")):
        meta, _ = parse_frontmatter(index_path.read_text(encoding="utf-8"))
        folder_slug = index_path.parent.name
        posts.append(
            PostInfo(
                title=first_value(meta, "title", default=folder_slug),
                slug=first_value(meta, "slug", default=folder_slug),
                category=first_value(meta, "category", "categories"),
                subcategory=first_value(meta, "subcategory", "subcategories"),
                date=first_value(meta, "date"),
                path=index_path,
            )
        )

    posts.sort(key=lambda item: item.date or "", reverse=True)
    return posts


def publish_state_path(blog_root: Path) -> Path:
    return blog_root / "tools" / ".publish-state.json"


def load_publish_state(blog_root: Path) -> dict[str, Any]:
    path = publish_state_path(blog_root)
    if not path.is_file():
        return {"notes": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"notes": {}}
    if not isinstance(data, dict):
        return {"notes": {}}
    data.setdefault("notes", {})
    return data


def save_publish_state(blog_root: Path, state: dict[str, Any]) -> None:
    path = publish_state_path(blog_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def note_state_key(source_dir: Path) -> str:
    return str(source_dir.resolve())


def find_vault_root(note_dir: Path) -> Path | None:
    """从笔记目录向上找 Obsidian 库根(含子栏目顶层文件夹)"""
    known = set(FOLDER_TO_CATEGORY.keys())
    current = note_dir.resolve()
    for parent in [current, *current.parents]:
        try:
            children = {child.name for child in parent.iterdir() if child.is_dir()}
        except OSError:
            continue
        if children & known:
            return parent
    return None


def infer_taxonomy(note_dir: Path, vault_root: Path | None = None) -> tuple[str, str]:
    """根据 Obsidian 路径推断栏目/子栏目"""
    vault = vault_root or find_vault_root(note_dir)
    if vault is None:
        return "", "basic"

    try:
        parts = note_dir.resolve().relative_to(vault.resolve()).parts
    except ValueError:
        return "", "basic"

    if not parts:
        return "", "basic"

    category = FOLDER_TO_CATEGORY.get(parts[0], "")
    subcategory = "basic"

    if len(parts) >= 2 and parts[1] in FOLDER_TO_SUBCATEGORY:
        subcategory = FOLDER_TO_SUBCATEGORY[parts[1]]

    return category, subcategory


def discover_note_dirs(vault_root: Path) -> list[Path]:
    """扫描库中所有含 md 的笔记文件夹"""
    vault_root = vault_root.resolve()
    if not vault_root.is_dir():
        raise FileNotFoundError(f"Obsidian 库不存在: {vault_root}")

    found: set[Path] = set()
    for md_path in vault_root.rglob("*.md"):
        parent = md_path.parent
        if parent.name in IMAGE_DIR_NAMES:
            continue
        if any(part in IMAGE_DIR_NAMES for part in parent.parts):
            # 图片目录里的 md 忽略
            if parent.name in IMAGE_DIR_NAMES:
                continue
        # 只收「目录内直接有 md」的笔记夹
        found.add(parent)

    # 排除库根本身 以及纯栏目/子栏目容器(没有直接 md 的已自然排除)
    notes = []
    for path in sorted(found):
        if path == vault_root:
            continue
        if not list(path.glob("*.md")):
            continue
        notes.append(path)
    return notes


def note_fingerprint(source_dir: Path) -> str:
    """笔记正文 + 图片元信息指纹 用于判断是否变更"""
    md_path = find_markdown_file(source_dir)
    digest = hashlib.md5()
    digest.update(md_path.read_bytes())

    image_files = [
        path
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ]
    for path in sorted(image_files, key=lambda item: str(item.relative_to(source_dir)).lower()):
        stat = path.stat()
        digest.update(str(path.relative_to(source_dir)).encode("utf-8", errors="replace"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))

    return digest.hexdigest()


def resolve_note_publish_meta(
    source_dir: Path,
    blog_root: Path,
    vault_root: Path | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, str]:
    """综合路径推断、已发布文章、同步状态 得到发布元数据"""
    detected = detect_from_source(source_dir, blog_root)
    path_category, path_subcategory = infer_taxonomy(source_dir, vault_root)

    key = note_state_key(source_dir)
    saved = ((state or {}).get("notes") or {}).get(key) or {}

    existing = None
    needle = normalize_title(detected["title"])
    for post in list_posts(blog_root):
        if normalize_title(post.title) == needle or post.slug == detected["slug"]:
            existing = post
            break
        if saved.get("slug") and post.slug == saved.get("slug"):
            existing = post
            break

    category = (
        detected["category"]
        or (existing.category if existing else "")
        or saved.get("category", "")
        or path_category
    )
    subcategory = (
        detected["subcategory"]
        or (existing.subcategory if existing else "")
        or saved.get("subcategory", "")
        or path_subcategory
        or "basic"
    )
    slug = detected["slug"] or saved.get("slug", "") or (existing.slug if existing else "")
    if not slug:
        slug = slugify(source_dir.name) or slugify(detected["title"]) or "post"
    if slug.startswith("post-") and category:
        slug = f"{category}-{slug[5:]}"

    # 更新已有文章时保留原日期
    post_date = detected["date"]
    if existing and existing.date:
        post_date = existing.date

    return {
        "title": detected["title"],
        "slug": slug,
        "category": category,
        "subcategory": subcategory,
        "cover": detected["cover"],
        "date": post_date,
        "tags": ",".join(detected["tags"]),
        "markdown_file": detected["markdown_file"],
    }


def scan_vault_notes(
    vault_root: Path,
    blog_root: Path,
    only_changed: bool = False,
) -> list[NoteScanItem]:
    """扫描库内笔记并标记 new/changed/unchanged"""
    state = load_publish_state(blog_root)
    items: list[NoteScanItem] = []

    for source_dir in discover_note_dirs(vault_root):
        try:
            meta = resolve_note_publish_meta(source_dir, blog_root, vault_root, state)
            fingerprint = note_fingerprint(source_dir)
        except Exception:
            rel = str(source_dir)
            try:
                rel = str(source_dir.relative_to(vault_root))
            except ValueError:
                pass
            items.append(
                NoteScanItem(
                    source_dir=source_dir,
                    title=source_dir.name,
                    slug="",
                    category="",
                    subcategory="",
                    fingerprint="",
                    status="skipped",
                    rel_path=rel,
                )
            )
            continue

        key = note_state_key(source_dir)
        saved = (state.get("notes") or {}).get(key) or {}
        published = posts_root(blog_root) / meta["slug"] / "index.md"

        if not published.is_file() and not saved:
            status = "new"
        elif saved.get("fingerprint") == fingerprint and published.is_file():
            status = "unchanged"
        else:
            status = "changed"

        try:
            rel_path = str(source_dir.relative_to(vault_root))
        except ValueError:
            rel_path = str(source_dir)

        items.append(
            NoteScanItem(
                source_dir=source_dir,
                title=meta["title"],
                slug=meta["slug"],
                category=meta["category"],
                subcategory=meta["subcategory"],
                fingerprint=fingerprint,
                status=status,
                rel_path=rel_path,
            )
        )

    if only_changed:
        items = [item for item in items if item.status in {"new", "changed"}]

    status_rank = {"changed": 0, "new": 1, "skipped": 2, "unchanged": 3}
    items.sort(key=lambda item: (status_rank.get(item.status, 9), item.rel_path.lower()))
    return items


def sync_note(
    item: NoteScanItem,
    blog_root: Path,
    vault_root: Path | None = None,
) -> PublishResult:
    """同步单篇笔记到博客 并写入指纹状态"""
    state = load_publish_state(blog_root)
    meta = resolve_note_publish_meta(item.source_dir, blog_root, vault_root, state)
    tags = [part.strip() for part in meta["tags"].split(",") if part.strip()]

    options = PublishOptions(
        source_dir=item.source_dir,
        blog_root=blog_root,
        title=meta["title"],
        slug=meta["slug"],
        category=meta["category"],
        subcategory=meta["subcategory"],
        tags=tags,
        cover=meta["cover"],
        post_date=meta["date"],
    )
    result = publish_article(options)

    fingerprint = note_fingerprint(item.source_dir)
    notes = state.setdefault("notes", {})
    notes[note_state_key(item.source_dir)] = {
        "slug": result.slug,
        "title": meta["title"],
        "category": meta["category"],
        "subcategory": meta["subcategory"],
        "fingerprint": fingerprint,
        "rel_path": item.rel_path,
        "synced_at": now_china_iso(),
    }
    save_publish_state(blog_root, state)
    return result


def sync_changed_notes(
    vault_root: Path,
    blog_root: Path,
    only_changed: bool = True,
) -> tuple[list[PublishResult], list[str]]:
    """批量同步 默认只处理新增和变更"""
    items = scan_vault_notes(vault_root, blog_root, only_changed=only_changed)
    results: list[PublishResult] = []
    errors: list[str] = []

    for item in items:
        if item.status == "skipped":
            errors.append(f"{item.rel_path}: 跳过(无法读取)")
            continue
        if only_changed and item.status == "unchanged":
            continue
        try:
            results.append(sync_note(item, blog_root, vault_root))
        except Exception as exc:
            errors.append(f"{item.rel_path}: {exc}")

    return results, errors


def delete_post(blog_root: Path, slug: str) -> Path:
    """删除整篇文章目录"""
    dest_dir = posts_root(blog_root) / slug
    if not dest_dir.is_dir():
        raise FileNotFoundError(f"文章不存在: {dest_dir}")
    shutil.rmtree(dest_dir)
    return dest_dir


def update_post_category(blog_root: Path, slug: str, category: str, subcategory: str) -> Path:
    """只改 frontmatter 里的栏目和子栏目"""
    if not category:
        raise ValueError("请选择栏目")
    if not subcategory:
        raise ValueError("请选择子栏目")

    index_path = posts_root(blog_root) / slug / "index.md"
    if not index_path.is_file():
        raise FileNotFoundError(f"文章不存在: {index_path}")

    raw_text = index_path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw_text)
    if not meta:
        raise ValueError(f"无法解析 frontmatter: {index_path}")

    title = first_value(meta, "title", default=slug)
    post_date = first_value(meta, "date", default=now_china_iso())
    tags = first_list(meta, "tags")
    cover = first_value(meta, "cover", "image")

    options = PublishOptions(
        source_dir=index_path.parent,
        blog_root=blog_root,
        title=title,
        slug=first_value(meta, "slug", default=slug),
        category=category,
        subcategory=subcategory,
        tags=tags,
        cover=cover,
        post_date=post_date,
    )
    output = render_hugo_frontmatter(options) + "\n" + body.strip() + "\n"
    index_path.write_text(output, encoding="utf-8")
    return index_path


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


# 常见中文词转写 方便生成稳定英文 slug
CN_SLUG_WORDS = {
    "基础": "basic",
    "指针": "pointer",
    "进阶": "advanced",
    "入门": "intro",
    "原理": "principle",
    "笔记": "notes",
}


def slugify(value: str) -> str:
    """生成纯 ASCII slug 避免中文路径在 GitHub Pages 上 404"""
    text = unicodedata.normalize("NFKC", (value or "").strip())
    if not text:
        return ""

    for cn, en in CN_SLUG_WORDS.items():
        text = text.replace(cn, f"-{en}-")

    ascii_part = (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    )
    ascii_slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_part).strip("-").lower()
    ascii_slug = re.sub(r"-{2,}", "-", ascii_slug)

    # 若仍有未映射中文 追加短哈希保证唯一且可上线
    original = unicodedata.normalize("NFKC", (value or "").strip())
    remain_non_ascii = any(ord(ch) > 127 for ch in original)
    mapped = original
    for cn, _en in CN_SLUG_WORDS.items():
        mapped = mapped.replace(cn, "")
    still_non_ascii = any(ord(ch) > 127 for ch in mapped)

    if still_non_ascii:
        digest = hashlib.md5(original.encode("utf-8")).hexdigest()[:6]
        base = ascii_slug or "post"
        return f"{base}-{digest}"

    if remain_non_ascii and not ascii_slug:
        digest = hashlib.md5(original.encode("utf-8")).hexdigest()[:6]
        return f"post-{digest}"

    return ascii_slug


def ensure_unique_slug(blog_root: Path, slug: str, title: str) -> None:
    """若同 slug 已有不同标题的文章 则拒绝覆盖"""
    index_path = posts_root(blog_root) / slug / "index.md"
    if not index_path.is_file():
        return

    meta, _ = parse_frontmatter(index_path.read_text(encoding="utf-8"))
    existing_title = first_value(meta, "title")
    if existing_title and existing_title != title:
        raise ValueError(
            f"slug「{slug}」已被文章「{existing_title}」占用\n"
            f"当前要发布的是「{title}」\n"
            f"请换一个 slug 再发布 避免互相覆盖"
        )


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


def normalize_title(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip()).lower()


def find_slug_by_title(blog_root: Path, title: str) -> str:
    """已有同名文章时复用其 slug 避免重复发布出第二份"""
    needle = normalize_title(title)
    if not needle:
        return ""
    for post in list_posts(blog_root):
        if normalize_title(post.title) == needle:
            return post.slug
    return ""


def detect_from_source(source_dir: Path, blog_root: Path | None = None) -> dict:
    md_path = find_markdown_file(source_dir)
    meta, _ = parse_frontmatter(md_path.read_text(encoding="utf-8"))

    title = first_value(meta, "title", default=md_path.stem)
    slug = first_value(meta, "slug")
    if not slug and blog_root is not None:
        slug = find_slug_by_title(blog_root, title)
    if not slug:
        slug = (
            slugify(source_dir.name)
            or slugify(title)
            or slugify(md_path.stem)
            or "post"
        )
    category = first_value(meta, "category", "categories")
    subcategory = first_value(meta, "subcategory", "subcategories")
    path_category, path_subcategory = infer_taxonomy(source_dir)
    if not category:
        category = path_category
    if not subcategory:
        subcategory = path_subcategory
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
        add(match.group(2))

    return refs


def resolve_source_image(source_dir: Path, note_name: str) -> Path:
    """按笔记文件名找图 支持图片在子文件夹(如 图片/1.1/)"""
    raw_name = note_name.strip().replace("\\", "/")
    basename = Path(raw_name).name
    safe_name = sanitize_image_name(basename)

    direct_candidates = [
        source_dir / raw_name,
        source_dir / basename,
        source_dir / safe_name,
    ]
    for candidate in direct_candidates:
        if candidate.is_file():
            return candidate

    matches: list[Path] = []
    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.name == basename or path.name == safe_name:
            matches.append(path)

    if not matches:
        raise FileNotFoundError(
            f"图片不存在: {basename}\n已在整个笔记文件夹递归查找: {source_dir}"
        )

    if len(matches) == 1:
        return matches[0]

    preferred_dirs = {"图片", "attachments", "assets", "imgs", "images", "media"}
    preferred = [path for path in matches if preferred_dirs.intersection(path.parts)]
    pool = preferred or matches
    # 路径更短优先 其次较新文件
    pool.sort(key=lambda path: (len(path.parts), -path.stat().st_mtime))
    return pool[0]


def convert_body_images(body: str, rename_map: dict[str, str]) -> str:
    """转成 Markdown 图 空 alt 无图注 title 放 Obsidian 宽度可点开放大"""

    def replace_wiki(match: re.Match[str]) -> str:
        filename = normalize_image_ref(match.group(1))
        pipe_value = (match.group(2) or "").strip()
        safe_name = rename_map[filename]

        alt = ""
        width = ""
        if pipe_value.isdigit():
            width = pipe_value
        elif pipe_value:
            alt = pipe_value

        return render_image_tag(safe_name, alt, width)

    def replace_md(match: re.Match[str]) -> str:
        alt = match.group(1)
        filename = normalize_image_ref(match.group(2))
        title = (match.group(3) or "").strip()
        safe_name = rename_map.get(filename, sanitize_image_name(filename))

        width = ""
        # 已是宽度 title 则保留 文件名当 alt 的旧写法清掉图注
        if title.isdigit():
            width = title
            alt = ""
        elif alt.startswith("Pasted image") or alt.startswith("Pasted-image"):
            alt = ""

        return render_image_tag(safe_name, alt, width)

    converted = WIKI_IMAGE_RE.sub(replace_wiki, body)
    converted = MARKDOWN_IMAGE_RE.sub(replace_md, converted)
    converted = ensure_blank_line_around_images(converted)
    return converted


def render_image_tag(src: str, alt: str = "", width: str = "") -> str:
    """Markdown 图片 空 alt 无图注 数字 title 给渲染钩子当显示宽度"""
    safe_alt = alt.replace("[", "\\[").replace("]", "\\]")
    if width:
        return f'![{safe_alt}]({src} "{width}")'
    return f"![{safe_alt}]({src})"


def ensure_blank_line_around_images(body: str) -> str:
    """图片前后补空行 避免标题被吞 也避免和文字粘在一起"""
    body = re.sub(
        r"([^\n])\n(!\[[^\]]*\]\([^)]+\))",
        r"\1\n\n\2",
        body,
    )
    body = re.sub(
        r"(!\[[^\]]*\]\([^)]+\))\n(?!\n)([^\n])",
        r"\1\n\n\2",
        body,
    )
    body = re.sub(
        r"(<img\b[^>]*>)\s*\n(?!\n)",
        r"\1\n\n",
        body,
        flags=re.IGNORECASE,
    )
    return body


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
    ensure_unique_slug(options.blog_root, options.slug, options.title)

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
    detected = detect_from_source(source_dir, Path(args.blog_root).resolve())

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
