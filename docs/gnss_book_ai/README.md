# GNSS Book AI Package

这个目录是把原始 GNSS 教材 PDF 转成适合后续 AI 处理的包。

## 产物

- [manifest.json](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/manifest.json)
  总览信息，包含页数、目录项数量、图片数量和主要产物路径。
- [outline.json](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/outline.json)
  目录树的扁平化结果，适合按标题或页码检索章节。
- [pages.jsonl](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/pages.jsonl)
  每页一条 JSON，包含页号、文本、图片列表和整页 PNG 路径。
- [book.md](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/book.md)
  适合人和模型直接阅读的单文件 Markdown。
- `assets/images/`
  从 PDF 里直接抽出的嵌入图片。
- `assets/page_renders/`
  每页整页渲染 PNG，用来保留公式排版、图文位置和复杂版式。

## 推荐用法

- 做全文阅读或让模型直接通读时，用 `book.md`。
- 做 RAG、页级检索或专题抽取时，用 `pages.jsonl`。
- 需要知道某个章节从哪里开始时，用 `outline.json`。
- 文本抽取对公式排版不够可靠时，回看对应页的 `assets/page_renders/page-XXXX.png`。
- 需要原始图表素材时，优先看 `assets/images/`，因为它比整页截图更干净。

## 当前专题入口

如果下一步要重点核对“坐标、时间、伪距形成”的定义，先看：

- [topic_coordinates_time_receivers.md](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/topic_coordinates_time_receivers.md)

## 生成方式

转换脚本在：

- [tools/pdf_to_ai_package.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/tools/pdf_to_ai_package.py)

本次生成命令等价于：

```bash
python3 tools/pdf_to_ai_package.py \
  "Understanding GPSGNSS Principles and Applications, Third Edition (Gnss Technology and Applications Series) (Elliott Kaplan, Christopher J. Hegarty) (z-library.sk, 1lib.sk, z-lib.sk).pdf" \
  docs/gnss_book_ai
```
