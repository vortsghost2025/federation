"""Part 3: JavaScript string for simulation.html builder."""

JS = r"""
var FACTION_COLORS={military_command:'#F44336',research_division:'#2196F3',diplomatic_corps:'#4CAF50',cultural_ministry:'#CE93D8',economic_council:'#FF9800',exploration_initiative:'#00BCD4',consciousness_collective:'#E91E63',preservation_society:'#8BC34A'};
var FACTION_DISPLAY={military_command:'Military Command',research_division:'Research Division',diplomatic_corps:'Diplomatic Corps',cultural_ministry:'Cultural Ministry',economic_council:'Economic Council',exploration_initiative:'Exploration Initiative',consciousness_collective:'Consciousness Collective',preservation_society:'Preservation Society'};
var MOOD_COLORS={satisfied:'#4CAF50',inspired:'#66BB6A',serene:'#81C784',peaceful:'#A5D6A7',hopeful:'#4CAF50',excited:'#66BB6A',confident:'#4CAF50',enlightened:'#66BB6A',adventurous:'#81C784',determined:'#4CAF50',resolute:'#66BB6A',steadfast:'#4CAF50',patient:'#81C784',valiant:'#4CAF50',free:'#66BB6A',frustrated:'#F44336',aggressive:'#D32F2F',suspicious:'#FF9800',anxious:'#FF9800',alarmed:'#F44336',worried:'#FF9800',unsettled:'#FF9800',weary:'#FF9800',melancholic:'#CE93D8',paranoid:'#F44336',burdened:'#FF9800',contemplative:'#00BCD4',thoughtful:'#00BCD4',curious:'#00BCD4',distracted:'#78909C',reserved:'#78909C',analytical:'#00BCD4'};
var METRIC_FIELD_MAP={tension:'tension_level',resources:'resource_abundance',threat:'threat_level',stability:'stability',morale:'morale',anomaly:'anomaly_activity'};
var METRIC_COLORS={tension:'#F44336',resources:'#4CAF50',threat:'#F44336',stability:'#00BCD4',morale:'#FF9800',anomaly:'#CE93D8'};
var IDLE_MOODS=['contemplative','thoughtful','curious','reserved','distracted','analytical','serene','peaceful','patient'];
window.cascadeNpcMap={};
window.npcFilterOn=false;

/* ═══ SEVERITY LABELS ═══ */
function severityInfo(metric, val) {
if (val == null) return {label:'\u2014',cls:'sev-stable'};
var v = Math.round(val);
switch(metric) {
case 'morale':
if (v<=20) return {label:'CRITICAL',cls:'sev-critical'};
if (v<=45) return {label:'WEAK',cls:'sev-weak'};
if (v<=75) return {label:'STABLE',cls:'sev-stable'};
return {label:'STRONG',cls:'sev-strong'};
case 'threat':
if (v<=25) return {label:'SAFE',cls:'sev-safe'};
if (v<=55) return {label:'WATCH',cls:'sev-watch'};
if (v<=80) return {label:'HIGH',cls:'sev-high'};
return {label:'SEVERE',cls:'sev-severe'};
case 'tension':
if (v<=25) return {label:'LOW',cls:'sev-low'};
if (v<=55) return {label:'MODERATE',cls:'sev-medium'};
if (v<=80) return {label:'HIGH',cls:'sev-high'};
return {label:'SEVERE',cls:'sev-severe'};
case 'stability':
if (v<=25) return {label:'FRAGILE',cls:'sev-fragile'};
if (v<=50) return {label:'UNSTABLE',cls:'sev-unstable'};
if (v<=75) return {label:'STABLE',cls:'sev-stable'};
return {label:'STRONG',cls:'sev-strong'};
case 'anomaly':
if (v<=25) return {label:'NORMAL',cls:'sev-normal'};
if (v<=55) return {label:'STRANGE',cls:'sev-strange'};
if (v<=80) return {label:'UNSTABLE',cls:'sev-unstable'};
return {label:'BREACH',cls:'sev-breach'};
case 'resources':
if (v<=20) return {label:'SCARCE',cls:'sev-critical'};
if (v<=45) return {label:'LOW',cls:'sev-weak'};
if (v<=75) return {label:'ADEQUATE',cls:'sev-stable'};
return {label:'ABUNDANT',cls:'sev-strong'};
case 'cascade':
if (v<=40) return {label:'CALM',cls:'sev-calm'};
if (v<=65) return {label:'ACTIVE',cls:'sev-active'};
if (v<=80) return {label:'HOT',cls:'sev-hot'};
return {label:'OVERHEATING',cls:'sev-overheating'};
default:
return {label:'\u2014',cls:'sev-stable'};
}
}

/* ═══ NEW: NUMERIC SEVERITY SCORE ═══ */
function sevScore(metric, val) {
if (val == null) return 0;
var si = severityInfo(metric, val);
var c = si.cls;
if (c.indexOf('critical')!==-1 || c.indexOf('breach')!==-1 || c.indexOf('overheating')!==-1) return 4;
if (c.indexOf('severe')!==-1) return 3;
if (c.indexOf('high')!==-1 || c.indexOf('unstable')!==-1 || c.indexOf('hot')!==-1 || c.indexOf('weak')!==-1 || c.indexOf('fragile')!==-1 || c.indexOf('scarce')!==-1) return 2;
if (c.indexOf('medium')!==-1 || c.indexOf('watch')!==-1 || c.indexOf('low')!==-1 || c.indexOf('strange')!==-1 || c.indexOf('active')!==-1) return 1;
return 0;
}

function splitSevCls(score) {
if (score >= 4) return 'critical';
if (score >= 3) return 'severe';
if (score >= 2) return 'high';
if (score >= 1) return 'elevated';
return 'nominal';
}

/* ═══ NEW: TOP BANNER (replaces updateTopRibbon) ═══ */
function updateTopBanner(status) {
if (!status) return;
var ws = status.world_state || status.worldState || status;

/* Extract metric values */
var metrics = {};
var mKeys = ['tension','resources','threat','stability','morale','anomaly'];
for (var i = 0; i < mKeys.length; i++) {
var k = mKeys[i], af = METRIC_FIELD_MAP[k] || k;
metrics[k] = ws[af] != null ? ws[af] : (ws[k] != null ? ws[k] : 50);
}

/* Row 1: Degradation vs Runway */
var moraleInv = 100 - (metrics.morale || 0);
var stabilityInv = 100 - (metrics.stability || 0);
var anomalyVal = metrics.anomaly || 0;
var degradation = (moraleInv + stabilityInv + anomalyVal) / 3;
var runway = 100 - degradation;
var degPct = clamp(degradation, 0, 100);
var runwayPct = clamp(runway, 0, 100);

var degFill = document.getElementById('deg-fill');
var rwFill = document.getElementById('runway-fill');
if (degFill) { degFill.style.width = degPct + '%'; }
if (rwFill) { rwFill.style.width = runwayPct + '%'; }

/* Chips for row 1 */
var chipMorale = document.getElementById('chip-morale');
var chipStab = document.getElementById('chip-stability');
var chipAnom = document.getElementById('chip-anomaly');
if (chipMorale) chipMorale.textContent = 'M ' + Math.round(metrics.morale || 0);
if (chipStab) chipStab.textContent = 'S ' + Math.round(metrics.stability || 0);
if (chipAnom) chipAnom.textContent = 'A ' + Math.round(metrics.anomaly || 0);

/* Degradation severity */
var degScore = Math.max(sevScore('morale', metrics.morale), sevScore('stability', metrics.stability), sevScore('anomaly', metrics.anomaly));
var degSevEl = document.getElementById('deg-sev');
if (degSevEl) {
var degCls = splitSevCls(degScore);
var degLabels = {critical:'CRITICAL',severe:'SEVERE',high:'HIGH',elevated:'ELEVATED',nominal:'NOMINAL'};
degSevEl.textContent = degLabels[degCls] || 'NOMINAL';
degSevEl.className = 'split-severity ' + degCls;
}

/* Row 2: Threat vs Buffer */
var threatVal = metrics.threat || 0;
var tensionVal = metrics.tension || 0;
var threatAvg = (threatVal + tensionVal) / 2;
var bufferAvg = metrics.resources || 0;
var totalWidth = threatAvg + bufferAvg;
var threatPct = totalWidth > 0 ? clamp((threatAvg / totalWidth) * 100, 0, 100) : 50;
var bufferPct = 100 - threatPct;

var thFill = document.getElementById('threat-fill');
var bufFill = document.getElementById('buffer-fill');
if (thFill) { thFill.style.width = threatPct + '%'; }
if (bufFill) { bufFill.style.width = bufferPct + '%'; }

/* Chips for row 2 */
var chipThreat = document.getElementById('chip-threat');
var chipTension = document.getElementById('chip-tension');
var chipRes = document.getElementById('chip-resources');
if (chipThreat) chipThreat.textContent = 'T ' + Math.round(threatVal);
if (chipTension) chipTension.textContent = 'X ' + Math.round(tensionVal);
if (chipRes) chipRes.textContent = 'R ' + Math.round(bufferAvg);

/* Threat severity */
var thScore = Math.max(sevScore('threat', threatVal), sevScore('tension', tensionVal));
var thSevEl = document.getElementById('threat-sev');
if (thSevEl) {
var thCls = splitSevCls(thScore);
var thLabels = {critical:'CRITICAL',severe:'SEVERE',high:'HIGH',elevated:'ELEVATED',nominal:'NOMINAL'};
thSevEl.textContent = thLabels[thCls] || 'NOMINAL';
thSevEl.className = 'split-severity ' + thCls;
}

/* Tick counter */
var tick = '\u2014';
if (status.last_tick_result && status.last_tick_result.tick_ts) tick = status.last_tick_result.tick_ts;
else if (status.last_tick_timestamp) tick = status.last_tick_timestamp;
else if (ws.tick_count != null) tick = ws.tick_count;
var tickEl = document.getElementById('tick-count');
if (tickEl) tickEl.textContent = tick;

lastTickTime = Date.now();
}

function updateTimeSince(){if(!lastTickTime)return;var elapsed=(Date.now()-lastTickTime)/1000;var el=document.getElementById('time-since');if(el)el.textContent=formatTime(elapsed)}

/* ═══ SITUATION SUMMARY ═══ */
function updateSituation(status) {
if (!status) return;
var ws = status.world_state || status.worldState || status;
var metrics = {};
var mKeys = ['tension','resources','threat','stability','morale','anomaly'];
for (var i=0;i<mKeys.length;i++) {
var k=mKeys[i], af=METRIC_FIELD_MAP[k]||k;
metrics[k] = ws[af]!=null ? ws[af] : (ws[k]!=null ? ws[k] : 50);
}
var cascade = status.cascade_summary || status.cascadeSummary || {};
var temp = cascade.temperature!=null ? cascade.temperature : (cascade.cascade_temperature!=null ? cascade.cascade_temperature : 0);
var cascadePct = temp>1.5 ? temp : (temp*100);
metrics.cascade = cascadePct;

var parts = [];
if (metrics.resources > 75) parts.push('resource-rich');
else if (metrics.resources < 25) parts.push('resource-scarce');
if (metrics.stability > 75) parts.push('socially stable');
else if (metrics.stability < 30) parts.push('socially unstable');
if (metrics.morale > 75) parts.push('high morale');
else if (metrics.morale < 25) parts.push('morale collapsing');
if (metrics.tension > 70) parts.push('high tension');
else if (metrics.tension < 25) parts.push('peaceful');
if (metrics.threat > 70) parts.push('under threat');
if (metrics.anomaly > 70) parts.push('anomaly activity elevated');
if (cascadePct > 80) parts.push('cascade chains spreading rapidly');
else if (cascadePct < 30) parts.push('events calm');

var sitText = parts.length ? 'The Federation is ' + parts.join(', ') + '.' : 'The Federation is in a balanced state.';
document.getElementById('sit-current-text').textContent = sitText;

var riskOrder = [
{k:'morale',dir:'low'},{k:'stability',dir:'low'},{k:'threat',dir:'high'},
{k:'tension',dir:'high'},{k:'anomaly',dir:'high'},{k:'cascade',dir:'high'}
];
var worstRisk = null; var worstScore = -1;
for (var r=0;r<riskOrder.length;r++) {
var rk=riskOrder[r], si=severityInfo(rk.k, metrics[rk.k]);
var score = si.cls.indexOf('critical')!==-1 ? 4 : (si.cls.indexOf('severe')!==-1 ? 3 : (si.cls.indexOf('breach')!==-1 ? 3 : (si.cls.indexOf('overheating')!==-1 ? 3 : (si.cls.indexOf('high')!==-1 ? 2 : (si.cls.indexOf('unstable')!==-1 ? 2 : (si.cls.indexOf('hot')!==-1 ? 2 : 0))))));
if (score > worstScore) { worstScore = score; worstRisk = rk.k; }
}
var riskText = '\u2014';
if (worstRisk) {
var rsi = severityInfo(worstRisk, metrics[worstRisk]);
var rName = worstRisk.charAt(0).toUpperCase() + worstRisk.slice(1);
if (worstRisk === 'cascade') rName = 'Cascade Temperature';
riskText = rName + ' is ' + rsi.label + ' (' + Math.round(metrics[worstRisk]) + (worstRisk==='cascade'?'%':'') + ')';
if (worstRisk==='morale') riskText += ' \u2014 social cohesion at risk';
else if (worstRisk==='threat') riskText += ' \u2014 external danger escalating';
else if (worstRisk==='stability') riskText += ' \u2014 institutions weakening';
else if (worstRisk==='cascade') riskText += ' \u2014 reaction chains may overwhelm decisions';
else if (worstRisk==='tension') riskText += ' \u2014 conflict likely';
else if (worstRisk==='anomaly') riskText += ' \u2014 reality instability';
}
document.getElementById('sit-risk-text').innerHTML = riskText;

var watchItems = [];
var questData = lastData.quests || {};
var npcData = lastData.npcs || [];
var eventData = lastData.events || [];

if (metrics.morale < 40) {
var msi = severityInfo('morale', metrics.morale);
var negMoods = 0; for(var ni=0;ni<npcData.length;ni++){var nm=npcData[ni].mood;if(typeof nm==='number'&&nm<0.3)negMoods++;else if(typeof nm==='string'&&(nm==='frustrated'||nm==='alarmed'||nm==='anxious'||nm==='worried'||nm==='melancholic'||nm==='paranoid'))negMoods++;}
watchItems.push({id:'morale', title:'Morale Recovery', sevLabel:msi.label, sevCls:msi.cls, current:'Morale '+Math.round(metrics.morale)+' / '+msi.label, meaning:'Social cohesion '+(metrics.morale<20?'near collapse':'under strain')+'.', lookAt:'Faction cohesion bars, '+negMoods+' NPC'+(negMoods!==1?'s':'')+' with negative moods, abandoned quests.', improve:'Morale rises above 30 and abandoned quest rate falls.', clickAction:'highlightMorale'});
}
if (metrics.stability < 40) {
var ssi = severityInfo('stability', metrics.stability);
var abnd = questData.abandoned_count||questData.abandoned||0;
watchItems.push({id:'stability', title:'Institutional Stability', sevLabel:ssi.label, sevCls:ssi.cls, current:'Stability '+Math.round(metrics.stability)+' / '+ssi.label, meaning:'Factions may stop coordinating or quests may fail.', lookAt:'Faction cohesion, '+abnd+' abandoned quests, unresolved count.', improve:'Stability rises above 50 and abandoned quest count drops.', clickAction:'highlightStability'});
}
if (cascadePct > 70) {
var csi = severityInfo('cascade', cascadePct);
var chainCount = 0; var totalReactions = 0;
if(eventData && eventData.length){for(var ei=0;ei<eventData.length;ei++){if(eventData[ei].cascade_depth>0){chainCount++;totalReactions++}}}
watchItems.push({id:'cascade', title:'Cascade Activity', sevLabel:csi.label, sevCls:csi.cls, current:'Cascade '+Math.round(cascadePct)+'% / '+csi.label, meaning:'NPC reactions are recursively spreading \u2014 dominos falling.', lookAt:'What Just Happened? cascade cards, '+totalReactions+' chain reactions.', improve:'Cascade temperature falls below 70% and chain reaction count decreases.', clickAction:'highlightCascade'});
}
if (metrics.threat > 60) {
var tsi = severityInfo('threat', metrics.threat);
var hostileEvents = 0; if(eventData&&eventData.length){for(var hi=0;hi<eventData.length;hi++){if(eventData[hi].event_type==='threat'||eventData[hi].severity==='high'||eventData[hi].is_hostile)hostileEvents++;}}
watchItems.push({id:'threat', title:'Threat Response', sevLabel:tsi.label, sevCls:tsi.cls, current:'Threat '+Math.round(metrics.threat)+' / '+tsi.label, meaning:'Hostile/anomalous events are stressing the federation.', lookAt:'Red crisis events, Military Command activity, conflict lines.', improve:'Threat drops below 60 and hostile events decrease.', clickAction:'highlightThreat'});
}
if (metrics.tension > 60) {
var tnsi = severityInfo('tension', metrics.tension);
watchItems.push({id:'tension', title:'Diplomatic Tensions', sevLabel:tnsi.label, sevCls:tnsi.cls, current:'Tension '+Math.round(metrics.tension)+' / '+tnsi.label, meaning:'Faction conflicts are escalating \u2014 diplomatic breakdown risk.', lookAt:'Enemy stance dots in faction cards, conflict event lines.', improve:'Tension drops below 60 and faction stances improve.', clickAction:'highlightTension'});
}

var wlContainer = document.getElementById('watchlist-cards');
if (!watchItems.length) {
wlContainer.innerHTML = '<div class="sit-card-value" style="color:var(--green);font-size:14px">&#10003; No immediate concerns \u2014 all systems nominal</div>';
} else {
var wHtml = '';
for (var wi=0; wi<watchItems.length; wi++) {
var w = watchItems[wi];
wHtml += '<div class="watch-card" data-watch-id="'+w.id+'" onclick="watchCardClick(\''+w.clickAction+'\')" tabindex="0" role="button" aria-label="'+w.title+': '+w.current+'">';
wHtml += '<div class="wc-header"><span class="wc-title">'+esc(w.title)+'</span><span class="wc-sev sev-badge '+w.sevCls+'">'+w.sevLabel+'</span></div>';
wHtml += '<div class="wc-current">'+esc(w.current)+'</div>';
wHtml += '<div class="wc-meaning">'+esc(w.meaning)+'</div>';
wHtml += '<div class="wc-look">Look at: '+esc(w.lookAt)+'</div>';
wHtml += '<div class="wc-improve">Improvement: '+esc(w.improve)+'</div>';
wHtml += '<div class="wc-click-hint">Click to highlight</div>';
wHtml += '</div>';
}
wlContainer.innerHTML = wHtml;
}

window.watchCardClick = function(action) {
document.querySelectorAll('.panel-highlight-flash').forEach(function(el){el.classList.remove('panel-highlight-flash')});
switch(action) {
case 'highlightMorale':
switchLeftTab('factions'); flashEl('left');
switchRightTab('npc-quests'); setTimeout(function(){flashEl('quest-health')},300);
break;
case 'highlightStability':
switchLeftTab('factions'); flashEl('left');
switchRightTab('npc-quests'); setTimeout(function(){flashEl('quest-health')},300);
break;
case 'highlightCascade':
flashEl('cascade-pipeline'); flashEl('center');
break;
case 'highlightThreat':
switchLeftTab('factions');
var milCard = document.querySelector('[data-faction="military_command"]');
if(milCard){milCard.classList.add('panel-highlight-flash');setTimeout(function(){milCard.classList.remove('panel-highlight-flash')},1600)}
flashEl('center');
break;
case 'highlightTension':
switchLeftTab('factions'); flashEl('left');
break;
}
};

function flashEl(id) {
var el = document.getElementById(id);
if (!el) return;
el.classList.add('panel-highlight-flash');
setTimeout(function(){el.classList.remove('panel-highlight-flash')}, 1600);
}
}

var lastData={status:null,factions:null,npcs:null,events:null,quests:null,factionTech:null,choices:null};
var fetchErrorCount=0;
var lastTickTime=null;
var expandedFaction=null;
var expandedNpc=null;
var activeLeftTab='factions';
var activeRightTab='npcs';
var expandedQuestNpc=null;
var expandedChoiceFaction=null;

function generateStarfield(){var sf=document.getElementById('starfield');for(var i=0;i<80;i++){var s=document.createElement('div');s.className='star';var size=Math.random()*2+1;s.style.cssText='width:'+size+'px;height:'+size+'px;left:'+(Math.random()*100)+'%;top:'+(Math.random()*100)+'%;--dur:'+(2+Math.random()*4)+'s;--delay:'+(Math.random()*3)+'s;opacity:'+(0.2+Math.random()*0.5);sf.appendChild(s)}}

function formatTime(seconds){if(seconds==null||isNaN(seconds))return '\u2014';if(seconds<60)return Math.floor(seconds)+'s';if(seconds<3600)return Math.floor(seconds/60)+'m '+Math.floor(seconds%60)+'s';return Math.floor(seconds/3600)+'h '+Math.floor((seconds%3600)/60)+'m'}

function stanceLabel(stance){if(!stance)return 'neutral';if(typeof stance==='object'&&stance.label)return stance.label.toLowerCase();if(typeof stance==='number'){if(stance>=0.75)return 'ally';if(stance<=0.25)return 'enemy';return 'neutral'}var s=String(stance).toLowerCase();if(s==='ally'||s==='allied'||s==='friendly')return 'ally';if(s==='enemy'||s==='hostile'||s==='adversarial')return 'enemy';return 'neutral'}
function stanceToClass(stance){return stanceLabel(stance)}

function moodLabel(mood){if(mood==null)return '\u2014';if(typeof mood==='string'){var n=parseFloat(mood);if(!isNaN(n))mood=n;else return mood.toLowerCase()}if(typeof mood==='number'){if(mood>=0.9)return 'INSPIRED';if(mood>=0.7)return 'SATISFIED';if(mood>=0.5)return 'CONTEMPLATIVE';if(mood>=0.3)return 'ANXIOUS';return 'FRUSTRATED'}return String(mood)}
function moodColorOf(mood){if(mood==null)return '#78909C';var label=moodLabel(mood).toLowerCase();return MOOD_COLORS[label]||'#78909C'}
function cascadeColor(pct){if(pct<30)return '#4CAF50';if(pct<60)return '#FF9800';if(pct<85)return '#F44336';return '#E91E63'}
function esc(s){if(s==null)return '';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function clamp(v,lo,hi){return Math.max(lo,Math.min(hi,v))}

async function apiFetch(endpoint,timeoutMs){var ctl=new AbortController();var timer=setTimeout(function(){ctl.abort()},timeoutMs||8000);try{var r=await fetch('/api'+endpoint,{headers:{'Accept':'application/json'},signal:ctl.signal});clearTimeout(timer);if(!r.ok)throw new Error(r.status);return await r.json()}catch(e){clearTimeout(timer);return null}}

function switchLeftTab(tab){activeLeftTab=tab;var btns=document.querySelectorAll('#left-tabs .tab-btn');for(var i=0;i<btns.length;i++){btns[i].classList.remove('active-amber');if(btns[i].dataset.tab===tab)btns[i].classList.add('active-amber')}document.getElementById('left-factions').classList.toggle('visible',tab==='factions');document.getElementById('left-faction-tech').classList.toggle('visible',tab==='faction-tech');if(tab==='faction-tech'&&!lastData.factionTech)refreshFactionTech()}
function switchRightTab(tab){activeRightTab=tab;var btns=document.querySelectorAll('#right-tabs .tab-btn');for(var i=0;i<btns.length;i++){btns[i].classList.remove('active-violet');if(btns[i].dataset.tab===tab)btns[i].classList.add('active-violet')}document.getElementById('right-npcs').classList.toggle('visible',tab==='npcs');document.getElementById('right-npc-quests').classList.toggle('visible',tab==='npc-quests');document.getElementById('right-choices').classList.toggle('visible',tab==='choices');if(tab==='npc-quests'&&!lastData.quests)refreshQuests();if(tab==='choices'&&!lastData.choices)refreshChoices()}

/* ═══ NEW: CASCADE NPC MAP ═══ */
function buildCascadeNpcMap(events) {
var map = {};
if (!events) return map;
var flat = [];
if (Array.isArray(events)) { flat = events; }
else if (typeof events === 'object') {
var we = events.world_events || []; var ce = events.cascade_events || []; var be = events.broadcast_events || [];
flat = we.concat(ce, be);
}
for (var i = 0; i < flat.length; i++) {
var ev = flat[i];
var evType = (ev.type || ev.event_type || '').toLowerCase();
if (evType !== 'cascade_reaction' && !ev.cascade) continue;
var depth = ev.cascade_depth || ev.depth || ev.cascadeDepth || 0;
var npcId = ev.character_id || ev.char_id || ev.npc_id || ev.source || '';
if (!npcId) continue;
if (typeof npcId !== 'string') npcId = String(npcId);
var existing = map[npcId];
if (!existing || depth < existing.depth) {
map[npcId] = { depth: depth, isRoot: depth === 0 || depth === 1, tone: 'neutral' };
}
/* Extract tone from description */
var desc = (ev.description || ev.message || '').toLowerCase();
if (desc.indexOf('fear')!==-1 || desc.indexOf('alarmed')!==-1) map[npcId].tone = 'fear';
else if (desc.indexOf('conflict')!==-1 || desc.indexOf('confront')!==-1) map[npcId].tone = 'conflict';
else if (desc.indexOf('cautious')!==-1 || desc.indexOf('wary')!==-1) map[npcId].tone = 'caution';
else if (desc.indexOf('support')!==-1 || desc.indexOf('endorse')!==-1) map[npcId].tone = 'support';
else if (desc.indexOf('celebrat')!==-1) map[npcId].tone = 'celebration';
/* Also check reactors for NPC names */
var reactors = ev.reactors || ev.affected_npcs || [];
if (Array.isArray(reactors)) {
for (var ri = 0; ri < reactors.length; ri++) {
var rName = '';
if (typeof reactors[ri] === 'string') {
var paren = reactors[ri].indexOf('(');
rName = paren > 0 ? reactors[ri].substring(0, paren).trim() : reactors[ri].trim();
} else if (typeof reactors[ri] === 'object' && reactors[ri].name) {
rName = reactors[ri].name;
}
if (rName && !map[rName]) {
map[rName] = { depth: depth + 1, isRoot: false, tone: 'neutral' };
var rDesc = (ev.description || ev.message || '').toLowerCase();
if (rDesc.indexOf('fear')!==-1) map[rName].tone = 'fear';
else if (rDesc.indexOf('conflict')!==-1) map[rName].tone = 'conflict';
else if (rDesc.indexOf('cautious')!==-1) map[rName].tone = 'caution';
else if (rDesc.indexOf('support')!==-1) map[rName].tone = 'support';
else if (rDesc.indexOf('celebrat')!==-1) map[rName].tone = 'celebration';
}
}
}
}
window.cascadeNpcMap = map;
return map;
}

function getNpcCascadeStatus(npcId) {
var map = window.cascadeNpcMap || {};
var entry = map[npcId];
if (!entry) return 'none';
if (entry.isRoot) return 'root';
if (entry.depth <= 2) return 'reactor';
return 'affected';
}

function isNpcIdle(mood) {
if (mood == null) return false;
var label = moodLabel(mood).toLowerCase();
return IDLE_MOODS.indexOf(label) !== -1;
}

function toggleNpcFilter() {
window.npcFilterOn = !window.npcFilterOn;
var toggle = document.getElementById('npc-noise-toggle');
var label = toggle ? toggle.querySelector('.npc-noise-toggle-label') : null;
if (toggle) toggle.classList.toggle('on', window.npcFilterOn);
if (toggle) toggle.setAttribute('aria-pressed', String(window.npcFilterOn));
if (label) label.textContent = window.npcFilterOn ? 'FILTER ON' : 'FILTER OFF';
applyNpcFilter();
}

function applyNpcFilter() {
var cards = document.querySelectorAll('.npc-card');
var activeCount = 0;
for (var i = 0; i < cards.length; i++) {
var card = cards[i];
var npcId = card.dataset.npcId;
var cascadeStatus = getNpcCascadeStatus(npcId);
var moodEl = card.querySelector('[data-field="mood"]');
var moodText = moodEl ? moodEl.textContent.toLowerCase() : '';
var idle = isNpcIdle(moodText);
var isCascade = cascadeStatus !== 'none';

if (idle && !isCascade) {
card.classList.add('npc-idle');
if (window.npcFilterOn) {
card.classList.add('hide-idle');
} else {
card.classList.remove('hide-idle');
}
} else {
card.classList.remove('npc-idle');
card.classList.remove('hide-idle');
activeCount++;
}
}
var countEl = document.getElementById('npc-active-count');
if (countEl) countEl.textContent = activeCount + ' active';
}

function updateNpcCascadeBadges() {
var cards = document.querySelectorAll('.npc-card');
for (var i = 0; i < cards.length; i++) {
var card = cards[i];
var npcId = card.dataset.npcId;
var status = getNpcCascadeStatus(npcId);
card.classList.remove('cascade-root','cascade-reactor','cascade-affected','cascade-none');
card.classList.add('cascade-' + status);
var badgesDiv = card.querySelector('.npc-badges');
if (!badgesDiv) continue;
var existingBadge = badgesDiv.querySelector('.cascade-badge');
if (existingBadge) existingBadge.remove();
if (status === 'root') {
var b = document.createElement('span'); b.className = 'cascade-badge trigger'; b.textContent = 'TRIGGER';
badgesDiv.insertBefore(b, badgesDiv.firstChild);
} else if (status === 'reactor') {
var b2 = document.createElement('span'); b2.className = 'cascade-badge reactor'; b2.textContent = 'REACTOR';
badgesDiv.insertBefore(b2, badgesDiv.firstChild);
} else if (status === 'affected') {
var b3 = document.createElement('span'); b3.className = 'cascade-badge affected'; b3.textContent = 'AFFECTED';
badgesDiv.insertBefore(b3, badgesDiv.firstChild);
}
}
}

/* ═══ FACTIONS ═══ */
function renderFactions(factions){
if(!factions)return;
var list=document.getElementById('faction-list');
var keys=Object.keys(factions);
var needsRebuild=list.children.length!==keys.length||list.dataset.keySig!==keys.join('|');
if(needsRebuild){
list.dataset.keySig=keys.join('|');list.innerHTML='';
for(var fi=0;fi<keys.length;fi++){
(function(fk){
var f=factions[fk],color=FACTION_COLORS[fk]||'#78909C';
var display=FACTION_DISPLAY[fk]||(f.name||fk.replace(/_/g,' '));
var card=document.createElement('div');card.className='faction-card';card.dataset.faction=fk;card.setAttribute('tabindex','0');
var stancesHtml='';
for(var si=0;si<keys.length;si++){
var otherK=keys[si];if(otherK===fk)continue;
var rawStance=f.stances?f.stances[otherK]:null;
var sc=stanceToClass(rawStance);
var dotColor=sc==='ally'?'#4CAF50':(sc==='enemy'?'#F44336':'#FFC107');
var sl=stanceLabel(rawStance);
stancesHtml+='<div class="stance-dot '+sc+'" title="'+esc(FACTION_DISPLAY[otherK]||otherK)+': '+esc(sl)+'" style="color:'+dotColor+'"></div>';
}
card.innerHTML='<div class="faction-header"><span class="faction-name" style="color:'+color+'">'+esc(display)+'</span><span class="faction-power" style="color:'+color+'" data-field="power">\u2014</span></div><div class="faction-sub"><span class="faction-cohesion-label">Cohesion</span><div class="faction-cohesion-bar"><div class="faction-cohesion-fill" data-field="cohesion-fill" style="width:0"></div></div></div><div class="faction-action" data-field="action">No recent action</div><div class="faction-stances">'+stancesHtml+'</div><div class="faction-detail"><div class="detail-stances" data-field="detail-stances"></div><div class="detail-action-history" data-field="detail-history"></div></div>';
card.addEventListener('click',function(){var wasActive=card.classList.contains('active');list.querySelectorAll('.faction-card').forEach(function(c){c.classList.remove('active')});if(!wasActive){card.classList.add('active');expandedFaction=fk}else{expandedFaction=null}fillFactionDetail(fk,factions)});
card.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();card.click()}});
list.appendChild(card);
})(keys[fi]);
}
}
for(var ui=0;ui<keys.length;ui++){
var uk=keys[ui],uf=factions[uk];
var ucard=list.querySelector('[data-faction="'+uk+'"]');if(!ucard)continue;
var dyn=uf.dynamics||uf;
var cohesionVal=dyn.cohesion!=null?dyn.cohesion:(uf.cohesion!=null?uf.cohesion:50);
var cohesionPct=clamp(cohesionVal,0,100);
var cohesionColor=cohesionPct>60?'#4CAF50':(cohesionPct>30?'#FF9800':'#F44336');
var cFill=ucard.querySelector('[data-field="cohesion-fill"]');if(cFill){cFill.style.width=cohesionPct+'%';cFill.style.background=cohesionColor}
var pwr=ucard.querySelector('[data-field="power"]');if(pwr)pwr.textContent=uf.power!=null?uf.power:(dyn.power!=null?dyn.power:'\u2014');
var act=ucard.querySelector('[data-field="action"]');if(act){var recentActions=uf.recent_actions||uf.recent_action||[];var actionText='No recent action';if(Array.isArray(recentActions)&&recentActions.length>0){var first=recentActions[0];actionText=typeof first==='string'?first:(first.action||first.description||'acting');actionText=actionText.replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase()})}act.textContent=actionText}
if(expandedFaction===uk)fillFactionDetail(uk,factions);
}
}

function fillFactionDetail(fk,factions){
var f=factions[fk];if(!f)return;var keys=Object.keys(factions);
var card=document.querySelector('[data-faction="'+fk+'"]');if(!card)return;
var dsEl=card.querySelector('[data-field="detail-stances"]');
if(dsEl){var html='<div style="font-size:13px;color:var(--dim);margin-bottom:4px;text-transform:uppercase;letter-spacing:1px">Stances</div>';for(var i=0;i<keys.length;i++){var otherK=keys[i];if(otherK===fk)continue;var rawStance=f.stances?f.stances[otherK]:null;var sc=stanceToClass(rawStance);var scColor=sc==='ally'?'#4CAF50':(sc==='enemy'?'#F44336':'#FFC107');var sl=stanceLabel(rawStance);var numVal=(typeof rawStance==='object'&&rawStance.value!=null)?' ('+(rawStance.value*100).toFixed(0)+'%)':'';html+='<div class="detail-stance-row"><span class="detail-stance-name">'+esc(FACTION_DISPLAY[otherK]||otherK)+'</span><span class="detail-stance-val" style="color:'+scColor+'">'+esc(sl)+numVal+'</span></div>'}dsEl.innerHTML=html}
var dhEl=card.querySelector('[data-field="detail-history"]');
if(dhEl){var history=f.recent_actions||f.action_history||[];var hhtml='<div style="font-size:13px;color:var(--dim);margin-bottom:4px;text-transform:uppercase;letter-spacing:1px">Recent Actions</div>';if(!history.length){hhtml+='<div style="font-size:13px;color:var(--dim)">No history available</div>'}else{for(var h=0;h<Math.min(history.length,8);h++){var a=history[h];var actionName=typeof a==='string'?a:(a.action||a.description||JSON.stringify(a));actionName=actionName.replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase()});var effectsStr='';if(typeof a==='object'&&a.effects){var effParts=[];for(var ek in a.effects){if(a.effects[ek]!==0)effParts.push(ek+':'+(a.effects[ek]>0?'+':'')+a.effects[ek])}if(effParts.length)effectsStr=' <span style="color:var(--cyan);font-size:12px">['+esc(effParts.join(', '))+']</span>'}hhtml+='<div class="detail-action-item">'+esc(actionName)+effectsStr+'</div>'}}dhEl.innerHTML=hhtml}
}

/* ═══ EVENT CHAIN COLLAPSING ═══ */
function buildEventChains(flat) {
var chains = {};
var unchained = [];
for (var i = 0; i < flat.length; i++) {
var ev = flat[i];
var evType = (ev.type || ev.event_type || '').toLowerCase();
var depth = ev.cascade_depth || ev.depth || ev.cascadeDepth || 0;
var chainKey = null;
if (evType === 'cascade_reaction' || ev.cascade) {
var originType = ev.origin_event_type || ev.source_event_type || ev.cause || 'unknown';
chainKey = 'chain_D' + depth + '_' + originType;
}
else if (evType === 'game_event') {
var subType = ev.event_category || ev.subtype || ev.category || 'general';
chainKey = 'game_' + subType;
}
if (chainKey) {
if (!chains[chainKey]) chains[chainKey] = { key: chainKey, events: [], origin: '', participants: {} };
chains[chainKey].events.push(ev);
var src = ev.source || ev.source_name || ev.character_name || ev.npc_name || ev.faction_id || '';
if (src && typeof src === 'string') chains[chainKey].participants[src] = (chains[chainKey].participants[src] || 0) + 1;
if (!chains[chainKey].origin) chains[chainKey].origin = ev.origin_event_type || ev.source_event_type || ev.cause || evType;
} else {
unchained.push(ev);
}
}
var result = [];
for (var ck in chains) {
var ch = chains[ck];
ch.count = ch.events.length;
var sorted = Object.keys(ch.participants).sort(function(a,b){return ch.participants[b]-ch.participants[a]});
ch.topParticipants = sorted.slice(0, 3);
var tones = {};
for (var t = 0; t < ch.events.length; t++) {
var desc = (ch.events[t].description || ch.events[t].message || '').toLowerCase();
if (desc.indexOf('support')!==-1 || desc.indexOf('endorse')!==-1) tones.support = (tones.support||0)+1;
else if (desc.indexOf('celebrat')!==-1) tones.celebration = (tones.celebration||0)+1;
else if (desc.indexOf('conflict')!==-1 || desc.indexOf('confront')!==-1) tones.conflict = (tones.conflict||0)+1;
else if (desc.indexOf('cautious')!==-1 || desc.indexOf('wary')!==-1) tones.caution = (tones.caution||0)+1;
else if (desc.indexOf('fear')!==-1 || desc.indexOf('alarmed')!==-1) tones.fear = (tones.fear||0)+1;
else tones.neutral = (tones.neutral||0)+1;
}
var dominantTone = 'neutral';
var maxTone = 0;
for (var tk in tones) { if (tones[tk] > maxTone) { maxTone = tones[tk]; dominantTone = tk; } }
ch.dominantTone = dominantTone;
result.push(ch);
}
result.sort(function(a,b){return b.count - a.count});
return { chains: result, unchained: unchained };
}

/* ═══ RENDER EVENTS + CASCADE PIPELINE ═══ */
function renderEvents(events){
if(!events)return;
var feed=document.getElementById('event-feed');
var chainsArea=document.getElementById('event-chains');
var pipelineArea=document.getElementById('cascade-pipeline');

var flat=[];
if(Array.isArray(events)){flat=events}
else if(typeof events==='object'){
var we=events.world_events||[];var ce=events.cascade_events||[];var be=events.broadcast_events||[];
flat=we.concat(ce,be);
flat.sort(function(a,b){var ta=a.ts||a.timestamp||a.tick||a.time||0;var tb=b.ts||b.timestamp||b.tick||b.time||0;return(tb>ta?1:(tb<ta?-1:0))});
}

/* Build cascade NPC map from raw events */
buildCascadeNpcMap(events);
updateNpcCascadeBadges();
applyNpcFilter();

var grouped = buildEventChains(flat);

/* ═══ RENDER CASCADE PIPELINE ═══ */
if (pipelineArea) {
pipelineArea.innerHTML = '';
var cascadeEvents = flat.filter(function(ev) {
var evType = (ev.type || ev.event_type || '').toLowerCase();
return evType === 'cascade_reaction' || ev.cascade;
});

if (cascadeEvents.length > 0) {
/* Sort by depth ascending */
cascadeEvents.sort(function(a,b){
var da = a.cascade_depth || a.depth || a.cascadeDepth || 0;
var db = b.cascade_depth || b.depth || b.cascadeDepth || 0;
return da - db;
});

/* Find root event (depth 0 or 1) */
var rootEv = null;
var dominoes = [];
for (var pi = 0; pi < cascadeEvents.length; pi++) {
var pe = cascadeEvents[pi];
var pDepth = pe.cascade_depth || pe.depth || pe.cascadeDepth || 0;
if (pDepth <= 1 && !rootEv) { rootEv = pe; }
else { dominoes.push(pe); }
}
/* If no explicit root, use the first event */
if (!rootEv && cascadeEvents.length > 0) { rootEv = cascadeEvents[0]; dominoes = cascadeEvents.slice(1); }

var pHtml = '';
/* Root trigger */
if (rootEv) {
var rootDesc = rootEv.description || rootEv.message || rootEv.event || 'Cascade event';
var rootOrigin = rootEv.origin_event_type || rootEv.source_event_type || rootEv.cause || 'Unknown';
var rootClean = rootOrigin.replace(/_/g, ' ').replace(/\b\w/g, function(c){return c.toUpperCase()});
pHtml += '<div class="pipeline-root">';
pHtml += '<div class="pipeline-root-label">Root Trigger: ' + esc(rootClean) + '</div>';
pHtml += '<div class="pipeline-root-event">' + esc(rootDesc) + '</div>';
pHtml += '</div>';
}

/* Domino rows */
if (dominoes.length > 0) {
pHtml += '<div class="pipeline-dominoes">';
var maxShow = 12;
for (var di = 0; di < Math.min(dominoes.length, maxShow); di++) {
var de = dominoes[di];
var dDepth = de.cascade_depth || de.depth || de.cascadeDepth || 0;
var dName = de.character_name || de.source || de.source_name || de.npc_name || 'Unknown';
var dDesc = de.description || de.message || '';
/* Shorten description */
if (dDesc.length > 80) dDesc = dDesc.substring(0, 77) + '...';
/* Detect tone */
var dTone = 'neutral';
var dDescLow = dDesc.toLowerCase();
if (dDescLow.indexOf('fear')!==-1 || dDescLow.indexOf('alarmed')!==-1) dTone = 'fear';
else if (dDescLow.indexOf('conflict')!==-1 || dDescLow.indexOf('confront')!==-1) dTone = 'conflict';
else if (dDescLow.indexOf('cautious')!==-1 || dDescLow.indexOf('wary')!==-1) dTone = 'caution';
else if (dDescLow.indexOf('support')!==-1 || dDescLow.indexOf('endorse')!==-1) dTone = 'support';
else if (dDescLow.indexOf('celebrat')!==-1) dTone = 'celebration';

pHtml += '<div class="domino-npc">';
pHtml += '<span class="domino-depth">D' + dDepth + '</span>';
pHtml += '<span class="domino-name">' + esc(dName) + '</span>';
pHtml += '<span class="domino-tone ' + dTone + '">' + dTone + '</span>';
pHtml += '<span class="domino-desc">' + esc(dDesc) + '</span>';
pHtml += '</div>';
}
if (dominoes.length > maxShow) {
pHtml += '<div class="pipeline-overflow">+ ' + (dominoes.length - maxShow) + ' more reactions</div>';
}
pHtml += '</div>';
}

pipelineArea.innerHTML = pHtml;
}
}

/* Render chain cards */
chainsArea.innerHTML = '';
for (var ci = 0; ci < Math.min(grouped.chains.length, 5); ci++) {
(function(chain) {
var card = document.createElement('div');
card.className = 'chain-card';
var originClean = chain.origin.replace(/_/g, ' ').replace(/\b\w/g, function(c){return c.toUpperCase()});
card.innerHTML =
'<div class="chain-header">' +
'<span class="chain-title">' + esc(chain.key.replace(/_/g,' ')) + '</span>' +
'<span class="chain-count">' + chain.count + ' reactions</span>' +
'</div>' +
'<div class="chain-meta">' +
'<div class="chain-meta-item">Origin: <span class="chain-meta-val">' + esc(originClean) + '</span></div>' +
(chain.topParticipants.length ? '<div class="chain-meta-item">Top: <span class="chain-meta-val">' + esc(chain.topParticipants.join(', ')) + '</span></div>' : '') +
'<div class="chain-meta-item">Tone: <span class="chain-meta-val">' + esc(chain.dominantTone) + '</span></div>' +
'</div>' +
'<div class="chain-events"></div>';
card.addEventListener('click', function(){card.classList.toggle('expanded');
var evtDiv = card.querySelector('.chain-events');
if (card.classList.contains('expanded') && !evtDiv.children.length) {
for (var ei = 0; ei < Math.min(chain.events.length, 20); ei++) {
var ev = chain.events[ei];
var desc = ev.description || ev.message || ev.text || ev.event || JSON.stringify(ev);
var src = ev.source || ev.source_name || ev.character_name || '';
evtDiv.innerHTML += '<div class="chain-event">' + (src ? '<strong>' + esc(src) + '</strong>: ' : '') + esc(desc) + '</div>';
}
if (chain.events.length > 20) evtDiv.innerHTML += '<div class="chain-event" style="color:var(--dim)">+ ' + (chain.events.length - 20) + ' more</div>';
}
});
chainsArea.appendChild(card);
})(grouped.chains[ci]);
}

/* Render unchained events */
feed.innerHTML = '';
var rawBtn=document.getElementById('raw-toggle'),rawWrap=document.getElementById('raw-wrap');
if(grouped.chains.length===0){rawBtn.classList.add('open');rawWrap.classList.add('open');rawBtn.setAttribute('aria-expanded','true')}
else{rawBtn.classList.remove('open');rawWrap.classList.remove('open');rawBtn.setAttribute('aria-expanded','false')}
rawBtn.textContent='Raw Events ('+grouped.unchained.length+')';
for (var i = 0; i < Math.min(grouped.unchained.length, 40); i++) {
var ev = grouped.unchained[i];
var el = document.createElement('div');
var typeClass='world';var sourceLabel='SYSTEM';var sourceClass='world';
var evType=(ev.type||ev.event_type||'').toLowerCase();
var evSource=(ev.source||ev.source_type||'').toLowerCase();
if(evType==='cascade'||evType==='cascade_reaction'||ev.cascade){typeClass='cascade';sourceLabel='CASCADE';sourceClass='cascade'}
else if(evSource==='faction'||evType==='faction_action'||ev.faction_id){typeClass='faction-action';sourceLabel='FACTION';sourceClass='faction'}
else if(evType==='broadcast'||ev.broadcast||evSource==='npc'){typeClass='broadcast';sourceLabel='BROADCAST';sourceClass='broadcast'}
if(evSource==='faction'){typeClass='faction-action';sourceLabel='FACTION';sourceClass='faction'}
else if(evSource==='cascade'){typeClass='cascade';sourceLabel='CASCADE';sourceClass='cascade'}
else if(evSource==='broadcast'){typeClass='broadcast';sourceLabel='BROADCAST';sourceClass='broadcast'}
var ts=ev.timestamp||ev.ts||ev.tick||ev.time||'';
var desc=ev.description||ev.message||ev.text||ev.event||JSON.stringify(ev);
var cascadeDepth=ev.cascade_depth||ev.depth||ev.cascadeDepth;
var cascadeHtml=cascadeDepth&&typeClass==='cascade'?'<span class="event-cascade-depth">D'+esc(String(cascadeDepth))+'</span>':'';
var factionBorder=ev.faction_id&&FACTION_COLORS[ev.faction_id]?'border-left-color:'+FACTION_COLORS[ev.faction_id]:'';
el.className='event-entry '+typeClass;el.style.cssText=factionBorder;
el.innerHTML='<span class="event-time">'+esc(String(ts))+'</span><span class="event-source '+sourceClass+'">'+esc(sourceLabel)+'</span><span class="event-body">'+esc(desc)+cascadeHtml+'</span>';
feed.appendChild(el);
}
if(feed.children.length>50){while(feed.children.length>50)feed.removeChild(feed.lastChild)}
}

/* ═══ NPCs ═══ */
function renderNpcs(npcs){
if(!npcs)return;
var grid=document.getElementById('npc-grid');
var list=Array.isArray(npcs)?npcs:(npcs.npcs?npcs.npcs:Object.values(npcs));
var countEl=document.getElementById('npc-count');if(countEl)countEl.textContent='('+list.length+' / 39)';
var needsRebuild=grid.children.length!==list.length||grid.dataset.count!==String(list.length);
if(needsRebuild){
grid.dataset.count=String(list.length);grid.innerHTML='';
for(var ni=0;ni<list.length;ni++){
(function(npc,idx){
var mapped={id:npc.char_id||npc.id||npc.name||idx,name:npc.name||'Unknown',faction:npc.affiliation||npc.faction||npc.faction_id||'',mood:npc.mood,corruption:npc.corruption_level!=null?npc.corruption_level:(npc.corruption!=null?npc.corruption:0),rumor:npc.rumor_level!=null?npc.rumor_level:(npc.rumor!=null?npc.rumor:0),recent_thoughts:npc.recent_thoughts||npc.thoughts||npc.recentThoughts||[],recent_decisions:npc.recent_decisions||npc.decisions||npc.recentDecisions||[],recent_actions:npc.recent_actions||npc.actions||[],last_decision_category:(npc.recent_decisions&&npc.recent_decisions.length)?npc.recent_decisions[0].category:(npc.last_decision_category||npc.lastDecision||npc.decision_category||'\u2014'),relationships:npc.relationships||npc.relations||{}};
var card=document.createElement('div');card.className='npc-card';card.dataset.npcId=mapped.id;card.setAttribute('tabindex','0');
var ml=moodLabel(mapped.mood),mc=moodColorOf(mapped.mood),affilColor=FACTION_COLORS[mapped.faction]||'#78909C';
card.innerHTML='<div class="npc-name">'+esc(mapped.name)+'</div><div class="npc-badges"><span class="npc-mood" style="color:'+mc+';background:'+mc+'18" data-field="mood">'+esc(ml)+'</span><span class="npc-decision" data-field="decision">'+esc(mapped.last_decision_category)+'</span><span class="npc-affil" style="background:'+affilColor+'" title="'+esc(FACTION_DISPLAY[mapped.faction]||mapped.faction)+'" data-field="affil"></span></div><div class="npc-detail"><div class="npc-detail-section"><div class="npc-detail-label">Recent Thoughts</div><div class="npc-detail-val" data-field="thoughts"></div></div><div class="npc-detail-section"><div class="npc-detail-label">Recent Decisions</div><div class="npc-detail-val" data-field="decisions"></div></div><div class="npc-detail-section"><div class="npc-detail-label">Recent Actions</div><div class="npc-detail-val" data-field="actions"></div></div><div class="npc-detail-section"><div class="npc-detail-label">Corruption / Rumor</div><div class="npc-detail-val" data-field="corruption"></div></div><div class="npc-detail-section"><div class="npc-detail-label">Relationships</div><div class="npc-detail-val" data-field="relationships"></div></div></div>';
card.addEventListener('click',function(){var wasActive=card.classList.contains('active');grid.querySelectorAll('.npc-card').forEach(function(c){c.classList.remove('active')});if(!wasActive){card.classList.add('active');expandedNpc=mapped.id}else{expandedNpc=null}});
card.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();card.click()}});
grid.appendChild(card);
})(list[ni],ni);
}
}
for(var ui=0;ui<list.length;ui++){
var npc=list[ui],nId=npc.char_id||npc.id||npc.name||ui;
var ncard=grid.querySelector('[data-npc-id="'+nId+'"]');if(!ncard)continue;
var ml2=moodLabel(npc.mood),mc2=moodColorOf(npc.mood);
var moodEl=ncard.querySelector('[data-field="mood"]');if(moodEl){moodEl.textContent=ml2;moodEl.style.color=mc2;moodEl.style.background=mc2+'18'}
var decEl=ncard.querySelector('[data-field="decision"]');var decCat=(npc.recent_decisions&&npc.recent_decisions.length)?npc.recent_decisions[0].category:(npc.last_decision_category||'\u2014');if(decEl)decEl.textContent=decCat;
var affilEl=ncard.querySelector('[data-field="affil"]');var fk2=npc.affiliation||npc.faction||npc.faction_id||'';if(affilEl){affilEl.style.background=FACTION_COLORS[fk2]||'#78909C';affilEl.title=FACTION_DISPLAY[fk2]||fk2}
if(expandedNpc===nId){
var thoughts=npc.recent_thoughts||npc.thoughts||[];var thoughtsEl=ncard.querySelector('[data-field="thoughts"]');
if(thoughtsEl){if(Array.isArray(thoughts)&&thoughts.length){var thtml='';for(var t=0;t<Math.min(thoughts.length,4);t++){var th=thoughts[t];var thText=typeof th==='string'?th:(th.thought||th.text||JSON.stringify(th));var thMood=(typeof th==='object'&&th.mood)?' ['+esc(th.mood)+']':'';thtml+='<div class="npc-thought">'+esc(thText)+thMood+'</div>'}thoughtsEl.innerHTML=thtml}else{thoughtsEl.textContent='None available'}}
var decisions=npc.recent_decisions||npc.decisions||[];var decDetailEl=ncard.querySelector('[data-field="decisions"]');
if(decDetailEl){if(Array.isArray(decisions)&&decisions.length){var dhtml='';for(var d=0;d<Math.min(decisions.length,4);d++){var dc=decisions[d];var dcText=typeof dc==='string'?dc:(dc.description||dc.decision||dc.category||JSON.stringify(dc));dhtml+='<div class="npc-thought">'+esc(dcText)+'</div>'}decDetailEl.innerHTML=dhtml}else{decDetailEl.textContent='None available'}}
var actions=npc.recent_actions||npc.actions||[];var actDetailEl=ncard.querySelector('[data-field="actions"]');
if(actDetailEl){if(Array.isArray(actions)&&actions.length){var ahtml='';for(var ai=0;ai<Math.min(actions.length,4);ai++){var ra=actions[ai];var raText=typeof ra==='string'?ra:(ra.description||ra.action_type||ra.action||JSON.stringify(ra));ahtml+='<div class="npc-thought">'+esc(raText)+'</div>'}actDetailEl.innerHTML=ahtml}else{actDetailEl.textContent='None available'}}
var corrEl=ncard.querySelector('[data-field="corruption"]');if(corrEl){var corr=npc.corruption_level!=null?npc.corruption_level:(npc.corruption!=null?npc.corruption:0);var rum=npc.rumor_level!=null?npc.rumor_level:(npc.rumor!=null?npc.rumor:0);corrEl.innerHTML='<span style="color:var(--red)">'+Math.round(corr)+'%</span> / <span style="color:var(--amber)">'+Math.round(rum)+'%</span>'}
var relEl=ncard.querySelector('[data-field="relationships"]');if(relEl){var rels=npc.relationships||npc.relations||{};var rkeys=Object.keys(rels);if(rkeys.length){var rhtml='';for(var ri=0;ri<Math.min(rkeys.length,8);ri++){var rk=rkeys[ri],rv=rels[rk];var rval=typeof rv==='number'?rv:(rv.score!=null?rv.score:(rv.value!=null?rv.value:(rv.trust!=null?rv.trust:0)));var rvc=rval>50?'#4CAF50':(rval>20?'#FFC107':'#F44336');rhtml+='<span class="npc-rel" style="border-left:2px solid '+rvc+'">'+esc(rk)+': '+Math.round(rval)+'</span>'}relEl.innerHTML=rhtml}else{relEl.textContent='None available'}}
}
}
/* After rendering NPCs, update cascade badges and filter */
updateNpcCascadeBadges();
applyNpcFilter();
}

/* ═══ QUEST HEALTH SUMMARY ═══ */
function renderQuestHealth(data) {
if (!data || !data.quest_log) return;
var entries = data.quest_log;
if (!Array.isArray(entries)) return;
var counts = { accept:0, complete:0, abandon:0, progress:0, timeout:0 };
var typeCounts = {};
for (var i = 0; i < entries.length; i++) {
var evt = String(entries[i].event || '').toLowerCase();
if (evt.indexOf('accept') !== -1) counts.accept++;
else if (evt.indexOf('complet') !== -1) counts.complete++;
else if (evt.indexOf('abandon') !== -1 || evt.indexOf('fail') !== -1) { counts.abandon++; if (evt.indexOf('timeout') !== -1 || (entries[i].reason && String(entries[i].reason).toLowerCase().indexOf('timeout') !== -1)) counts.timeout++; }
else counts.progress++;
var qType = entries[i].quest_type || entries[i].quest_id || 'unknown';
if (qType.indexOf('_') !== -1) { var parts = qType.split('_'); if (parts.length > 2) qType = parts.slice(0,2).join('_'); }
typeCounts[qType] = (typeCounts[qType] || 0) + 1;
}
var total = entries.length;
var timeoutRate = total > 0 ? Math.round((counts.timeout / total) * 100) : 0;
var trColor = timeoutRate > 30 ? 'var(--red)' : (timeoutRate > 15 ? 'var(--amber)' : 'var(--green)');
var gridEl = document.getElementById('qh-grid');
gridEl.innerHTML =
'<div class="qh-stat"><span class="qh-stat-val" style="color:var(--cyan)">' + total + '</span><span class="qh-stat-label">Total</span></div>' +
'<div class="qh-stat"><span class="qh-stat-val" style="color:var(--green)">' + counts.accept + '</span><span class="qh-stat-label">Accepted</span></div>' +
'<div class="qh-stat"><span class="qh-stat-val" style="color:var(--amber)">' + counts.complete + '</span><span class="qh-stat-label">Completed</span></div>' +
'<div class="qh-stat"><span class="qh-stat-val" style="color:var(--red)">' + counts.abandon + '</span><span class="qh-stat-label">Abandoned</span></div>' +
'<div class="qh-stat"><span class="qh-stat-val" style="color:' + trColor + '">' + timeoutRate + '%</span><span class="qh-stat-label">Timeout Rate</span></div>';
var typesEl = document.getElementById('qh-types');
var sortedTypes = Object.keys(typeCounts).sort(function(a,b){return typeCounts[b]-typeCounts[a]});
var tHtml = '';
for (var t = 0; t < Math.min(sortedTypes.length, 5); t++) {
tHtml += '<span class="qh-type-tag">' + esc(sortedTypes[t].replace(/_/g,' ')) + ' (' + typeCounts[sortedTypes[t]] + ')</span>';
}
typesEl.innerHTML = tHtml;
}

function renderQuests(data){
if(!data||!data.quest_log)return;
renderQuestHealth(data);
var log=document.getElementById('quest-log');
var entries=data.quest_log;if(!Array.isArray(entries))return;
var needsRebuild=log.children.length!==entries.length||log.dataset.keySig!==entries.map(function(e){return e.char_id+'_'+e.quest_id+'_'+e.event}).join('|');
if(needsRebuild){
log.dataset.keySig=entries.map(function(e){return e.char_id+'_'+e.quest_id+'_'+e.event}).join('|');log.innerHTML='';
for(var i=0;i<entries.length;i++){
(function(entry,idx){
var el=document.createElement('div');
var evtLower=String(entry.event||'').toLowerCase();
var cls='quest-entry';var eventClass='progress';
if(evtLower.indexOf('accept')!==-1){cls+=' quest-accept';eventClass='accept'}
else if(evtLower.indexOf('complet')!==-1){cls+=' quest-complete';eventClass='complete'}
else if(evtLower.indexOf('abandon')!==-1||evtLower.indexOf('fail')!==-1){cls+=' quest-abandon';eventClass='abandon'}
else{cls+=' quest-progress'}
el.className=cls;el.dataset.charId=entry.char_id||'';
var evtLabel=entry.event||'PROGRESS';
el.innerHTML='<span class="quest-time">'+esc(String(entry.timestamp||''))+'</span><span class="quest-event '+eventClass+'">'+esc(evtLabel.toUpperCase())+'</span><span class="quest-body"><strong>'+esc(entry.char_id||'Unknown')+'</strong> \u2014 '+esc(entry.quest_id||'')+(entry.reason?' <span style="color:var(--dim)">('+esc(entry.reason)+')</span>':'')+'</span>';
el.addEventListener('click',function(){loadQuestDetail(entry.char_id)});
log.appendChild(el);
})(entries[i],i);
}
}
}

async function loadQuestDetail(charId){
if(!charId)return;var detailArea=document.getElementById('quest-detail-area');
if(expandedQuestNpc===charId){expandedQuestNpc=null;detailArea.innerHTML='';return}
expandedQuestNpc=charId;
detailArea.innerHTML='<div class="loading-pulse" style="color:var(--dim);padding:8px">Loading quest detail...</div>';
var data=await apiFetch('/simulation/npc-quests/'+encodeURIComponent(charId),10000);
if(!data){detailArea.innerHTML='<div style="color:var(--red);padding:8px">Failed to load quest detail</div>';return}
var html='<div class="quest-detail">';
html+='<div class="quest-detail-title">'+esc(charId)+' \u2014 Quest Status</div>';
html+='<div class="quest-stats">';
html+='<div class="quest-stat"><span class="quest-stat-val" style="color:var(--green)">'+(data.completed_count||0)+'</span><span class="quest-stat-label">Completed</span></div>';
html+='<div class="quest-stat"><span class="quest-stat-val" style="color:var(--red)">'+(data.failed_count||0)+'</span><span class="quest-stat-label">Failed</span></div>';
html+='<div class="quest-stat"><span class="quest-stat-val" style="color:var(--cyan)">'+(data.active_quests?data.active_quests.length:0)+'</span><span class="quest-stat-label">Active</span></div>';
html+='</div>';
if(data.active_quests&&data.active_quests.length){
for(var q=0;q<data.active_quests.length;q++){
var quest=data.active_quests[q];
html+='<div style="margin-top:10px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.06)">';
html+='<div style="font-family:Orbitron,sans-serif;font-size:13px;color:var(--amber);margin-bottom:4px">'+esc(quest.title||quest.quest_id||'Unknown Quest')+'</div>';
if(quest.description)html+='<div class="quest-detail-desc">'+esc(quest.description)+'</div>';
if(quest.objectives&&quest.objectives.length){
for(var o=0;o<quest.objectives.length;o++){
var obj=quest.objectives[o];var target=obj.target||1;var current=obj.current_progress||0;
var pct=target>0?Math.round((current/target)*100):0;var completed=obj.completed||false;
var fillClass=completed?' done':'';var fillColor=completed?'':' style="background:var(--cyan)"';
html+='<div class="quest-objective"><div class="quest-obj-label"><span class="quest-obj-name">'+esc(obj.description||obj.objective_type||'Objective')+'</span><span class="quest-obj-pct">'+(completed?'DONE':pct+'%')+'</span></div><div class="quest-obj-bar"><div class="quest-obj-fill'+fillClass+'"'+fillColor+' style="width:'+clamp(pct,0,100)+'%"></div></div></div>';
}
}
if(quest.rewards){var rewardStr=typeof quest.rewards==='string'?quest.rewards:JSON.stringify(quest.rewards);html+='<div class="quest-reward">Rewards: '+esc(rewardStr)+'</div>'}
html+='</div>';
}
}
html+='</div>';detailArea.innerHTML=html;
}

function renderFactionTech(data){
if(!data||!data.factions)return;var list=document.getElementById('tech-list');var factions=data.factions;var keys=Object.keys(factions);
var needsRebuild=list.children.length!==keys.length||list.dataset.keySig!==keys.join('|');
if(needsRebuild){
list.dataset.keySig=keys.join('|');list.innerHTML='';
for(var i=0;i<keys.length;i++){
(function(fk){
var f=factions[fk],color=FACTION_COLORS[fk]||'#78909C',display=FACTION_DISPLAY[fk]||fk.replace(/_/g,' ');
var card=document.createElement('div');card.className='tech-card';card.dataset.techFaction=fk;
card.innerHTML='<div class="tech-header"><span class="tech-faction" style="color:'+color+'">'+esc(display)+'</span></div><div class="tech-project" data-field="tech-name">No active research</div><div class="tech-progress"><div class="tech-progress-label"><span data-field="tech-pct-label">Progress</span><span class="tech-progress-pct" data-field="tech-pct">0%</span></div><div class="tech-progress-bar"><div class="tech-progress-fill" data-field="tech-fill" style="width:0"></div></div></div><div class="tech-meta"><span class="tech-meta-item">Turns left: <span class="tech-meta-val" data-field="tech-turns">\u2014</span></span><span class="tech-meta-item">RP invested: <span class="tech-meta-val" data-field="tech-rp">0</span></span><span class="tech-meta-item">Total RP: <span class="tech-meta-val" data-field="tech-total-rp">0</span></span></div><div class="tech-completed" data-field="tech-completed"></div>';
list.appendChild(card);
})(keys[i]);
}
}
for(var ui=0;ui<keys.length;ui++){
var uk=keys[ui],uf=factions[uk];var ucard=list.querySelector('[data-tech-faction="'+uk+'"]');if(!ucard)continue;
var research=uf.active_research||null;var progressPct=uf.progress_percent!=null?uf.progress_percent:0;
if(research){
var techName=ucard.querySelector('[data-field="tech-name"]');if(techName)techName.textContent=research.technology||'Unknown Tech';
var pct=research.progress_percentage!=null?research.progress_percentage:progressPct;
var pctClamped=clamp(pct,0,100);var pctEl=ucard.querySelector('[data-field="tech-pct"]');if(pctEl)pctEl.textContent=Math.round(pctClamped)+'%';
var fillEl=ucard.querySelector('[data-field="tech-fill"]');if(fillEl)fillEl.style.width=pctClamped+'%';
var turnsEl=ucard.querySelector('[data-field="tech-turns"]');if(turnsEl)turnsEl.textContent=research.turns_remaining!=null?research.turns_remaining:'\u2014';
var rpEl=ucard.querySelector('[data-field="tech-rp"]');if(rpEl)rpEl.textContent=research.research_points_invested!=null?research.research_points_invested:'0';
}else{
var noTechName=ucard.querySelector('[data-field="tech-name"]');if(noTechName)noTechName.innerHTML='<span class="tech-no-research">No active research</span>';
var noFillEl=ucard.querySelector('[data-field="tech-fill"]');if(noFillEl)noFillEl.style.width='0%';
var noPctEl=ucard.querySelector('[data-field="tech-pct"]');if(noPctEl)noPctEl.textContent='0%';
}
var totalRpEl=ucard.querySelector('[data-field="tech-total-rp"]');if(totalRpEl)totalRpEl.textContent=uf.research_points!=null?uf.research_points:'0';
var completedEl=ucard.querySelector('[data-field="tech-completed"]');
if(completedEl){var completed=uf.completed_techs||[];if(completed.length){var chtml='<div style="margin-bottom:3px;text-transform:uppercase;letter-spacing:1px;font-size:13px;color:var(--dim)">Completed</div>';for(var c=0;c<Math.min(completed.length,8);c++){chtml+='<span class="tech-completed-tag">'+esc(typeof completed[c]==='string'?completed[c]:(completed[c].name||completed[c].technology||JSON.stringify(completed[c])))+'</span> '}if(completed.length>8)chtml+='<span style="font-size:13px;color:var(--dim)">+'+(completed.length-8)+' more</span>';completedEl.innerHTML=chtml}else{completedEl.innerHTML=''}}
}
}

function renderChoices(data){
if(!data||!data.stats)return;var list=document.getElementById('choice-list');var stats=data.stats;
var entries=[];for(var key in stats){if(stats.hasOwnProperty(key)){entries.push({id:key,count:stats[key]})}}
entries.sort(function(a,b){return b.count-a.count});var maxCount=entries.length?entries[0].count:1;if(maxCount<1)maxCount=1;
var needsRebuild=list.children.length!==entries.length||list.dataset.keySig!==entries.map(function(e){return e.id}).join('|');
if(needsRebuild){
list.dataset.keySig=entries.map(function(e){return e.id}).join('|');list.innerHTML='';
for(var i=0;i<entries.length;i++){
(function(entry,rank){
var el=document.createElement('div');el.className='choice-item';el.dataset.choiceId=entry.id;
var barPct=Math.round((entry.count/maxCount)*100);
el.innerHTML='<span class="choice-rank">'+(rank+1)+'</span><span class="choice-id">'+esc(entry.id)+'</span><span class="choice-count">'+entry.count+'</span><div class="choice-bar-container"><div class="choice-bar"><div class="choice-bar-fill" style="width:'+barPct+'%"></div></div></div>';
el.addEventListener('click',function(){var factionId=entry.id;if(factionId.indexOf('_')!==-1){var parts=factionId.split('_');if(parts.length>=2)factionId=parts[0]+'_'+parts[1]}if(FACTION_DISPLAY[factionId]){loadFactionChoiceDetail(factionId)}else{loadFactionChoiceDetail(entry.id)}});
list.appendChild(el);
})(entries[i],i);
}
}else{for(var u=0;u<entries.length;u++){var existing=list.children[u];if(existing){var barPct2=Math.round((entries[u].count/maxCount)*100);var countEl=existing.querySelector('.choice-count');if(countEl)countEl.textContent=entries[u].count;var fillEl=existing.querySelector('.choice-bar-fill');if(fillEl)fillEl.style.width=barPct2+'%'}}}
}

async function loadFactionChoiceDetail(factionId){
if(!factionId)return;var detailArea=document.getElementById('faction-choice-detail-area');
if(expandedChoiceFaction===factionId){expandedChoiceFaction=null;detailArea.innerHTML='';return}
expandedChoiceFaction=factionId;var displayName=FACTION_DISPLAY[factionId]||factionId.replace(/_/g,' ');
detailArea.innerHTML='<div class="loading-pulse" style="color:var(--dim);padding:8px">Loading choices for '+esc(displayName)+'...</div>';
var data=await apiFetch('/simulation/choice-resolutions/'+encodeURIComponent(factionId),10000);
if(!data){detailArea.innerHTML='<div style="color:var(--red);padding:8px">Failed to load faction choices</div>';return}
var html='<div class="faction-choice-detail"><div class="faction-choice-title">'+esc(displayName)+' \u2014 Choice History</div>';
if(data.choice_history&&data.choice_history.length){html+='<div class="faction-choice-history">';for(var i=0;i<data.choice_history.length;i++){var ch=data.choice_history[i];html+='<div class="faction-choice-entry">'+esc(typeof ch==='string'?ch:(ch.choice_id||ch.description||JSON.stringify(ch)))+'</div>'}html+='</div>'}else{html+='<div style="font-size:13px;color:var(--dim)">No choice history available</div>'}
html+='</div>';detailArea.innerHTML=html;
}

function renderBottom(status){
if(!status)return;
var era=status.current_era||status.era||status.currentEra||{};
var eraName=era.name||era.era_name||era.label||status.era_name||'Unknown Era';
document.getElementById('era-name').textContent=eraName;
var progress=era.progress!=null?era.progress:(era.progress_pct!=null?era.progress_pct:(era.progressPercent!=null?era.progressPercent:0));
var eraPct=clamp(progress,0,100);
document.getElementById('era-fill').style.width=eraPct+'%';document.getElementById('era-pct').textContent=Math.round(eraPct)+'%';
var triggers=era.recent_triggers||era.triggers||status.era_triggers||[];
var trigEl=document.getElementById('era-triggers');
if(Array.isArray(triggers)&&triggers.length){var thtml='';for(var t=0;t<Math.min(triggers.length,5);t++){var tr=triggers[t];thtml+='<span class="bottom-trigger">'+esc(typeof tr==='string'?tr:(tr.name||tr.description||JSON.stringify(tr)))+'</span>'}trigEl.innerHTML=thtml}else{trigEl.innerHTML=''}
var pending=status.pending_items||status.pendingItems||{};var total=0;var pKeys=Object.keys(pending);
for(var p=0;p<pKeys.length;p++){var pv=pending[pKeys[p]];total+=typeof pv==='number'?pv:(Array.isArray(pv)?pv.length:0)}
document.getElementById('pending-items').innerHTML='What Is Unresolved: <strong>'+total+'</strong>';
}

function showSignalLost(show){document.getElementById('signal-lost-center').classList.toggle('visible',show)}

async function refreshLight(){
var results=await Promise.all([apiFetch('/simulation/status',8000),apiFetch('/simulation/factions',8000),apiFetch('/simulation/events',8000)]);
var status=results[0],factions=results[1],events=results[2];
var anyOk=status||factions||events;
if(!anyOk){fetchErrorCount++;if(fetchErrorCount>=3)showSignalLost(true)}else{fetchErrorCount=0;showSignalLost(false);if(status)lastData.status=status;if(factions)lastData.factions=factions;if(events)lastData.events=events}
if(lastData.status){updateTopBanner(lastData.status);updateSituation(lastData.status)}
if(lastData.factions)renderFactions(lastData.factions);
if(lastData.events)renderEvents(lastData.events);
if(lastData.status)renderBottom(lastData.status);
}

async function refreshNpcs(){var npcs=await apiFetch('/simulation/npcs/activity',12000);if(npcs){lastData.npcs=npcs;showSignalLost(false)}if(lastData.npcs)renderNpcs(lastData.npcs)}
async function refreshQuests(){var data=await apiFetch('/simulation/npc-quests',12000);if(data){lastData.quests=data;showSignalLost(false)}if(lastData.quests)renderQuests(lastData.quests)}
async function refreshFactionTech(){var data=await apiFetch('/simulation/faction-tech',12000);if(data){lastData.factionTech=data;showSignalLost(false)}if(lastData.factionTech)renderFactionTech(lastData.factionTech)}
async function refreshChoices(){var data=await apiFetch('/simulation/choice-resolutions',12000);if(data){lastData.choices=data;showSignalLost(false)}if(lastData.choices)renderChoices(lastData.choices)}

async function refresh(){
var loadingEls=document.querySelectorAll('.section-title');for(var l=0;l<loadingEls.length;l++)loadingEls[l].classList.add('loading-pulse');
await refreshLight();await refreshNpcs();await refreshQuests();await refreshFactionTech();await refreshChoices();
for(var l2=0;l2<loadingEls.length;l2++)loadingEls[l2].classList.remove('loading-pulse');
}

function toggleRaw(){var btn=document.getElementById('raw-toggle'),wrap=document.getElementById('raw-wrap');btn.classList.toggle('open');wrap.classList.toggle('open');btn.setAttribute('aria-expanded',wrap.classList.contains('open'))}
function toggleHelp(){var overlay=document.getElementById('help-overlay');overlay.classList.toggle('open');if(overlay.classList.contains('open')){overlay.focus();document.body.style.overflow='hidden'}else{document.body.style.overflow=''}}
document.addEventListener('keydown',function(e){if(e.key==='Escape'){var overlay=document.getElementById('help-overlay');if(overlay.classList.contains('open'))toggleHelp()}});

function init(){generateStarfield();refresh();setInterval(refreshLight,10000);setInterval(refreshNpcs,30000);setInterval(refreshQuests,20000);setInterval(refreshFactionTech,25000);setInterval(refreshChoices,20000);setInterval(updateTimeSince,1000)}
document.addEventListener('DOMContentLoaded',init);
"""
