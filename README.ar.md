# ذاكرة هرمس الذكية (`hermes-intelligent-memory`)

[![Language: Arabic](https://img.shields.io/badge/Language-العربية-green.svg)](README.ar.md)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-purple.svg)](LICENSE)
[![Hermes Plugin](https://img.shields.io/badge/Hermes-Standalone%20Plugin-emerald.svg)](plugin.yaml)

[**English Documentation**](README.md) | [**المستندات باللغة الإنجليزية**](README.md)

---

## 📌 نبذة عن المشروع

مشروع **`hermes-intelligent-memory`** هو محرك ذاكرة ذكي محلي أولياً (`Local-First`) ومصمم خصيصاً لدعم **اللغة العربية والمحتوى متعدد اللغات** كخيار رئيسي لوكيل **Hermes Agent**.

يوفر النظام استرجاعاً فوريًا وسريعاً بدون أي تأخير، مع تتبع كامل لأصل وسجل الذاكرة (`Append-Only Provenance`) والمزامنة الآمنة مع ملفات التراكم السريعة `MEMORY.md` و `USER.md`.

---

## 🔥 الميزات الأساسية

1. **🇸🇦 دعم عربي متقدم جداً:** يعتمد على التفكيك اللغوي، التداخل اللفظي (`Token Overlap`)، وتقنية الـ `Character Trigrams` للبحث والتعرف على المستندات والكلمات العربية والمركبة بدقة فائقة.
2. **⚡ استرجاع محلي بدون تأخير (Zero-Latency):** الاستعلام والبحث يتمان 100% محلياً عبر داتابيز SQLite في نمط الـ `WAL` وفهارس `FTS5` دون الاعتماد على السحابة في المسار السريع.
3. **📜 دورة حياة وحفظ أصل الذاكرة:** تتبع دقيق لجميع حالات الذاكرة (`active`, `superseded`, `archived`, `rejected`) لمنع التعارض أو فقدان التاريخ السلسلي.
4. **🔄 المزامنة التلقائية للملفات:** كتابة وتزكية الحقائق الهامة تلقائياً بداخل ملفات `MEMORY.md` و `USER.md` باستخدام عمليات كتابة ذرية وبسجلات احتياطية.
5. **🔒 عزل البروفايلات:** تخزين مستقل لكل بروفايل تحت المسار الخفي `$HERMES_HOME/intelligent_memory/memory.db`.
6. **🛠️ أدوات محرك هرمس:** دعم كامل لأدوات الذاكرة الذكية المستقلة في التلغرام والـ CLI.

---

## 🏗️ الهيكلية المعمارية

```mermaid
graph TD
    A[Hermes Agent] -->|MemoryProvider API| B[Intelligent Memory Provider]
    B --> C[(Local SQLite DB WAL)]
    B --> D[FTS5 + Trigram Index]
    B --> E[Projection Engine]
    E --> F[MEMORY.md]
    E --> G[USER.md]
    B -.->|Selective Async| H[Cloud Inference / Reranking]
```

---

## 🔧 طريقة التثبيت والاستخدام

### 1. التثبيت السريع عبر أمر هرمس (One-Line Install):

```bash
hermes plugins install https://github.com/hoysama/hermes-intelligent-memory
```

### 2. التكوين الكامل في إعدادات هرمس (`~/.hermes/config.yaml`):

أضف المربع الشامل لإعدادات الذاكرة بداخل ملف الإعدادات الرئيسي (`~/.hermes/config.yaml`):

```yaml
memory:
  provider: intelligent_memory
  memory_enabled: true
  user_profile_enabled: true
  memory_char_limit: 35000
  user_char_limit: 35000
  write_approval: false
  flush_min_turns: 6
  nudge_interval: 10
  intelligent_memory:
    cloud_mode: 'off' # الخيارات المتاحة: 'off', 'selective', 'session'
    max_recall_facts: 6
    max_recall_chars: 1800
```

---

## 🛠️ أدوات الذاكرة المتاحة في النظام

| اسم الأداة | الوصف |
| :--- | :--- |
| `intelligent_memory_remember` | حفظ حقيقة هيكلية دائمة بداخل الذاكرة الذكية |
| `intelligent_memory_recall` | البحث عن الحقائق النشطة المتعلقة باستعلام معين |
| `intelligent_memory_revise` | تعديل حقيقة سابقة مع حفظ تاريخ السجل |
| `intelligent_memory_forget` | أرشفة حقيقة دون حذف تاريخها السلسلي |
| `intelligent_memory_status` | تقرير عن حالة نظام الذاكرة وعدد الحقائق |
| `intelligent_memory_feedback` | تسجيل تقييم فائدة الحقائق المسترجعة لتطوير النتائج |

---

## 🧪 تشغيل الاختبارات

لتشغيل حزمة الاختبارات الشاملة:
```bash
uv run pytest
```

---

## 📄 الترخيص (License)

تخضع هذه الحزمة لترخيص **MIT License**. تطوير وصيانة **HoySama** لمنظومة Hermes Agent.
