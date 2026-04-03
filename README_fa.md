# راهنمای سریع seyd-yaar-LCS

این نسخه برای اجرای کامل روی GitHub ساخته شده است:
- اجرای دستی با ورودی از صفحه Actions
- اجرای خودکار روزانه برای today و tomorrow
- تخمین حجم دانلود قبل از اجرای واقعی
- تولید خروجی‌ها در `outputs/latest/`
- ساخت یک صفحه واحد در `docs/latest/`

## Secrets لازم
در Settings > Secrets and variables > Actions این دو secret را بساز:
- `COPERNICUSMARINE_SERVICE_USERNAME`
- `COPERNICUSMARINE_SERVICE_PASSWORD`

## فایل مهم برای تغییر پیش‌فرض‌ها
فقط این فایل را ادیت کن:
- `config/defaults.json`

چیزهایی که آنجا تنظیم می‌کنی:
- bbox پیش‌فرض
- تعداد روزهای backward
- scheduled modes
- روشن/خاموش بودن بعضی خروجی‌ها
- روشن/خاموش بودن نگه‌داری archive در آینده

## اجرای دستی
Actions > Run LCS pipeline > Run workflow

## تخمین حجم دانلود
Actions > Estimate LCS download > Run workflow

## محل خروجی‌ها
- `outputs/latest/today/`
- `outputs/latest/tomorrow/`
- `outputs/latest/custom/`
- `docs/latest/`

## Pages
در Settings > Pages:
- Source را روی GitHub Actions بگذار.
