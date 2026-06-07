# Constraints: P002

## Hard Rules
- [x] No backend code changes
- [x] No VPS deploys
- [x] No Docker changes
- [x] No new files created — only modify existing 3 JS files
- [x] All changes must be backward-compatible (token optional on backend)
- [x] `currentChoiceToken` must be module-level `let` variable
- [x] Fallback `|| null` and `|| ''` must exist on every token reference
- [x] Error recovery must null the token and re-fetch, not crash

## Deferred to P003
- Spatial mode sticky flag in starmap.js
- VPS deploy of P002 changes