# Docker (All-in-one) — Core + Bots

الهدف من هذا الملف: تشغيل المشروع **من الصفر** بشكل ثابت، علشان نقدر نختبر كل حاجة ونكمل التوحيد بدون ما نكسر أي ميزة شغالة.

## الخدمات والـPorts

- Gateway API: `8200`
- Brain API: `8100`
- Brain UI (Unified Dashboard): `5173`
- Mina Dashboards (Legacy — لا نكسر القديم):
  - Paper: `8000`
  - Live: `8001`
  - Pump: `8002`
- Postgres: `5432`

> المبدأ: Brain UI هي الواجهة الموحدة الأساسية، والـ3 Dashboards القديمة موجودة كـLegacy/Debug/Backward-compat.

## تشغيل من الصفر

### 1) تشغيل عادي (يحافظ على الداتا)
```bash
bash scripts/bootstrap_allinone.sh
bash scripts/smoke_batch35.sh
```

### 2) تشغيل “نظيف” (يمسح Postgres volume)
⚠️ **يحذف الداتا بالكامل**
```bash
bash scripts/bootstrap_allinone.sh --reset-volumes
bash scripts/smoke_batch35.sh
```

## التست الأساسي اللي لازم يعدّي

1) `GET http://localhost:8200/health` ✅  
2) `GET http://localhost:8100/health` ✅  
3) `GET http://localhost:8200/api/unified/overview` ✅  
4) `POST http://localhost:8100/api/sync/run?role=paper&limit=500` ✅  
5) `select count(*) from brain.trade_features;` >= 1 (بعد وجود Trades في mina_paper) ✅

## ملاحظات توحيد الداتا
حاليًا كل المشروع على **Postgres واحد** (database=`trading`) لكن بــschemas مختلفة:
- `gateway` (audit/events)
- `brain` (trade_features + sync_state)
- `mina_paper`, `mina_live`, `mina_pump` (Mina Bot data)

الخطوة الجاية في التوحيد هتكون “Unified Views” أو “Unified Tables” بدون ما نخسر أي ميزة:
- Views بتجمع Trades/Signals من كل roles في schema موحد (مثال: `core.trades_all`)
- بعد ما نتأكد من كل حاجة، نقرر هل ننقل لجدول واحد مع عمود `bot_role` ولا نفضل schemas منفصلة + Views.
