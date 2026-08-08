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

/* ═══ UNIFIED VERDICT (single source of truth) ═══ */
function getMetrics(status) {
  var ws = (status && (status.world_state || status.worldState)) || status || {};
  var out = {}, mKeys = ['tension','resources','threat','stability','morale','anomaly'];
  for (var i = 0; i < mKeys.length; i++) {
    var k = mKeys[i], af = METRIC_FIELD_MAP[k] || k;
    out[k] = ws[af] != null ? ws[af] : (ws[k] != null ? ws[k] : 50);
  }
  return out;
}

function computeVerdict(status) {
  status = status || {};
  var m = getMetrics(status);
  var cascade = status.cascade_summary || status.cascadeSummary || {};
  var temp = cascade.temperature != null ? cascade.temperature : (cascade.cascade_temperature != null ? cascade.cascade_temperature : 0);
  var cascadePct = temp > 1.5 ? temp : (temp * 100);
  m.cascade = cascadePct;

  var score = Math.max(
    sevScore('morale', m.morale),
    sevScore('stability', m.stability),
    sevScore('threat', m.threat),
    sevScore('tension', m.tension),
    sevScore('anomaly', m.anomaly),
    sevScore('cascade', cascadePct)
  );
  var state = score >= 4 ? 'crisis' : (score >= 3 ? 'unstable' : (score >= 2 ? 'watch' : 'stable'));
  var labelMap = {stable:'STABLE', watch:'WATCH', unstable:'UNSTABLE', crisis:'CRISIS'};
  var label = labelMap[state];
  var severityClass = 'state-' + state;

  var parts = [];
  if (m.resources > 75) parts.push('resource-rich'); else if (m.resources < 25) parts.push('resource-scarce');
  if (m.stability > 75) parts.push('socially stable'); else if (m.stability < 30) parts.push('socially unstable');
  if (m.morale > 75) parts.push('high morale'); else if (m.morale < 25) parts.push('morale collapsing');
  if (m.tension > 70) parts.push('high tension'); else if (m.tension < 25) parts.push('peaceful');
  if (m.threat > 70) parts.push('under threat');
  if (m.anomaly > 70) parts.push('anomaly activity elevated');
  if (cascadePct > 80) parts.push('cascade chains spreading'); else if (cascadePct < 30) parts.push('experiencing calm events');

  var recentEvents = status.recent_events || [];
  var topEvent = null;
  for (var ei = recentEvents.length - 1; ei >= 0; ei--) {
    var ev = recentEvents[ei];
    if (ev && ev.event_type && ev.event_type !== 'routine') { topEvent = ev; break; }
  }
  if (!topEvent && recentEvents.length > 0) topEvent = recentEvents[recentEvents.length - 1];
  var headline = topEvent && topEvent.description ? topEvent.description
    : (parts.length ? 'The Federation is ' + parts.join(', ') + '.' : 'The Federation is in a balanced state.');

  var riskOrder = [
    {k:'morale',dir:'low'},{k:'stability',dir:'low'},{k:'threat',dir:'high'},
    {k:'tension',dir:'high'},{k:'anomaly',dir:'high'},{k:'cascade',dir:'high'}
  ];
  var worstRisk = null, worstScore = -1;
  for (var r = 0; r < riskOrder.length; r++) {
    var rk = riskOrder[r], si = severityInfo(rk.k, m[rk.k]);
    var sc = si.cls.indexOf('critical')!==-1 ? 4 : (si.cls.indexOf('severe')!==-1 ? 3 : (si.cls.indexOf('breach')!==-1 ? 3 : (si.cls.indexOf('overheating')!==-1 ? 3 : (si.cls.indexOf('high')!==-1 ? 2 : (si.cls.indexOf('unstable')!==-1 ? 2 : (si.cls.indexOf('hot')!==-1 ? 2 : 0))))));
    if (sc > worstScore) { worstScore = sc; worstRisk = rk.k; }
  }
  var mainRisk = 'No active risks detected';
  if (worstRisk) {
    var rsi = severityInfo(worstRisk, m[worstRisk]);
    var rName = worstRisk.charAt(0).toUpperCase() + worstRisk.slice(1);
    if (worstRisk === 'cascade') rName = 'Cascade Temperature';
    mainRisk = rName + ' is ' + rsi.label + ' (' + Math.round(m[worstRisk]) + (worstRisk === 'cascade' ? '%' : '') + ')';
  }

  var careMap = {
    crisis: 'Active crisis pressure. Systems may cascade-fail without intervention.',
    unstable: 'Conditions are unstable. Small NPC choices can now trigger larger faction cascades.',
    watch: 'Watch key pressures \u2014 stability, morale, and threat shifts matter now.',
    stable: 'The important story is who gains trust, who loses patience, and who starts a cascade.'
  };

  var watchItems = [];
  if (m.morale < 40) watchItems.push('Morale ' + Math.round(m.morale));
  if (m.stability < 40) watchItems.push('Stability ' + Math.round(m.stability));
  if (m.threat > 60) watchItems.push('Threat ' + Math.round(m.threat));
  if (m.tension > 60) watchItems.push('Tension ' + Math.round(m.tension));
  if (m.anomaly > 60) watchItems.push('Anomaly ' + Math.round(m.anomaly));
  if (cascadePct > 70) watchItems.push('Cascade ' + Math.round(cascadePct) + '%');

  return {
    state: state, label: label, severityClass: severityClass,
    headline: headline, mainRisk: mainRisk, careText: careMap[state], watchItems: watchItems
  };
}

/* ═══ NEW: TOP BANNER (replaces updateTopRibbon) ═══ */
function updateTopBanner(status) {
if (!status) return;
var ws = status.world_state || status.worldState || status;

/* Extract metric values (single source via getMetrics) */
var metrics = getMetrics(status);

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

/* Tick counter + Federation Date */
var tick = '\u2014';
if (status.last_tick_result && status.last_tick_result.tick_ts) tick = status.last_tick_result.tick_ts;
else if (status.last_tick_timestamp) tick = status.last_tick_timestamp;
else if (ws.tick_count != null) tick = ws.tick_count;
var tickEl = document.getElementById('tick-count');
if (tickEl) tickEl.textContent = tick;
/* Federation Calendar date */
var fedEl = document.getElementById('fed-date');
if (fedEl) {
  if (tick && tick !== '\u2014') {
    var fullDate = formatFedDateFull(tick);
    var shortDate = formatFedDateShort(tick);
    fedEl.textContent = shortDate;
    fedEl.title = fullDate;
  } else {
    fedEl.textContent = '\u2014';
  }
}

lastTickTime = Date.now();
}

function updateTimeSince(){if(!lastTickTime)return;var elapsed=(Date.now()-lastTickTime)/1000;var el=document.getElementById('time-since');if(el)el.textContent=formatTime(elapsed)}

/* ═══ FEDERATION STATUS BRIEF ═══ */
function updateFedBrief() {
  var status = lastData.status;
  if (!status) return;
  var ws = status.world_state || status.worldState || status;
  var v = computeVerdict(status);

  var badge = document.getElementById('brief-state-badge');
  if (badge) {
    badge.textContent = v.label;
    badge.className = 'brief-state-badge ' + v.severityClass;
  }

  var meta = document.getElementById('brief-meta');
  if (meta) {
    var tick = status.tick_count || ws.tick_count || '\u2014';
    var metaText = 'Tick '+tick;
    if (status.last_tick_timestamp) metaText += ' \u00b7 '+formatFedDateShort(status.last_tick_timestamp);
    meta.textContent = metaText;
  }

  var headline = document.getElementById('brief-headline');
  if (headline) headline.textContent = v.headline;

  var devEl = document.getElementById('brief-developments');
  if (devEl) {
    var allEvents = (status.recent_events||[]).slice();
    var evts = lastData.events;
    if (evts) {
      if (Array.isArray(evts)) allEvents = allEvents.concat(evts);
      else { if(evts.world_events) allEvents=allEvents.concat(evts.world_events.slice(-5)); if(evts.cascade_events) allEvents=allEvents.concat(evts.cascade_events.slice(-3)) }
    }
    var devHtml='',shown=0,seen={};
    for (var ei=allEvents.length-1;ei>=0&&shown<3;ei--) {
      var ev=allEvents[ei]; if(!ev) continue;
      var desc=ev.description||ev.text||ev.summary||'';
      if(!desc||seen[desc]) continue; seen[desc]=true;
      devHtml += '<span class="brief-dev-item">'+esc(desc.substring(0,100))+'</span>'; shown++;
    }
    devEl.innerHTML = devHtml;
  }

  var watchEl = document.getElementById('brief-watch');
  if (watchEl) {
    if (v.watchItems.length === 0) {
      watchEl.innerHTML = '<span class="brief-watch-item">No active watch items</span>';
    } else {
      var wHtml='';
      for (var wi=0;wi<Math.min(v.watchItems.length,3);wi++) wHtml += '<span class="brief-watch-item">\u25cf '+v.watchItems[wi]+'</span>';
      watchEl.innerHTML = wHtml;
    }
  }
}

