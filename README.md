# 📡 Personal Opportunity Radar

دستیار شخصی برای پیدا کردن آگهی‌های **سئو و جئو (GEO)**: کارشناس/متخصص/مدیر سئو، سئوکار، GEO و دیده‌شدن برند در نتایج هوش مصنوعی — فقط **دورکاری تمام‌وقت، دورکاری پاره‌وقت یا پروژه‌ای**، و فقط **۷ روز اخیر**.

## داشبورد (نسخه‌ی ۳)

یک صفحه، دو جا: داخل claude.ai (همان لینک همیشگی) و روی مک در
`http://localhost:3000/app`

| صفحه | چه چیزی |
|---|---|
| داشبورد | خلاصه‌ی هفته، نمودار روزبه‌روز، پربازده‌ترین منابع، قیف پیگیری |
| سایت‌های ایرانی | جابینجا، جاب‌ویژن، ای‌استخدام، پونیشا، کارلنسر… (پست‌های تلگرامی که به این سایت‌ها لینک می‌دهند هم اینجا) |
| لینکدین | آگهی‌های دورکاری سئو و جئو |
| تلگرام و اینستاگرام | پست‌های کانال‌ها |
| خارجی | سایت‌های خارجی — پیش‌فرض خاموش |
| قابل بررسی | آگهی‌های خوب ولی نامطمئن، با دلیل (تاریخ نامشخص، دورکاری نامشخص، سئو فقط در متن، عنوان ترکیبی) |
| پیگیری | برد ذخیره‌شده → پیام دادم → درخواست دادم → قبول/رد |
| تنظیمات | فیلتر هوشمند (نقش‌ها، کلمات حذف، بازه)، منابع (سایت‌ها، کانال‌ها، هشتگ‌ها، لینکدین، جستجوها)، متن‌ها و رزومه، گزارش ایمیلی |

هر صفحه فیلتر چک‌باکسی مثل جاب‌ویژن دارد: نوع همکاری، نقش، سطح، زمان انتشار، منبع/کانال/کشور، وضعیت.
قوانین دسته‌بندی در
`radar/tiers.py`
هستند و همان قوانین داخل داشبورد هم اجرا می‌شوند، پس تغییر تنظیمات فورا روی همه‌ی صفحه‌ها اعمال می‌شود.

```
منابع → جمع‌آوری → نرمال‌سازی → حذف تکراری → تحلیل → امتیاز → داشبورد → Excel → ایمیل
```

- ابزار شخصی است: لاگین، پرداخت و چندکاربره ندارد.
- بدون AI کار می‌کند (موتور امتیازدهی داخلی)؛ لایه‌ی AI برای آینده آماده است.

---

## معماری: چرا دو بخش؟

| | مک تو (IP ایران) | GitHub Actions (سرور خارج) |
|---|---|---|
| سایت‌های ایرانی (جابینجا، جاب‌ویژن، پونیشا، کارلنسر…) | ✅ | ❌ اتصال از خارج را رد می‌کنند |
| LinkedIn، تلگرام، Indeed، گوگل، RemoteOK… | ❌ فیلتر / تحریم | ✅ |
| ایمیل روزانه + Google Sheet | اختیاری | ✅ حتی وقتی مک خاموش است |
| داشبورد و CRM | ✅ | — |

دو طرف از طریق یک برنچ جدا در همین ریپو (`radar-data`) نتایج را رد و بدل می‌کنند. تنظیمات (پروفایل، منابع، زمان ایمیل) فقط یک جاست:
`config/`
و وقتی در داشبورد عوض شوند، خودکار به GitHub هم فرستاده می‌شوند.

> اگر همگام‌سازی را تنظیم نکنی، همه‌ی منابع روی همان مک اسکن می‌شوند (منابع خارجی فقط با VPN جواب می‌دهند).

---

## نصب و اجرا (مک)

1. پوشه‌ی پروژه را روی مک داشته باش (دانلود ZIP یا `git clone`)
2. روی `start.command` دابل‌کلیک کن (بار اول اگر مک اجازه نداد: کلیک راست ← Open)
3. مرورگر خودکار باز می‌شود:
   `http://localhost:3000`

پیش‌نیاز: Python 3.9 یا بالاتر. اگر نصب نیست:
`https://www.python.org/downloads/`

> وقتی منابع ایرانی را اسکن می‌کنی، VPN باید خاموش باشد.

اجرای خودکار ساعتی روی مک (حتی وقتی داشبورد بسته است):

