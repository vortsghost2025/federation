#!/usr/bin/env python3
"""Build simulation.html with the redesigned UI."""

import os

CSS = r"""
:root{--amber:#FF9800;--amber-dim:rgba(255,152,0,0.15);--cyan:#00BCD4;--cyan-dim:rgba(0,188,212,0.12);--violet:#CE93D8;--red:#F44336;--red-dim:rgba(244,67,54,0.12);--green:#4CAF50;--green-dim:rgba(76,175,80,0.12);--white:#e0e0e0;--dim:#90A4AE;--panel-bg:rgba(8,12,20,0.94);--panel-border:rgba(0,188,212,0.15);--glow-cyan:0 0 10px rgba(0,188,212,0.25);--glow-amber:0 0 10px rgba(255,152,0,0.25);--sev-critical:#F44336;--sev-severe:#E91E63;--sev-high:#FF9800;--sev-medium:#FFC107;--sev-low:#4CAF50;--sev-stable:#00BCD4;--sev-calm:#81C784}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;overflow:hidden;background:#040810;color:var(--white);font-family:'Share Tech Mono',monospace;font-size:18px}
#app{display:grid;grid-template-rows:100px auto 1fr 64px;grid-template-columns:30% 40% 30%;grid-template-areas:"top top top" "sit sit sit" "left center right" "bottom bottom bottom";height:100vh;gap:1px;background:radial-gradient(ellipse at 50% 30%,rgba(0,188,212,0.03) 0%,transparent 60%)}
.panel{background:var(--panel-bg);overflow-y:auto;scrollbar-width:thin;scrollbar-color:rgba(0,188,212,0.2) transparent}
.panel::-webkit-scrollbar{width:4px}
.panel::-webkit-scrollbar-thumb{background:rgba(0,188,212,0.2);border-radius:2px}
#top{grid-area:top;display:flex;flex-direction:column;background:var(--panel-bg);border-bottom:1px solid var(--panel-border);padding:6px 12px;z-index:5;overflow:hidden}
#situation{grid-area:sit;display:flex;gap:12px;padding:8px 16px;background:rgba(8,12,20,0.98);border-bottom:1px solid var(--panel-border)}
#left{grid-area:left;border-right:1px solid var(--panel-border);padding:12px}
#center{grid-area:center;padding:12px;position:relative}
#right{grid-area:right;border-left:1px solid var(--panel-border);padding:12px}
#bottom{grid-area:bottom;display:flex;align-items:center;gap:16px;background:var(--panel-bg);border-top:1px solid var(--panel-border);padding:0 16px;overflow-x:auto}

/* ═══ TOP SPLIT BANNER ═══ */
.top-row{display:flex;align-items:center;gap:6px;min-height:38px;padding:2px 0}
.top-row-label{font-family:'Orbitron',sans-serif;font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--dim);min-width:110px;white-space:nowrap}
.split-bar-container{flex:1;height:22px;background:rgba(255,255,255,0.06);border-radius:11px;overflow:hidden;position:relative;border:1px solid rgba(255,255,255,0.08);min-width:120px}
.split-bar-left{height:100%;float:left;border-radius:11px 0 0 11px;transition:width 0.8s ease,background 0.5s ease;position:relative}
.split-bar-right{height:100%;float:right;border-radius:0 11px 11px 0;transition:width 0.8s ease,background 0.5s ease;position:relative}
.split-bar-left::after,.split-bar-right::after{content:'';position:absolute;inset:0;background:linear-gradient(180deg,rgba(255,255,255,0.18) 0%,transparent 50%)}
.degradation-fill{background:linear-gradient(90deg,var(--red),var(--sev-severe))}
.runway-fill{background:linear-gradient(90deg,#1B5E20,var(--green))}
.threat-fill{background:linear-gradient(90deg,var(--red),var(--amber))}
.buffer-fill{background:linear-gradient(90deg,#0D47A1,var(--cyan))}
.split-metric-chips{display:flex;gap:4px;margin-left:8px;flex-shrink:0}
.split-chip{font-family:'Orbitron',sans-serif;font-size:12px;font-weight:700;letter-spacing:1px;padding:2px 7px;border-radius:4px;white-space:nowrap}
.split-chip.degradation{color:var(--red);background:rgba(244,67,54,0.15);border:1px solid rgba(244,67,54,0.3)}
.split-chip.runway{color:var(--green);background:rgba(76,175,80,0.15);border:1px solid rgba(76,175,80,0.3)}
.split-chip.threat{color:var(--amber);background:rgba(255,152,0,0.15);border:1px solid rgba(255,152,0,0.3)}
.split-chip.buffer{color:var(--cyan);background:rgba(0,188,212,0.15);border:1px solid rgba(0,188,212,0.3)}
.split-severity{font-family:'Orbitron',sans-serif;font-size:11px;font-weight:900;letter-spacing:1px;padding:2px 6px;border-radius:3px;margin-left:6px;white-space:nowrap}
.split-severity.critical{background:rgba(244,67,54,0.25);color:var(--sev-critical);border:1px solid rgba(244,67,54,0.4);animation:sevPulse 2s ease infinite}
.split-severity.severe{background:rgba(233,30,99,0.2);color:var(--sev-severe);border:1px solid rgba(233,30,99,0.35)}
.split-severity.high{background:rgba(255,152,0,0.2);color:var(--sev-high);border:1px solid rgba(255,152,0,0.35)}
.split-severity.elevated{background:rgba(255,193,7,0.15);color:var(--sev-medium);border:1px solid rgba(255,193,7,0.3)}
.split-severity.nominal{background:rgba(76,175,80,0.15);color:var(--sev-low);border:1px solid rgba(76,175,80,0.3)}
.top-tick-display{display:flex;align-items:center;gap:6px;margin-left:auto;flex-shrink:0;padding-left:12px;border-left:1px solid var(--panel-border)}
.top-tick-label{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:1.5px}
.top-tick-val{font-family:'Orbitron',sans-serif;font-size:16px;color:var(--amber);min-width:50px;text-align:right}
.time-since{display:flex;align-items:center;gap:6px;padding-left:10px;white-space:nowrap}
.time-since-label{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:1px}
.time-since-val{font-family:'Orbitron',sans-serif;font-size:14px;color:var(--cyan)}
.top-nav{display:flex;gap:4px;align-items:center;flex-shrink:0;padding-left:10px;border-left:1px solid var(--panel-border);margin-left:4px}
.top-nav a{color:var(--dim);font-size:13px;text-decoration:none;padding:4px 8px;letter-spacing:1px;text-transform:uppercase;transition:color 0.2s;border-radius:4px}
.top-nav a:hover,.top-nav a.active{color:var(--cyan);background:var(--cyan-dim)}
.help-btn{background:none;border:1px solid rgba(0,188,212,0.3);color:var(--cyan);font-size:15px;cursor:pointer;padding:4px 8px;border-radius:6px;margin-left:4px;transition:background 0.2s,border-color 0.2s;line-height:1;font-weight:700}
.help-btn:hover{background:var(--cyan-dim);border-color:var(--cyan)}

/* ═══ CASCADE PIPELINE ═══ */
.pipeline-root{background:rgba(244,67,54,0.08);border:2px solid rgba(244,67,54,0.5);border-radius:10px;padding:10px 14px;margin-bottom:8px;position:relative;animation:rootPulse 3s ease infinite}
@keyframes rootPulse{0%,100%{box-shadow:0 0 8px rgba(244,67,54,0.2)}50%{box-shadow:0 0 18px rgba(244,67,54,0.5)}}
.pipeline-root-label{font-family:'Orbitron',sans-serif;font-size:11px;font-weight:900;letter-spacing:2px;text-transform:uppercase;color:var(--red);margin-bottom:4px}
.pipeline-root-event{font-size:15px;font-weight:700;color:var(--white);line-height:1.4}
.pipeline-dominoes{margin-left:16px;border-left:3px solid rgba(206,147,216,0.25);padding-left:14px;margin-top:4px}
.domino-npc{display:flex;align-items:flex-start;gap:8px;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.04);position:relative}
.domino-npc::before{content:'';position:absolute;left:-17px;top:50%;width:10px;height:2px;background:rgba(206,147,216,0.3)}
.domino-depth{font-family:'Orbitron',sans-serif;font-size:10px;font-weight:900;letter-spacing:1px;padding:2px 5px;border-radius:3px;color:var(--violet);background:rgba(206,147,216,0.15);border:1px solid rgba(206,147,216,0.25);white-space:nowrap;flex-shrink:0}
.domino-name{font-family:'Orbitron',sans-serif;font-size:13px;font-weight:700;color:var(--white);flex-shrink:0}
.domino-tone{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;padding:1px 5px;border-radius:3px;white-space:nowrap;flex-shrink:0}
.domino-tone.fear{color:var(--red);background:rgba(244,67,54,0.12)}
.domino-tone.conflict{color:var(--sev-severe);background:rgba(233,30,99,0.12)}
.domino-tone.caution{color:var(--amber);background:rgba(255,152,0,0.12)}
.domino-tone.support{color:var(--green);background:rgba(76,175,80,0.12)}
.domino-tone.celebration{color:var(--cyan);background:rgba(0,188,212,0.12)}
.domino-tone.neutral{color:var(--dim);background:rgba(255,255,255,0.05)}
.domino-desc{font-size:13px;color:var(--dim);line-height:1.4;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pipeline-overflow{font-size:13px;color:var(--violet);padding:4px 0;margin-left:16px;border-left:3px solid rgba(206,147,216,0.15);padding-left:14px}

/* ═══ NPC CASCADE STATUS COLORS ═══ */
.npc-card.cascade-root{border-color:rgba(244,67,54,0.7) !important;box-shadow:0 0 10px rgba(244,67,54,0.3);animation:rootPulse 3s ease infinite}
.npc-card.cascade-reactor{border-color:rgba(206,147,216,0.7) !important;box-shadow:0 0 6px rgba(206,147,216,0.2)}
.npc-card.cascade-affected{border-color:rgba(255,152,0,0.6) !important;box-shadow:0 0 4px rgba(255,152,0,0.15)}
.npc-card.cascade-none{border-color:rgba(255,255,255,0.06)}
.npc-card.npc-idle{opacity:0.35;transition:opacity 0.4s ease}
.npc-card.npc-idle:hover{opacity:0.7}
.npc-card.npc-idle.hide-idle{display:none}
.cascade-badge{font-family:'Orbitron',sans-serif;font-size:9px;font-weight:900;letter-spacing:0.5px;padding:1px 4px;border-radius:3px;margin-left:4px;vertical-align:middle}
.cascade-badge.trigger{color:var(--red);background:rgba(244,67,54,0.15);border:1px solid rgba(244,67,54,0.3)}
.cascade-badge.reactor{color:var(--violet);background:rgba(206,147,216,0.15);border:1px solid rgba(206,147,216,0.3)}
.cascade-badge.affected{color:var(--amber);background:rgba(255,152,0,0.15);border:1px solid rgba(255,152,0,0.3)}

/* ═══ NOISE FILTER TOGGLE ═══ */
.npc-noise-toggle{display:flex;align-items:center;gap:8px;margin-bottom:8px;padding:4px 10px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:6px;cursor:pointer;user-select:none;transition:border-color 0.3s,background 0.3s}
.npc-noise-toggle:hover{background:rgba(0,188,212,0.06);border-color:rgba(0,188,212,0.2)}
.npc-noise-toggle-label{font-family:'Orbitron',sans-serif;font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--dim);transition:color 0.3s}
.npc-noise-toggle.on .npc-noise-toggle-label{color:var(--cyan)}
.npc-noise-toggle-count{font-family:'Orbitron',sans-serif;font-size:12px;color:var(--amber);margin-left:auto}

/* ═══ RETAINED STYLES ═══ */
.help-overlay{display:none;position:fixed;inset:0;z-index:100;background:rgba(4,8,16,0.95);overflow-y:auto;padding:40px 20px}
.help-overlay.open{display:block}
.help-box{max-width:800px;margin:0 auto;background:rgba(8,12,20,0.98);border:1px solid var(--panel-border);border-radius:12px;padding:32px 36px}
.help-box h2{font-family:'Orbitron',sans-serif;font-size:22px;color:var(--cyan);letter-spacing:3px;margin-bottom:20px}
.help-box h3{font-family:'Orbitron',sans-serif;font-size:15px;color:var(--amber);letter-spacing:2px;margin:20px 0 10px 0;text-transform:uppercase}
.help-box p,.help-box li{font-size:15px;line-height:1.7;color:var(--white);margin-bottom:8px}
.help-box ul{padding-left:20px;margin-bottom:12px}
.help-box li{margin-bottom:4px}
.help-box .color-swatch{display:inline-block;width:14px;height:14px;border-radius:3px;vertical-align:middle;margin-right:6px}
.help-close{position:sticky;top:0;float:right;background:none;border:1px solid var(--red);color:var(--red);font-size:18px;cursor:pointer;padding:6px 14px;border-radius:6px;font-weight:700;transition:background 0.2s}
.help-close:hover{background:var(--red-dim)}
.help-section{border-left:3px solid var(--cyan-dim);padding-left:16px;margin-bottom:16px}
.section-title{font-family:'Orbitron',sans-serif;font-weight:700;font-size:14px;letter-spacing:2px;text-transform:uppercase;padding-bottom:8px;margin-bottom:10px;border-bottom:1px solid var(--panel-border)}
.section-title.amber{color:var(--amber)}
.section-title.cyan{color:var(--cyan)}
.section-title.violet{color:var(--violet)}
.sit-card{flex:1;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:8px 12px;min-width:0}
.sit-card-label{font-family:'Orbitron',sans-serif;font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--dim);margin-bottom:4px}
.sit-card-value{font-size:14px;line-height:1.5;color:var(--white)}
.sit-card-value strong{font-weight:700}
.sit-risk{border-color:rgba(244,67,54,0.25)}
.sit-watch{border-color:rgba(0,188,212,0.25)}
.watchlist{display:flex;gap:8px;flex:2;overflow-x:auto;padding-bottom:2px}
.watch-card{background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:8px 12px;min-width:200px;max-width:280px;cursor:pointer;transition:border-color 0.3s,background 0.3s,box-shadow 0.3s;flex-shrink:0}
.watch-card:hover{background:rgba(0,188,212,0.06);border-color:rgba(0,188,212,0.3);box-shadow:0 0 8px rgba(0,188,212,0.1)}
.watch-card.highlight{background:rgba(0,188,212,0.1);border-color:rgba(0,188,212,0.5);box-shadow:0 0 12px rgba(0,188,212,0.2)}
.wc-header{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:4px}
.wc-title{font-family:'Orbitron',sans-serif;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase}
.wc-sev{font-family:'Orbitron',sans-serif;font-size:10px;font-weight:900;letter-spacing:1px;padding:2px 6px;border-radius:3px}
.wc-current{font-size:14px;font-weight:700;margin-bottom:3px}
.wc-meaning{font-size:12px;color:var(--dim);margin-bottom:3px;line-height:1.4}
.wc-look{font-size:12px;color:var(--cyan);margin-bottom:2px;line-height:1.3}
.wc-improve{font-size:12px;color:var(--green);font-style:italic;line-height:1.3}
.wc-click-hint{font-size:11px;color:var(--dim);margin-top:4px;text-transform:uppercase;letter-spacing:1px;border-top:1px solid rgba(255,255,255,0.06);padding-top:4px}
.panel-highlight-flash{animation:panelFlash 1.5s ease}
@keyframes panelFlash{0%,100%{box-shadow:none}30%{box-shadow:0 0 20px rgba(0,188,212,0.4),inset 0 0 10px rgba(0,188,212,0.1)}70%{box-shadow:0 0 10px rgba(0,188,212,0.2)}}
.sev-badge{display:inline-block;font-family:'Orbitron',sans-serif;font-size:10px;font-weight:900;letter-spacing:1px;padding:1px 5px;border-radius:3px;vertical-align:middle;margin-left:4px}
.sev-critical{background:rgba(244,67,54,0.25);color:var(--sev-critical);border:1px solid rgba(244,67,54,0.4)}
.sev-severe{background:rgba(233,30,99,0.2);color:var(--sev-severe);border:1px solid rgba(233,30,99,0.35)}
.sev-high{background:rgba(255,152,0,0.2);color:var(--sev-high);border:1px solid rgba(255,152,0,0.35)}
.sev-medium{background:rgba(255,193,7,0.15);color:var(--sev-medium);border:1px solid rgba(255,193,7,0.3)}
.sev-low{background:rgba(76,175,80,0.15);color:var(--sev-low);border:1px solid rgba(76,175,80,0.3)}
.sev-stable{background:rgba(0,188,212,0.15);color:var(--sev-stable);border:1px solid rgba(0,188,212,0.3)}
.sev-calm{background:rgba(129,199,132,0.15);color:var(--sev-calm);border:1px solid rgba(129,199,132,0.3)}
.sev-weak{background:rgba(255,152,0,0.15);color:var(--sev-high);border:1px solid rgba(255,152,0,0.3)}
.sev-fragile{background:rgba(244,67,54,0.15);color:var(--sev-critical);border:1px solid rgba(244,67,54,0.3)}
.sev-unstable{background:rgba(255,152,0,0.2);color:var(--sev-high);border:1px solid rgba(255,152,0,0.35)}
.sev-overheating{background:rgba(233,30,99,0.25);color:var(--sev-severe);border:1px solid rgba(233,30,99,0.4);animation:sevPulse 2s ease infinite}
.sev-hot{background:rgba(255,152,0,0.2);color:var(--sev-high);border:1px solid rgba(255,152,0,0.35)}
.sev-active{background:rgba(255,193,7,0.15);color:var(--sev-medium);border:1px solid rgba(255,193,7,0.3)}
.sev-strong{background:rgba(76,175,80,0.15);color:var(--sev-low);border:1px solid rgba(76,175,80,0.3)}
.sev-safe{background:rgba(76,175,80,0.15);color:var(--sev-low);border:1px solid rgba(76,175,80,0.3)}
.sev-watch{background:rgba(255,193,7,0.15);color:var(--sev-medium);border:1px solid rgba(255,193,7,0.3)}
.sev-normal{background:rgba(129,199,132,0.15);color:var(--sev-calm);border:1px solid rgba(129,199,132,0.3)}
.sev-strange{background:rgba(255,193,7,0.15);color:var(--sev-medium);border:1px solid rgba(255,193,7,0.3)}
.sev-breach{background:rgba(233,30,99,0.25);color:var(--sev-severe);border:1px solid rgba(233,30,99,0.4);animation:sevPulse 2s ease infinite}
@keyframes sevPulse{0%,100%{opacity:0.85}50%{opacity:1}}
.chain-card{background:rgba(206,147,216,0.06);border:1px solid rgba(206,147,216,0.15);border-radius:8px;padding:8px 12px;margin-bottom:8px;cursor:pointer;transition:border-color 0.3s,background 0.3s}
.chain-card:hover{background:rgba(206,147,216,0.1);border-color:rgba(206,147,216,0.3)}
.chain-header{display:flex;align-items:center;justify-content:space-between;gap:8px}
.chain-title{font-family:'Orbitron',sans-serif;font-size:13px;font-weight:700;color:var(--violet);letter-spacing:1px}
.chain-count{font-family:'Orbitron',sans-serif;font-size:16px;font-weight:900;color:var(--violet)}
.chain-meta{display:flex;gap:12px;margin-top:4px;font-size:13px;color:var(--dim);flex-wrap:wrap}
.chain-meta-item{display:flex;align-items:center;gap:4px}
.chain-meta-val{color:var(--white);font-weight:700}
.chain-events{max-height:0;overflow:hidden;transition:max-height 0.4s ease;opacity:0}
.chain-card.expanded .chain-events{max-height:600px;opacity:1;margin-top:8px;padding-top:8px;border-top:1px solid rgba(206,147,216,0.1)}
.chain-event{padding:3px 6px;margin:2px 0;border-radius:3px;font-size:13px;background:rgba(255,255,255,0.02);border-left:2px solid var(--violet)}
.quest-health{background:rgba(255,255,255,0.03);border:1px solid rgba(206,147,216,0.15);border-radius:8px;padding:8px 12px;margin-bottom:10px}
.qh-grid{display:flex;gap:12px;flex-wrap:wrap;margin-top:4px}
.qh-stat{display:flex;flex-direction:column;align-items:center;gap:1px;min-width:50px}
.qh-stat-val{font-family:'Orbitron',sans-serif;font-size:18px;font-weight:900}
.qh-stat-label{font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:1px}
.qh-type-list{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px}
.qh-type-tag{font-size:12px;padding:2px 6px;border-radius:3px;background:rgba(206,147,216,0.1);border:1px solid rgba(206,147,216,0.2);color:var(--violet)}
.raw-toggle{display:flex;align-items:center;gap:6px;padding:6px 10px;margin-top:10px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:6px;cursor:pointer;color:var(--dim);font-size:13px;letter-spacing:1px;text-transform:uppercase;font-family:'Orbitron',sans-serif;font-weight:700;transition:border-color 0.3s,background 0.3s;user-select:none}
.raw-toggle:hover{background:rgba(255,255,255,0.05);border-color:rgba(0,188,212,0.2)}
.raw-toggle::before{content:'\25B8';transition:transform 0.3s}
.raw-toggle.open::before{content:'\25BE'}
.raw-events-wrap{max-height:0;overflow:hidden;transition:max-height 0.4s ease;opacity:0}
.raw-events-wrap.open{max-height:2000px;opacity:1;margin-top:4px}
.intro-box{background:rgba(0,188,212,0.06);border:1px solid rgba(0,188,212,0.15);border-radius:8px;padding:10px 12px;margin-bottom:12px;font-size:13px;line-height:1.5;color:var(--dim)}
.intro-box strong{color:var(--cyan)}
.intro-legend{display:flex;gap:12px;margin-top:8px;flex-wrap:wrap;font-size:13px}
.legend-item{display:flex;align-items:center;gap:4px}
.legend-dot{width:14px;height:14px;border-radius:50%;flex-shrink:0}
.faction-card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:10px 12px;margin-bottom:8px;cursor:pointer;transition:border-color 0.3s,background 0.3s,box-shadow 0.3s}
.faction-card:hover{background:rgba(255,255,255,0.05);border-color:rgba(0,188,212,0.2)}
.faction-card.active{box-shadow:0 0 12px rgba(0,188,212,0.15);border-color:rgba(0,188,212,0.35)}
.faction-header{display:flex;align-items:center;justify-content:space-between;gap:8px}
.faction-name{font-family:'Orbitron',sans-serif;font-size:15px;font-weight:700;letter-spacing:1px}
.faction-power{font-family:'Orbitron',sans-serif;font-size:18px;font-weight:900}
.faction-sub{display:flex;align-items:center;gap:8px;margin-top:6px;font-size:13px}
.faction-cohesion-label{color:var(--dim);font-size:13px;text-transform:uppercase;letter-spacing:1px}
.faction-cohesion-bar{flex:1;height:8px;background:rgba(255,255,255,0.06);border-radius:4px;overflow:hidden}
.faction-cohesion-fill{height:100%;border-radius:4px;transition:width 0.8s ease}
.faction-action{color:var(--dim);font-size:13px;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.faction-stances{display:flex;gap:4px;margin-top:6px;flex-wrap:wrap}
.stance-dot{width:16px;height:16px;border-radius:50%;border:1px solid rgba(255,255,255,0.1);transition:transform 0.2s,box-shadow 0.2s}
.stance-dot:hover{transform:scale(1.5);box-shadow:0 0 6px currentColor}
.stance-dot.ally{background:var(--green);border-color:var(--green)}
.stance-dot.neutral{background:#FFC107;border-color:#FFC107}
.stance-dot.enemy{background:var(--red);border-color:var(--red)}
.faction-detail{max-height:0;overflow:hidden;transition:max-height 0.4s ease,opacity 0.3s ease;opacity:0}
.faction-card.active .faction-detail{max-height:600px;opacity:1}
.detail-stances{margin-top:8px;font-size:13px}
.detail-stance-row{display:flex;align-items:center;gap:8px;padding:2px 0}
.detail-stance-name{color:var(--dim);min-width:140px}
.detail-stance-val{font-weight:700;text-transform:uppercase;font-size:13px;letter-spacing:1px}
.detail-action-history{margin-top:8px;font-size:13px;color:var(--dim)}
.detail-action-item{padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.03)}
.event-feed{display:flex;flex-direction:column;gap:4px}
.event-entry{display:flex;gap:10px;padding:8px 10px;border-radius:6px;border-left:3px solid transparent;background:rgba(255,255,255,0.02);transition:opacity 0.3s;font-size:14px;animation:fadeSlideIn 0.4s ease}
@keyframes fadeSlideIn{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:translateY(0)}}
.event-entry.world{border-left-color:var(--cyan)}
.event-entry.cascade{border-left-color:var(--violet)}
.event-entry.faction-action{border-left-color:var(--amber)}
.event-entry.broadcast{border-left-color:var(--red)}
.event-time{color:var(--dim);font-size:13px;white-space:nowrap;min-width:55px;padding-top:2px}
.event-source{font-size:13px;text-transform:uppercase;letter-spacing:1px;padding:2px 6px;border-radius:3px;white-space:nowrap;align-self:flex-start}
.event-source.world{color:var(--cyan);background:var(--cyan-dim)}
.event-source.cascade{color:var(--violet);background:rgba(206,147,216,0.12)}
.event-source.faction{color:var(--amber);background:var(--amber-dim)}
.event-source.broadcast{color:var(--red);background:var(--red-dim)}
.event-body{flex:1;line-height:1.4}
.event-cascade-depth{font-family:'Orbitron',sans-serif;font-size:13px;color:var(--violet);margin-left:4px}
.npc-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.npc-card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:6px;padding:8px 10px;cursor:pointer;transition:border-color 0.3s,background 0.3s,opacity 0.4s}
.npc-card:hover{background:rgba(255,255,255,0.05);border-color:rgba(0,188,212,0.2)}
.npc-card.active{border-color:rgba(0,188,212,0.4);box-shadow:0 0 8px rgba(0,188,212,0.1)}
.npc-name{font-family:'Orbitron',sans-serif;font-size:14px;font-weight:700;letter-spacing:0.5px;margin-bottom:4px}
.npc-badges{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.npc-mood{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;padding:1px 6px;border-radius:3px}
.npc-decision{font-size:13px;color:var(--dim)}
.npc-affil{width:12px;height:12px;border-radius:50%;flex-shrink:0}
.npc-detail{max-height:0;overflow:hidden;transition:max-height 0.4s ease,opacity 0.3s;opacity:0}
.npc-card.active .npc-detail{max-height:500px;opacity:1;margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.06)}
.npc-detail-section{margin-bottom:6px}
.npc-detail-label{font-size:13px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin-bottom:2px}
.npc-detail-val{font-size:14px;line-height:1.4}
.npc-thought{font-size:13px;color:var(--dim);padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.03);font-style:italic}
.npc-rel{display:inline-block;font-size:13px;padding:1px 5px;margin:1px;border-radius:3px;background:rgba(255,255,255,0.04)}
.bottom-era{font-family:'Orbitron',sans-serif;font-weight:700;font-size:18px;color:var(--amber);white-space:nowrap;text-shadow:var(--glow-amber)}
.bottom-progress{flex:1;display:flex;align-items:center;gap:10px;min-width:200px}
.bottom-progress-label{font-size:13px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;white-space:nowrap}
.bottom-progress-bar{flex:1;height:12px;background:rgba(255,255,255,0.06);border-radius:6px;overflow:hidden;border:1px solid rgba(255,255,255,0.06)}
.bottom-progress-fill{height:100%;border-radius:6px;background:linear-gradient(90deg,var(--cyan),var(--amber));transition:width 1s ease;position:relative}
.bottom-progress-fill::after{content:'';position:absolute;inset:0;background:linear-gradient(180deg,rgba(255,255,255,0.15) 0%,transparent 50%);border-radius:6px}
.bottom-progress-pct{font-family:'Orbitron',sans-serif;font-size:16px;color:var(--cyan);min-width:50px}
.bottom-triggers{display:flex;gap:6px;flex-wrap:nowrap;overflow-x:auto}
.bottom-trigger{font-size:13px;padding:3px 8px;border-radius:4px;background:rgba(206,147,216,0.1);border:1px solid rgba(206,147,216,0.2);color:var(--violet);white-space:nowrap}
.bottom-pending{font-size:14px;color:var(--dim);white-space:nowrap;border-left:1px solid var(--panel-border);padding-left:16px;margin-left:8px}
.bottom-pending strong{color:var(--amber);font-family:'Orbitron',sans-serif;font-size:16px}
.signal-lost{position:absolute;inset:0;background:rgba(4,8,16,0.85);display:flex;align-items:center;justify-content:center;z-index:10;opacity:0;pointer-events:none;transition:opacity 0.5s ease}
.signal-lost.visible{opacity:1;pointer-events:auto}
.signal-lost-text{font-family:'Orbitron',sans-serif;font-size:28px;color:var(--red);letter-spacing:4px;text-transform:uppercase;animation:signalBlink 1.5s ease infinite;text-shadow:0 0 20px rgba(244,67,54,0.5)}
@keyframes signalBlink{0%,100%{opacity:0.6}50%{opacity:1}}
.loading-pulse{animation:loadPulse 1.2s ease infinite}
@keyframes loadPulse{0%,100%{opacity:0.4}50%{opacity:1}}
.starfield{position:fixed;inset:0;z-index:-1;overflow:hidden}
.star{position:absolute;background:#fff;border-radius:50%;animation:twinkle var(--dur) ease infinite var(--delay)}
@keyframes twinkle{0%,100%{opacity:0.2}50%{opacity:0.8}}
.tab-bar{display:flex;gap:2px;margin-bottom:10px;border-bottom:1px solid var(--panel-border);padding-bottom:4px}
.tab-btn{font-family:'Orbitron',sans-serif;font-size:13px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:8px 14px;cursor:pointer;border:1px solid transparent;border-radius:6px 6px 0 0;background:rgba(255,255,255,0.02);color:var(--dim);transition:color 0.2s,background 0.2s,border-color 0.2s;min-width:60px;text-align:center}
.tab-btn:hover{color:var(--white);background:rgba(255,255,255,0.04)}
.tab-btn.active-amber{color:var(--amber);background:var(--amber-dim);border-color:rgba(255,152,0,0.25);border-bottom-color:transparent}
.tab-btn.active-cyan{color:var(--cyan);background:var(--cyan-dim);border-color:rgba(0,188,212,0.25);border-bottom-color:transparent}
.tab-btn.active-violet{color:var(--violet);background:rgba(206,147,216,0.12);border-color:rgba(206,147,216,0.25);border-bottom-color:transparent}
.tab-content{display:none}
.tab-content.visible{display:block}
.quest-log{display:flex;flex-direction:column;gap:4px}
.quest-entry{display:flex;gap:8px;padding:8px 10px;border-radius:6px;border-left:3px solid var(--violet);background:rgba(255,255,255,0.02);font-size:14px;cursor:pointer;transition:background 0.2s}
.quest-entry:hover{background:rgba(255,255,255,0.05)}
.quest-entry.quest-accept{border-left-color:var(--green)}
.quest-entry.quest-progress{border-left-color:var(--cyan)}
.quest-entry.quest-complete{border-left-color:var(--amber)}
.quest-entry.quest-abandon{border-left-color:var(--red)}
.quest-time{color:var(--dim);font-size:13px;white-space:nowrap;min-width:50px;padding-top:2px}
.quest-event{font-size:13px;text-transform:uppercase;letter-spacing:1px;padding:2px 6px;border-radius:3px;white-space:nowrap;align-self:flex-start}
.quest-event.accept{color:var(--green);background:var(--green-dim)}
.quest-event.progress{color:var(--cyan);background:var(--cyan-dim)}
.quest-event.complete{color:var(--amber);background:var(--amber-dim)}
.quest-event.abandon{color:var(--red);background:var(--red-dim)}
.quest-body{flex:1;line-height:1.4}
.quest-detail{background:rgba(255,255,255,0.03);border:1px solid rgba(206,147,216,0.2);border-radius:8px;padding:12px;margin-top:8px;margin-bottom:8px}
.quest-detail-title{font-family:'Orbitron',sans-serif;font-size:14px;font-weight:700;color:var(--violet);margin-bottom:6px}
.quest-detail-desc{font-size:13px;color:var(--dim);margin-bottom:8px;line-height:1.4}
.quest-objective{margin-bottom:6px}
.quest-obj-label{font-size:13px;display:flex;justify-content:space-between;margin-bottom:3px}
.quest-obj-name{color:var(--white)}
.quest-obj-pct{color:var(--cyan);font-family:'Orbitron',sans-serif;font-size:13px}
.quest-obj-bar{height:10px;background:rgba(255,255,255,0.06);border-radius:5px;overflow:hidden}
.quest-obj-fill{height:100%;border-radius:5px;transition:width 0.8s ease}
.quest-obj-fill.done{background:var(--green)}
.quest-reward{font-size:13px;color:var(--amber);margin-top:6px}
.quest-stats{display:flex;gap:12px;margin-top:8px;font-size:14px}
.quest-stat{display:flex;flex-direction:column;align-items:center;gap:1px}
.quest-stat-val{font-family:'Orbitron',sans-serif;font-size:18px;font-weight:900}
.quest-stat-label{font-size:13px;color:var(--dim);text-transform:uppercase;letter-spacing:1px}
.tech-card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:10px 12px;margin-bottom:8px;transition:border-color 0.3s}
.tech-card:hover{border-color:rgba(0,188,212,0.2)}
.tech-header{display:flex;align-items:center;justify-content:space-between;gap:8px}
.tech-faction{font-family:'Orbitron',sans-serif;font-size:14px;font-weight:700;letter-spacing:1px}
.tech-project{font-size:13px;color:var(--cyan);margin-top:4px}
.tech-progress{margin-top:6px}
.tech-progress-label{display:flex;justify-content:space-between;font-size:13px;margin-bottom:3px}
.tech-progress-pct{font-family:'Orbitron',sans-serif;color:var(--amber);font-size:13px}
.tech-progress-bar{height:12px;background:rgba(255,255,255,0.06);border-radius:6px;overflow:hidden;border:1px solid rgba(255,255,255,0.06)}
.tech-progress-fill{height:100%;border-radius:6px;background:linear-gradient(90deg,var(--cyan),var(--amber));transition:width 0.8s ease;position:relative}
.tech-progress-fill::after{content:'';position:absolute;inset:0;background:linear-gradient(180deg,rgba(255,255,255,0.15) 0%,transparent 50%);border-radius:6px}
.tech-meta{display:flex;gap:10px;margin-top:6px;font-size:13px;color:var(--dim);flex-wrap:wrap}
.tech-meta-item{display:flex;align-items:center;gap:4px}
.tech-meta-val{color:var(--white);font-weight:700}
.tech-completed{margin-top:6px;font-size:13px;color:var(--dim)}
.tech-completed-tag{display:inline-block;font-size:13px;padding:2px 6px;margin:2px;border-radius:3px;background:rgba(76,175,80,0.1);border:1px solid rgba(76,175,80,0.2);color:var(--green)}
.tech-no-research{font-size:13px;color:var(--dim);padding:8px 0}
.choice-list{display:flex;flex-direction:column;gap:6px}
.choice-item{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:6px;background:rgba(255,255,255,0.02);cursor:pointer;transition:background 0.2s}
.choice-item:hover{background:rgba(255,255,255,0.05)}
.choice-rank{font-family:'Orbitron',sans-serif;font-size:18px;font-weight:900;color:var(--amber);min-width:30px;text-align:center}
.choice-id{font-size:14px;color:var(--white);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.choice-count{font-family:'Orbitron',sans-serif;font-size:16px;color:var(--cyan);min-width:40px;text-align:right}
.choice-bar-container{width:100%;margin-top:4px}
.choice-bar{height:8px;background:rgba(255,255,255,0.06);border-radius:4px;overflow:hidden}
.choice-bar-fill{height:100%;border-radius:4px;background:var(--violet);transition:width 0.8s ease}
.faction-choice-detail{background:rgba(255,255,255,0.03);border:1px solid rgba(206,147,216,0.2);border-radius:8px;padding:12px;margin-top:8px;margin-bottom:8px}
.faction-choice-title{font-family:'Orbitron',sans-serif;font-size:14px;font-weight:700;color:var(--violet);margin-bottom:6px}
.faction-choice-history{display:flex;flex-direction:column;gap:3px;font-size:13px;color:var(--dim)}
.faction-choice-entry{padding:3px 6px;border-radius:3px;background:rgba(206,147,216,0.06)}
:focus{outline:2px solid var(--cyan);outline-offset:2px}
"""

# Import from part files
import importlib.util


def _load_part(filename, varname):
    """Load a variable from a sibling Python file without importing as a module."""
    spec = importlib.util.spec_from_file_location(
        filename.replace(".py", ""),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), filename),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, varname)


HTML_BODY = _load_part("build_sim_part2_html.py", "HTML_BODY")
JS = _load_part("build_sim_part3_js.py", "JS")

# ═══ ASSEMBLE FINAL HTML ═══

HTML_PREAMBLE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Federation &mdash; Live Simulation</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
"""

CLOSING_STYLE = """
</style>
</head>
<body>
"""

JS_OPEN = """
<script>
"""

JS_CLOSE = """
</script>
</body>
</html>
"""

output = HTML_PREAMBLE + CSS + CLOSING_STYLE + HTML_BODY + JS_OPEN + JS + JS_CLOSE

# Write output
outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "simulation.html")
with open(outpath, "w", encoding="utf-8") as f:
    f.write(output)

print(f"Built simulation.html ({len(output)} chars) -> {outpath}")