/* ═══ SITUATION SUMMARY ═══ */
function updateSituation(status) {
if (!status) return;
var ws = status.world_state || status.worldState || status;
var metrics = getMetrics(status);
var cascade = status.cascade_summary || status.cascadeSummary || {};
var temp = cascade.temperature!=null ? cascade.temperature : (cascade.cascade_temperature!=null ? cascade.cascade_temperature : 0);
var cascadePct = temp>1.5 ? temp : (temp*100);
metrics.cascade = cascadePct;
var v = computeVerdict(status);

document.getElementById('sit-current-text').textContent = v.headline;
document.getElementById('sit-risk-text').innerHTML = v.mainRisk;

var watchItems = [];
var questData = lastData.quests || {};
var npcData = lastData.npcs || [];
var _rawEvts = lastData.events || [];
  var eventData;
  if (Array.isArray(_rawEvts)) { eventData = _rawEvts; }
  else if (typeof _rawEvts === 'object') { eventData = (_rawEvts.world_events||[]).concat(_rawEvts.cascade_events||[],_rawEvts.broadcast_events||[]); }
  else { eventData = []; }

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
  wlContainer.innerHTML = '<div class="sit-card-value" style="color:var(--green);font-size:0.875rem">&#10003; No active watch items</div>';
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

var lastData={status:null,factions:null,npcs:null,events:null,quests:null,factionTech:null,choices:null,npcDirectory:null,npcRealityLogs:null};
var fetchErrorCount=0;
var lastTickTime=null;
var expandedFaction=null;
var expandedNpc=null;
var activeLeftTab='factions';
var activeRightTab='npcs';
var expandedQuestNpc=null;
var expandedChoiceFaction=null;
var npcRealityFilter='all';
var npcRealityBusy=false;

function generateStarfield(){var sf=document.getElementById('starfield');for(var i=0;i<80;i++){var s=document.createElement('div');s.className='star';var size=Math.random()*2+1;s.style.cssText='width:'+size+'px;height:'+size+'px;left:'+(Math.random()*100)+'%;top:'+(Math.random()*100)+'%;--dur:'+(2+Math.random()*4)+'s;--delay:'+(Math.random()*3)+'s;opacity:'+(0.2+Math.random()*0.5);sf.appendChild(s)}}

function formatTime(seconds){if(seconds==null||isNaN(seconds))return '\u2014';if(seconds<60)return Math.floor(seconds)+'s';if(seconds<3600)return Math.floor(seconds/60)+'m '+Math.floor(seconds%60)+'s';return Math.floor(seconds/3600)+'h '+Math.floor((seconds%3600)/60)+'m'}

/* ═══ FEDERATION CALENDAR ═══ */
var FEDERATION_EPOCH = 1779825069; // Tick value = Day 1, 00:00 Federation Time
var MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
var WEEK_NAMES = ['Primus','Secundus','Tertius','Quartus','Quintus','Sextus','Septimus'];

function federationTime(tickVal) {
  if (tickVal == null || isNaN(tickVal)) return null;
  var num = typeof tickVal === 'number' ? tickVal : parseInt(tickVal, 10);
  if (isNaN(num)) return null;
  var elapsed = Math.max(0, num - FEDERATION_EPOCH); // seconds of Federation time
  var fedMinute = Math.floor(elapsed / 60);
  var fedHour = Math.floor(fedMinute / 60);
  var fedDay = Math.floor(fedHour / 24); // 0-based
  var minute = fedMinute % 60;
  var hour = fedHour % 24;
  var day = fedDay + 1; // 1-based
  var year = Math.floor(fedDay / 360) + 1;
  var dayOfYear = fedDay % 360;
  var month = Math.floor(dayOfYear / 30);
  var dayOfMonth = (dayOfYear % 30) + 1;
  var week = Math.floor(dayOfYear / 7) + 1;
  var dayOfWeek = dayOfYear % 7;
  return {
    day: day, hour: hour, minute: minute,
    year: year, month: month, dayOfMonth: dayOfMonth,
    week: week, dayOfWeek: dayOfWeek,
    elapsedSeconds: elapsed
  };
}

function formatFedDateShort(tickVal) {
  var ft = federationTime(tickVal);
  if (!ft) return '\u2014';
  var hh = String(ft.hour).padStart(2,'0');
  var mm = String(ft.minute).padStart(2,'0');
  return 'Day '+ft.day+' \u00b7 '+hh+':'+mm;
}

function formatFedDateFull(tickVal) {
  var ft = federationTime(tickVal);
  if (!ft) return '\u2014';
  var hh = String(ft.hour).padStart(2,'0');
  var mm = String(ft.minute).padStart(2,'0');
  var monthName = MONTH_NAMES[ft.month] || '???';
  var weekName = WEEK_NAMES[ft.dayOfWeek] || '???';
  return 'Yr '+ft.year+', '+monthName+' '+ft.dayOfMonth+' ('+weekName+') \u00b7 '+hh+':'+mm;
}

function stanceLabel(stance){if(!stance)return 'neutral';if(typeof stance==='object'&&stance.label)return stance.label.toLowerCase();if(typeof stance==='number'){if(stance>=0.75)return 'ally';if(stance<=0.25)return 'enemy';return 'neutral'}var s=String(stance).toLowerCase();if(s==='ally'||s==='allied'||s==='friendly')return 'ally';if(s==='enemy'||s==='hostile'||s==='adversarial')return 'enemy';return 'neutral'}
function stanceToClass(stance){return stanceLabel(stance)}

function moodLabel(mood){if(mood==null)return '\u2014';if(typeof mood==='string'){var n=parseFloat(mood);if(!isNaN(n))mood=n;else return mood.toLowerCase()}if(typeof mood==='number'){if(mood>=0.9)return 'INSPIRED';if(mood>=0.7)return 'SATISFIED';if(mood>=0.5)return 'CONTEMPLATIVE';if(mood>=0.3)return 'ANXIOUS';return 'FRUSTRATED'}return String(mood)}
function moodColorOf(mood){if(mood==null)return '#78909C';var label=moodLabel(mood).toLowerCase();return MOOD_COLORS[label]||'#78909C'}
function cascadeColor(pct){if(pct<30)return '#4CAF50';if(pct<60)return '#FF9800';if(pct<85)return '#F44336';return '#E91E63'}
function esc(s){if(s==null)return '';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

/* ═══ Markdown → HTML for AI assistant responses ═══ */
function md(text){
  if(text==null)return '';
  // Escape HTML first to prevent XSS
  var s = String(text).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  // Inline conversions (before block wrapping)
  s = s.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>');
  s = s.replace(/\*(.+?)\*/g,'<em>$1</em>');
  s = s.replace(/`(.+?)`/g,'<code>$1</code>');
  // Block-level conversions (applied per-line)
  s = s.replace(/^### (.+)$/gm,'<h3>$1</h3>');
  s = s.replace(/^## (.+)$/gm,'<h2>$1</h2>');
  s = s.replace(/^# (.+)$/gm,'<h1>$1</h1>');
  s = s.replace(/^-{3,}$/gm,'<hr>');
  s = s.replace(/^&gt; (.+)$/gm,'<blockquote>$1</blockquote>');
  // List items (unordered and ordered)
  s = s.replace(/^- (.+)$/gm,'<li>$1</li>');
  s = s.replace(/^\d+\.\s(.+)$/gm,'<li>$1</li>');
  // Wrap consecutive list items in <ul>
  s = s.replace(/((?:<li>.*?<\/li>\s*)+)/g,'<ul>$1</ul>');
  // Tables — capture blocks of |...| lines
  s = s.replace(/((?:\|.*\|(?:\s|$)\s*)+)/g, function(m){
    var rows = m.trim().split('\n');
    var html = '<table>';
    for(var r=0;r<rows.length;r++){
      var row = rows[r].trim();
      if(row.match(/^\|[-: ]+\|$/)) continue; // skip separator
      var cells = row.split('|').slice(1,-1);
      // first row is header if second row is a separator
      var isHead = (r===0 && rows.length>1 && rows[1].match(/^\|[-: ]+\|$/));
      var tag = isHead ? 'th' : 'td';
      html += '<tr>';
      for(var c=0;c<cells.length;c++){
        html += '<' + tag + '>' + cells[c].trim() + '</' + tag + '>';
      }
      html += '</tr>';
    }
    html += '</table>';
    return html;
  });
  // Paragraphs and line breaks
  s = s.replace(/\n/g,'<br>');
  // Cleanup: remove <br> immediately after block-closing tags
  s = s.replace(/<\/(h[1-3]|blockquote|ul|table)>\s*<br>/g,'</$1>');
  // Collapse multiple blank lines
  s = s.replace(/(<br>\s*){3,}/g,'<br><br>');
  return s;
}
function clamp(v,lo,hi){return Math.max(lo,Math.min(hi,v))}
function timeAgo(isoStr){if(!isoStr)return '';var t=Date.parse(isoStr);if(isNaN(t))return String(isoStr);var diff=Date.now()-t;if(diff<0)diff=0;var s=Math.floor(diff/1000);if(s<60)return s+'s ago';var m=Math.floor(s/60);if(m<60)return m+'m ago';var h=Math.floor(m/60);if(h<24)return h+'h ago';var d=Math.floor(h/24);return d+'d ago'}

/* ═══ API FETCH - now uses fedFetch ═══ */
async function apiFetch(endpoint, timeoutMs) {
  const key = endpoint.replace(/^\/simulation\//, '').replace(/^\/map\//, '').replace(/\//g, '_');
  const data = await fedFetch(key, endpoint, {timeout: timeoutMs || 8000});
  return data;
}

async function quietJsonFetch(endpoint, timeoutMs) {
  var data = await fedFetch('qfetch', endpoint, { timeout: timeoutMs || 8000, retries: 1, retryDelay: 2000 });
  if (data !== null) return {ok:true, status:200, data:data};
  return {ok:false, status:0, data:null};
}

function normalizeNpcList(data) {
  var raw = [];
  if (Array.isArray(data)) raw = data;
  else if (data && Array.isArray(data.npcs)) raw = data.npcs;
  else if (data && typeof data === 'object') raw = Object.values(data);
  var list = [];
  for (var i=0;i<raw.length;i++) {
    var n = raw[i] || {};
    var id = n.char_id || n.id || n.character_id || n.name;
    if (!id) continue;
    list.push({
      char_id:String(id),
      name:n.name || n.character_name || String(id),
      title:n.title || '',
      affiliation:n.affiliation || n.faction || n.faction_id || 'independent'
    });
  }
  return list;
}

function mergeNpcLists(a,b) {
  var seen = {}, out = [];
  function add(list){
    for (var i=0;i<list.length;i++) {
      var n = list[i];
      if (!n || !n.char_id || seen[n.char_id]) continue;
      seen[n.char_id] = true;
      out.push(n);
    }
  }
  add(a || []); add(b || []);
  return out;
}

async function loadNpcDirectory() {
  if (lastData.npcDirectory && lastData.npcDirectory.length) return lastData.npcDirectory;
  var res = await quietJsonFetch('/npcs?limit=200', 8000);
  if (res.ok) lastData.npcDirectory = normalizeNpcList(res.data);
  return lastData.npcDirectory || [];
}

function npcNameMap() {
  var map = {};
  var combined = mergeNpcLists(normalizeNpcList(lastData.npcs), lastData.npcDirectory || []);
  for (var i=0;i<combined.length;i++) map[combined[i].char_id] = combined[i].name;
  return map;
}

function parseLogData(raw) {
  if (!raw) return {};
  if (typeof raw === 'object') return raw;
  if (typeof raw === 'string') {
    try { return JSON.parse(raw); } catch(e) { return {text:raw}; }
  }
  return {value:raw};
}

function timestampScore(v) {
  if (v == null) return 0;
  if (typeof v === 'number') return v > 100000000000 ? v : v * 1000;
  var n = Number(v);
  if (!isNaN(n)) return n > 100000000000 ? n : n * 1000;
  var d = Date.parse(v);
  return isNaN(d) ? 0 : d;
}

function formatLogTime(v) {
  var score = timestampScore(v);
  if (!score) return 'recent';
  if (score > 946684800000) return timeAgo(new Date(score).toISOString());
  return 'tick ' + String(v);
}

function logTextValue(v) {
  if (v == null || v === '') return '';
  if (Array.isArray(v)) return v.map(logTextValue).filter(Boolean).join('; ');
  if (typeof v === 'object') {
    if (v.description) return String(v.description);
    if (v.text) return String(v.text);
    if (v.action) return String(v.action);
    if (v.action_type) return String(v.action_type).replace(/_/g,' ');
    try { return JSON.stringify(v); } catch(e) { return String(v); }
  }
  return String(v);
}

function firstLogText(data, keys) {
  for (var i=0;i<keys.length;i++) {
    var val = data ? data[keys[i]] : null;
    var text = logTextValue(val);
    if (text) return text;
  }
  return '';
}

function normalizeNpcLogEntry(entry, fallbackNpc, names) {
  if (!entry || typeof entry !== 'object') entry = {data:entry};
  var data = parseLogData(entry.data || entry.data_json || entry.payload || entry.details);
  var charId = entry.char_id || entry.character_id || data.char_id || data.character_id || (fallbackNpc && fallbackNpc.char_id) || '';
  var type = (entry.entry_type || entry.type || entry.category || data.type || data.category || 'activity').toString().toLowerCase();
  var name = entry.character_name || entry.char_name || data.character_name || data.name || names[charId] || (fallbackNpc && fallbackNpc.name) || charId || 'Unknown NPC';
  return {
    id: entry.id || entry.log_id || (charId + ':' + (entry.timestamp || entry.created_at || Math.random())),
    char_id: charId,
    actor: name,
    type: type,
    timestamp: entry.timestamp || entry.created_at || entry.ts || data.timestamp || data.ts,
    score: timestampScore(entry.timestamp || entry.created_at || entry.ts || data.timestamp || data.ts),
    data: data,
    raw: entry
  };
}

function detectNpcSemanticType(log, summary) {
  var text = (summary + ' ' + JSON.stringify(log.data || {})).toLowerCase();
  if (/\b(plan|planning|strategy|objective|goal|quest|prepare|intent)\b/.test(text)) return 'plan';
  if (/\b(alliance|ally|allied|coalition|support|cooperate|accord)\b/.test(text)) return 'alliance';
  if (/\b(conflict|hostile|threat|attack|rival|war|sabotage|betray)\b/.test(text)) return 'conflict';
  return log.type;
}

function summarizeNpcLog(log) {
  var data = log.data || {};
  var type = log.type;
  var summary = '';
  var why = '';
  if (type === 'chat') {
    summary = firstLogText(data, ['response','message','text','prompt']) || 'spoke in conversation';
    why = data.sentiment ? 'Sentiment: ' + data.sentiment : '';
  } else if (type === 'decision') {
    summary = firstLogText(data, ['decision','description','action','action_type','choice','goal','plan']) || 'made a decision';
    why = firstLogText(data, ['reason','motivation','rationale','context']);
  } else if (type === 'interaction') {
    var target = firstLogText(data, ['target','target_name','with','recipient']);
    summary = firstLogText(data, ['description','message','action','action_type','interaction','category']);
    if (!summary) summary = target ? 'interacted with ' + target : 'interacted with another NPC';
    else if (target && summary.toLowerCase().indexOf(target.toLowerCase()) === -1) summary += ' with ' + target;
    why = firstLogText(data, ['outcome','result','sentiment','relationship_change']);
    if (data.relationship_delta != null && !isNaN(Number(data.relationship_delta))) {
      var rel = Number(data.relationship_delta);
      var relText = 'Relationship ' + (rel > 0 ? '+' : '') + rel.toFixed(2).replace(/\.?0+$/,'');
      why = why ? why + ' · ' + relText : relText;
    }
  } else if (type === 'cognition') {
    summary = firstLogText(data, ['thought','reflection','focus','intent','response','text']) || 'formed a private thought';
    why = firstLogText(data, ['mood','emotion','pressure','trigger']);
  } else {
    summary = firstLogText(data, ['description','message','text','action','value']) || logTextValue(log.raw) || 'recorded activity';
    why = firstLogText(data, ['reason','outcome','result']);
  }
  if (summary.length > 220) summary = summary.slice(0,217) + '...';
  if (why.length > 140) why = why.slice(0,137) + '...';
  return {summary:summary,why:why,semantic:detectNpcSemanticType(log, summary)};
}

function npcRealityEntryMatches(log, filter) {
  if (!filter || filter === 'all') return true;
  var summary = summarizeNpcLog(log);
  return log.type === filter || summary.semantic === filter;
}

function renderNpcRealityFeed() {
  var listEl = document.getElementById('npc-reality-list');
  if (!listEl) return;
  var logs = lastData.npcRealityLogs || [];
  var filtered = [];
  for (var i=0;i<logs.length;i++) if (npcRealityEntryMatches(logs[i], npcRealityFilter)) filtered.push(logs[i]);
  filtered.sort(function(a,b){return (b.score||0)-(a.score||0)});
  filtered = filtered.slice(0, 20);
  if (!filtered.length) {
    listEl.innerHTML = '<div class="nrf-empty">No matching NPC activity yet. Open full logs for the archive.</div>';
    return;
  }
  var html = '';
  for (var j=0;j<filtered.length;j++) {
    var log = filtered[j];
    var text = summarizeNpcLog(log);
    var cls = ['decision','interaction','cognition','chat'].indexOf(log.type) !== -1 ? log.type : text.semantic;
    html += '<div class="nrf-item ' + esc(cls) + '">';
    html += '<div class="nrf-row"><span class="nrf-actor">' + esc(log.actor) + '</span><span class="nrf-type">' + esc(text.semantic || log.type) + '</span><span class="nrf-time">' + esc(formatLogTime(log.timestamp)) + '</span></div>';
    html += '<div class="nrf-summary">' + esc(text.summary) + '</div>';
    if (text.why) html += '<div class="nrf-why">' + esc(text.why) + '</div>';
    html += '</div>';
  }
  listEl.innerHTML = html;
}

function renderHumanBriefing() {
  var headline = document.getElementById('hb-headline');
  var what = document.getElementById('hb-what');
  var changed = document.getElementById('hb-changed');
  var care = document.getElementById('hb-care');
  if (!headline || !what || !changed || !care) return;
  var status = lastData.status || {};
  var v = computeVerdict(status);
  if (!lastData.status) headline.textContent = 'Federation is loading its living society.';
  else headline.textContent = v.headline;
  var npcCount = normalizeNpcList(lastData.npcs).length || (lastData.npcDirectory ? lastData.npcDirectory.length : 47);
  what.textContent = npcCount + ' AI citizens, factions, and systems are thinking, reacting, and changing without direct player control.';
  var latestLog = lastData.npcRealityLogs && lastData.npcRealityLogs.length ? lastData.npcRealityLogs.slice().sort(function(a,b){return (b.score||0)-(a.score||0)})[0] : null;
  if (latestLog) {
    var s = summarizeNpcLog(latestLog);
    var actor = latestLog.actor;
    if (/^char_\d{3}$/.test(actor)) { var nm=npcNameMap(); actor = nm[actor] || actor; }
    changed.textContent = actor + ': ' + s.summary;
  } else {
    changed.textContent = 'Waiting for the next NPC decision, conversation, or cognition trace.';
  }
  care.textContent = v.careText;
}

async function fetchNpcRealityEntriesFor(npc, entryType) {
  var logs = [];
  var names = npcNameMap();
  if (!window._npcLogsApiUnavailable) {
    var qs = new URLSearchParams({char_id:npc.char_id,limit:String(entryType ? 8 : 4)});
    if (entryType) qs.set('entry_type', entryType);
    var apiRes = await quietJsonFetch('/api/npc-logs?' + qs.toString(), 7000);
    if (apiRes.ok && apiRes.data) {
      var results = apiRes.data.results || apiRes.data.entries || [];
      for (var i=0;i<results.length;i++) logs.push(normalizeNpcLogEntry(results[i], npc, names));
      return logs;
    }
    if (apiRes.status === 404) window._npcLogsApiUnavailable = true;
  }
  var fallback = '/npcs/' + encodeURIComponent(npc.char_id) + '/log?limit=' + encodeURIComponent(String(entryType ? 8 : 4));
  if (entryType) fallback += '&type=' + encodeURIComponent(entryType);
  var fallbackRes = await quietJsonFetch(fallback, 7000);
  if (fallbackRes.ok && fallbackRes.data) {
    var entries = fallbackRes.data.entries || fallbackRes.data.results || [];
    for (var j=0;j<entries.length;j++) logs.push(normalizeNpcLogEntry(entries[j], npc, names));
  }
  return logs;
}

function setNpcRealityFilter(filter) {
  npcRealityFilter = filter || 'all';
  var btns = document.querySelectorAll('#nrf-filters button');
  for (var i=0;i<btns.length;i++) btns[i].classList.toggle('active', btns[i].dataset.filter === npcRealityFilter);
  renderNpcRealityFeed();
  refreshNpcRealityFeed();
}

async function refreshNpcRealityFeed() {
  if (npcRealityBusy) return;
  npcRealityBusy = true;
  var listEl = document.getElementById('npc-reality-list');
  if (listEl && !lastData.npcRealityLogs) listEl.innerHTML = '<div class="nrf-empty">Loading NPC communications...</div>';
  try {
    var directory = await loadNpcDirectory();
    var active = normalizeNpcList(lastData.npcs);
    var sources = mergeNpcLists(active, directory).slice(0, 48);
    if (!sources.length) {
      lastData.npcRealityLogs = [];
      renderNpcRealityFeed();
      renderHumanBriefing();
      return;
    }
    var coreType = ['chat','decision','interaction','cognition'].indexOf(npcRealityFilter) !== -1 ? npcRealityFilter : null;
    var batches = await Promise.all(sources.map(function(npc){return fetchNpcRealityEntriesFor(npc, coreType)}));
    var all = [];
    for (var i=0;i<batches.length;i++) all = all.concat(batches[i]);
    all.sort(function(a,b){return (b.score||0)-(a.score||0)});
    lastData.npcRealityLogs = all.slice(0, 120);
    renderNpcRealityFeed();
    renderHumanBriefing();
  } finally {
    npcRealityBusy = false;
  }
}
window.setNpcRealityFilter = setNpcRealityFilter;

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
if (label) label.textContent = window.npcFilterOn ? 'Active Only' : 'Show All';
applyNpcFilter();
fedSaveUIState({npc_filter_on:window.npcFilterOn});
}

function applyNpcFilter() {
var cards = document.querySelectorAll('.npc-card-story');
var activeCount = 0;
for (var i = 0; i < cards.length; i++) {
var card = cards[i];
var npcId = card.dataset.npcId;
var cascadeStatus = getNpcCascadeStatus(npcId);
var moodDot = card.querySelector('.npc-mood');
var moodText = moodDot ? moodDot.textContent.toLowerCase() : '';
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
var cards = document.querySelectorAll('.npc-card-story');
for (var i = 0; i < cards.length; i++) {
var card = cards[i];
var npcId = card.dataset.npcId;
var status = getNpcCascadeStatus(npcId);
card.classList.remove('cascade-root','cascade-reactor','cascade-affected','cascade-none');
card.classList.add('cascade-' + status);
var nameDiv = card.querySelector('.npc-story-name');
if (!nameDiv) continue;
var existingBadge = nameDiv.querySelector('.cascade-badge');
if (existingBadge) existingBadge.remove();
  if (status === 'root') {
      var b = document.createElement('span'); b.className = 'cascade-badge trigger'; b.textContent = 'TRIGGER';
      nameDiv.insertBefore(b, nameDiv.firstChild);
    } else if (status === 'reactor') {
      var b2 = document.createElement('span'); b2.className = 'cascade-badge reactor'; b2.textContent = 'REACTOR';
      nameDiv.insertBefore(b2, nameDiv.firstChild);
    }
    /* Skip "AFFECTED" badge — too noisy when many NPCs are in cascade chains */
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
      card.innerHTML='<div class="faction-header"><span class="faction-name" style="color:'+color+'">'+esc(display)+'</span><span class="faction-power" style="color:'+color+'" data-field="power"></span></div><div class="faction-sub"><span class="faction-cohesion-label">Cohesion</span><div class="faction-cohesion-bar"><div class="faction-cohesion-fill" data-field="cohesion-fill" style="width:0"></div></div></div><div class="faction-action" data-field="action"></div><div class="faction-stances">'+stancesHtml+'</div><div class="faction-detail"><div class="detail-stances" data-field="detail-stances"></div><div class="detail-action-history" data-field="detail-history"></div></div>';
      card.addEventListener('click',function(){if(card.classList.contains('expanded')){card.classList.remove('expanded');expandedFaction=null}else{list.querySelectorAll('.faction-card.expanded').forEach(function(c){c.classList.remove('expanded')});card.classList.add('expanded');expandedFaction=fk;fillFactionDetail(fk,factions)}});
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
      /* Update left color strip */
      var leftStrip=ucard; /* the ::before pseudo-element uses this element's state */
      var pwr=ucard.querySelector('[data-field="power"]');if(pwr)pwr.textContent=uf.power!=null?uf.power:(dyn.power!=null?dyn.power:'');
      /* Set left border color to cohesion color */
      ucard.style.setProperty('--cohesion-color',cohesionColor);
      /* Remove any old dynamic style and replace */
      var oldStyle=ucard.querySelector('.cohesion-strip-style');
      if(oldStyle)oldStyle.remove();
      var stripStyle=document.createElement('style');stripStyle.className='cohesion-strip-style';
      stripStyle.textContent='[data-faction="'+uk+'"]::before{background:'+cohesionColor+'}';
      ucard.appendChild(stripStyle);
      var act=ucard.querySelector('[data-field="action"]');if(act){var recentActions=uf.recent_actions||uf.recent_action||[];var actionText='';if(Array.isArray(recentActions)&&recentActions.length>0){var first=recentActions[0];actionText=typeof first==='string'?first:(first.action||first.description||'')}if(actionText){actionText=actionText.replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase()})}act.textContent=actionText}
      /* Highlight dangerous factions */
      ucard.classList.remove('faction-warning','faction-critical');
      if(cohesionPct<30){ucard.classList.add('faction-critical')}
      else if(cohesionPct<40){ucard.classList.add('faction-warning')}
      if(expandedFaction===uk){ucard.classList.add('expanded');fillFactionDetail(uk,factions)}
      }
      /* Remove "all clear" message — we always show the roster */
}

function fillFactionDetail(fk,factions){
var f=factions[fk];if(!f)return;var keys=Object.keys(factions);
var card=document.querySelector('[data-faction="'+fk+'"]');if(!card)return;
var dsEl=card.querySelector('[data-field="detail-stances"]');
if(dsEl){var html='<div style="font-size:0.8125rem;color:var(--dim);margin-bottom:4px;text-transform:uppercase;letter-spacing:1px">Stances</div>';for(var i=0;i<keys.length;i++){var otherK=keys[i];if(otherK===fk)continue;var rawStance=f.stances?f.stances[otherK]:null;var sc=stanceToClass(rawStance);var scColor=sc==='ally'?'#4CAF50':(sc==='enemy'?'#F44336':'#FFC107');var sl=stanceLabel(rawStance);var numVal=(typeof rawStance==='object'&&rawStance.value!=null)?' ('+(rawStance.value*100).toFixed(0)+'%)':'';html+='<div class="detail-stance-row"><span class="detail-stance-name">'+esc(FACTION_DISPLAY[otherK]||otherK)+'</span><span class="detail-stance-val" style="color:'+scColor+'">'+esc(sl)+numVal+'</span></div>'}dsEl.innerHTML=html}
var dhEl=card.querySelector('[data-field="detail-history"]');
if(dhEl){var history=f.recent_actions||f.action_history||[];var hhtml='<div style="font-size:0.8125rem;color:var(--dim);margin-bottom:4px;text-transform:uppercase;letter-spacing:1px">Recent Actions</div>';if(!history.length){hhtml+='<div style="font-size:0.8125rem;color:var(--dim)">No history available</div>'}else{for(var h=0;h<Math.min(history.length,8);h++){var a=history[h];var actionName=typeof a==='string'?a:(a.action||a.description||JSON.stringify(a));actionName=actionName.replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase()});var effectsStr='';if(typeof a==='object'&&a.effects){var effParts=[];for(var ek in a.effects){if(a.effects[ek]!==0)effParts.push(ek+':'+(a.effects[ek]>0?'+':'')+a.effects[ek])}if(effParts.length)effectsStr=' <span style="color:var(--cyan);font-size:0.75rem">['+esc(effParts.join(', '))+']</span>'}hhtml+='<div class="detail-action-item">'+esc(actionName)+effectsStr+'</div>'}}dhEl.innerHTML=hhtml}
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

/* Domino rows — compress into summary block */
if (dominoes.length > 0) {
/* Count by tone */
var toneCounts={fear:0,conflict:0,caution:0,support:0,celebration:0,neutral:0};
var depthCounts={};
var npcByTone={};
for (var di = 0; di < dominoes.length; di++) {
var de = dominoes[di];
var dDepth = de.cascade_depth || de.depth || de.cascadeDepth || 0;
var dName = de.character_name || de.source || de.source_name || de.npc_name || 'Unknown';
var dDesc = de.description || de.message || '';
var dTone = 'neutral';
var dDescLow = dDesc.toLowerCase();
if (dDescLow.indexOf('fear')!==-1 || dDescLow.indexOf('alarmed')!==-1) dTone = 'fear';
else if (dDescLow.indexOf('conflict')!==-1 || dDescLow.indexOf('confront')!==-1) dTone = 'conflict';
else if (dDescLow.indexOf('cautious')!==-1 || dDescLow.indexOf('wary')!==-1) dTone = 'caution';
else if (dDescLow.indexOf('support')!==-1 || dDescLow.indexOf('endorse')!==-1) dTone = 'support';
else if (dDescLow.indexOf('celebrat')!==-1) dTone = 'celebration';
toneCounts[dTone]++;
depthCounts[dDepth]=(depthCounts[dDepth]||0)+1;
if(!npcByTone[dTone])npcByTone[dTone]=[];
if(npcByTone[dTone].length<5)npcByTone[dTone].push(dName);
}
/* Find dominant tone */
var dominantTone='neutral';var maxTone=0;
for(var tn in toneCounts){if(toneCounts[tn]>maxTone){maxTone=toneCounts[tn];dominantTone=tn}}
var toneEmoji={fear:'\uD83D\uDE31',conflict:'\u2694\uFE0F',caution:'\u26A0\uFE0F',support:'\uD83D\uDC4D',celebration:'\uD83C\uDF89',neutral:'\uD83D\uDD0D'};
  /* Build summary — clean Totals Bar with progressive disclosure */
  /* Build tone spread string */
  var toneSpreadParts = [];
  var toneOrder = ['neutral','support','caution','fear','conflict','celebration'];
  for (var to = 0; to < toneOrder.length; to++) {
    var tKey = toneOrder[to];
    if (toneCounts[tKey] > 0) {
      toneSpreadParts.push(toneCounts[tKey] + ' ' + tKey.charAt(0).toUpperCase() + tKey.slice(1));
    }
  }
  var toneSpreadStr = toneSpreadParts.join(', ') || '0 Neutral';
  /* Determine cascade root type label */
  var cascadeTypeLabel = 'Unknown Event';
  if (rootEv) {
    var rType = rootEv.event_type || rootEv.origin_event_type || rootEv.source_event_type || rootEv.cause || '';
    if (rType) cascadeTypeLabel = rType.replace(/_/g, ' ').replace(/\b\w/g, function(c){return c.toUpperCase()});
  }
  pHtml += '<div class="cascade-summary" style="cursor:pointer" title="Click to expand/collapse domino details">';
  pHtml += '<span class="cascade-summary-icon">' + (toneEmoji[dominantTone]||'\uD83D\uDD0D') + '</span>';
  pHtml += '<span class="cascade-summary-text">' + dominoes.length + ' NPCs reacting to a <strong>' + esc(cascadeTypeLabel) + '</strong></span>';
  pHtml += '<div class="cascade-summary-detail">Spread: ' + toneSpreadStr + '</div>';
  pHtml += '<div class="cascade-summary-roster" style="font-size:0.75rem;color:var(--dim);margin-top:2px">Click to expand full roster</div>';
  pHtml += '</div>';
/* Still keep dominoes but collapsed — click to expand */
pHtml += '<div class="pipeline-dominoes" style="max-height:0;overflow:hidden;opacity:0;transition:max-height 0.4s ease,opacity 0.3s ease" id="domino-expand">';
for (var di2 = 0; di2 < Math.min(dominoes.length, 12); di2++) {
var de2 = dominoes[di2];
var dDepth2 = de2.cascade_depth || de2.depth || de2.cascadeDepth || 0;
var dName2 = de2.character_name || de2.source || de2.source_name || de2.npc_name || 'Unknown';
var dDesc2 = de2.description || de2.message || '';
if (dDesc2.length > 80) dDesc2 = dDesc2.substring(0, 77) + '...';
var dTone2 = 'neutral';
var dDescLow2 = dDesc2.toLowerCase();
if (dDescLow2.indexOf('fear')!==-1 || dDescLow2.indexOf('alarmed')!==-1) dTone2 = 'fear';
else if (dDescLow2.indexOf('conflict')!==-1 || dDescLow2.indexOf('confront')!==-1) dTone2 = 'conflict';
else if (dDescLow2.indexOf('cautious')!==-1 || dDescLow2.indexOf('wary')!==-1) dTone2 = 'caution';
else if (dDescLow2.indexOf('support')!==-1 || dDescLow2.indexOf('endorse')!==-1) dTone2 = 'support';
else if (dDescLow2.indexOf('celebrat')!==-1) dTone2 = 'celebration';
pHtml += '<div class="domino-npc">';
pHtml += '<span class="domino-depth">D' + dDepth2 + '</span>';
pHtml += '<span class="domino-name">' + esc(dName2) + '</span>';
pHtml += '<span class="domino-tone ' + dTone2 + '">' + dTone2 + '</span>';
pHtml += '<span class="domino-desc">' + esc(dDesc2) + '</span>';
pHtml += '</div>';
}
if (dominoes.length > 12) {
pHtml += '<div class="pipeline-overflow">+ ' + (dominoes.length - 12) + ' more reactions</div>';
}
pHtml += '</div>';
}

pipelineArea.innerHTML = pHtml;
/* Attach click handlers for cascade summary expand/collapse */
var summaries = pipelineArea.querySelectorAll('.cascade-summary');
for (var si = 0; si < summaries.length; si++) {
  (function(summary) {
    summary.addEventListener('click', function() {
      var expandDiv = summary.nextElementSibling;
      if (expandDiv && expandDiv.id === 'domino-expand') {
        if (expandDiv.style.maxHeight === '0px' || expandDiv.style.maxHeight === '0') {
          expandDiv.style.maxHeight = '600px';
          expandDiv.style.opacity = '1';
          summary.classList.add('cascade-expanded');
        } else {
          expandDiv.style.maxHeight = '0';
          expandDiv.style.opacity = '0';
          summary.classList.remove('cascade-expanded');
        }
      }
    });
  })(summaries[si]);
}
}
}

/* Update activity log summary */
var sumEl=document.getElementById('activity-log-summary');
if(sumEl){var pts=[];if(cascadeEvents.length)pts.push(cascadeEvents.length+' cascade'+(cascadeEvents.length===1?'':'s'));if(grouped.chains.length)pts.push(grouped.chains.length+' chain'+(grouped.chains.length===1?'':'s'));if(grouped.unchained.length)pts.push(grouped.unchained.length+' raw');sumEl.textContent=pts.length?pts.join(', '):'No recent activity'}

/* Render chain cards */
chainsArea.innerHTML = '';
for (var ci = 0; ci < Math.min(grouped.chains.length, 3); ci++) {
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
var countEl=document.getElementById('npc-count');if(countEl)countEl.textContent='('+list.length+' total)';
/* Group by faction */
var byFaction={};
var factionOrder=[];
for(var ni=0;ni<list.length;ni++){
var npc=list[ni];var fk=npc.affiliation||npc.faction||npc.faction_id||'independent';
if(!byFaction[fk]){byFaction[fk]=[];factionOrder.push(fk)}
byFaction[fk].push(npc);
}
/* Render faction groups */
var rebuildKey=factionOrder.join(',')+':'+list.map(function(n){return n.char_id||n.id||n.name||''}).join(',');
var needsRebuild=grid.dataset.keySig!==rebuildKey;
if(needsRebuild){
grid.dataset.keySig=rebuildKey;grid.innerHTML='';
for(var fi=0;fi<factionOrder.length;fi++){
var fk=factionOrder[fi];
var fGroup=byFaction[fk];
var color=FACTION_COLORS[fk]||'#78909C';
var display=FACTION_DISPLAY[fk]||fk.replace(/_/g,' ');
/* Faction header */
var header=document.createElement('div');header.className='npc-faction-group';header.style.cssText='width:100%';
header.innerHTML='<div class="npc-faction-header" style="color:'+color+';background:'+color+'10;border-left:3px solid '+color+'"><span class="npc-faction-dot" style="background:'+color+'"></span>'+esc(display)+'<span class="npc-faction-count">'+fGroup.length+' characters</span></div>';
grid.appendChild(header);
/* Character cards for this faction */
for(var nci=0;nci<fGroup.length;nci++){
(function(npc,idx){
var mapped={id:npc.char_id||npc.id||npc.name||idx,name:npc.name||'Unknown',faction:fk,mood:npc.mood,recent_thoughts:npc.recent_thoughts||npc.thoughts||npc.recentThoughts||[],recent_actions:npc.recent_actions||npc.actions||[],recent_decisions:npc.recent_decisions||npc.decisions||npc.recentDecisions||[],corruption:npc.corruption_level!=null?npc.corruption_level:(npc.corruption!=null?npc.corruption:0)};
var ml=moodLabel(mapped.mood),mc=moodColorOf(mapped.mood);
/* Build status narrative */
var statusText='Status: '+ml;
if(mapped.recent_actions&&mapped.recent_actions.length){var lastAct=mapped.recent_actions[0];var actText=typeof lastAct==='string'?lastAct:(lastAct.description||lastAct.action_type||lastAct.action||'');if(actText)statusText=esc(actText)}
/* Role: use decision category or mood */
var role=mapped.recent_decisions&&mapped.recent_decisions.length?esc(mapped.recent_decisions[0].category||''):'';
var leaderBadge=fk&&FACTION_COLORS[fk]?'<span class="npc-leader-badge" style="font-size:0.625rem;padding:1px 5px;background:'+color+'20;color:'+color+'">LEADER</span>':'';
var card=document.createElement('div');card.className='npc-card-story';card.dataset.npcId=mapped.id;card.setAttribute('tabindex','0');
card.innerHTML='<div class="npc-story-name"><span class="npc-mood" style="color:'+mc+'">\u25CF</span> '+esc(mapped.name)+' '+leaderBadge+'<span class="npc-story-role">'+(role||ml)+'</span></div><div class="npc-story-status">'+statusText+'</div><div class="npc-story-detail"><div class="npc-story-section"><div class="npc-detail-label">\uD83D\uDCDD Recent Thoughts</div><div class="npc-detail-val" data-field="story-thoughts"></div></div><div class="npc-story-section" style="margin-top:6px"><div class="npc-detail-label">\u2694\uFE0F Recent Actions</div><div class="npc-detail-val" data-field="story-actions"></div></div></div>';
card.addEventListener('click',function(){var wasActive=card.classList.contains('active');grid.querySelectorAll('.npc-card-story').forEach(function(c){c.classList.remove('active')});if(!wasActive){card.classList.add('active');expandedNpc=mapped.id}else{expandedNpc=null}});
card.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();card.click()}});
grid.appendChild(card);
})(fGroup[nci],nci);
}
}
}
/* Update data on each tick */
for(var ui=0;ui<list.length;ui++){
var npc=list[ui],nId=npc.char_id||npc.id||npc.name||ui;
var ncard=grid.querySelector('[data-npc-id="'+nId+'"]');if(!ncard)continue;
var ml2=moodLabel(npc.mood),mc2=moodColorOf(npc.mood);
var moodDot=ncard.querySelector('.npc-story-name .npc-mood');if(moodDot){moodDot.style.color=mc2;moodDot.textContent='\u25CF'}
/* Status line */
var statusEl=ncard.querySelector('.npc-story-status');
if(statusEl){var acts=npc.recent_actions||npc.actions||[];if(acts.length){var aText=typeof acts[0]==='string'?acts[0]:(acts[0].description||acts[0].action_type||acts[0].action||'');statusEl.textContent=esc(aText)}else{statusEl.textContent='Status: '+ml2}}
/* Role line */
var roleEl=ncard.querySelector('.npc-story-role');
if(roleEl){var decs=npc.recent_decisions||npc.decisions||[];var roleText=decs.length?(decs[0].category||''):ml2;roleEl.textContent=roleText||ml2}
/* Expanded detail */
if(expandedNpc===nId){
var thoughts=npc.recent_thoughts||npc.thoughts||[];var thoughtsEl=ncard.querySelector('[data-field="story-thoughts"]');
if(thoughtsEl){if(Array.isArray(thoughts)&&thoughts.length){var thtml='';for(var t2=0;t2<Math.min(thoughts.length,3);t2++){var th=thoughts[t2];var thText=typeof th==='string'?th:(th.thought||th.text||JSON.stringify(th));thtml+='<div class="npc-story-thought">'+esc(thText)+'</div>'}thoughtsEl.innerHTML=thtml}else{thoughtsEl.innerHTML='<div style="font-size:0.8125rem;color:var(--dim);font-style:italic">No recent thoughts recorded</div>'}}
var actions=npc.recent_actions||npc.actions||[];var actEl=ncard.querySelector('[data-field="story-actions"]');
if(actEl){if(Array.isArray(actions)&&actions.length){var ahtml='';for(var ai2=0;ai2<Math.min(actions.length,3);ai2++){var ra=actions[ai2];var raText=typeof ra==='string'?ra:(ra.description||ra.action_type||ra.action||JSON.stringify(ra));ahtml+='<div class="npc-story-action">'+esc(raText)+'</div>'}actEl.innerHTML=ahtml}else{actEl.innerHTML='<div style="font-size:0.8125rem;color:var(--dim);font-style:italic">No recent actions</div>'}}
}
/* Cascade badges and filter */
updateNpcCascadeBadges();
applyNpcFilter();
}
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
/* Still compute health but hide the raw display; keep for data dependency */
renderQuestHealth(data);
var log=document.getElementById('quest-log');
var entries=data.quest_log;if(!Array.isArray(entries))return;
var nameMap=npcNameMap();
/* Build narrative entries grouped by event type */
var narrativeMap={active:[],completed:[],abandoned:[]};
for(var i=0;i<entries.length;i++){
var e=entries[i];var evt=String(e.event||'').toLowerCase();
var charName=nameMap[e.char_id]||e.char_id||'Unknown';
var narr={char:charName,rawChar:e.char_id,quest:e.quest_id||'',reason:e.reason||'',ts:e.timestamp||'',tType:''};
if(evt.indexOf('accept')!==-1||evt.indexOf('start')!==-1){narr.tType='active';narrativeMap.active.push(narr)}
else if(evt.indexOf('complet')!==-1){narr.tType='completed';narrativeMap.completed.push(narr)}
else if(evt.indexOf('abandon')!==-1||evt.indexOf('fail')!==-1){narr.tType='abandoned';narrativeMap.abandoned.push(narr)}
else{narr.tType='active';narrativeMap.active.push(narr)}
}
/* Build story-oriented display */
var keySig=JSON.stringify(entries.map(function(e){return e.char_id+'_'+e.event+'_'+e.quest_id}));
var needsRebuild=log.dataset.keySig!==keySig;
if(needsRebuild){
log.dataset.keySig=keySig;log.innerHTML='';
/* Active narrative */
if(narrativeMap.active.length){
var activeSec=document.createElement('div');activeSec.style.marginBottom='10px';
activeSec.innerHTML='<div class="quest-narr-header" style="color:var(--cyan);border-left:3px solid var(--cyan);padding:4px 10px;margin-bottom:6px;font-family:Orbitron,sans-serif;font-size:0.75rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;background:var(--cyan-dim)">\u25B6 In Progress</div>';
for(var ai=0;ai<Math.min(narrativeMap.active.length,10);ai++){
var ae=narrativeMap.active[ai];
var aEl=document.createElement('div');aEl.className='quest-entry quest-progress';aEl.dataset.charId=ae.char;
aEl.innerHTML='<span class="quest-time">'+timeAgo(ae.ts)+'</span><span class="quest-event progress">\u2694\uFE0F</span><span class="quest-body"><strong>'+esc(ae.char)+'</strong> set out to <em>'+esc(ae.quest.replace(/_/g,' '))+'</em>'+(ae.reason?' <span style="color:var(--dim)">('+esc(ae.reason)+')</span>':'')+'</span>';
aEl.addEventListener('click',function(){loadQuestDetail(ae.char)});
activeSec.appendChild(aEl);
}
if(narrativeMap.active.length>10){var moreA=document.createElement('div');moreA.style.cssText='font-size:0.75rem;color:var(--dim);padding:4px 10px';moreA.textContent='+'+(narrativeMap.active.length-10)+' more ongoing activities';activeSec.appendChild(moreA)}
log.appendChild(activeSec);
}
/* Completed narrative */
if(narrativeMap.completed.length){
var compSec=document.createElement('div');compSec.style.marginBottom='10px';
compSec.innerHTML='<div class="quest-narr-header" style="color:var(--green);border-left:3px solid var(--green);padding:4px 10px;margin-bottom:6px;font-family:Orbitron,sans-serif;font-size:0.75rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;background:var(--green-dim)">\u2714\uFE0F Completed</div>';
for(var ci=0;ci<Math.min(narrativeMap.completed.length,6);ci++){
var ce=narrativeMap.completed[ci];
var cEl=document.createElement('div');cEl.className='quest-entry quest-complete';cEl.dataset.charId=ce.char;
cEl.innerHTML='<span class="quest-time">'+timeAgo(ce.ts)+'</span><span class="quest-event complete">\u2714\uFE0F</span><span class="quest-body"><strong>'+esc(ce.char)+'</strong> completed <em>'+esc(ce.quest.replace(/_/g,' '))+'</em></span>';
cEl.addEventListener('click',function(){loadQuestDetail(ce.char)});
compSec.appendChild(cEl);
}
if(narrativeMap.completed.length>6){var moreC=document.createElement('div');moreC.style.cssText='font-size:0.75rem;color:var(--dim);padding:4px 10px';moreC.textContent='+'+(narrativeMap.completed.length-6)+' more completed';compSec.appendChild(moreC)}
log.appendChild(compSec);
}
/* Abandoned narrative */
if(narrativeMap.abandoned.length){
var abanSec=document.createElement('div');
abanSec.innerHTML='<div class="quest-narr-header" style="color:var(--red);border-left:3px solid var(--red);padding:4px 10px;margin-bottom:6px;font-family:Orbitron,sans-serif;font-size:0.75rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;background:var(--red-dim)">\u274C Abandoned / Failed</div>';
for(var bi=0;bi<Math.min(narrativeMap.abandoned.length,4);bi++){
var be=narrativeMap.abandoned[bi];
var bEl=document.createElement('div');bEl.className='quest-entry quest-abandon';bEl.dataset.charId=be.char;
bEl.innerHTML='<span class="quest-time">'+timeAgo(be.ts)+'</span><span class="quest-event abandon">\u274C</span><span class="quest-body"><strong>'+esc(be.char)+'</strong> abandoned <em>'+esc(be.quest.replace(/_/g,' '))+'</em>'+(be.reason?' <span style="color:var(--dim)">('+esc(be.reason)+')</span>':'')+'</span>';
bEl.addEventListener('click',function(){loadQuestDetail(be.char)});
abanSec.appendChild(bEl);
}
log.appendChild(abanSec);
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
var nameMap=npcNameMap();
var displayName=nameMap[charId]||charId;
var html='<div class="quest-detail">';
html+='<div class="quest-detail-title">'+esc(displayName)+' \u2014 Quest Status</div>';
html+='<div class="quest-stats">';
html+='<div class="quest-stat"><span class="quest-stat-val" style="color:var(--green)">'+(data.completed_count||0)+'</span><span class="quest-stat-label">Completed</span></div>';
html+='<div class="quest-stat"><span class="quest-stat-val" style="color:var(--red)">'+(data.failed_count||0)+'</span><span class="quest-stat-label">Failed</span></div>';
html+='<div class="quest-stat"><span class="quest-stat-val" style="color:var(--cyan)">'+(data.active_quests?data.active_quests.length:0)+'</span><span class="quest-stat-label">Active</span></div>';
html+='</div>';
if(data.active_quests&&data.active_quests.length){
for(var q=0;q<data.active_quests.length;q++){
var quest=data.active_quests[q];
html+='<div style="margin-top:10px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.06)">';
html+='<div style="font-family:Orbitron,sans-serif;font-size:0.8125rem;color:var(--amber);margin-bottom:4px">'+esc(quest.title||quest.quest_id||'Unknown Quest')+'</div>';
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
if(completedEl){var completed=uf.completed_techs||[];if(completed.length){var chtml='<div style="margin-bottom:3px;text-transform:uppercase;letter-spacing:1px;font-size:0.8125rem;color:var(--dim)">Completed</div>';for(var c=0;c<Math.min(completed.length,8);c++){chtml+='<span class="tech-completed-tag">'+esc(typeof completed[c]==='string'?completed[c]:(completed[c].name||completed[c].technology||JSON.stringify(completed[c])))+'</span> '}if(completed.length>8)chtml+='<span style="font-size:0.8125rem;color:var(--dim)">+'+(completed.length-8)+' more</span>';completedEl.innerHTML=chtml}else{completedEl.innerHTML=''}}
}
}

function renderChoices(data){
if(!data||!data.stats)return;
var list=document.getElementById('choice-list');
var narrativeEl=document.getElementById('choice-narrative');
var stats=data.stats;
/* Group choices by faction */
var byFaction={};
var totalChoices=0;
for(var key in stats){
if(!stats.hasOwnProperty(key))continue;
totalChoices+=stats[key];
var factionId=key;
if(factionId.indexOf('_')!==-1){var p=factionId.split('_');if(p.length>=2)factionId=p[0]+'_'+p[1]}
if(!byFaction[factionId])byFaction[factionId]=[];
byFaction[factionId].push({id:key,count:stats[key]});
}
/* Sort factions by total choices */
var factionOrder=Object.keys(byFaction).sort(function(a,b){
var sumA=byFaction[a].reduce(function(s,x){return s+x.count},0);
var sumB=byFaction[b].reduce(function(s,x){return s+x.count},0);
return sumB-sumA;
});
/* Narrative intro */
if(narrativeEl){
narrativeEl.innerHTML='The powers have made <strong>'+totalChoices+'</strong> decisions shaping the course of events.';
}
/* Build display */
var keySig=JSON.stringify(Object.keys(stats).sort());
var needsRebuild=list.dataset.keySig!==keySig;
if(needsRebuild){
list.dataset.keySig=keySig;list.innerHTML='';
for(var fi=0;fi<factionOrder.length;fi++){
var fk=factionOrder[fi];
var fChoices=byFaction[fk];
var fTotal=fChoices.reduce(function(s,x){return s+x.count},0);
var color=FACTION_COLORS[fk]||'#78909C';
var display=FACTION_DISPLAY[fk]||fk.replace(/_/g,' ');
/* Faction decision header */
var fHeader=document.createElement('div');fHeader.style.cssText='width:100%;margin-top:'+(fi>0?'8px':'0')+';margin-bottom:4px';
fHeader.innerHTML='<div style="display:flex;align-items:center;gap:6px;font-family:Orbitron,sans-serif;font-size:0.75rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:'+color+';padding:4px 8px;background:'+color+'10;border-left:3px solid '+color+';border-radius:3px"><span style="width:8px;height:8px;border-radius:50%;background:'+color+';flex-shrink:0"></span>'+esc(display)+'<span style="font-size:0.6875rem;font-weight:400;opacity:0.6;margin-left:auto">'+fTotal+' decision'+(fTotal!==1?'s':'')+'</span></div>';
list.appendChild(fHeader);
/* Decision items for this faction */
for(var di=0;di<fChoices.length;di++){
(function(entry){
var el=document.createElement('div');el.className='choice-item';el.dataset.choiceId=entry.id;
var barPct=Math.round((entry.count/Math.max(fChoices[0].count,1))*100);
/* Human-readable choice label */
var choiceLabel=entry.id.replace(fk+'_','').replace(/_/g,' ');
var labelParts=choiceLabel.split(' ');
var narrLabel=labelParts.map(function(w){return w.charAt(0).toUpperCase()+w.slice(1)}).join(' ');
el.innerHTML='<span class="choice-rank">'+entry.count+'</span><span class="choice-id">'+esc(narrLabel)+'</span><div class="choice-bar-container"><div class="choice-bar"><div class="choice-bar-fill" style="width:'+barPct+'%"></div></div></div>';
el.addEventListener('click',function(){loadFactionChoiceDetail(fk)});
list.appendChild(el);
})(fChoices[di]);
}
}
}
}

async function loadFactionChoiceDetail(factionId){
if(!factionId)return;var detailArea=document.getElementById('faction-choice-detail-area');
if(expandedChoiceFaction===factionId){expandedChoiceFaction=null;detailArea.innerHTML='';return}
expandedChoiceFaction=factionId;var displayName=FACTION_DISPLAY[factionId]||factionId.replace(/_/g,' ');
detailArea.innerHTML='<div class="loading-pulse" style="color:var(--dim);padding:8px">Loading choices for '+esc(displayName)+'...</div>';
var data=await apiFetch('/simulation/choice-resolutions/'+encodeURIComponent(factionId),10000);
if(!data){detailArea.innerHTML='<div style="color:var(--red);padding:8px">Failed to load faction choices</div>';return}
var html='<div class="faction-choice-detail"><div class="faction-choice-title">'+esc(displayName)+' \u2014 Choice History</div>';
if(data.choice_history&&data.choice_history.length){html+='<div class="faction-choice-history">';for(var i=0;i<data.choice_history.length;i++){var ch=data.choice_history[i];html+='<div class="faction-choice-entry">'+esc(typeof ch==='string'?ch:(ch.choice_id||ch.description||JSON.stringify(ch)))+'</div>'}html+='</div>'}else{html+='<div style="font-size:0.8125rem;color:var(--dim)">No choice history available</div>'}
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


// ═══ SITUATION ROOM STORY ENGINE ═══

var _sitroomData = null;
var _latestNarration = null;

function fetchNarrationData() {
    apiFetch('/map/narration/latest', 5000).then(function(data) {
        if (data && data.narration) {
            _latestNarration = data.narration;
        }
    }).catch(function(err) { console.warn('[fetchNarrationData]', err); });
}

function _sitCategorize(desc) {
  var d = (desc || '').toLowerCase();
  if (/gathered intel|planted disinformation|sabotage|heist|stole|acquired a valuable|under-the-table|insider|black market|covert|secret|undermine|vanish|illicit|smuggl/.test(d)) return 'scheming';
  if (/blocked unauthorized|enforced security|led a security sweep|repelled|increased surveillance|ordered reinforced|rallied|issued a new directive|conducted a surprise review|broke up/.test(d)) return 'heroism';
  if (/explore|uncharted|expedition|discovered new|stumbled upon|returned with tales|signal source|outpost|charted|frontier/.test(d)) return 'exploration';
  if (/confront|challenged|combat drills|threat level|raised the threat|war|offensive|strike|skirmish|clash|hostile/.test(d)) return 'conflict';
  if (/spy|espionage|uncovered|intel on|infiltrat|intercept|surveillance on/.test(d)) return 'espionage';
  if (/breakthrough|research|published a cautionary|data-share|temporal physics|meditation on the nature|quantum|dimensional|analysis|experiment/.test(d)) return 'science';
  if (/sensed a disturbance|dimensional breach|corruption|anomal|consciousness-aligning|esoteric|strange signal|artifact|ancient|rift/.test(d)) return 'mystery';
  if (/security|reinforced|defenses|void gates|docking|blocked access|sweep|patrol|guard|perimeter/.test(d)) return 'defense';
  return 'other';
}
function _sitSubType(desc){
  var d=(desc||'').toLowerCase();
  if(/gathered intel|intel on|intel breach/.test(d))return{label:'Intel Breach',icon:'\uD83D\uDD0D'};
  if(/planted disinformation|disinformation/.test(d))return{label:'Disinformation',icon:'\uD83D\uDEAB'};
  if(/sabotage/.test(d))return{label:'Sabotage',icon:'\uD83D\uDCA3'};
  if(/heist|stole|acquired a valuable/.test(d))return{label:'Heist',icon:'\uD83D\uDCB0'};
  if(/under-the-table|insider|black market|illicit|smuggl/.test(d))return{label:'Black Market',icon:'\uD83D\uDCB8'};
  if(/covert|secret|vanish/.test(d))return{label:'Covert Op',icon:'\uD83D\uDD75\uFE0F'};
  if(/undermine/.test(d))return{label:'Undermining',icon:'\u2696\uFE0F'};
  if(/spy|espionage|infiltrat|intercept|surveillance/.test(d))return{label:'Espionage',icon:'\uD83D\uDD0E'};
  return{label:'Rogue Activity',icon:'\u2694\uFE0F'};
}



function _sitGroupByNpc(events) {
  var byNpc = {};
  for (var i = 0; i < events.length; i++) {
    var e = events[i];
    var name = e.source_char_name || '';
    // Fallback: extract name from description like "The Trickster gathered intel..."
    if (!name && e.description) {
      var m = e.description.match(/^([A-Z][A-Za-z\s]+?)(?:\s+(?:gathered|planted|acquired|set out|stumbled|exchanged|published|conducted|led|enforced|blocked|increased|ordered|sensed|explored|returned|chart|discovered|sabotage|heist|vanish|smuggl|broke|repelled|rallied|issued|confront|challenged|intercept|infiltrat))/);
      if (m && m[1].trim().length > 2 && m[1].trim().length < 40) name = m[1].trim();
    }
    if (!name && e.name) name = e.name;
    if (!name) continue; // Skip events with no identifiable NPC
    if (!byNpc[name]) byNpc[name] = [];
    byNpc[name].push(e);
  }
  return byNpc;
}

function _sitHtml(text) {
  // Wrap NPC names, faction names, and keywords with semantic spans
  // Dynamic NPC names: build regex from known NPC list
  if (window._sitNpcRegex) {
    text = text.replace(window._sitNpcRegex, '<span class="npc-name">$1</span>');
  }
  // Dynamic faction names: build regex from FACTION_DISPLAY values
  if (window._sitFactionRegex) {
    text = text.replace(window._sitFactionRegex, '<span class="faction-name" style="color:var(--violet)">$1</span>');
  }
  text = text.replace(/\b(crisis|critical|danger|threat|sabotage|doom|collapse|failure)\b/gi, '<span class="danger">$1</span>');
  text = text.replace(/\b(secure|stable|protect|defend|reinforced|recovery|success|breakthrough)\b/gi, '<span class="good">$1</span>');
  text = text.replace(/\b(scheme|covert|secret|illicit|undermine|disinformation|intel|smuggl)\b/gi, '<span class="sneaky">$1</span>');
  return text;
}

function _sitBuildRegexes(data) {
  // Build NPC name regex from actual data
  var npcNames = [];
  if (data && data.npcs) {
    for (var i = 0; i < data.npcs.length; i++) {
      var n = data.npcs[i];
      if (n.name && n.name !== 'Unknown') npcNames.push(n.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    }
  }
  if (npcNames.length > 0) {
    window._sitNpcRegex = new RegExp('\\b(' + npcNames.join('|') + ')\\b', 'g');
  } else {
    window._sitNpcRegex = null;
  }
  // Build faction name regex from FACTION_DISPLAY values
  var factionDisplayVals = [];
  if (typeof FACTION_DISPLAY !== 'undefined') {
    var fk = Object.keys(FACTION_DISPLAY);
    for (var j = 0; j < fk.length; j++) {
      var dv = FACTION_DISPLAY[fk[j]];
      if (dv) factionDisplayVals.push(dv.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    }
  }
  if (factionDisplayVals.length > 0) {
    window._sitFactionRegex = new RegExp('\\b(' + factionDisplayVals.join('|') + ')\\b', 'g');
  } else {
    window._sitFactionRegex = null;
  }
}

function renderSituationRoom() {
    var headlineEl = document.getElementById('sitroom-headline');
    var bodyEl = document.getElementById('sitroom-body');
    if (!headlineEl || !bodyEl) return;

    // Fetch narration FIRST so _latestNarration is populated before we render
    var narrPromise = _latestNarration
        ? Promise.resolve(_latestNarration)
        : apiFetch('/map/narration/latest', 5000).then(function(data) {
            if (data && data.narration) {
                _latestNarration = data.narration;
            }
            return _latestNarration;
        }).catch(function() { return _latestNarration; });

    // We need /map/data for crisis_readout + events; narration is optional
    Promise.allSettled([apiFetch('/map/data', 8000), narrPromise]).then(function(results) {
        var data = results[0].status === 'fulfilled' ? results[0].value : null;
        var narrResult = results[1].status === 'fulfilled' ? results[1].value : _latestNarration;
        if (!data) { headlineEl.textContent = 'Signal interrupted...'; return; }

    // Build dynamic NPC/faction regexes from live data
    _sitBuildRegexes(data);

    var ws = data.world_state || {};
    var crisis = data.crisis_readout || {};
    var events = data.events || [];
    var npcs = data.npcs || [];
    // ── 0. FILTER LLM ARTIFACTS ──
    // Detect LLM chain-of-thought leakage (unfinished thinking, meta-commentary)
    function _isLLMLeak(text) {
        if (!text) return false;
        var t = text.trim().toLowerCase();
        // Common LLM thinking patterns that leak into output
        if (/^(okay|let me|let's|i need to|i should|the user|first,? i|perhaps|maybe i|maybe mention|i'll|so something like)/i.test(t)) return true;
        // Half-sentence that trails off with "..."
        if (/\.{3,}\s*$/.test(text) && text.length < 200) return true;
        return false;
    }
    function _cleanNarr(n) {
        if (!n) return n;
        // Filter headline
        if (_isLLMLeak(n.headline)) n.headline = '';
        // Filter developments — remove leaked thinking
        if (n.developments) {
            n.developments = n.developments.filter(function(d) { return !_isLLMLeak(d); });
        }
        // Filter voices — remove empty/leaked
        if (n.voices) {
            n.voices = n.voices.filter(function(v) { return v && !_isLLMLeak(v); });
        }
        // Filter forewarning
        if (_isLLMLeak(n.forewarning)) n.forewarning = '';
        return n;
    }
    var narr = _cleanNarr(narrResult || _latestNarration);
    var html = '';

    // ── 1. HEADLINE ──
    var headline = crisis.headline || '';
    if (!headline && narr && narr.headline) headline = narr.headline;
    if (!headline) {
            var threat = ws.threat_level || ws.threat || 0;
            var morale = ws.morale || 50;
            var anomaly = ws.anomaly_activity || ws.anomaly || 0;
      if (threat > 70) headline = 'Threat level critical across the Federation';
      else if (anomaly > 70) headline = 'Anomalous readings sweeping the sector';
      else if (morale < 30) headline = 'Morale collapsing across factions';
      else headline = 'Federation status: holding steady';
    }
    headlineEl.textContent = headline;

    // ── 2. THE BIG PICTURE ──
    var bigPic = crisis.plain_english || '';
    if (bigPic) {
      html += '<div class="sitroom-section">';
      html += '<div class="sitroom-section-title">The Big Picture</div>';
      html += '<div class="sitroom-text">' + _sitHtml(bigPic) + '</div>';
      html += '</div>';
    }

    // ── 3. OFFICIAL BRIEFING (from LLM narration) ──
    if (narr && narr.developments && narr.developments.length > 0) {
      html += '<div class="sitroom-section">';
      html += '<div class="sitroom-section-title">Official Briefing</div>';
      for (var d = 0; d < Math.min(narr.developments.length, 3); d++) {
        html += '<div class="sitroom-text" style="margin-bottom:4px">' + _sitHtml(narr.developments[d]) + '</div>';
      }
      html += '</div>';
    }

    // ── 4. VOICES FROM THE Factions ──
    if (narr && narr.voices && narr.voices.length > 0) {
      html += '<div class="sitroom-section">';
      html += '<div class="sitroom-section-title">Voices from the Factions</div>';
      for (var v = 0; v < Math.min(narr.voices.length, 4); v++) {
        var voice = narr.voices[v] || '';
        // Format: "Speaker — quote" or "Speaker: quote"
        var parts = voice.split(/\s*[—–:]\s*/);
        if (parts.length >= 2) {
          html += '<div class="sitroom-voice"><span class="speaker">' + esc(parts[0]) + '</span> — ' + esc(parts.slice(1).join(' — ')) + '</div>';
        } else {
          html += '<div class="sitroom-voice">' + esc(voice) + '</div>';
        }
      }
      html += '</div>';
    }

    // ── 5. CATEGORIZE EVENTS INTO STORY BUCKETS ──
    var buckets = {scheming:[], heroism:[], exploration:[], conflict:[], espionage:[], science:[], mystery:[], defense:[], other:[]};
    for (var e = 0; e < events.length; e++) {
      var ev = events[e];
      var desc = ev.description || ev.name || '';
      var cat = _sitCategorize(desc);
      buckets[cat].push(ev);
    }

  // ── 6. UNDER THE SURFACE — Rogue Activity Dashboard ──
  var schemers = buckets.scheming.concat(buckets.espionage);
  if (schemers.length > 0) {
    html += '<div class="sitroom-section">';
    html += '<div class="sitroom-section-title">Under the Surface</div>';
    /* Group by action sub-type instead of by NPC */
    var subTypes = {};
    for (var st = 0; st < schemers.length; st++) {
      var stEv = schemers[st];
      var stDesc = stEv.description || stEv.name || '';
      var subInfo = _sitSubType(stDesc);
      var stKey = subInfo.label;
      if (!subTypes[stKey]) subTypes[stKey] = {icon: subInfo.icon, label: subInfo.label, npcs: []};
      /* Extract NPC name */
      var stName = stEv.source_char_name || '';
      if (!stName && stDesc) {
        var stMatch = stDesc.match(/^([A-Z][A-Za-z\s]+?)(?:\s+(?:gathered|planted|acquired|set|stumbled|exchanged|published|conducted|led|enforced|blocked|increased|ordered|sensed|explored|returned|chart|discovered|sabotage|heist|vanish|smuggl|broke|repelled|rallied|issued|confront|challenged|intercept|infiltrat))/);
        if (stMatch && stMatch[1].trim().length > 2 && stMatch[1].trim().length < 40) stName = stMatch[1].trim();
      }
      if (!stName && stEv.name) stName = stEv.name;
      if (stName && subTypes[stKey].npcs.indexOf(stName) === -1) {
        subTypes[stKey].npcs.push(stName);
      }
    }
    /* Render as a single dashboard line */
    var rogueParts = [];
    var stKeys = Object.keys(subTypes);
    for (var sk = 0; sk < stKeys.length; sk++) {
      var skInfo = subTypes[stKeys[sk]];
      var npcCount = skInfo.npcs.length;
      var npcList = skInfo.npcs.slice(0, 4).map(function(n){return '<span class="npc-name">' + esc(n) + '</span>';}).join(', ');
      if (skInfo.npcs.length > 4) npcList += ' +' + (skInfo.npcs.length - 4) + ' more';
      rogueParts.push(skInfo.icon + ' <strong>' + npcCount + ' ' + skInfo.label + (npcCount !== 1 ? 's' : '') + '</strong> (' + npcList + ')');
    }
    html += '<div class="sitroom-text">' + rogueParts.join(' <span style="color:var(--dim)">|</span> ') + '</div>';
    html += '</div>';
  }

  // ── 7. MOVEMENT & OPERATIONS ── (Destination Cards)
  var broadcasts = crisis.key_broadcasts || [];
  if (broadcasts.length > 0) {
    html += '<div class="sitroom-section">';
    html += '<div class="sitroom-section-title">Who Is Moving</div>';
    /* Group broadcasts by type for destination cards */
    var bcGroups = {};
    var bcLabels = {
      expedition_launched: {icon: '\uD83D\uDE80', label: 'Deep Space Migration'},
      security_sweep: {icon: '\uD83D\uDEE1\uFE0F', label: 'Guarding Core Gates'},
      covert_operation: {icon: '\uD83D\uDD75\uFE0F', label: 'Shadow Operations'},
      anomaly_investigation: {icon: '\u2728', label: 'Anomaly Response'},
      diplomatic_mission: {icon: '\uD83C\uDF0D', label: 'Diplomatic Corps'},
      resource_extraction: {icon: '\u26CF\uFE0F', label: 'Resource Operations'},
      patrol: {icon: '\uD83D\uDDE1\uFE0F', label: 'Patrol Duty'},
      research_expedition: {icon: '\uD83D\uDD2C', label: 'Research Detail'}
    };
    for (var b = 0; b < broadcasts.length; b++) {
      var bc = broadcasts[b];
      var bcType = 'other';
      var bcSource = '';
      if (typeof bc === 'object' && bc !== null) {
        bcType = bc.type || 'other';
        bcSource = bc.source || '';
      } else if (typeof bc === 'string') {
        bcSource = bc.replace(/^([^:]+):.*/, '$1').trim();
        var bcLow = bc.toLowerCase();
        if (bcLow.indexOf('expedition') !== -1 || bcLow.indexOf('explore') !== -1) bcType = 'expedition_launched';
        else if (bcLow.indexOf('security') !== -1 || bcLow.indexOf('sweep') !== -1) bcType = 'security_sweep';
        else if (bcLow.indexOf('covert') !== -1 || bcLow.indexOf('shadow') !== -1) bcType = 'covert_operation';
        else if (bcLow.indexOf('anomal') !== -1) bcType = 'anomaly_investigation';
        else if (bcLow.indexOf('diplomat') !== -1) bcType = 'diplomatic_mission';
        else if (bcLow.indexOf('resource') !== -1) bcType = 'resource_extraction';
        else if (bcLow.indexOf('patrol') !== -1) bcType = 'patrol';
      }
      if (!bcGroups[bcType]) bcGroups[bcType] = [];
      bcGroups[bcType].push(bcSource);
    }
    /* Render grouped destination cards */
    var bcTypeKeys = Object.keys(bcGroups);
    for (var g = 0; g < bcTypeKeys.length; g++) {
      var gKey = bcTypeKeys[g];
      var gMeta = bcLabels[gKey] || {icon: '\uD83D\uDCCD', label: gKey.replace(/_/g, ' ').replace(/\b\w/g, function(c){return c.toUpperCase()})};
      var gNpcs = bcGroups[gKey].filter(function(n){return n && n.length > 0});
      if (gNpcs.length === 0) continue;
      html += '<div class="sitroom-text" style="margin-bottom:5px">';
      html += gMeta.icon + ' <strong>' + esc(gMeta.label) + ':</strong> ';
      html += gNpcs.slice(0, 6).map(function(n){return '<span class="npc-name">' + esc(n) + '</span>';}).join(', ');
      if (gNpcs.length > 6) html += ' +' + (gNpcs.length - 6) + ' more';
      html += '</div>';
    }
    html += '</div>';
  }

    // ── 8. EXPEDITIONS & DISCOVERIES ──
    if (buckets.exploration.length > 0) {
      html += '<div class="sitroom-section">';
      html += '<div class="sitroom-section-title">Expeditions &amp; Discoveries</div>';
      var exploreByNpc = _sitGroupByNpc(buckets.exploration);
      var eNames = Object.keys(exploreByNpc);
      var eSentences = [];
      for (var en = 0; en < Math.min(eNames.length, 5); en++) {
        var eNpc = eNames[en];
        var eEvts = exploreByNpc[eNpc];
        var eDescs = [];
        for (var ed = 0; ed < Math.min(eEvts.length, 2); ed++) {
          var eDesc = eEvts[ed].description || eEvts[ed].name || '';
          eDesc = eDesc.replace(new RegExp('^' + eNpc.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*', 'i'), '');
          if (eDesc) eDescs.push(eDesc);
        }
        if (eDescs.length > 0) {
          eSentences.push('<span class="npc-name">' + esc(eNpc) + '</span> ' + _sitHtml(eDescs.join(', and ')).toLowerCase());
        }
      }
      html += '<div class="sitroom-text">' + eSentences.join('. ') + '.</div>';
      html += '</div>';
    }

    // ── 9. HOLDING THE LINE (defense + heroism) ──
    var defenders = buckets.defense.concat(buckets.heroism);
    if (defenders.length > 0) {
      html += '<div class="sitroom-section">';
      html += '<div class="sitroom-section-title">Holding the Line</div>';
      var defByNpc = _sitGroupByNpc(defenders);
      var dNames = Object.keys(defByNpc);
      var dSentences = [];
      for (var dn = 0; dn < Math.min(dNames.length, 5); dn++) {
        var dNpc = dNames[dn];
        var dEvts = defByNpc[dNpc];
        var dDescs = [];
        for (var dd = 0; dd < Math.min(dEvts.length, 2); dd++) {
          var dDesc = dEvts[dd].description || dEvts[dd].name || '';
          dDesc = dDesc.replace(new RegExp('^' + dNpc.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*', 'i'), '');
          if (dDesc) dDescs.push(dDesc);
        }
        if (dDescs.length > 0) {
          dSentences.push('<span class="npc-name">' + esc(dNpc) + '</span> ' + _sitHtml(dDescs.join(', and ')).toLowerCase());
        }
      }
      html += '<div class="sitroom-text">' + dSentences.join('. ') + '.</div>';
      html += '</div>';
    }

    // ── 10. STRANGE SIGNALS (mystery + science) ──
    var strange = buckets.mystery.concat(buckets.science);
    if (strange.length > 0) {
      html += '<div class="sitroom-section">';
      html += '<div class="sitroom-section-title">Strange Signals</div>';
      for (var s = 0; s < Math.min(strange.length, 4); s++) {
        var sDesc = strange[s].description || strange[s].name || '';
        html += '<div class="sitroom-text" style="margin-bottom:3px">' + _sitHtml(esc(sDesc)) + '</div>';
      }
      html += '</div>';
    }

    // ── 11. FOREWARNING ──
    var forewarning = '';
    if (narr && narr.forewarning) forewarning = narr.forewarning;
    else if (crisis.why_it_matters) forewarning = crisis.why_it_matters;
    if (forewarning) {
      html += '<div class="sitroom-forewarning">' + _sitHtml(esc(forewarning)) + '</div>';
    }

    // ── 12. QUIET STATE ──
    if (!html) {
      html = '<div class="sitroom-quiet">All sectors nominal. No significant activity detected.</div>';
    }

    bodyEl.innerHTML = html;

}).catch(function(err) {
    console.warn('[renderSituationRoom]', err);
    headlineEl.textContent = 'Intelligence report unavailable';
    bodyEl.innerHTML = '<div class="sitroom-quiet">Could not reach the data stream.</div>';
});
}

/* ═══ QUICK STATUS SUMMARY ═══ */
function renderQuickStatus() {
  var panel = document.getElementById('quick-status');
  var body = document.getElementById('qs-body');
  var tickEl = document.getElementById('qs-tick');
  if (!panel || !body) return;

  var status = lastData.status;
  var events = lastData.events;
  if (!status) { panel.style.display = 'none'; return; }

  var ws = status.world_state || status.worldState || status;
  var metrics = getMetrics(status);
  var v = computeVerdict(status);
  var cascade = status.cascade_summary || status.cascadeSummary || {};
  var temp = cascade.temperature != null ? cascade.temperature : (cascade.cascade_temperature != null ? cascade.cascade_temperature : 0);
  var cascadePct = temp > 1.5 ? temp : (temp * 100);

  /* Tick display */
  var tick = '\u2014';
  if (status.last_tick_result && status.last_tick_result.tick_ts) tick = status.last_tick_result.tick_ts;
  else if (status.last_tick_timestamp) tick = status.last_tick_timestamp;
  else if (ws.tick_count != null) tick = ws.tick_count;
  tickEl.textContent = 'Tick ' + tick;

  panel.style.display = 'block';
  var html = '';

  /* ── 1. VITALS ── */
  html += '<div class="qs-section">';
  html += '<div class="qs-section-title"><span class="qs-num">1</span> Vitals</div>';

  var goodParts = [];
  if (metrics.morale >= 75) goodParts.push('Morale (' + Math.round(metrics.morale) + ') is strong');
  else if (metrics.morale >= 50) goodParts.push('Morale (' + Math.round(metrics.morale) + ') is stable');
  if (metrics.resources >= 70) goodParts.push('Resource Abundance (' + Math.round(metrics.resources) + ') is high');
  else if (metrics.resources >= 45) goodParts.push('Resource Abundance (' + Math.round(metrics.resources) + ') is adequate');
  if (metrics.stability >= 70) goodParts.push('Stability (' + Math.round(metrics.stability) + ') is solid');
  if (metrics.threat <= 30) goodParts.push('Threat level (' + Math.round(metrics.threat) + ') is low');
  if (metrics.tension <= 30) goodParts.push('Tension (' + Math.round(metrics.tension) + ') is low');

  var badParts = [];
  if (metrics.stability < 40) badParts.push('Stability is <span class="qs-bad">UNSTABLE</span> (' + Math.round(metrics.stability) + ')');
  else if (metrics.stability < 60) badParts.push('Stability (' + Math.round(metrics.stability) + ') is weakening');
  if (metrics.morale < 35) badParts.push('Morale is <span class="qs-bad">COLLAPSING</span> (' + Math.round(metrics.morale) + ')');
  else if (metrics.morale < 55) badParts.push('Morale (' + Math.round(metrics.morale) + ') is low');
  if (metrics.threat > 70) badParts.push('Threat level is <span class="qs-bad">CRITICAL</span> (' + Math.round(metrics.threat) + ')');
  else if (metrics.threat > 55) badParts.push('Threat level (' + Math.round(metrics.threat) + ') is elevated');
  if (metrics.tension > 70) badParts.push('Tension is <span class="qs-bad">SEVERE</span> (' + Math.round(metrics.tension) + ')');
  else if (metrics.tension > 55) badParts.push('Tension (' + Math.round(metrics.tension) + ') is elevated');
  if (metrics.anomaly > 70) badParts.push('Anomaly activity is <span class="qs-bad">ELEVATED</span> (' + Math.round(metrics.anomaly) + ')');

  if (goodParts.length > 0) {
    html += '<div class="qs-row"><span class="qs-good">&#x2713; The Good:</span> ' + goodParts.join('. ') + '.</div>';
  }
  if (badParts.length > 0) {
    html += '<div class="qs-row"><span class="qs-bad">&#x26A0; The Bad:</span> ' + badParts.join('. ') + '.</div>';
  }
  if (goodParts.length === 0 && badParts.length === 0) {
    html += '<div class="qs-row"><span class="qs-neutral">&#x2014; All metrics are in mid-range \u2014 current status: ' + v.label + '.</span></div>';
  }
  html += '</div>';

  /* ── 2. UNDER THE SURFACE ── */
  var surfaceItems = [];
  if (events) {
    var flat = [];
    if (Array.isArray(events)) { flat = events; }
    else if (typeof events === 'object') {
      var we = events.world_events || []; var ce = events.cascade_events || []; var be = events.broadcast_events || [];
      flat = we.concat(ce, be);
    }
    /* Scan for scheming/covert ops/black markets/disinformation */
    var blackMarketNpcs = []; var covertNpcs = []; var disinfoNpcs = []; var espionageNpcs = [];
    for (var ei = 0; ei < flat.length; ei++) {
      var ev = flat[ei];
      var desc = (ev.description || ev.name || ev.message || '').toLowerCase();
      var srcName = ev.source_char_name || ev.character_name || ev.source_name || ev.source || '';
      if (!srcName && ev.description) {
        var srcMatch = ev.description.match(/^([A-Z][A-Za-z\s]+?)(?:\s+(?:gathered|planted|acquired|set|stumbled|exchanged|published|conducted|led|enforced|blocked|increased|ordered|sensed|explored|returned|chart|discovered|sabotage|heist|vanish|smuggl|broke|repelled|rallied|issued|confront|challenged|intercept|infiltrat))/);
        if (srcMatch && srcMatch[1].trim().length > 2) srcName = srcMatch[1].trim();
      }
      if (desc.indexOf('black market') !== -1 || desc.indexOf('illicit') !== -1 || desc.indexOf('smuggl') !== -1) {
        if (srcName && blackMarketNpcs.indexOf(srcName) === -1) blackMarketNpcs.push(srcName);
      }
      if (desc.indexOf('covert') !== -1 || desc.indexOf('secret') !== -1 || desc.indexOf('vanish') !== -1) {
        if (srcName && covertNpcs.indexOf(srcName) === -1) covertNpcs.push(srcName);
      }
      if (desc.indexOf('disinformation') !== -1 || desc.indexOf('planted') !== -1) {
        if (srcName && disinfoNpcs.indexOf(srcName) === -1) disinfoNpcs.push(srcName);
      }
      if (desc.indexOf('spy') !== -1 || desc.indexOf('espionage') !== -1 || desc.indexOf('infiltrat') !== -1 || desc.indexOf('intercept') !== -1) {
        if (srcName && espionageNpcs.indexOf(srcName) === -1) espionageNpcs.push(srcName);
      }
      /* Also check event type for covert operations */
      var evType = (ev.type || ev.event_type || '').toLowerCase();
      if (evType === 'covert_operation' || evType === 'covert') {
        if (srcName && covertNpcs.indexOf(srcName) === -1) covertNpcs.push(srcName);
      }
    }
    if (blackMarketNpcs.length > 0) {
      surfaceItems.push('<span class="qs-strong">Black Markets:</span> ' + blackMarketNpcs.length + ' active (' + blackMarketNpcs.map(function(n){return '<span class="qs-name">' + esc(n) + '</span>';}).join(', ') + ')');
    }
    if (covertNpcs.length > 0) {
      surfaceItems.push('<span class="qs-strong">Covert Ops:</span> ' + covertNpcs.length + ' active (' + covertNpcs.map(function(n){return '<span class="qs-name">' + esc(n) + '</span>';}).join(', ') + ')');
    }
    if (disinfoNpcs.length > 0) {
      surfaceItems.push('<span class="qs-strong">Disinformation:</span> ' + disinfoNpcs.map(function(n){return '<span class="qs-name">' + esc(n) + '</span>';}).join(', ') + ' spreading false narratives');
    }
    if (espionageNpcs.length > 0) {
      surfaceItems.push('<span class="qs-strong">Espionage:</span> ' + espionageNpcs.length + ' active (' + espionageNpcs.map(function(n){return '<span class="qs-name">' + esc(n) + '</span>';}).join(', ') + ')');
    }
  }
  if (surfaceItems.length > 0) {
    html += '<div class="qs-section">';
    html += '<div class="qs-section-title"><span class="qs-num">2</span> Under the Surface</div>';
    html += '<div class="qs-row">' + surfaceItems.join(' <span class="qs-dim">|</span> ') + '</div>';
    html += '</div>';
  }

  /* ── 3. MAJOR CATALYSTS ── */
  var catalysts = [];

  /* Cascade analysis */
  var cascadeEvents = [];
  if (events) {
    var flat2 = [];
    if (Array.isArray(events)) flat2 = events;
    else if (typeof events === 'object') {
      flat2 = (events.world_events || []).concat(events.cascade_events || [], events.broadcast_events || []);
    }
    for (var ci = 0; ci < flat2.length; ci++) {
      var cev = flat2[ci];
      var cevType = (cev.type || cev.event_type || '').toLowerCase();
      if (cevType === 'cascade_reaction' || cev.cascade) cascadeEvents.push(cev);
    }
  }

  if (cascadeEvents.length >= 3) {
    var uniqueTypes = {};
    for (var cti = 0; cti < cascadeEvents.length; cti++) {
      var origin = cascadeEvents[cti].origin_event_type || cascadeEvents[cti].source_event_type || cascadeEvents[cti].cause || 'unknown';
      uniqueTypes[origin] = (uniqueTypes[origin] || 0) + 1;
    }
    var dominantType = Object.keys(uniqueTypes).sort(function(a,b){return uniqueTypes[b] - uniqueTypes[a];})[0];
    var catLabel = dominantType.replace(/_/g, ' ').replace(/\b\w/g, function(c){return c.toUpperCase();});
    catalysts.push(
      '<div class="qs-catalyst"><span class="qs-cat-label">&#x1F300; The ' + esc(catLabel) + ' Cascade:</span> ' +
      cascadeEvents.length + ' NPC reactions triggered by a <span class="qs-name">' + esc(catLabel) + '</span> event' +
      (cascadePct > 70 ? ' <span class="qs-badge bad">OVERHEATING</span>' : '') +
      '</div>'
    );
  }

  /* Large cascade chains */
  var chainCount = cascade.total_chains || cascade.chain_count || 0;
  if (chainCount >= 2) {
    var totalReactions = cascade.total_cascade_reactions || cascade.reaction_count || 0;
    catalysts.push(
      '<div class="qs-catalyst"><span class="qs-cat-label">&#x1F52D; Chain Reactions:</span> ' +
      chainCount + ' active chains with ' + totalReactions + ' total reactions' +
      (cascadePct > 60 ? ' <span class="qs-badge neutral">' + Math.round(cascadePct) + '% temperature</span>' : '') +
      '</div>'
    );
  }

  /* Philosophical/cultural shifts from narration or crisis */
  if (window._latestNarration) {
    var narr = window._latestNarration;
    if (narr.headline && (narr.headline.toLowerCase().indexOf('revolution') !== -1 || narr.headline.toLowerCase().indexOf('cultural') !== -1 || narr.headline.toLowerCase().indexOf('shift') !== -1)) {
      catalysts.push(
        '<div class="qs-catalyst"><span class="qs-cat-label">&#x1F4A1; Cultural Shift:</span> ' +
        esc(narr.headline) + '</div>'
      );
    }
    if (narr.developments && narr.developments.length > 0) {
      for (var nd = 0; nd < Math.min(narr.developments.length, 2); nd++) {
        var dev = narr.developments[nd];
        if (dev.toLowerCase().indexOf('revolution') !== -1 || dev.toLowerCase().indexOf('massive') !== -1 || dev.toLowerCase().indexOf('unknown') !== -1) {
          catalysts.push(
            '<div class="qs-catalyst"><span class="qs-cat-label">&#x26A1; Development:</span> ' +
            esc(dev) + '</div>'
          );
        }
      }
    }
  }

  /* Stability crisis catalyst */
  if (metrics.stability < 30) {
    catalysts.push(
      '<div class="qs-catalyst"><span class="qs-cat-label">&#x26A0; Stability Crisis:</span> ' +
      'Stability at ' + Math.round(metrics.stability) + ' — quests will begin failing, factions losing coordination ' +
      '<span class="qs-badge bad">CRITICAL</span></div>'
    );
  }

  /* Anomaly crisis */
  if (metrics.anomaly > 70) {
    catalysts.push(
      '<div class="qs-catalyst"><span class="qs-cat-label">&#x2728; Anomaly Surge:</span> ' +
      'Anomaly activity at ' + Math.round(metrics.anomaly) + ' — reality instability affecting NPC behavior' +
      (metrics.anomaly > 85 ? ' <span class="qs-badge bad">BREACH</span>' : '') +
      '</div>'
    );
  }

  if (catalysts.length > 0) {
    html += '<div class="qs-section">';
    html += '<div class="qs-section-title"><span class="qs-num">3</span> Major Catalysts</div>';
    html += '<div class="qs-row" style="flex-direction:column">' + catalysts.join('') + '</div>';
    html += '</div>';
  }

  if (!html) {
    html = '<div class="qs-empty">No data available</div>';
  }

  body.innerHTML = html;
}

async function refreshLight(){
var results=await Promise.all([apiFetch('/simulation/status',8000),apiFetch('/simulation/factions',8000),apiFetch('/simulation/events',8000)]);
var status=results[0],factions=results[1],events=results[2];
var anyOk=status||factions||events;
if(!anyOk){fetchErrorCount++;if(fetchErrorCount>=3)showSignalLost(true)}else{fetchErrorCount=0;showSignalLost(false);if(status)lastData.status=status;if(factions)lastData.factions=factions;if(events)lastData.events=events}
if(lastData.status){updateTopBanner(lastData.status);updateSituation(lastData.status);updateFedBrief()}renderQuickStatus();renderReadableSummary();renderSituationRoom();renderHumanBriefing();
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
await refreshLight();await refreshNpcs();await refreshNpcRealityFeed();await refreshQuests();await refreshFactionTech();await refreshChoices();
for(var l2=0;l2<loadingEls.length;l2++)loadingEls[l2].classList.remove('loading-pulse');
}

/* ═══ Fed UI Phenotype State (compact-restore pattern) ═══ */
const FED_UI_SCHEMA = '1.0.0';
const FED_UI_AUTH_FIELDS = ['activity_log_expanded','raw_open','npc_filter_on'];
const FED_UI_MAX_AGE = 300000; // 5 minutes before stale

function _fedHash(s) {
  var h=0; for(var i=0;i<s.length;i++){h=((h<<5)-h)+s.charCodeAt(i);h=h&h}
  return 'h'+Math.abs(h).toString(36);
}

function fedSaveUIState(changes) {
  try {
    var existing = fedLoadRawUIState();
    var state = {activity_log_expanded:false,raw_open:false,npc_filter_on:false};
    if (existing&&existing.payload) for(var k in existing.payload) state[k]=existing.payload[k];
    if (changes) for(var k in changes) state[k]=changes[k];
    var packet = {
      schema:FED_UI_SCHEMA,timestamp:Date.now(),source:'federation-dashboard',
      authority:{fields_authoritative:FED_UI_AUTH_FIELDS,fields_advisory:[]},
      payload:state,hash:''
    };
    packet.hash=_fedHash(packet.schema+'|'+packet.timestamp+'|'+packet.source+'|'+JSON.stringify(packet.payload)+'|'+JSON.stringify(packet.authority));
    localStorage.setItem('fed_ui_phenotype',JSON.stringify(packet));
    return true;
  } catch(e){return false}
}

function fedLoadRawUIState() {
  try {
    var raw=localStorage.getItem('fed_ui_phenotype'); if(!raw) return null;
    var p=JSON.parse(raw); if(!p.schema||!p.timestamp) return null;
    var ch=p.hash; p.hash='';
    var cmp=_fedHash(p.schema+'|'+p.timestamp+'|'+p.source+'|'+JSON.stringify(p.payload)+'|'+JSON.stringify(p.authority));
    if(ch!==cmp) return null; // integrity fail — treat as no state
    p.hash=ch; p._stale=(Date.now()-p.timestamp)>FED_UI_MAX_AGE;
    return p;
  } catch(e){return null}
}

function fedRestoreUIState() {
  var p = fedLoadRawUIState();
  if (!p) return null;
  return p.payload;
}
/* ═══ End Phenotype State ═══ */

function toggleRaw(){var btn=document.getElementById('raw-toggle'),wrap=document.getElementById('raw-wrap');var nowOpen=!wrap.classList.contains('open');btn.classList.toggle('open');wrap.classList.toggle('open');btn.setAttribute('aria-expanded',String(nowOpen));fedSaveUIState({raw_open:nowOpen})}
function toggleHelp(){var overlay=document.getElementById('help-overlay');overlay.classList.toggle('open');if(overlay.classList.contains('open')){overlay.focus();document.body.style.overflow='hidden'}else{document.body.style.overflow=''}}
function toggleActivityLog(){var log=document.getElementById('activity-log');var bar=document.getElementById('activity-log-bar');var expanded=log.classList.toggle('expanded');bar.setAttribute('aria-expanded',String(expanded));fedSaveUIState({activity_log_expanded:expanded})}

/* ═══ HUMAN READABILITY MODE ═══ */
function toggleReadableMode() {
  var on = document.body.classList.toggle('readable-mode');
  var btn = document.getElementById('rm-toggle');
  if (btn) btn.classList.toggle('on', on);
  var summary = document.getElementById('rm-summary');
  var qs = document.getElementById('quick-status');
  var progBar = document.getElementById('rm-prog-bar');
  var collapseToggles = document.querySelectorAll('.rm-collapse-toggle');
  var sitRoom = document.getElementById('situation-room');
  var activityLog = document.getElementById('activity-log');
  var mainTitle = document.querySelector('.section-title.cyan');
  if (on) {
    if (summary) summary.style.display = 'block';
    if (qs) qs.style.display = 'none';
    if (progBar) progBar.style.display = 'flex';
    if (mainTitle) mainTitle.style.display = 'none';
    collapseToggles.forEach(function(el) { el.style.display = 'flex'; });
    var npcGrid = document.getElementById('npc-grid');
    if (npcGrid) npcGrid.classList.remove('rm-expanded');
    var fList = document.getElementById('left-factions');
    if (fList) fList.classList.remove('rm-expanded');
  } else {
    if (summary) summary.style.display = 'none';
    if (qs) qs.style.display = '';
    if (progBar) progBar.style.display = 'none';
    if (mainTitle) mainTitle.style.display = '';
    collapseToggles.forEach(function(el) { el.style.display = 'none'; });
    var npcGrid = document.getElementById('npc-grid');
    if (npcGrid) npcGrid.classList.add('rm-expanded');
    var fList = document.getElementById('left-factions');
    if (fList) fList.classList.add('rm-expanded');
  }
  renderReadableSummary();
  try { localStorage.setItem('fed_readable_mode', on ? 'true' : 'false'); } catch(e) {}
}
function switchRMPanel(panelId) {
  document.querySelectorAll('.rm-prog-panel').forEach(function(el) { el.classList.remove('visible'); });
  var panel = document.getElementById(panelId);
  if (panel) panel.classList.add('visible');
  document.querySelectorAll('.rm-prog-btn').forEach(function(btn) { btn.classList.toggle('active', btn.dataset.rmPanel === panelId); });
}
function rmToggleSection(sectionId) {
  var el = document.getElementById(sectionId);
  if (!el) return;
  el.classList.toggle('rm-expanded');
  var toggle = document.querySelector('[onclick="rmToggleSection(\'' + sectionId + '\')"]');
  if (toggle) {
    var arrow = el.classList.contains('rm-expanded') ? '\u25BC' : '\u25B6';
    toggle.innerHTML = arrow + ' ' + toggle.textContent.replace(/^[\u25B6\u25BC]\s*/, '');
  }
}
function renderReadableSummary() {
  var panel = document.getElementById('rm-summary');
  var body = document.getElementById('rm-summary-body');
  var tickEl = document.getElementById('rm-summary-tick');
  if (!panel || !body) return;
  var status = lastData ? (lastData.status || lastData) : null;
  if (!status) { panel.style.display = 'none'; return; }
  var ws = status.world_state || status.worldState || status;
  var rawEvents = lastData.events || [];
  var events;
  if (Array.isArray(rawEvents)) { events = rawEvents; }
  else if (typeof rawEvents === 'object') {
    events = (rawEvents.world_events || []).concat(rawEvents.cascade_events || [], rawEvents.broadcast_events || []);
    events.sort(function(a,b){ var ta=a.ts||a.timestamp||0; var tb=b.ts||b.timestamp||0; return (tb>ta?1:(tb<ta?-1:0)); });
  } else { events = []; }
  var factions = lastData.factions || {};
  var m = getMetrics(status);
  var v = computeVerdict(status);
  var overallState = v.label;
  var stateClass = v.state;
  var mainRisk = v.mainRisk;
  var threat = m.threat, anomaly = m.anomaly, stability = m.stability;
  var topEvents = events.slice(0, 3);
  var involvedNpcs = [];
  var involvedFactions = [];
  for (var i = 0; i < Math.min(events.length, 10); i++) {
    var ev = events[i];
    if (ev && ev.char_name && involvedNpcs.indexOf(ev.char_name) === -1) { involvedNpcs.push(ev.char_name); }
    if (ev && ev.faction_id && involvedFactions.indexOf(ev.faction_id) === -1) { involvedFactions.push(ev.faction_id); }
  }
  involvedNpcs = involvedNpcs.slice(0, 3);
  involvedFactions = involvedFactions.slice(0, 3);
  var consequence = 'Monitoring degradation and threat metrics.';
  if (v.state === 'crisis') consequence = 'Immediate intervention may be required. Systems at risk of cascade failure.';
  else if (v.state === 'unstable' || v.state === 'watch') consequence = 'Conditions deteriorating. Watch for cascade triggers.';
  else if (threat > 40) consequence = 'External pressure increasing. Faction cohesion may weaken.';
  else if (anomaly > 40) consequence = 'Anomaly activity rising. Unknown events likely.';
  var tick = '\u2014';
  if (status.last_tick_result && status.last_tick_result.tick_ts) tick = status.last_tick_result.tick_ts;
  else if (status.last_tick_timestamp) tick = status.last_tick_timestamp;
  else if (ws.tick_count != null) tick = ws.tick_count;
  tickEl.textContent = 'Tick ' + tick;
  panel.style.display = 'block';
  var html = '';
  html += '<div class="rm-summary-section"><div class="rm-summary-section-title">Current Overall State</div>';
  html += '<div class="rm-summary-row"><span class="rm-summary-state ' + stateClass + '">' + overallState + '</span></div></div>';
  html += '<div class="rm-summary-section"><div class="rm-summary-section-title">Main Risk</div>';
  html += '<div class="rm-summary-row">' + mainRisk + '</div></div>';
  html += '<div class="rm-summary-section"><div class="rm-summary-section-title">Top Recent Events</div>';
  if (topEvents.length === 0) { html += '<div class="rm-summary-row" style="color:var(--dim)">No recent events</div>'; }
  else {
    for (var i = 0; i < topEvents.length; i++) {
      var ev = topEvents[i];
      var badgeClass = 'world';
      if (ev.event_type === 'cascade') badgeClass = 'cascade';
      else if (ev.event_type === 'faction') badgeClass = 'faction';
      else if (ev.event_type === 'crisis') badgeClass = 'crisis';
      var npcName = ev.char_name ? '<span class="rm-ev-npc">' + ev.char_name + '</span>' : '';
      var desc = ev.description || ev.action_type || 'Unknown event';
      html += '<div class="rm-summary-event-item"><span class="rm-ev-badge ' + badgeClass + '">' + badgeClass.toUpperCase() + '</span> ' + npcName + ' ' + desc + '</div>';
    }
  }
  html += '</div>';
  html += '<div class="rm-summary-section"><div class="rm-summary-section-title">Who Is Involved</div>';
  if (involvedNpcs.length > 0) { html += '<div style="font-size:0.9375rem;color:var(--cyan);">NPCs: ' + involvedNpcs.join(', ') + '</div>'; }
  if (involvedFactions.length > 0) {
    html += '<div style="font-size:0.9375rem;margin-top:4px;">';
    for (var i = 0; i < involvedFactions.length; i++) { html += '<span class="rm-summary-faction-chip">' + (FACTION_DISPLAY[involvedFactions[i]] || involvedFactions[i]) + '</span> '; }
    html += '</div>';
  }
  if (involvedNpcs.length === 0 && involvedFactions.length === 0) { html += '<div class="rm-summary-row" style="color:var(--dim)">No active participants</div>'; }
  html += '</div>';
  html += '<div class="rm-summary-section"><div class="rm-summary-section-title">Next Likely Consequence</div>';
  html += '<div class="rm-summary-consequence">' + consequence + '</div></div>';
  body.innerHTML = html;
}
function initReadableMode() {
  try { var saved = localStorage.getItem('fed_readable_mode'); if (saved === 'true') { toggleReadableMode(); } } catch(e) {}
}
/* Restore persisted toggle states from phenotype state packet */
function restoreToggleStates() {
  var state = fedRestoreUIState();
  if (!state) return;
  /* Activity log */
  if (state.activity_log_expanded) {
    var log = document.getElementById('activity-log');
    var bar = document.getElementById('activity-log-bar');
    if (log) { log.classList.add('expanded'); }
    if (bar) { bar.setAttribute('aria-expanded', 'true'); }
  }
  /* Raw events */
  if (state.raw_open) {
    var btn = document.getElementById('raw-toggle');
    var wrap = document.getElementById('raw-wrap');
    if (btn) { btn.classList.add('open'); btn.setAttribute('aria-expanded', 'true'); }
    if (wrap) { wrap.classList.add('open'); }
  }
  /* NPC filter */
  if (state.npc_filter_on) {
    window.npcFilterOn = true;
    var toggle = document.getElementById('npc-noise-toggle');
    var label = toggle ? toggle.querySelector('.npc-noise-toggle-label') : null;
    if (toggle) { toggle.classList.add('on'); toggle.setAttribute('aria-pressed', 'true'); }
    if (label) { label.textContent = 'Active Only'; }
  }
}
document.addEventListener('keydown',function(e){if(e.key==='Escape'){var overlay=document.getElementById('help-overlay');if(overlay.classList.contains('open'))toggleHelp()}});

function init(){generateStarfield();restoreToggleStates();initReadableMode();refresh();setInterval(refreshLight,10000);setInterval(refreshNpcs,30000);setInterval(refreshNpcRealityFeed,30000);setInterval(refreshQuests,20000);setInterval(refreshFactionTech,25000);setInterval(refreshChoices,20000);setInterval(updateTimeSince,1000);setInterval(renderSituationRoom,15000)}
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}


/* ═══ AI ASSISTANT CHAT ═══ */
var aiChatHistory = [];
var aiChatBusy = false;

function aiChatRender() {
  var el = document.getElementById("ai-chat-messages");
  if (!el) return;
  var html = "";
  for (var i = 0; i < aiChatHistory.length; i++) {
    var m = aiChatHistory[i];
    if (m.role === "user") {
      html += '<div class="ai-chat-msg user">' + esc(m.text) + '</div>';
    } else if (m.role === "thinking") {
      html += '<div class="ai-chat-msg thinking">Analyzing simulation data...</div>';
    } else if (m.role === "assistant") {
      var prov = m.provider ? '<span class="ai-provider">' + esc(m.provider) + '</span>' : '';
      html += '<div class="ai-chat-msg assistant">' + md(m.text) + prov + '</div>';
    } else if (m.role === "error") {
      html += '<div class="ai-chat-msg error">' + esc(m.text) + '</div>';
    }
  }
  el.innerHTML = html;
  el.scrollTop = el.scrollHeight;
}

function aiChatAsk(text) {
  var input = document.getElementById("ai-chat-input");
  if (input) input.value = text;
  aiChatSend();
}

async function aiChatSend() {
  if (aiChatBusy) return;
  var input = document.getElementById("ai-chat-input");
  if (!input) return;
  var question = input.value.trim();
  if (!question) return;
  input.value = "";
  aiChatBusy = true;
  var btn = document.getElementById("ai-chat-send");
  var restoreBtn = btnSpinner(btn, "Thinking…");

  aiChatHistory.push({role: "user", text: question});
  aiChatHistory.push({role: "thinking"});
  aiChatRender();

  try {
    var data = await fedFetch('assistant', '/map/assistant', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
      body: JSON.stringify({question: question}),
      timeout: 45000,
      retries: 0,
    });

    aiChatHistory = aiChatHistory.filter(function(m){ return m.role !== "thinking"; });

    if (!data) {
      aiChatHistory.push({
        role: "error",
        text: "Connection failed. The simulation may be offline."
      });
    } else if (data.status === "ok") {
      aiChatHistory.push({
        role: "assistant",
        text: data.answer || "No answer returned.",
        provider: data.provider || ""
      });
    } else {
      aiChatHistory.push({
        role: "error",
        text: data.answer || "The intelligence systems are offline."
      });
    }
  } finally {
    aiChatBusy = false;
    restoreBtn();
    aiChatRender();
  }
}

// Toggle chat drawer
function toggleChatDrawer() {
  var chat = document.getElementById("ai-chat");
  var btn = document.getElementById("ai-chat-toggle");
  if (!chat || !btn) return;
  var isOpen = chat.classList.toggle("open");
  btn.classList.toggle("open", isOpen);
}

// Enter key to send
document.addEventListener("DOMContentLoaded", function(){
  var input = document.getElementById("ai-chat-input");
  if (input) {
    input.addEventListener("keydown", function(e){
      if (e.key === "Enter") { e.preventDefault(); aiChatSend(); }
    });
  }
});