```bash
./scripts/install_mac_schedule.sh            # نصب
./scripts/install_mac_schedule.sh uninstall  # حذف
```

دستورات ترمینال:

```bash
.venv/bin/python -m radar              # داشبورد
.venv/bin/python -m radar tick         # هر کاری که موعدش رسیده
.venv/bin/python -m radar daily        # اسکن همه + ارسال گزارش همین الان
.venv/bin/python -m radar scan --source jobinja-seo
.venv/bin/python -m radar report
.venv/bin/python -m radar sync pull    # pull | push | config-push | config-pull
```

---

## راه‌اندازی GitHub (ایمیل روزانه + منابع خارجی)

### ۱) Secrets
در ریپو برو به:
`Settings → Secrets and variables → Actions → New repository secret`

| Secret | مقدار |
|---|---|
| `SMTP_USER` | آدرس Gmail |
| `SMTP_PASSWORD` | App Password (پایین‌تر) |
| `REPORT_EMAIL_TO` | ایمیلی که گزارش به آن برسد |
| `GOOGLE_SHEET_WEBHOOK_URL` | اختیاری — Google Sheet |
| `GOOGLE_SHEET_WEBHOOK_SECRET` | اختیاری — Google Sheet |
| `GOOGLE_SHEET_URL` | اختیاری — لینک شیت برای ایمیل |
| `SERPER_API_KEY` | اختیاری — نتایج واقعی گوگل |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | اختیاری |

### ۲) فعال‌سازی
تب Actions ← Opportunity Radar ← Run workflow

از این به بعد هر ساعت اجرا می‌شود ولی فقط کارهای موعددار را انجام می‌دهد؛ ایمیل روزی یک بار در ساعتی که در «تنظیمات» گذاشتی ارسال می‌شود.

### ۳) اتصال مک به GitHub
1. یک Fine-grained token بساز:
   `https://github.com/settings/personal-access-tokens/new`
   - Repository access: فقط همین ریپو
   - Permissions → Contents: Read and write
2. در فایل `.env` روی مک:

```
GITHUB_TOKEN=github_pat_...
GITHUB_REPO=momohebbi72-spec/hire
```

---

## ایمیل (Gmail)

1. در حساب گوگل 2-Step Verification را روشن کن
2. App Password بساز:
   `https://myaccount.google.com/apppasswords`
3. همان را در `SMTP_PASSWORD` (GitHub Secret و `.env`) بگذار

ساعت، دفعات (روزانه/هفتگی/خاموش) و ایمیل گیرنده از صفحه‌ی «تنظیمات» داشبورد عوض می‌شود. عنوان ایمیل:
`Daily Opportunity Radar Report`
و فایل `opportunity_report.xlsx` پیوست آن است.

## Google Sheet (بدون Google Cloud)

1. یک Google Sheet بساز ← Extensions ← Apps Script
2. محتوای این فایل را در آن بگذار و `SECRET` را عوض کن:
   `scripts/google_apps_script.gs`
3. Deploy ← New deployment ← Web app ← Execute as: Me ← Who has access: Anyone
4. آدرس Web app را در `GOOGLE_SHEET_WEBHOOK_URL` و رمز را در `GOOGLE_SHEET_WEBHOOK_SECRET` بگذار

فقط ردیف‌های جدید اضافه می‌شوند؛ وضعیت و یادداشتی که در شیت می‌نویسی پاک نمی‌شود.

## جستجوی گوگل (۱۰ نتیجه‌ی اول)

منابع «جستجوی گوگل»، «پست‌های LinkedIn»، «Instagram» و «جستجو در یک سایت خاص» از جستجوی وب استفاده می‌کنند:

- با `SERPER_API_KEY` (ثبت‌نام رایگان، ۲۵۰۰ جستجو): نتایج واقعی گوگل
  `https://serper.dev`
- بدون کلید: DuckDuckGo (رایگان، گاهی محدود می‌شود)

دامنه‌های جدیدی که در نتایج پیدا می‌شوند در صفحه‌ی «منابع» ← «سایت‌های کشف‌شده» می‌آیند و با یک کلیک منبع می‌شوند.

---

## منابع

از صفحه‌ی «منابع»: افزودن، ویرایش، حذف، روشن/خاموش، تغییر کلمات کلیدی، دفعات اسکن، تست تکی، نمایش آخرین اسکن، تعداد یافته و خطا.

