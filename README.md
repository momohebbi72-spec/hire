# 📡 Personal Opportunity Radar

دستیار شخصی برای پیدا کردن فرصت‌های کاری و درآمدی مرتبط با مهارت‌های تو (SEO، دیجیتال مارکتینگ، وردپرس، مشاوره، پروژه‌ی فریلنس، کار ریموت).

هر روز خودکار:

1. از منابع مختلف فرصت جمع می‌کند
2. هر فرصت را با پروفایل مهارتی‌ات مقایسه می‌کند و امتیاز ۰ تا ۱۰۰ + دلیل می‌دهد
3. در داشبورد (CRM شخصی) نگه می‌دارد تا وضعیت و یادداشت بگذاری
4. گزارش روزانه را به **ایمیل** (با فایل Excel پیوست)، **تلگرام** و **Google Sheet** می‌فرستد

```
SEO Manager - Remote Canada
Match Score: 92%
✓ Role: SEO Manager  ✓ SEO  ✓ Technical SEO  ✓ GA4  ✓ WordPress  ✓ Remote  ✓ Canada
```

---

## شروع سریع (مک)

1. پوشه را باز کن و روی `start.command` دابل‌کلیک کن
   (بار اول اگر مک اجازه نداد: کلیک راست ← Open)
2. داشبورد خودکار باز می‌شود:
   `http://127.0.0.1:3000`
3. دکمه‌ی «اسکن الان» را بزن

یا از ترمینال:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m radar            # داشبورد
python -m radar scan       # فقط اسکن
python -m radar report     # ارسال گزارش
python -m radar daily      # اسکن + گزارش + Google Sheet (برای اجرای روزانه)
python -m radar rescore    # امتیازدهی مجدد بعد از تغییر پروفایل
```

---

## بخش‌ها

| بخش | کار |
|---|---|
| **فرصت‌ها** | فهرست با امتیاز، دلایل، فیلتر (وضعیت، دسته، منبع، حداقل امتیاز، جستجو) و تغییر وضعیت |
| **جزئیات فرصت** | متن کامل آگهی، یادداشت، وضعیت |
| **افزودن دستی** | فرصت‌هایی که از لینکدین، معرفی یا ایمیل پیدا کردی + ورود گروهی از CSV |
| **منابع** | افزودن، خاموش/روشن، تست تکی، نمایش خطای هر منبع |
| **پروفایل** | ویرایش مهارت‌ها، وزن‌ها، عنوان‌های هدف، موقعیت‌ها، کلمات حذفی |
| **گزارش** | پیش‌نمایش ایمیل، ارسال دستی، همگام‌سازی شیت، دانلود Excel/CSV |

وضعیت‌های CRM:
`New` → `Saved` → `Contacted` → `Applied` → `Won` / `Rejected` / `Archived`

ایمیل روزانه برای موارد `Contacted` و `Applied` که ۵ روز تغییری نداشته‌اند، **یادآوری پیگیری** هم دارد.

---

## منابع

| نوع | مثال مقدار | توضیح |
|---|---|---|
| `remoteok` | `seo,marketing` | RemoteOK |
| `remotive` | `seo` یا `category:marketing` | Remotive |
| `jobicy` | `seo` یا `industry:marketing` | Jobicy |
| `himalayas` | `digital marketing` | Himalayas |
| `arbeitnow` | — | اروپا |
| `freelancer` | `seo`, `wordpress` | پروژه‌های فریلنس Freelancer.com |
| `rss` | لینک فید | We Work Remotely، Reddit، Google Alerts، هر سایت دارای RSS |
| `greenhouse` / `lever` / `ashby` | `airbnb,gitlab` | صفحه‌ی کاریابی شرکت‌ها |
| `telegram` | `channel_username` | کانال‌های عمومی تلگرام (بدون ربات) |

نکته‌ها:

- **Google Alerts** بهترین راه برای پوشش سایت‌هایی است که API ندارند: یک Alert بساز، Deliver to را روی RSS بگذار و لینک فید را به‌عنوان منبع `rss` اضافه کن.
- **LinkedIn / Indeed** API عمومی ندارند؛ Job Alert ایمیلی بساز و موارد مهم را با «افزودن دستی» یا CSV وارد کن.
- منابع پیش‌فرض در
  `config/sources.yaml`
  هستند. بعد از اولین اجرا از صفحه‌ی «منابع» مدیریت می‌شوند.

---

## امتیازدهی

فایل پروفایل:
`config/profile.yaml`

| بخش | امتیاز |
|---|---|
| عنوان آگهی شامل یکی از `target_roles` | ۳۵ (یا مهارت در عنوان: ۲۲) |
| مهارت‌های پیدا شده در متن آگهی | تا ۴۰ (جمع وزن‌ها نسبت به `skill_target`) |
| Remote | ۱۰ |
| کشور/منطقه‌ی دلخواه | ۵ تا ۱۰ |
| نوع همکاری دلخواه (`work_types`) | ۱۰ |
| کلمه‌ی حذفی (`exclude_in_title` / `exclude_anywhere`) | امتیاز = ۰ |
| منطقه‌ی نامطلوب (`avoid_locations`) | −۲۰ |
| آگهی قدیمی‌تر از ۱۴ روز | −۵ |

آگهی‌های تکراری (یک شغل در چند سایت) خودکار حذف می‌شوند.

---

## گزارش روزانه

فایل `.env` را از روی `.env.example` بساز. هر کانالی که خالی بماند نادیده گرفته می‌شود.

### ۱) ایمیل (پیشنهاد اصلی)

1. در حساب گوگل، 2-Step Verification را روشن کن
2. از این آدرس یک App Password بساز:
   `https://myaccount.google.com/apppasswords`
