# Plan: P002

## Objective
Integrate choice_token into all 3 frontend JS files so /choose requests include the token from /event responses.

## Steps
1. Add `let currentChoiceToken = null` after module-level vars in each file
2. Store token from /event response: `currentChoiceToken = data.choice_token || null`
3. Append token to /choose URL: `?choice_token=${currentChoiceToken || ''}`
4. Add error recovery: on "Invalid choice token" → null token, re-fetch event
5. Git commit the 3 changed files

## Success Criteria
- [ ] index.js stores and sends choice_token
- [ ] bridge.js stores and sends choice_token
- [ ] adult.js stores and sends choice_token
- [ ] All 3 have "Invalid choice token" error recovery
- [ ] git diff shows only 3 frontend JS files changed
- [ ] No backend changes, no VPS deploy