| گروه | نوع‌ها |
|---|---|
| کاریابی ایرانی (مک) | `jobinja`، `jobvision`، `eestekhdam`، `karbord`، `kardix`، `divar`، `webpage` |
| فریلنس ایرانی (مک) | `ponisha`، `karlancer`، `parscoders`، `lancerify` |
| کاریابی بین‌المللی (GitHub) | `linkedin`، `indeed`، `glassdoor`، `remoteok`، `remotive`، `jobicy`، `himalayas`، `arbeitnow` |
| فریلنس بین‌المللی | `freelancer` |
| جستجو و شبکه‌های اجتماعی | `websearch`، `site_search` (مثلا Wellfound)، `linkedin_posts`، `instagram`، `google_jobs` |
| سایت شرکت‌ها | `greenhouse`، `lever`، `ashby`، `webpage` |
| فید و کانال | `rss`، `telegram` |
| دستی | «افزودن دستی» + ورود CSV |

- **هر سایتی که نوع آماده ندارد:** نوع «هر صفحه‌ی وب» را انتخاب کن و آدرس صفحه‌ی لیست آگهی‌ها را بده. لینک‌های آگهی خودکار تشخیص داده می‌شوند.
- **کلمات کلیدی:** در منابع جستجویی، همان عبارت جستجو هستند. در فید، تلگرام و سایت شرکت‌ها، فیلترند (فقط آیتم‌های شامل آن‌ها نگه داشته می‌شوند).
- **افزودن سایت جدید در کد:** یک تابع با `@register(...)` در پوشه‌ی `radar/sources/` کافی است.

## امتیازدهی (۰ تا ۱۰۰)

| بخش | وزن |
|---|---|
| تطابق مهارت (وزن هر مهارت در پروفایل) | ۳۵ |
| تطابق کلمه‌ی کلیدی / عنوان هدف | ۲۵ |
| نوع فرصت (Remote، Freelance، Contract…) | ۱۵ |
| موقعیت | ۱۰ |
| ترجیحات (صنعت، تازگی آگهی) | ۱۵ |

متن فارسی نرمال‌سازی می‌شود (ي/ی، ك/ک، نیم‌فاصله). علامت `!` قبل از یک کلمه یعنی حساس به حروف بزرگ؛ مثلا `!GEO` تا با geo-targeting قاطی نشود.

**حذف تکراری:** اثرانگشت از عنوان + شرکت + موقعیت (+ آدرس)؛ اگر همان فرصت دوباره یا در سایت دیگری دیده شود، رکورد قبلی به‌روز می‌شود و «همچنین در …» نشان داده می‌شود.

## لایه‌ی AI (اختیاری)

رابط `AIProvider` با متدهای `analyze_opportunity`، `summarize_opportunity` و `explain_match` در این مسیر است:
`radar/ai/`

پیش‌فرض `rules` است: بدون کلید و بدون اینترنت، خلاصه، دلیل تطابق و «قدم بعدی» می‌دهد. جای OpenAI، Claude، Gemini و مدل محلی (Ollama) آماده است.

---

## پشتیبان‌گیری و به‌روزرسانی

```bash
./scripts/backup.sh     # data/radar.db + config + .env → backups/
git pull                # به‌روزرسانی کد (یا ZIP جدید را روی پوشه کپی کن؛ data/ و .env دست نمی‌خورند)
```

## تست‌ها

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

در GitHub هم با هر push خودکار اجرا می‌شوند (workflow به نام `Tests`).

## ساختار

```
config/          profile.yaml · sources.yaml · settings.yaml
radar/sources/   کانکتورها (ایرانی، بین‌المللی، جستجو، RSS، تلگرام، اینستاگرام)
radar/scoring.py موتور امتیازدهی
radar/scanner.py اسکن موازی + حذف تکراری
radar/scheduler.py زمان‌بند (tick)
radar/sync.py    همگام‌سازی مک ⇄ GitHub
radar/report.py  ایمیل، تلگرام، EmailLogs
radar/exporters.py Excel، CSV، Google Sheet
radar/ai/        لایه‌ی AI
radar/web.py     داشبورد
```

ایده‌ی `LinkedIn guest endpoint` و استفاده از `python-jobspy` از پروژه‌ی `ScottCoffin/Job_Scraper` گرفته شده، ولی کد آن (با لایسنس `AGPL-3.0`) کپی نشده است.

---

## ساخت پست «سؤال روز» (جئو)

ابزار جدا برای پرسیدن یک سؤال از هوش مصنوعی، شمارش اسم‌ها و ساخت کاروسل، ریلز، کپشن و متن لینکدین و ویرگول. راهنما:
`geo_cards/README.md`