3. در `.env`:

```
SMTP_USER=you@gmail.com
SMTP_PASSWORD=abcd efgh ijkl mnop
REPORT_EMAIL_TO=you@gmail.com
```

ایمیل شامل: تعداد بررسی‌شده، بهترین فرصت‌ها با امتیاز و دلیل، یادآوری پیگیری، وضعیت پایپ‌لاین + فایل Excel کامل پیوست.

### ۲) Google Sheet (CRM ابری)

1. در Google Cloud Console یک پروژه بساز و **Google Sheets API** را فعال کن
2. یک **Service Account** بساز و کلید JSON آن را دانلود کن
3. فایل را اینجا بگذار:
   `config/google-service-account.json`
4. یک Google Sheet خالی بساز و آن را با ایمیل Service Account (`...@...iam.gserviceaccount.com`) با دسترسی Editor به اشتراک بگذار
5. شناسه‌ی شیت (بخش بین `/d/` و `/edit` در آدرس) را در `.env` بگذار:

```
GOOGLE_SHEET_ID=1AbC...xyz
```

فقط ردیف‌های جدید اضافه می‌شوند؛ وضعیت و یادداشتی که در شیت می‌نویسی هیچ‌وقت بازنویسی نمی‌شود.

### ۳) تلگرام (نوتیفیکیشن فوری، اختیاری)

1. از `@BotFather` یک ربات بساز و توکن را بگیر
2. به ربات پیام بده و Chat ID خودت را از `@userinfobot` بگیر
3. در `.env`:

```
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
```

---

## اجرای خودکار روزانه

### گزینه‌ی الف: روی مک

```bash
./scripts/install_mac_schedule.sh 9 0     # هر روز ساعت ۹:۰۰
```

مک باید روشن باشد. لاگ در
`data/daily.log`

### گزینه‌ی ب: GitHub Actions (پیشنهادی — حتی وقتی مک خاموش است)

فایل workflow آماده است:
`.github/workflows/daily-radar.yml`

1. در ریپو به Settings ← Secrets and variables ← Actions برو
2. این Secretها را اضافه کن (هر کدام را که لازم داری):
   - `SMTP_USER`، `SMTP_PASSWORD`، `REPORT_EMAIL_TO`
   - `TELEGRAM_BOT_TOKEN`، `TELEGRAM_CHAT_ID`
   - `GOOGLE_SHEET_ID`، `GOOGLE_SERVICE_ACCOUNT_JSON` (کل محتوای فایل JSON)
3. از تب Actions یک بار دستی `Run workflow` بزن

هر روز ساعت 05:15 UTC اجرا می‌شود (ساعت را در فایل workflow عوض کن). دیتابیس بین اجراها در Cache می‌ماند تا فرصت تکراری گزارش نشود. در این حالت Google Sheet نقش CRM را دارد و منابع از
`config/sources.yaml`
خوانده می‌شوند (برای خاموش کردن یک منبع `enabled: false` بگذار).

> پیشنهاد: **GitHub Actions + ایمیل + Google Sheet** برای گزارش روزانه، و داشبورد محلی مک برای وقتی که می‌خواهی عمیق‌تر بررسی کنی.

---

## ساختار پروژه

```
config/profile.yaml       پروفایل مهارتی
config/sources.yaml       منابع پیش‌فرض
radar/sources/            جمع‌آورنده‌ها (job board، RSS، ATS شرکت‌ها، فریلنس، تلگرام)
radar/scoring.py          امتیازدهی و دسته‌بندی
radar/scanner.py          اجرای اسکن موازی
radar/report.py           ایمیل، تلگرام، گزارش
radar/exporters.py        Excel، CSV، Google Sheets
radar/web.py              داشبورد
data/                     دیتابیس و گزارش‌ها (در git نیست)
```

## قدم‌های بعدی (Roadmap)

- لایه‌ی AI: خلاصه‌ی هر فرصت، مقایسه‌ی فرصت‌ها و پیشنهاد اقدام بعدی (متن پیام/پروپوزال)
- همگام‌سازی دوطرفه‌ی وضعیت‌ها با Google Sheet
- منابع بیشتر (Upwork با API رسمی، سایت‌های کاریابی ایرانی)
