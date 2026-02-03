Batch-31 Hotfix-1: UI blank screen guard
- Adds ErrorBoundary to show crashes instead of blank page.
- Lazy-loads pages to avoid one broken page killing the whole app.
- brain_ui depends_on includes gateway_api.
