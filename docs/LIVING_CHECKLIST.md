# Living Checklist — Trading Monorepo

> هذا الملف هو سجل رسمي للخطوات/الباتشات اللي اتعملت واتاختبرت، علشان ما نضيعش سكة أو نكرر شغل.

## مبادئ ثابتة (لا تتغير)
- ما نخسرش أي ميزة شغالة.
- Gateway هو المدخل الموحد للـUI.
- Contracts Events ثابتة (SignalEvent/TradeEvent/HealthEvent) + trace_id + schema_version.
- Postgres هو الـPrimary DB.
- الحفاظ على الـLegacy endpoints/ports أثناء التوحيد (خصوصًا dashboards 8000/8001/8002).

## المنجز (حسب آخر جلسات)
- ✅ Phase 2 UI: إصلاح Vite/MUI Grid2 + تشغيل brain_ui.
- ✅ Gateway health proxy JSON: معالجة /health من dashboards وإرجاع JSON ثابت.
- ✅ Batch-28 Auth: إضافة API Key header + حماية endpoints.
- ✅ Batch-29 Manual Trades: إصلاح أخطاء monitor مع manual trades.
- ✅ Batch-31 Brain Postgres Driver: اعتماد psycopg v3 (DSN + deps).
- ✅ Batch-32 Brain Sync limit: توحيد signature + دعم limit في sync.
- ✅ All-in-one stack + Postgres schemas + unified endpoints + smoke_unified_v2.
- ✅ Pump Hunter heartbeat + /api/trades endpoint.

## Batch-35 (جاري) — All-in-one “Core + Bots”
- [ ] إضافة docker-compose.allinone.yml (تشغيل كامل stack في ملف واحد)
- [ ] إضافة scripts/bootstrap_allinone.sh + scripts/smoke_batch35.sh
- [ ] توثيق تشغيل من الصفر في docs/DOCKER_ALLINONE.md
- [ ] اختبار كامل على جهازك:
  - [ ] stack up
  - [ ] smoke_batch35.sh
  - [ ] brain sync يكتب rows في brain.trade_features
- [ ] بعد نجاح الاختبار: نبدأ توحيد الداتا بشكل “نظيف” (Views ثم قرار نقل جداول)

## الخطوة الجاية بعد Batch-35
- توحيد الداتا (بدون كسر):
  1) `core` schema + Views (trades/signals/positions) مجمعة.
  2) تحديث Brain Sync لقراءة من `core` بدل قراءة مباشرة من mina_* (اختياري).
  3) توحيد Dashboard: Brain UI تكون الرئيسية + صفحات أوامر/تحكم (Kill switch, Close all, Replay).
