#!/usr/bin/env python3
import os
from pathlib import Path
from groq import Groq
from rich.console import Console
from rich.markdown import Markdown

console = Console()

key_path = Path.home() / ".config/groq/api_key"
if not key_path.exists():
    console.print("[red]خطأ: حط الـ API Key في \~/.config/groq/api_key[/red]")
    exit(1)

client = Groq(api_key=key_path.read_text().strip())

project_path = Path.cwd()
files_info = []
for p in project_path.rglob("*"):
    if p.is_file() and p.stat().st_size < 500_000:
        try:
            content = p.read_text(errors="ignore")[:3000]
            files_info.append(f"### ملف: {p.relative_to(project_path)}\n```\n{content}\n```")
        except:
            pass

context = "\n\n".join(files_info[:15])

prompt = f"""أنت خبير برمجة. افحص المشروع التالي الموجود في المسار: {project_path}

محتوى الملفات:
{context}

المطلوب:
1. ملخص سريع عن المشروع
2. المشاكل والأخطاء المحتملة
3. تحسينات مقترحة
4. إصلاحات مهمة (إن وجدت)
5. تقييم عام من 10

اكتب التقرير بالعربية بشكل منظم وواضح.
"""

console.print("[bold cyan]جاري فحص المشروع... انتظر[/bold cyan]\n")

response = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[{"role": "user", "content": prompt}],
    temperature=0.3,
    max_tokens=2000
)

report = response.choices[0].message.content
console.print(Markdown(report))

with open("ai_report.md", "w") as f:
    f.write(report)
console.print("\n[green]تم حفظ التقرير في ملف: ai_report.md[/green]")
