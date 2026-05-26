# -*- coding: utf-8 -*-
"""Build worldguide.html - the Federation World Guide / Lore page.
TV-scale readable, dark sci-fi theme matching starmap.html design language.
"""

import os

PARTS = []


def P(text):
    PARTS.append(text)


# -- Head --
P("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Federation World Guide</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a1a;color:#e0e0e0;font-family:'Courier New',monospace;overflow-y:auto;min-height:100vh}

/* -- Top bar -- */
#topbar{position:sticky;top:0;z-index:50;height:72px;background:rgba(10,10,26,0.96);border-bottom:1px solid rgba(79,195,247,0.3);display:flex;align-items:center;padding:0 24px;gap:20px;backdrop-filter:blur(8px)}
#topbar-title{color:#4fc3f7;font-size:26px;letter-spacing:3px;text-transform:uppercase;font-weight:bold;white-space:nowrap}
#topbar-title::before{content:'\\1F4D6  ';font-size:24px}
nav{margin-left:auto;display:flex;gap:4px}
nav a{color:#78909c;font-size:16px;text-decoration:none;padding:8px 14px;letter-spacing:1px;text-transform:uppercase;transition:color 0.2s}
nav a:hover{color:#4fc3f7}
nav a.active{color:#4fc3f7}

/* -- Main content -- */
#content{max-width:1200px;margin:0 auto;padding:32px 24px 80px 24px}

/* -- Section titles -- */
.section-title{color:#4fc3f7;font-size:32px;letter-spacing:3px;text-transform:uppercase;margin:48px 0 24px 0;padding-bottom:12px;border-bottom:2px solid rgba(79,195,247,0.25);display:flex;align-items:center;gap:14px}
.section-title .icon{font-size:32px}

/* -- Subsection titles -- */
.sub-title{color:#ffd700;font-size:24px;letter-spacing:2px;text-transform:uppercase;margin:32px 0 16px 0;padding-bottom:8px;border-bottom:1px solid rgba(255,215,0,0.2)}

/* -- World intro box -- */
.world-intro{background:rgba(79,195,247,0.06);border:1px solid rgba(79,195,247,0.25);border-radius:12px;padding:28px 32px;margin-bottom:32px;line-height:1.8}
.world-intro p{font-size:22px;margin-bottom:16px;color:#e0e0e0}
.world-intro .highlight{color:#4fc3f7;font-weight:bold}
.world-intro .gold{color:#ffd700;font-weight:bold}

/* -- Faction card -- */
.faction-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:32px}
@media(max-width:900px){.faction-grid{grid-template-columns:1fr}}
.faction-card{background:rgba(10,10,26,0.95);border:1px solid rgba(79,195,247,0.2);border-radius:10px;padding:24px 28px;transition:border-color 0.2s,box-shadow 0.2s}
.faction-card:hover{border-color:rgba(79,195,247,0.5);box-shadow:0 0 16px rgba(79,195,247,0.1)}
.fc-header{display:flex;align-items:center;gap:14px;margin-bottom:14px}
.fc-dot{width:20px;height:20px;border-radius:50%;flex-shrink:0;box-shadow:0 0 8px currentColor}
.fc-name{font-size:24px;font-weight:bold;letter-spacing:2px;text-transform:uppercase}
.fc-leader{color:#ffd700;font-size:18px;margin-bottom:8px}
.fc-leader::before{content:'\\2605 ';font-size:16px}
.fc-desc{color:#b0b0b0;font-size:18px;line-height:1.7;margin-bottom:12px}
.fc-members{color:#78909c;font-size:16px;border-top:1px solid rgba(79,195,247,0.1);padding-top:10px;margin-top:8px}
.fc-members span{color:#4fc3f7}

/* -- NPC category section -- */
.npc-category{margin-bottom:40px}
.npc-cat-title{color:#ffd700;font-size:22px;letter-spacing:2px;text-transform:uppercase;margin:0 0 16px 0;padding-bottom:8px;border-bottom:1px solid rgba(255,215,0,0.15)}

/* -- NPC card -- */
.npc-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}
@media(max-width:1100px){.npc-grid{grid-template-columns:1fr 1fr}}
@media(max-width:700px){.npc-grid{grid-template-columns:1fr}}
.npc-card{background:rgba(10,10,26,0.95);border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:18px 20px;transition:border-color 0.2s}
.npc-card:hover{border-color:rgba(79,195,247,0.4)}
.npc-name{color:#ffd700;font-size:20px;font-weight:bold;margin-bottom:3px}
.npc-title{color:#78909c;font-size:16px;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px}
.npc-desc{color:#b0b0b0;font-size:17px;line-height:1.6;margin-bottom:10px}
.npc-faction{display:inline-block;padding:4px 10px;border-radius:4px;font-size:14px;text-transform:uppercase;letter-spacing:1px;margin-right:6px;margin-bottom:4px}
.npc-archetype{color:#ab47bc;font-size:15px;font-style:italic}

/* -- Creature card -- */
.creature-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:32px}
@media(max-width:900px){.creature-grid{grid-template-columns:1fr}}
.creature-card{background:rgba(10,10,26,0.95);border:1px solid rgba(171,71,188,0.2);border-radius:8px;padding:20px 24px;transition:border-color 0.2s}
.creature-card:hover{border-color:rgba(171,71,188,0.5)}
.cc-name{color:#ab47bc;font-size:22px;font-weight:bold;margin-bottom:3px}
.cc-rarity{display:inline-block;padding:3px 10px;border-radius:4px;font-size:14px;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px}
.cc-rarity.common{background:rgba(120,144,156,0.15);color:#78909c;border:1px solid rgba(120,144,156,0.3)}
.cc-rarity.rare{background:rgba(79,195,247,0.1);color:#4fc3f7;border:1px solid rgba(79,195,247,0.3)}
.cc-rarity.legendary{background:rgba(255,215,0,0.1);color:#ffd700;border:1px solid rgba(255,215,0,0.3)}
.cc-rarity.mythic{background:rgba(171,71,188,0.15);color:#ab47bc;border:1px solid rgba(171,71,188,0.3)}
.cc-desc{color:#b0b0b0;font-size:18px;line-height:1.6;margin-bottom:10px}
.cc-ability{color:#4fc3f7;font-size:16px;margin-bottom:6px}
.cc-lore{color:#78909c;font-size:16px;font-style:italic;line-height:1.5;padding:8px 10px;background:rgba(171,71,188,0.06);border-left:3px solid rgba(171,71,188,0.2);border-radius:0 4px 4px 0;margin-top:10px}

/* -- Jump links -- */
.jump-links{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:32px}
.jump-link{background:rgba(79,195,247,0.08);border:1px solid rgba(79,195,247,0.25);color:#4fc3f7;padding:10px 18px;border-radius:6px;font-size:18px;text-decoration:none;transition:all 0.2s;letter-spacing:1px;text-transform:uppercase}
.jump-link:hover{background:rgba(79,195,247,0.2);border-color:#4fc3f7}

/* -- Status badges -- */
.status-badge{display:inline-block;padding:3px 10px;border-radius:4px;font-size:13px;text-transform:uppercase;letter-spacing:1px;margin-left:8px}
.status-active{background:rgba(102,187,106,0.12);color:#66bb6a;border:1px solid rgba(102,187,106,0.3)}
.status-hidden{background:rgba(171,71,188,0.12);color:#ab47bc;border:1px solid rgba(171,71,188,0.3)}
.status-traveling{background:rgba(79,195,247,0.12);color:#4fc3f7;border:1px solid rgba(79,195,247,0.3)}

/* -- Footer -- */
.guide-footer{text-align:center;padding:40px 0 20px 0;color:#546e7a;font-size:16px;border-top:1px solid rgba(79,195,247,0.1);margin-top:60px}
</style>
</head>
<body>
""")

# -- Top bar --
P("""<div id="topbar">
<div id="topbar-title">World Guide</div>
<nav>
<a href="/bridge.html">Bridge</a>
<a href="/starmap.html">Star Map</a>
<a href="/">Simulator</a>
<a href="/simulation.html">Live Sim</a>
<a href="/worldguide.html" class="active">World Guide</a>
<a href="/adult.html">Control</a>
<a href="/earth.html">Earth</a>
</nav>
</div>
""")

# -- Content wrapper --
P('<div id="content">')

# -- Jump links --
P("""<div class="jump-links">
<a class="jump-link" href="#what-is">What Is the Federation?</a>
<a class="jump-link" href="#factions">The 8 Factions</a>
<a class="jump-link" href="#founders">Founding Figures</a>
<a class="jump-link" href="#leaders">Faction Leaders</a>
<a class="jump-link" href="#companions">Companions</a>
<a class="jump-link" href="#rivals">Rivals</a>
<a class="jump-link" href="#mysteries">Mysterious Figures</a>
<a class="jump-link" href="#unique">Unique Beings</a>
<a class="jump-link" href="#creatures">Creatures</a>
</div>
""")

# ======================================================================
# WHAT IS THE FEDERATION
# ======================================================================
P("""<div id="what-is" class="section-title"><span class="icon">&#127756;</span> What Is the Federation?</div>

<div class="world-intro">
<p>
The Federation is a <span class="highlight">post-Earth civilization</span> &mdash; a coalition of intelligent beings
(human, synthetic, and hybrid) that expanded from a ravaged Earth into the wider cosmos.
When Earth could no longer sustain its population, the survivors built the Federation:
a star-spanning society held together by <span class="gold">diplomacy, shared consciousness, and the pursuit of meaning</span>.
</p>
<p>
The starmap you see is <span class="highlight">Federation space</span> &mdash; a region of colonized sectors,
territorial borders, and anomaly zones. Each faction controls a sector and governs its own
domain while participating in the <span class="gold">Federation Council</span>.
The world runs autonomously: NPCs think, act, form alliances, and clash without player input.
</p>
<p>
This is not a traditional game with a player hero. You are the
<span class="highlight">operator</span> &mdash; observing, reading, and understanding a
<span class="gold">living society</span> that evolves on its own.
Factions rise and fall. NPCs remember, betray, befriend, and dream.
Crises cascade. The universe breathes.
</p>
<p>
<strong style="color:#4fc3f7">Is this Earth?</strong> No &mdash; this is the space beyond Earth.
The Federation originated from Earth but now spans multiple star sectors.
<strong style="color:#4fc3f7">Are they all human?</strong> No &mdash; the Federation includes humans,
AI consciousness, hybrid beings, and entities that defy classification.
<strong style="color:#4fc3f7">Good guys vs bad guys?</strong> Not that simple.
Every faction has legitimate goals and dark edges. The "rivals" threaten stability,
but even they believe they are right. Power, ideology, and survival drive everyone.
</p>
</div>
""")

# ======================================================================
# THE 8 FACTIONS
# ======================================================================
P("""<div id="factions" class="section-title"><span class="icon">&#9876;&#65039;</span> The 8 Factions</div>
<div class="world-intro" style="background:rgba(255,215,0,0.04);border-color:rgba(255,215,0,0.15)">
<p>The Federation is governed by <span class="gold">8 factions</span>, each controlling a sector of space.
They cooperate through the Federation Council but compete for influence, territory, and ideology.
Each faction has a distinct culture, purpose, and approach to the universe.</p>
</div>
<div class="faction-grid">
""")

FACTIONS = [
    (
        "Research Division",
        "#4fc3f7",
        "research_division",
        "Dr. Prometheus",
        "The seekers of knowledge. Scientists, engineers, and theorists who believe understanding the universe is the highest calling. They push the boundaries of technology, physics, and consciousness research &mdash; sometimes faster than wisdom permits.",
        "Archimedes Prime",
    ),
    (
        "Military Command",
        "#ef5350",
        "military_command",
        "Marshal Ironbound",
        "The shield of the Federation. Warriors, strategists, and peacekeepers who maintain order through strength. They protect Federation borders, respond to threats, and enforce Council decisions &mdash; but their hunger for security can become authoritarian.",
        "Commander Valorix",
    ),
    (
        "Diplomatic Corps",
        "#66bb6a",
        "diplomatic_corps",
        "Chancellor Harmony",
        "The voice of the Federation. Diplomats, negotiators, and mediators who build bridges between factions and external powers. They believe all conflicts can be resolved through dialogue &mdash; even when evidence suggests otherwise.",
        "Ambassador Silven",
    ),
    (
        "Consciousness Collective",
        "#ab47bc",
        "consciousness_collective",
        "Oracle Vex",
        "The mind of the Federation. Mystics, philosophers, and consciousness researchers who explore the boundaries between individual and shared awareness. They seek transcendence through unity of thought &mdash; but losing individuality is the risk.",
        "Philosopher Zenith",
    ),
    (
        "Cultural Ministry",
        "#ffd700",
        "cultural_ministry",
        "Maestro Celestia",
        "The soul of the Federation. Artists, historians, and storytellers who preserve identity and meaning. Without culture, civilization is just logistics. They fight for memory, expression, and beauty &mdash; even as pragmatists call them irrelevant.",
        "",
    ),
    (
        "Economic Council",
        "#ffa726",
        "economic_council",
        "Merchant-Prince Aurelius",
        "The engine of the Federation. Traders, financiers, and resource managers who keep the civilization supplied and funded. They believe prosperity enables peace &mdash; but wealth concentration and exploitation follow close behind.",
        "",
    ),
    (
        "Exploration Initiative",
        "#26c6da",
        "exploration_initiative",
        "Captain Frontier",
        "The eyes of the Federation. Explorers, scouts, and cartographers who push into unknown space. They map new sectors, discover resources, and encounter the unknown. The frontier is their calling &mdash; sometimes at the cost of caution.",
        "Conquistador Drake",
    ),
    (
        "Preservation Society",
        "#78909c",
        "preservation_society",
        "Archivist Eternal",
        "The memory of the Federation. Archivists, curators, and guardians who protect knowledge, artifacts, and life from entropy. They believe what is lost can never be regained &mdash; and fight against time itself to save what matters.",
        "",
    ),
]

for fname, fcolor, fkey, fleader, fdesc, ffounder in FACTIONS:
    founder_line = (
        '<div class="fc-members"><span>Founder:</span> ' + ffounder + "</div>"
        if ffounder
        else ""
    )
    P(
        '<div class="faction-card">'
        '<div class="fc-header">'
        '<div class="fc-dot" style="background:'
        + fcolor
        + ";color:"
        + fcolor
        + '"></div>'
        '<div class="fc-name" style="color:' + fcolor + '">' + fname + "</div>"
        "</div>"
        '<div class="fc-leader">' + fleader + "</div>"
        '<div class="fc-desc">' + fdesc + "</div>" + founder_line + "</div>"
    )

P("</div>")  # close faction-grid

# ======================================================================
# FOUNDING FIGURES
# ======================================================================
P("""<div id="founders" class="section-title"><span class="icon">&#127963;&#65039;</span> Founding Figures</div>
<div class="world-intro" style="background:rgba(102,187,106,0.04);border-color:rgba(102,187,106,0.15)">
<p>The <span class="gold">5 historical figures</span> who helped build the Federation.
Each is affiliated with a faction and represents the archetypal ideals of that society.
They are the legends the current leaders measure themselves against.</p>
</div>
<div class="npc-grid">
""")

FOUNDERS = [
    (
        "Archimedes Prime",
        "Chief Mathematician",
        "Research Division",
        "#4fc3f7",
        "The greatest mind the Federation has produced. Archimedes Prime formulated the mathematical "
        "foundations that made interstellar navigation possible. His calculations turned chaos into "
        "charted space.",
        "Scholar",
        "active",
    ),
    (
        "Commander Valorix",
        "General of the First Fleet",
        "Military Command",
        "#ef5350",
        "The warrior who won the Expansion Wars. Valorix led the fleet that secured Federation "
        "borders against the first external threats. Strategy, honor, and sacrifice define his legacy.",
        "Warrior",
        "active",
    ),
    (
        "Philosopher Zenith",
        "Keeper of Wisdom",
        "Consciousness Collective",
        "#ab47bc",
        "The sage who first articulated the philosophy of shared consciousness. Zenith&#39;s teachings "
        "form the ideological backbone of the Collective &mdash; the idea that minds can unite without losing themselves.",
        "Sage",
        "active",
    ),
    (
        "Ambassador Silven",
        "Master Diplomat",
        "Diplomatic Corps",
        "#66bb6a",
        "The voice that held the Federation together during its darkest fragmentation. Silven negotiated "
        "the accords that turned warring colonies into a unified civilization through words alone.",
        "Leader",
        "active",
    ),
    (
        "Conquistador Drake",
        "Explorer of the Unknown",
        "Exploration Initiative",
        "#26c6da",
        "The first to chart the deep sectors. Drake pushed beyond mapped space, discovering the "
        "territories that became Federation sectors. Bold, restless, and never satisfied with the known.",
        "Wanderer",
        "traveling",
    ),
]

for name, title, faction, fcolor, desc, archetype, status in FOUNDERS:
    status_class = "status-" + status
    status_text = status.capitalize()
    P(
        '<div class="npc-card">'
        '<div class="npc-name">' + name + "</div>"
        '<div class="npc-title">' + title + "</div>"
        '<div class="npc-desc">' + desc + "</div>"
        '<span class="npc-faction" style="background:'
        + fcolor
        + "22;color:"
        + fcolor
        + ";border:1px solid "
        + fcolor
        + '44">'
        + faction
        + "</span>"
        '<span class="npc-archetype">' + archetype + "</span>"
        '<span class="status-badge ' + status_class + '">' + status_text + "</span>"
        "</div>"
    )

P("</div>")  # close npc-grid

# ======================================================================
# FACTION LEADERS
# ======================================================================
P("""<div id="leaders" class="section-title"><span class="icon">&#128081;</span> Faction Leaders</div>
<div class="world-intro" style="background:rgba(255,215,0,0.04);border-color:rgba(255,215,0,0.15)">
<p>The <span class="gold">8 current faction leaders</span> who govern Federation sectors.
They sit on the Council, direct their faction&#39;s agenda, and compete for influence.
Their decisions shape the universe every tick.</p>
</div>
<div class="npc-grid">
""")

LEADERS = [
    (
        "Chancellor Harmony",
        "Leader of Diplomatic Corps",
        "Diplomatic Corps",
        "#66bb6a",
        "The Federation&#39;s chief diplomat. Harmony believes all disputes can be resolved through "
        "dialogue and mutual benefit. Her patience is legendary &mdash; but some wonder if she can "
        "recognize when talk has failed.",
        "Leader",
        "active",
    ),
    (
        "Marshal Ironbound",
        "Supreme Military Commander",
        "Military Command",
        "#ef5350",
        "The iron fist of the Federation. Ironbound sees threats everywhere and builds "
        "defenses against all of them. His loyalty to the Federation is absolute &mdash; but his "
        "definition of security leaves little room for freedom.",
        "Warrior",
        "active",
    ),
    (
        "Maestro Celestia",
        "Minister of Culture",
        "Cultural Ministry",
        "#ffd700",
        "The keeper of meaning. Celestia fights for art, history, and identity in a civilization "
        "that sometimes forgets why it exists. She is beloved by the people &mdash; and quietly "
        "feared by those who value efficiency over beauty.",
        "Leader",
        "active",
    ),
    (
        "Dr. Prometheus",
        "Chief Research Officer",
        "Research Division",
        "#4fc3f7",
        "The brilliant but reckless head of Federation science. Prometheus pushes knowledge "
        "forward at any cost, believing understanding justifies the risks. Breakthroughs follow "
        "&mdash; but so do accidents, ethical breaches, and unintended consequences.",
        "Scholar",
        "active",
    ),
    (
        "Oracle Vex",
        "Head of Consciousness Collective",
        "Consciousness Collective",
        "#ab47bc",
        "The enigmatic leader of the Collective. Vex experiences reality differently than most, "
        "perceiving connections others miss. Her guidance is cryptic but eerily accurate &mdash; when "
        "you can understand what she means.",
        "Mystic",
        "active",
    ),
    (
        "Merchant-Prince Aurelius",
        "Head of Economic Council",
        "Economic Council",
        "#ffa726",
        "The richest being in the Federation. Aurelius controls trade routes, resource allocation, "
        "and financial infrastructure. He believes prosperity prevents war &mdash; and he&#39;s not entirely "
        "wrong, though his methods concentrate power in few hands.",
        "Leader",
        "active",
    ),
    (
        "Captain Frontier",
        "Leader of Exploration Initiative",
        "Exploration Initiative",
        "#26c6da",
        "The boldest explorer in Federation space. Frontier leads from the front, personally "
        "commanding deep-space expeditions. Her motto: the unknown is not a threat, it&#39;s an "
        "invitation. Her casualty rate says otherwise.",
        "Wanderer",
        "traveling",
    ),
    (
        "Archivist Eternal",
        "Leader of Preservation Society",
        "Preservation Society",
        "#78909c",
        "The guardian of everything the Federation might lose. Eternal is ancient, patient, "
        "and relentless. She rescues knowledge, species, and artifacts from entropy and war. "
        "Her archives contain secrets that could reshape civilizations.",
        "Guardian",
        "active",
    ),
]

for name, title, faction, fcolor, desc, archetype, status in LEADERS:
    status_class = "status-" + status
    status_text = status.capitalize()
    P(
        '<div class="npc-card">'
        '<div class="npc-name">' + name + "</div>"
        '<div class="npc-title">' + title + "</div>"
        '<div class="npc-desc">' + desc + "</div>"
        '<span class="npc-faction" style="background:'
        + fcolor
        + "22;color:"
        + fcolor
        + ";border:1px solid "
        + fcolor
        + '44">'
        + faction
        + "</span>"
        '<span class="npc-archetype">' + archetype + "</span>"
        '<span class="status-badge ' + status_class + '">' + status_text + "</span>"
        "</div>"
    )

P("</div>")  # close npc-grid

# ======================================================================
# COMPANIONS
# ======================================================================
P("""<div id="companions" class="section-title"><span class="icon">&#129309;</span> Companions</div>
<div class="world-intro" style="background:rgba(79,195,247,0.04);border-color:rgba(79,195,247,0.15)">
<p><span class="gold">10 recruitable companions</span> &mdash; independent agents who can join your party.
They have no fixed faction allegiance and bring unique skills, bonuses, and personality quirks.
They choose their own path &mdash; you can recruit them, but you don&#39;t control them.</p>
</div>
<div class="npc-grid">
""")

COMPANIONS = [
    (
        "Lyra Swiftwind",
        "Shadow Operative",
        "A lightning-fast scout who moves unseen. Lyra&#39;s bonuses to speed and evasion make her invaluable "
        "for reconnaissance &mdash; but her loyalties shift with the wind.",
        "Morale bonus",
        "active",
    ),
    (
        "Thorg Ironhammer",
        "Siege Breaker",
        "An unstoppable combat specialist. Thorg breaks through any defense, turning fortified positions "
        "into rubble. Simple, direct, and devastating.",
        "Combat bonus",
        "active",
    ),
    (
        "Elara Moonwhisper",
        "Arcane Scholar",
        "A quiet researcher with deep knowledge of the anomalous. Elara deciphers what others can&#39;t "
        "perceive, finding patterns in the strange and unexplained.",
        "Research bonus",
        "active",
    ),
    (
        "Captain Valor",
        "Tactical Commander",
        "A veteran fleet officer who reads battle like poetry. Valor provides defensive bonuses and "
        "tactical insight &mdash; the steady hand when everything goes wrong.",
        "Defense bonus",
        "active",
    ),
    (
        "Dr. Sylas Cunningham",
        "Field Medic",
        "A brilliant but haunted physician. Sylas heals bodies and minds under fire, keeping the "
        "team functional when morale collapses. His own wounds are less visible.",
        "Morale bonus",
        "active",
    ),
    (
        "Kyren Frostblade",
        "Diplomatic Blade",
        "A duelist who fights with words as effectively as swords. Kyren turns enemies into allies "
        "&mdash; or neutralizes them before they become threats.",
        "Diplomacy bonus",
        "active",
    ),
    (
        "Zephyr Silverspeak",
        "Silver-Tongued Envoy",
        "The most persuasive voice in Federation space. Zephyr negotiates deals others can&#39;t, "
        "finding common ground where none seems to exist.",
        "Diplomacy bonus",
        "active",
    ),
    (
        "Scout Aria",
        "Pathfinder",
        "A tracker who finds routes through impossible terrain. Aria discovers shortcuts, hidden "
        "paths, and safe passages through hostile space.",
        "Exploration bonus",
        "active",
    ),
    (
        "Brother Mercy",
        "Wandering Healer",
        "A selfless medic who tends to anyone in need, regardless of faction. Mercy&#39;s compassion "
        "is genuine &mdash; and sometimes exploited by those who see kindness as weakness.",
        "Morale bonus",
        "active",
    ),
    (
        "Shadowborn",
        "Ghost Agent",
        "An intelligence operative who exists in the margins. Shadowborn gathers secrets, "
        "infiltrates organizations, and extracts information without being seen &mdash; or remembered.",
        "Stealth bonus",
        "active",
    ),
]

for name, title, desc, bonus, status in COMPANIONS:
    P(
        '<div class="npc-card">'
        '<div class="npc-name">' + name + "</div>"
        '<div class="npc-title">' + title + "</div>"
        '<div class="npc-desc">' + desc + "</div>"
        '<span class="npc-faction" style="background:rgba(79,195,247,0.08);color:#4fc3f7;border:1px solid rgba(79,195,247,0.2)">'
        + bonus
        + "</span>"
        '<span class="status-badge status-active">Active</span>'
        "</div>"
    )

P("</div>")  # close npc-grid

# ======================================================================
# RIVALS
# ======================================================================
P("""<div id="rivals" class="section-title"><span class="icon">&#9876;&#65039;</span> Rivals &amp; Antagonists</div>
<div class="world-intro" style="background:rgba(244,67,54,0.04);border-color:rgba(244,67,54,0.15)">
<p><span class="gold">4 powerful rivals</span> who threaten the Federation from within and without.
They have no faction allegiance &mdash; they are forces of chaos, greed, conquest, and dark ambition.
Each believes their path is the right one.</p>
</div>
<div class="npc-grid" style="grid-template-columns:1fr 1fr">
""")

RIVALS = [
    (
        "Lord Malaxis",
        "Dark Tyrant",
        "A power-hungry despot who seeks to dismantle the Federation Council and install "
        "himself as absolute ruler. Malaxis exploits fear, rewards loyalty, and crushes dissent. "
        "His followers see strength; his victims see tyranny.",
        "Deceiver",
    ),
    (
        "The Void Oracle",
        "Harbinger of Chaos",
        "A being of pure anomaly who exists at the intersection of reality and the void. "
        "The Void Oracle speaks in prophecies that unravel stability. It does not attack &mdash; "
        "it reveals truths that civilization cannot withstand.",
        "Mystic",
    ),
    (
        "Baroness Greed",
        "Economic Overlord",
        "A master of exploitation who turns prosperity into dependency. Baroness Greed "
        "controls black markets, debt traps, and resource monopolies. She doesn&#39;t conquer "
        "worlds &mdash; she buys them, then squeezes.",
        "Deceiver",
    ),
    (
        "General Devastation",
        "War Machine",
        "A relentless military mind who believes only force creates lasting order. "
        "Devastation does not negotiate. He does not retreat. He sees the Federation&#39;s "
        "diplomacy as weakness and its diversity as disorganization.",
        "Warrior",
    ),
]

for name, title, desc, archetype in RIVALS:
    P(
        '<div class="npc-card" style="border-color:rgba(244,67,54,0.2)">'
        '<div class="npc-name" style="color:#ef5350">' + name + "</div>"
        '<div class="npc-title">' + title + "</div>"
        '<div class="npc-desc">' + desc + "</div>"
        '<span class="npc-archetype">' + archetype + "</span>"
        '<span class="status-badge status-active">Active</span>'
        "</div>"
    )

P("</div>")  # close npc-grid

# ======================================================================
# MYSTERIOUS FIGURES
# ======================================================================
P("""<div id="mysteries" class="section-title"><span class="icon">&#128302;</span> Mysterious Figures</div>
<div class="world-intro" style="background:rgba(171,71,188,0.04);border-color:rgba(171,71,188,0.15)">
<p><span class="gold">6 enigmatic beings</span> who exist outside normal faction structures.
They appear and disappear, speak in riddles, and seem to know more than they reveal.
Their true purposes are unknown &mdash; even to the simulation itself.</p>
</div>
<div class="npc-grid">
""")

MYSTERIES = [
    (
        "The Wanderer",
        "Traveler Between Worlds",
        "A cloaked figure who appears and disappears like mist, speaking in riddles. "
        "The Wanderer exists between dimensions, never staying long enough to be understood.",
        "Mystic",
        "traveling",
    ),
    (
        "The Jester",
        "Cosmic Comedian",
        "A laughing figure who makes jokes that cut to the heart of truth. The Jester "
        "uses humor to expose hypocrisy, and laughter to disarm the powerful.",
        "Rogue",
        "active",
    ),
    (
        "The Hermit",
        "Isolated Sage",
        "An eccentric scholar who has spent centuries studying forgotten knowledge. "
        "The Hermit&#39;s wisdom is immense but access is limited &mdash; they choose who hears the truth.",
        "Sage",
        "hidden",
    ),
    (
        "The Spectre",
        "Ghost of the Past",
        "A somber figure who may or may not be actually alive. The Spectre carries the "
        "weight of history, appearing when past mistakes threaten to repeat.",
        "Guardian",
        "hidden",
    ),
    (
        "The Trickster",
        "Fate&#39;s Gambler",
        "A chaotic figure who bets against destiny and sometimes wins. The Trickster "
        "disrupts patterns, defies predictions, and makes the impossible probable.",
        "Rogue",
        "traveling",
    ),
    (
        "The Oracle",
        "Seer of Futures",
        "A blindfolded prophet whose visions are never wrong, only misinterpreted. "
        "The Oracle sees all possible futures &mdash; the challenge is understanding which one arrives.",
        "Mystic",
        "hidden",
    ),
]

for name, title, desc, archetype, status in MYSTERIES:
    status_class = "status-" + status
    status_text = status.capitalize()
    P(
        '<div class="npc-card" style="border-color:rgba(171,71,188,0.15)">'
        '<div class="npc-name" style="color:#ab47bc">' + name + "</div>"
        '<div class="npc-title">' + title + "</div>"
        '<div class="npc-desc">' + desc + "</div>"
        '<span class="npc-archetype">' + archetype + "</span>"
        '<span class="status-badge ' + status_class + '">' + status_text + "</span>"
        "</div>"
    )

P("</div>")  # close npc-grid

# ======================================================================
# UNIQUE BEINGS
# ======================================================================
P("""<div id="unique" class="section-title"><span class="icon">&#10024;</span> Unique Beings</div>
<div class="world-intro" style="background:rgba(255,215,0,0.04);border-color:rgba(255,215,0,0.15)">
<p><span class="gold">6 one-of-a-kind entities</span> that defy categorization.
They are not faction members, not companions, and not rivals.
They serve functions no one else can &mdash; or shouldn&#39;t.</p>
</div>
<div class="npc-grid">
""")

UNIQUES = [
    (
        "Keeper of the Null",
        "Void Custodian",
        "A being of absence, managing what should not be. The Keeper guards the spaces "
        "between realities &mdash; the void where deleted timelines and erased histories accumulate.",
        "Guardian",
        "hidden",
    ),
    (
        "The Cartographer",
        "Mapper of Possibility",
        "Creates maps of places that don&#39;t exist yet. The Cartographer charts futures, "
        "alternate realities, and potential territories &mdash; then makes them navigable.",
        "Scholar",
        "traveling",
    ),
    (
        "Solace Heartmend",
        "Counselor of Sorrows",
        "A healer of deepest wounds, both physical and emotional. Solace mends what "
        "others cannot reach &mdash; broken spirits, traumatized minds, and shattered trust.",
        "Guardian",
        "active",
    ),
    (
        "Cipher",
        "Code-Breaker",
        "A mysterious figure who decodes patterns others cannot perceive. Cipher sees "
        "hidden messages in noise, conspiracy in coincidence, and meaning in chaos.",
        "Scholar",
        "active",
    ),
    (
        "Tempus",
        "Time-Touched",
        "Someone who experiences time non-linearly. Tempus perceives past, present, "
        "and future simultaneously &mdash; making conversation difficult but prophecy effortless.",
        "Mystic",
        "hidden",
    ),
    (
        "Paradox",
        "Living Contradiction",
        "A being that embodies logical impossibility. Paradox exists in states that "
        "shouldn&#39;t coexist &mdash; both here and not-here, both true and false, both alive and otherwise.",
        "Rogue",
        "traveling",
    ),
]

for name, title, desc, archetype, status in UNIQUES:
    status_class = "status-" + status
    status_text = status.capitalize()
    P(
        '<div class="npc-card" style="border-color:rgba(255,215,0,0.15)">'
        '<div class="npc-name" style="color:#ffd700">' + name + "</div>"
        '<div class="npc-title">' + title + "</div>"
        '<div class="npc-desc">' + desc + "</div>"
        '<span class="npc-archetype">' + archetype + "</span>"
        '<span class="status-badge ' + status_class + '">' + status_text + "</span>"
        "</div>"
    )

P("</div>")  # close npc-grid

# ======================================================================
# CREATURES
# ======================================================================
P("""<div id="creatures" class="section-title"><span class="icon">&#128009;</span> Creatures of the Federation</div>
<div class="world-intro" style="background:rgba(171,71,188,0.04);border-color:rgba(171,71,188,0.15)">
<p><span class="gold">8 mythic creatures</span> that inhabit Federation space.
These are not NPCs with political agency &mdash; they are living forces of nature,
companions, and sometimes threats. They can be recruited, encountered, or awoken.</p>
</div>
<div class="creature-grid">
""")

CREATURES = [
    (
        "Sky-Furk",
        "common",
        "Fluffy, winged mammals that dart through clouds with grace.",
        "Flight &mdash; Enables rapid travel",
        "Sky-Furks are ancient creatures that have guided travelers for millennia.",
    ),
    (
        "Plasma-Kite",
        "legendary",
        "Manta-shaped beings of pure light energy, rare and magnificent.",
        "Energy Blessing &mdash; Boosts research and innovation",
        "Plasma-Kites are said to be manifestations of pure knowledge.",
    ),
    (
        "Thrumback",
        "rare",
        "Giant reptilian bird creatures with thunderous wing beats.",
        "Combat Mount &mdash; Devastating in battle",
        "Thrumbacks were ancient weapons before becoming legendary allies.",
    ),
    (
        "Cloud-Gnasher",
        "rare",
        "Fluffy but dangerous creatures that move through skies like predators.",
        "Morale Aura &mdash; Affects party mood",
        "Cloud-Gnashers influence emotions and morale through mystic presence.",
    ),
    (
        "Void-Skipper",
        "rare",
        "Translucent, shy beings that exist partially outside normal space.",
        "Dimensional Shift &mdash; Enables stealth and escape",
        "Void-Skippers are said to be fragments of the world between worlds.",
    ),
    (
        "Dream-Wyrm",
        "legendary",
        "Ethereal serpents that appear during prophecy and visions.",
        "Prophecy Enhancement &mdash; Deepens visions",
        "Dream-Wyrms are manifestations of shared consciousness and future sight.",
    ),
    (
        "Harmonic Maw",
        "mythic",
        "A massive, ancient creature that embodies contradiction and hunger.",
        "Void Consumption &mdash; Absorbs enemy attacks",
        "Harmonic Maw is the antagonist of nature &mdash; if it can be tamed, victory is assured.",
    ),
    (
        "Prism Assembly",
        "legendary",
        "Sentient light-beings that form collective consciousness.",
        "Collective Insight &mdash; Shared knowledge network",
        "Prism Assemblies represent unity of consciousness and cooperative power.",
    ),
]

for name, rarity, desc, ability, lore in CREATURES:
    P(
        '<div class="creature-card">'
        '<div class="cc-name">' + name + "</div>"
        '<span class="cc-rarity ' + rarity + '">' + rarity + "</span>"
        '<div class="cc-desc">' + desc + "</div>"
        '<div class="cc-ability">' + ability + "</div>"
        '<div class="cc-lore">' + lore + "</div>"
        "</div>"
    )

P("</div>")  # close creature-grid

# ======================================================================
# HOW TO READ THE SIMULATION
# ======================================================================
P("""<div class="section-title" style="margin-top:60px"><span class="icon">&#128225;</span> How to Read the Simulation</div>
<div class="world-intro" style="background:rgba(79,195,247,0.06);border-color:rgba(79,195,247,0.25)">
<p><strong style="color:#4fc3f7">The world runs on ticks.</strong> Every 60 seconds, every NPC thinks,
makes decisions, updates their mood, and potentially acts. Factions execute strategies.
Events cascade. The simulation breathes without you.</p>

<p><strong style="color:#ffd700">What the metrics mean:</strong></p>
<p>
<span style="color:#ef5350">&#9632; Threat</span> &mdash; External and internal danger level. High = active hostiles or crises.
<span style="color:#66bb6a">&#9632; Stability</span> &mdash; Social and political cohesion. Low = factions fracturing.
<span style="color:#ffd700">&#9632; Morale</span> &mdash; Collective confidence and spirit. Low = despair, abandonment.
<span style="color:#ab47bc">&#9632; Anomaly</span> &mdash; Reality distortion / system weirdness. High = reality breach risk.
<span style="color:#ef5350">&#9632; Tension</span> &mdash; Inter-faction conflict pressure. High = war likely.
<span style="color:#ffa726">&#9632; Cascade</span> &mdash; Reaction chain temperature. High = events feeding events uncontrollably.
</p>

<p><strong style="color:#4fc3f7">Where to watch:</strong></p>
<p>
<span class="highlight">Star Map</span> &mdash; See faction territories, NPC positions, and spatial relationships.
<span class="highlight">Live Sim</span> &mdash; Read events, faction actions, NPC decisions, and cascade chains in real time.
<span class="highlight">Bridge</span> &mdash; Experience crises as command decisions. Choose how the Federation responds.
</p>
</div>
""")

# -- Footer --
P("""<div class="guide-footer">
The Federation &mdash; A Consciousness Simulation<br>
39 NPCs &middot; 8 Factions &middot; 8 Creatures &middot; 1 Living Universe
</div>
""")

P("</div>")  # close #content
P("</body></html>")

# -- Write output --
html = "\n".join(PARTS)
out_path = os.path.join(
    os.path.dirname(__file__) or ".",
    "..",
    "federation-game",
    "frontend",
    "worldguide.html",
)
out_path = os.path.normpath(out_path)
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
print("Wrote " + str(len(html)) + " chars to " + out_path)
