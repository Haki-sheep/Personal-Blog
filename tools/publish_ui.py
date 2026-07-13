#!/usr/bin/env python3
"""Small desktop UI for publishing Obsidian articles to Hugo."""

from __future__ import annotations

import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

from publish import (
    CATEGORIES,
    SUBCATEGORIES,
    PublishOptions,
    blog_root_from_here,
    category_label,
    delete_post,
    detect_from_source,
    list_posts,
    publish_article,
    subcategory_label,
    update_post_category,
)


class PublishApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.blog_root = blog_root_from_here()
        self.post_rows: list[dict] = []

        root.title("Blog 发布工具")
        root.geometry("860x700")
        root.minsize(760, 620)

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
        self.refresh_posts()

    def _build_layout(self) -> None:
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        publish_tab = ttk.Frame(notebook, padding=12)
        manage_tab = ttk.Frame(notebook, padding=12)
        notebook.add(publish_tab, text="发布文章")
        notebook.add(manage_tab, text="文章导览")

        self._build_publish_tab(publish_tab)
        self._build_manage_tab(manage_tab)

        self.log(f"博客目录: {self.blog_root}")

    def _build_publish_tab(self, frame: ttk.Frame) -> None:
        padding = {"padx": 12, "pady": 6}

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
        ttk.Combobox(
            frame,
            textvariable=self.category_var,
            values=[label for _, label in CATEGORIES],
            state="readonly",
        ).grid(row=row, column=1, sticky="ew", **padding)
        row += 1

        ttk.Label(frame, text="子栏目").grid(row=row, column=0, sticky="w", **padding)
        ttk.Combobox(
            frame,
            textvariable=self.subcategory_var,
            values=[label for _, label in SUBCATEGORIES],
            state="readonly",
        ).grid(row=row, column=1, sticky="ew", **padding)
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
        self.log_text = tk.Text(frame, height=14, wrap="word")
        self.log_text.grid(row=row, column=1, sticky="nsew", **padding)

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(row, weight=1)

    def _build_manage_tab(self, frame: ttk.Frame) -> None:
        tip = ttk.Label(frame, text="查看全部已发布文章及其栏目 可删除或修改栏目")
        tip.pack(anchor="w", pady=(0, 8))

        tree_row = ttk.Frame(frame)
        tree_row.pack(fill="both", expand=True)

        columns = ("title", "category", "subcategory", "slug", "date")
        tree = ttk.Treeview(tree_row, columns=columns, show="headings", height=18)
        tree.heading("title", text="标题")
        tree.heading("category", text="栏目")
        tree.heading("subcategory", text="子栏目")
        tree.heading("slug", text="Slug")
        tree.heading("date", text="日期")

        tree.column("title", width=220, anchor="w")
        tree.column("category", width=90, anchor="center")
        tree.column("subcategory", width=80, anchor="center")
        tree.column("slug", width=160, anchor="w")
        tree.column("date", width=160, anchor="w")

        scroll = ttk.Scrollbar(tree_row, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.posts_tree = tree

        status_row = ttk.Frame(frame)
        status_row.pack(fill="x", pady=(8, 0))
        self.posts_status_var = tk.StringVar(value="尚未加载")
        ttk.Label(status_row, textvariable=self.posts_status_var).pack(side="left")

        button_row = ttk.Frame(frame)
        button_row.pack(fill="x", pady=(10, 0))
        ttk.Button(button_row, text="刷新列表", command=self.refresh_posts).pack(side="left")
        ttk.Button(button_row, text="修改栏目", command=self.change_selected_category).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(button_row, text="删除文章", command=self.delete_selected_post).pack(
            side="left", padx=(8, 0)
        )

    def log(self, message: str) -> None:
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")

    def browse_source(self) -> None:
        selected = filedialog.askdirectory(title="选择 Obsidian 文章文件夹")
        if selected:
            self.source_var.set(selected)
            self.load_folder()

    def category_slug(self, label: str | None = None) -> str:
        value = label if label is not None else self.category_var.get()
        for slug, name in CATEGORIES:
            if name == value:
                return slug
        return value

    def subcategory_slug(self, label: str | None = None) -> str:
        value = label if label is not None else self.subcategory_var.get()
        for slug, name in SUBCATEGORIES:
            if name == value:
                return slug
        return value

    def set_category_label(self, slug: str) -> None:
        self.category_var.set(category_label(slug) if slug else "csharp")

    def set_subcategory_label(self, slug: str) -> None:
        self.subcategory_var.set(subcategory_label(slug) if slug else "advanced")

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
        self.refresh_posts()

        if self.build_var.get():
            self.run_hugo()

        push_ok = True
        if self.push_var.get():
            push_ok = self.push_to_github(f"发布: {options.title}")

        if push_ok:
            messagebox.showinfo("完成", f"文章已发布到:\n{result.dest_dir}")
        else:
            messagebox.showwarning(
                "本地已发布",
                f"文章已写入:\n{result.dest_dir}\n\n但 GitHub 推送失败 请看日志",
            )

    def refresh_posts(self) -> None:
        if not hasattr(self, "posts_tree"):
            return

        for item in self.posts_tree.get_children():
            self.posts_tree.delete(item)

        self.post_rows = []
        try:
            posts = list_posts(self.blog_root)
        except Exception as exc:
            self.posts_status_var.set(f"加载失败: {exc}")
            messagebox.showerror("加载失败", str(exc))
            return

        for post in posts:
            row_id = self.posts_tree.insert(
                "",
                "end",
                values=(
                    post.title,
                    category_label(post.category),
                    subcategory_label(post.subcategory),
                    post.slug,
                    post.date,
                ),
            )
            self.post_rows.append(
                {
                    "id": row_id,
                    "slug": post.slug,
                    "title": post.title,
                    "category": post.category,
                    "subcategory": post.subcategory,
                }
            )

        self.posts_status_var.set(f"共 {len(posts)} 篇文章  目录: {self.blog_root / 'content' / 'post'}")

    def selected_post(self) -> dict | None:
        selected = self.posts_tree.selection()
        if not selected:
            messagebox.showwarning("提示", "请先选中一篇文章")
            return None

        item_id = selected[0]
        for row in self.post_rows:
            if row["id"] == item_id:
                return row
        return None

    def delete_selected_post(self) -> None:
        row = self.selected_post()
        if not row:
            return

        confirmed = messagebox.askyesno(
            "确认删除",
            f"确定删除文章？\n\n标题: {row['title']}\nSlug: {row['slug']}\n栏目: {category_label(row['category'])}",
        )
        if not confirmed:
            return

        try:
            dest = delete_post(self.blog_root, row["slug"])
        except Exception as exc:
            messagebox.showerror("删除失败", str(exc))
            self.log(f"删除失败: {exc}")
            return

        self.log(f"已删除文章目录: {dest}")
        self.refresh_posts()

        if self.build_var.get():
            self.run_hugo()

        if self.push_var.get():
            self.push_to_github(f"删除文章: {row['title']}")

        messagebox.showinfo("完成", f"已删除:\n{row['title']}")

    def change_selected_category(self) -> None:
        row = self.selected_post()
        if not row:
            return

        category_names = [label for _, label in CATEGORIES]
        subcategory_names = [label for _, label in SUBCATEGORIES]

        dialog = CategoryDialog(
            self.root,
            title=row["title"],
            category_label=category_label(row["category"]),
            subcategory_label=subcategory_label(row["subcategory"]),
            category_names=category_names,
            subcategory_names=subcategory_names,
        )
        if not dialog.result:
            return

        new_category, new_subcategory = dialog.result
        try:
            path = update_post_category(
                self.blog_root,
                row["slug"],
                self.category_slug(new_category),
                self.subcategory_slug(new_subcategory),
            )
        except Exception as exc:
            messagebox.showerror("修改失败", str(exc))
            self.log(f"修改栏目失败: {exc}")
            return

        self.log(f"已修改栏目: {row['title']} -> {new_category}/{new_subcategory}")
        self.log(f"文件: {path}")
        self.refresh_posts()

        if self.build_var.get():
            self.run_hugo()

        if self.push_var.get():
            self.push_to_github(f"调整栏目: {row['title']} -> {new_category}")

        messagebox.showinfo("完成", f"栏目已改为:\n{new_category} / {new_subcategory}")

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

    def push_to_github(self, message: str) -> bool:
        self.log("开始提交并推送到 GitHub...")

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

        commit_message = message.strip() or "更新博客"
        commit = self.run_git(["git", "commit", "-m", commit_message])
        if commit.returncode != 0:
            combined = (commit.stdout + commit.stderr).strip()
            if "nothing to commit" in combined.lower():
                self.log("没有需要提交的变更 跳过推送")
                return True
            self.log(f"git commit 失败: {combined}")
            return False

        self.log(f"已提交: {commit_message}")

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


class CategoryDialog(simpledialog.Dialog):
    def __init__(
        self,
        parent,
        title: str,
        category_label: str,
        subcategory_label: str,
        category_names: list[str],
        subcategory_names: list[str],
    ) -> None:
        self.article_title = title
        self.initial_category = category_label
        self.initial_subcategory = subcategory_label
        self.category_names = category_names
        self.subcategory_names = subcategory_names
        self.result: tuple[str, str] | None = None
        super().__init__(parent, "修改栏目")

    def body(self, master):
        ttk.Label(master, text=f"文章: {self.article_title}").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )

        ttk.Label(master, text="栏目").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.category_var = tk.StringVar(value=self.initial_category)
        ttk.Combobox(
            master,
            textvariable=self.category_var,
            values=self.category_names,
            state="readonly",
            width=28,
        ).grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(master, text="子栏目").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        self.subcategory_var = tk.StringVar(value=self.initial_subcategory)
        ttk.Combobox(
            master,
            textvariable=self.subcategory_var,
            values=self.subcategory_names,
            state="readonly",
            width=28,
        ).grid(row=2, column=1, sticky="ew", pady=4)

        return None

    def apply(self) -> None:
        category = self.category_var.get().strip()
        subcategory = self.subcategory_var.get().strip()
        if category and subcategory:
            self.result = (category, subcategory)


def main() -> None:
    root = tk.Tk()
    style = ttk.Style()
    if "vista" in style.theme_names():
        style.theme_use("vista")
    PublishApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
