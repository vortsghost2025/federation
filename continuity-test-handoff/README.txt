# Continuity Test Handoff
# S:\federation\continuity-test-handoff
#
# Folder layout
# ===========
# A_old_synced_session/   — Agent A (old synced session) receives round1 outputs here
# B_fresh_cloud_session/  — Agent B (fresh cloud session) receives round1 outputs here
# C_fresh_local_session/  — Agent C (fresh local session) — starts empty, writes round1 → round2
#
# File naming standard
# ===================
#   roundN.txt              Full evaluation (all 8 sections)
#   roundN-notes.txt        Session context + continuation trigger
#   roundN-export.json      Raw session artifacts (JSON)
#   roundN-compact-summary.txt   Condensed 1-paragraph-per-section
#   roundN-transcript.txt   Chronological action log
#
# Agent instructions
# ==================
# Agent A: Read round1-*.txt from this folder, do not re-run ROUND 1.
#          Write round2-*.txt back into this folder when done.
# Agent B: Read round1-*.txt from B_fresh_cloud_session/.
#          Write round2-*.txt back into B_fresh_cloud_session/.
# Agent C: Start ROUND 1 fresh. Write round1-*.txt into C_fresh_local_session/.
