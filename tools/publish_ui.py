#!/usr/bin/env python3
"""Small desktop UI for publishing Obsidian articles to Hugo."""

from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

from publish import (
    CATEGORIES,
    SUBCATEGORIES,
    PublishOptions,
    blog_root_from_here,
    detect_from_source,
    publish_article,
)


class PublishApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.blog_root = blog_root_from_here()

        root.title("Blog 发布工具")
        root.geometry("760x640")
        root.minsize(680, 580)

        self.source_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.slug_var = tk.StringVar()
        self.category_var = tk.StringVar(value="csharp")
        self.subcategory_var = tk.StringVar(value="advanced")
        self.tags_var = tk.StringVar()
        self.cover_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.build_var = tk.BooleanVar(value=True)
        self.push_var = tk.BooleanVar(value=True)

        self._build_layout()

    def _build_layout(self) -> None:
        padding = {"padx": 12, "pady": 6}

        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Obsidian 文章文件夹").grid(row=0, column=0, sticky="w", **padding)
        source_row = ttk.Frame(frame)
        source_row.grid(row=0, column=1, sticky="ew", **padding)
        ttk.Entry(source_row, textvariable=self.source_var).pack(side="left", fill="x", expand=True)
        ttk.Button(source_row, text="浏览...", command=self.browse_source).pack(side="left", padx=(8, 0))

        fields = [
            ("标题", self.title_var),
            ("Slug", self.slug_var),
            ("标签（逗号分隔）", self.tags_var),
            ("封面图文件名", self.cover_var),
            ("日期 YYYY-MM-DD", self.date_var),
        ]

        row = 1
        for label, var in fields:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", **padding)
            ttk.Entry(frame, textvariable=var).grid(row=row, column=1, sticky="ew", **padding)
            row += 1

        ttk.Label(frame, text="栏目").grid(row=row, column=0, sticky="w", **padding)
        category_box = ttk.Combobox(
            frame,
            textvariable=self.category_var,
            values=[label for _, label in CATEGORIES],
            state="readonly",
        )
        category_box.grid(row=row, column=1, sticky="ew", **padding)
        row += 1

        ttk.Label(frame, text="子栏目").grid(row=row, column=0, sticky="w", **padding)
        subcategory_box = ttk.Combobox(
            frame,
            textvariable=self.subcategory_var,
            values=[label for _, label in SUBCATEGORIES],
            state="readonly",
        )
        subcategory_box.grid(row=row, column=1, sticky="ew", **padding)
        row += 1

        ttk.Checkbutton(frame, text="发布后执行 hugo 构建", variable=self.build_var).grid(
            row=row, column=1, sticky="w", **padding
        )
        row += 1

        ttk.Checkbutton(frame, text="发布后推送到 GitHub", variable=self.push_var).grid(
            row=row, column=1, sticky="w", **padding
        )
        row += 1

        button_row = ttk.Frame(frame)
        button_row.grid(row=row, column=1, sticky="w", **padding)
        ttk.Button(button_row, text="读取文件夹", command=self.load_folder).pack(side="left")
        ttk.Button(button_row, text="发布", command=self.publish).pack(side="left", padx=(8, 0))
        row += 1

        ttk.Label(frame, text="日志").grid(row=row, column=0, sticky="nw", **padding)
        self.log_text = tk.Text(frame, height=16, wrap="word")
        self.log_text.grid(row=row, column=1, sticky="nsew", **padding)
        row += 1

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(row - 1, weight=1)

        self.log(f"博客目录: {self.blog_root}")

    def log(self, message: str) -> None:
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")

    def browse_source(self) -> None:
        selected = filedialog.askdirectory(title="选择 Obsidian 文章文件夹")
        if selected:
            self.source_var.set(selected)
            self.load_folder()

    def category_slug(self) -> str:
        label = self.category_var.get()
        for slug, name in CATEGORIES:
            if name == label:
                return slug
        return label

    def subcategory_slug(self) -> str:
        label = self.subcategory_var.get()
        for slug, name in SUBCATEGORIES:
            if name == label:
                return slug
        return label

    def set_category_label(self, slug: str) -> None:
        for item_slug, label in CATEGORIES:
            if item_slug == slug:
                self.category_var.set(label)
                return
        self.category_var.set(slug)

    def set_subcategory_label(self, slug: str) -> None:
        for item_slug, label in SUBCATEGORIES:
            if item_slug == slug:
                self.subcategory_var.set(label)
                return
        self.subcategory_var.set(slug)

    def load_folder(self) -> None:
        source = self.source_var.get().strip()
        if not source:
            messagebox.showwarning("提示", "请先选择 Obsidian 文件夹")
            return

        try:
            detected = detect_from_source(Path(source))
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc))
            return

        self.title_var.set(detected["title"])
        self.slug_var.set(detected["slug"])
        self.tags_var.set(", ".join(detected["tags"]))
        self.cover_var.set(detected["cover"])
        self.date_var.set(detected["date"])
        if detected["category"]:
            self.set_category_label(detected["category"])
        if detected["subcategory"]:
            self.set_subcategory_label(detected["subcategory"])

        self.log(f"已读取: {detected['markdown_file']}")

    def publish(self) -> None:
        source = self.source_var.get().strip()
        if not source:
            messagebox.showwarning("提示", "请先选择 Obsidian 文件夹")
            return

        options = PublishOptions(
            source_dir=Path(source).expanduser().resolve(),
            blog_root=self.blog_root,
            title=self.title_var.get().strip(),
            slug=self.slug_var.get().strip(),
            category=self.category_slug(),
            subcategory=self.subcategory_slug(),
            tags=[tag.strip() for tag in self.tags_var.get().split(",") if tag.strip()],
            cover=self.cover_var.get().strip(),
            post_date=self.date_var.get().strip(),
        )

        try:
            result = publish_article(options)
        except Exception as exc:
            messagebox.showerror("发布失败", str(exc))
            self.log(f"发布失败: {exc}")
            return

        self.log(result.message)

        if self.build_var.get():
            self.run_hugo()

        push_ok = True
        if self.push_var.get():
            push_ok = self.push_to_github(options.title)

        if push_ok:
            messagebox.showinfo("完成", f"文章已发布到:\n{result.dest_dir}")
        else:
            messagebox.showwarning(
                "本地已发布",
                f"文章已写入:\n{result.dest_dir}\n\n但 GitHub 推送失败 请看日志",
            )

    def run_git(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=str(self.blog_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def push_to_github(self, title: str) -> bool:
        self.log("开始提交并推送到 GitHub...")

        # 清掉已跟踪的 pycache 避免误提交
        self.run_git(["git", "rm", "-r", "--cached", "--ignore-unmatch", "tools/__pycache__"])

        status = self.run_git(["git", "status", "--porcelain"])
        if status.returncode != 0:
            self.log(f"git status 失败: {status.stderr.strip()}")
            return False

        if not status.stdout.strip():
            self.log("没有需要提交的变更 跳过推送")
            return True

        add = self.run_git(["git", "add", "-A"])
        if add.returncode != 0:
            self.log(f"git add 失败: {add.stderr.strip()}")
            return False

        message = f"发布: {title}" if title.strip() else "发布文章"
        commit = self.run_git(["git", "commit", "-m", message])
        if commit.returncode != 0:
            combined = (commit.stdout + commit.stderr).strip()
            if "nothing to commit" in combined.lower():
                self.log("没有需要提交的变更 跳过推送")
                return True
            self.log(f"git commit 失败: {combined}")
            return False

        self.log(f"已提交: {message}")

        push = self.run_git(["git", "push", "origin", "HEAD"])
        if push.returncode != 0:
            self.log(f"git push 失败: {(push.stdout + push.stderr).strip()}")
            return False

        self.log("GitHub 推送成功")
        return True

    def run_hugo(self) -> None:
        try:
            completed = subprocess.run(
                ["hugo", "-s", str(self.blog_root), "--minify"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        except FileNotFoundError:
            self.log("未找到 hugo，已跳过构建")
            return

        if completed.stdout:
            self.log(completed.stdout.strip())
        if completed.stderr:
            self.log(completed.stderr.strip())

        if completed.returncode == 0:
            self.log("Hugo 构建成功")
        else:
            self.log(f"Hugo 构建失败，退出码 {completed.returncode}")


def main() -> None:
    root = tk.Tk()
    style = ttk.Style()
    if "vista" in style.theme_names():
        style.theme_use("vista")
    PublishApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
