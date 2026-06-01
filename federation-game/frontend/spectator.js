// ── Constants ────────────────────────────────────────────────
const FC = {
military_command:{color:'#F44336',name:'Military Command',leader:'Marshal Ironbound'},
research_division:{color:'#2196F3',name:'Research Division',leader:'Dr. Prometheus'},
diplomatic_corps:{color:'#4CAF50',name:'Diplomatic Corps',leader:'Chancellor Harmony'},
cultural_ministry:{color:'#9C27B0',name:'Cultural Ministry',leader:'Maestro Celestia'},
economic_council:{color:'#FF9800',name:'Economic Council',leader:'Merchant-Prince Aurelius'},
exploration_initiative:{color:'#00BCD4',name:'Exploration Initiative',leader:'Captain Frontier'},
consciousness_collective:{color:'#E91E63',name:'Consciousness Collective',leader:'Oracle Vex'},
preservation_society:{color:'#8BC34A',name:'Preservation Society',leader:'Archivist Eternal'},
};
const MOOD_COLORS={
satisfied:'#4CAF50',inspired:'#66BB6A',serene:'#81C784',peaceful:'#A5D6A7',
hopeful:'#4CAF50',excited:'#66BB6A',confident:'#4CAF50',enlightened:'#66BB6A',
adventurous:'#81C784',determined:'#4CAF50',resolute:'#66BB6A',steadfast:'#4CAF50',
patient:'#81C784',valiant:'#4CAF50',free:'#66BB6A',
frustrated:'#F44336',aggressive:'#D32F2F',suspicious:'#FF9800',anxious:'#FF9800',
alarmed:'#F44336',worried:'#FF9800',unsettled:'#FF9800',weary:'#FF9800',
melancholic:'#9C27B0',paranoid:'#F44336',burdened:'#FF9800',
contemplative:'#00BCD4',thoughtful:'#00BCD4',curious:'#00BCD4',
distracted:'#78909C',reserved:'#78909C',
};
const METRICS=[
{key:'tension_level',label:'Tension',color:'#F44336'},
{key:'resource_abundance',label:'Resources',color:'#4CAF50'},
{key:'threat_level',label:'Threat',color:'#F44336'},
{key:'stability',label:'Stability',color:'#00BCD4'},
{key:'morale',label:'Morale',color:'#FF9800'},
{key:'anomaly_activity',label:'Anomaly',color:'#9C27B0'},
];

// ── State ────────────────────────────────────────────────────
let activeTab='thoughts';
let activeFaction=null;
let worldState={};
let factions={};
let npcActivity=[];
let narrationHistory=[];
let questLog=[];
let techData={};
let choiceStats={};
let eventLog=[];
let relationshipNetwork={};
let cascadeChains=[];
let factionBrains={};
let choiceResolutions=[];
let highlightedNPC=null;
let ws=null;
let wsReconnects=0;

// ── Helpers ──────────────────────────────────────────────────
function esc(s){if(s==null)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function clamp(v,lo,hi){return Math.max(lo,Math.min(hi,v))}
function moodColor(m){return MOOD_COLORS[String(m).toLowerCase()]||'#78909C'}
function factionColor(fid){return(FC[fid]||{}).color||'#78909C'}
function factionName(fid){return(FC[fid]||{}).name||fid.replace(/_/g,' ')}
function stanceClass(s){if(!s)return'neutral';var l=String(s).toLowerCase();if(l==='ally'||l==='allied'||l==='friendly')return'ally';if(l==='enemy'||l==='hostile'||l==='adversarial')return'enemy';return'neutral'}
function stanceColor(s){var c=stanceClass(s);return c==='ally'?'#4CAF50':c==='enemy'?'#F44336':'#FFC107'}
function ago(ts){if(!ts)return'';var s=Math.floor((Date.now()/1000)-ts);if(s<60)return s+'s ago';if(s<3600)return Math.floor(s/60)+'m ago';return Math.floor(s/3600)+'h ago'}

function getQuestForNPC(npcId){
if(!questLog||!questLog.quest_log)return null;
var log=questLog.quest_log;
for(var i=0;i<log.length;i++){
var q=log[i];
var qCharId=q.char_id||'';
if(qCharId===npcId||qCharId.indexOf(npcId)>-1||npcId.indexOf(qCharId)>-1){
if(!q.event||q.event.indexOf('complet')===-1&&q.event.indexOf('abandon')===-1&&q.event.indexOf('fail')===-1){
return q;
}
}
}
return null;
}

function getQuestCountForNPC(npcId){
if(!questLog||!questLog.quest_log)return 0;
return questLog.quest_log.filter(function(q){
var qCharId=q.char_id||'';
return qCharId===npcId||qCharId.indexOf(npcId)>-1||npcId.indexOf(qCharId)>-1;
}).length;
}

function getTechForFaction(fid){
if(!techData||!techData.factions||!techData.factions[fid])return null;
return techData.factions[fid].active_research||null;
}

// ── API ──────────────────────────────────────────────────────
async function api(ep,ms){
var ctl=new AbortController();
var t=setTimeout(function(){ctl.abort()},ms||10000);
try{
var r=await fetch(ep,{headers:{'Accept':'application/json'},signal:ctl.signal});
clearTimeout(t);
if(!r.ok)throw new Error(r.status);
return await r.json();
}catch(e){clearTimeout(t);return null}
}

// ── Starfield ────────────────────────────────────────────────
function makeStars(){
var sf=document.getElementById('starfield');
for(var i=0;i<60;i++){
var s=document.createElement('div');s.className='star';
var sz=Math.random()*2+1;
s.style.cssText='width:'+sz+'px;height:'+sz+'px;left:'+Math.random()*100+'%;top:'+Math.random()*100+'%;--d:'+(2+Math.random()*4)+'s;--dl:'+Math.random()*3+'s;opacity:'+(0.15+Math.random()*0.4);
sf.appendChild(s);
}
}

// ── Tabs ─────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(function(t){
t.addEventListener('click',function(){
document.querySelectorAll('.tab').forEach(function(x){x.classList.remove('active')});
document.querySelectorAll('.tab-panel').forEach(function(x){x.classList.remove('active')});
t.classList.add('active');
activeTab=t.dataset.tab;
document.getElementById('panel-'+activeTab).classList.add('active');
renderActiveTab();
});
});

// ── Header Metrics ───────────────────────────────────────────
function buildHeaderMetrics(){
var c=document.getElementById('header-metrics');
c.innerHTML='';
METRICS.forEach(function(m){
c.innerHTML+='<div class="hm"><span class="hm-label">'+m.label+'</span><span class="hm-val" id="hv-'+m.key+'">&mdash;</span><div class="hm-bar"><div class="hm-fill" id="hb-'+m.key+'" style="width:0;background:'+m.color+'"></div></div></div>';
});
}

function updateHeaderMetrics(ws){
if(!ws)return;
METRICS.forEach(function(m){
var v=ws[m.key]!=null?ws[m.key]:0;
var valEl=document.getElementById('hv-'+m.key);
var barEl=document.getElementById('hb-'+m.key);
if(valEl)valEl.textContent=Math.round(v);
if(barEl){barEl.style.width=clamp(v,0,100)+'%';barEl.style.background=m.color}
});
}

function updateEra(status){
if(!status)return;
var era=status.current_era||status.era||status.currentEra||{};
var name=era.name||era.era_name||era.label||status.era_name||status.current_phase||status.game_phase||'Unknown';
var progress=era.progress!=null?era.progress:(era.progress_pct!=null?era.progress_pct:0);
if(!progress&&status.turns_in_phase!=null){
progress=Math.min(100,status.turns_in_phase*5);
}
document.getElementById('era-name').textContent=name.replace(/_/g,' ');
document.getElementById('era-fill').style.width=clamp(progress,0,100)+'%';
document.getElementById('era-pct').textContent=Math.round(progress)+'%';
}

// ── Narration ────────────────────────────────────────────────
function renderNarration(data){
if(!data)return;
var hl=document.getElementById('narration-headline');
if(data.headline)hl.textContent=data.headline;
var meta=document.getElementById('narration-meta');
var src=data.source||'none';
var srcLabel=src==='llm'?'AI NARRATED':src==='fallback'?'DETERMINISTIC':src==='cached'?'CACHED':'WAITING';
meta.innerHTML='<span class="narration-source '+src+'">'+srcLabel+'</span>'+(data.model?'<span style="color:var(--dim)">'+esc(data.model)+'</span>':'')+(data.latency_ms?'<span style="color:var(--dim)">'+data.latency_ms+'ms</span>':'');

var devEl=document.getElementById('narration-developments');
var devs=data.developments||[];
if(devs.length){devEl.innerHTML=devs.map(function(d){return'<div class="ns-item">'+esc(d)+'</div>'}).join('')}
else{devEl.innerHTML='<div class="ns-item" style="color:var(--dim)">No developments yet</div>'}

var voiceEl=document.getElementById('narration-voices');
var voices=data.voices||[];
if(voices.length){voiceEl.innerHTML=voices.map(function(v){return'<div class="ns-item voice-item">'+esc(v)+'</div>'}).join('')}
else{voiceEl.innerHTML='<div class="ns-item voice-item" style="color:var(--dim)">Waiting for voices...</div>'}

if(data.forewarning){
voiceEl.innerHTML+='<div class="ns-item fore-item" style="margin-top:8px">'+esc(data.forewarning)+'</div>';
}
}

// ── Factions Sidebar ─────────────────────────────────────────
function renderFactions(data,tech,quests){
if(!data)return;
var list=document.getElementById('faction-list');
var keys=Object.keys(data);
var sig=keys.join('|');
if(list.dataset.sig!==sig){
list.dataset.sig=sig;
list.innerHTML='';
keys.forEach(function(fk){
var fc=FC[fk]||{color:'#78909C',name:fk};
var card=document.createElement('div');
card.className='faction-mini';
card.dataset.fk=fk;
card.innerHTML=
'<div class="fm-top"><span class="fm-dot" style="background:'+fc.color+'"></span><span class="fm-name" style="color:'+fc.color+'">'+esc(fc.name)+'</span><span class="fm-power" style="color:'+fc.color+'" data-f="power">&mdash;</span></div>'+
'<div class="fm-sub"><span data-f="cohesion-l">Cohesion</span><div class="fm-bar"><div class="fm-fill" data-f="cohesion" style="width:0"></div></div></div>'+
'<div class="fm-tech" data-f="tech">No research</div>'+
'<div class="fm-quest-count" data-f="quests"></div>'+
'<div class="fm-detail"><div data-f="stances"></div><div class="fm-action" data-f="action"></div></div>';
card.addEventListener('click',function(){
var was=card.classList.contains('active');
list.querySelectorAll('.faction-mini').forEach(function(c){c.classList.remove('active')});
if(!was){card.classList.add('active');activeFaction=fk}else{activeFaction=null}
});
list.appendChild(card);
});
}

keys.forEach(function(fk){
var f=data[fk];
var card=list.querySelector('[data-fk="'+fk+'"]');
if(!card)return;
var pwr=card.querySelector('[data-f="power"]');
if(pwr)pwr.textContent=f.power!=null?f.power:'\u2014';
var coh=card.querySelector('[data-f="cohesion"]');
var cohVal=f.cohesion!=null?f.cohesion:50;
if(coh){coh.style.width=clamp(cohVal,0,100)+'%';coh.style.background=cohVal>60?'#4CAF50':cohVal>30?'#FF9800':'#F44336'}

var techEl=card.querySelector('[data-f="tech"]');
if(techEl&&tech&&tech.factions&&tech.factions[fk]){
var ft=tech.factions[fk];
var active=ft.active_research;
var completed=ft.completed_techs||[];
if(active){
techEl.textContent='Researching: '+active.technology+' ('+Math.round(active.progress_percentage||0)+'%)';
}else{
techEl.textContent=completed.length?'Research paused ('+completed.length+' completed)':'No research';
}
}

var qEl=card.querySelector('[data-f="quests"]');
if(qEl&&quests&&quests.quest_log){
qEl.textContent=quests.quest_log.length+' active quests';
}

if(activeFaction===fk){
var stEl=card.querySelector('[data-f="stances"]');
if(stEl&&f.stances){
var sh='<div style="font-size:10px;color:var(--dim);margin-bottom:4px;text-transform:uppercase;letter-spacing:1px">Stances</div>';
Object.keys(f.stances).forEach(function(ok){
var sc=stanceClass(f.stances[ok]);
sh+='<div class="fm-stance-row"><span class="fm-stance-name">'+esc(factionName(ok))+'</span><span class="fm-stance-val" style="color:'+stanceColor(f.stances[ok])+'">'+esc(f.stances[ok])+'</span></div>';
});
stEl.innerHTML=sh;
}
var actEl=card.querySelector('[data-f="action"]');
if(actEl)actEl.textContent=f.recent_action||'No recent action';
}
});
}

// ── Tab: Thoughts ────────────────────────────────────────────
function renderThoughts(npcs){
var panel=document.getElementById('panel-thoughts');
if(!npcs||!npcs.length){panel.innerHTML='<div style="color:var(--dim)">No NPC data available</div>';return}
var html='';
npcs.forEach(function(npc){
var thoughts=npc.recent_thoughts||npc.thoughts||[];
var factionKey=npc.faction||npc.affiliation||npc.faction_id||'';
var fc=factionColor(factionKey);
var mc=moodColor(npc.mood);
var npcId=npc.char_id||npc.id||'';
var thHtml='';
if(thoughts.length){
thoughts.slice(0,3).forEach(function(th){
var text=typeof th==='string'?th:(th.text||th.thought||'');
thHtml+='<div class="thought-body">'+esc(text)+'</div>';
});
}else{
thHtml='<div class="thought-body" style="color:var(--dim)">No recent thoughts</div>';
}
var questHtml='';
var npcQuest=getQuestForNPC(npcId);
if(npcQuest){
var qTitle=npcQuest.quest_title||npcQuest.quest_id||'Unknown quest';
var qStatus=npcQuest.event||'active';
questHtml='<div class="thought-quest-badge">Quest: '+esc(qTitle)+' ('+esc(qStatus)+')</div>';
}
var techHtml='';
var factionTech=getTechForFaction(factionKey);
if(factionTech){
techHtml='<div class="thought-tech-line">Faction researching: '+esc(factionTech.technology)+' ('+Math.round(factionTech.progress_percentage||0)+'%)</div>';
}
html+=
'<div class="thought-card" style="border-left-color:'+fc+'">'+
'<div class="thought-header">'+
'<span class="thought-name" style="color:'+fc+'">'+esc(npc.name||'Unknown')+'</span>'+
'<span class="thought-title">'+esc(npc.title||npc.role||'')+'</span>'+
'<span class="thought-faction" style="color:'+fc+';background:'+fc+'14">'+esc(factionName(factionKey))+'</span>'+
'</div>'+
thHtml+
'<div class="thought-mood">Mood: <span style="color:'+mc+'">'+esc(npc.mood||'\u2014')+'</span><span class="thought-time">'+ago(npc.last_active||npc.last_thought||0)+'</span></div>'+
questHtml+
techHtml+
'</div>';
});
panel.innerHTML=html;
}

// ── Tab: Network ────────────────────────────────────────────
function renderNetwork(){
var panel=document.getElementById('panel-network');
var keys=Object.keys(relationshipNetwork);
if(!keys.length){panel.innerHTML='<div style="color:var(--dim)">No relationship data available — network populates as NPCs interact</div>';return}
var nameMap={};
(npcActivity||[]).forEach(function(n){nameMap[n.char_id||n.id]=n.name||n.char_id||n.id});
var npcFaction={};
(npcActivity||[]).forEach(function(n){npcFaction[n.char_id||n.id]=n.faction||n.affiliation||n.faction_id||''});
var html='<div style="margin-bottom:10px;color:var(--dim);font-size:14px">NPC relationship network — click a node to highlight connections</div>';
html+='<div class="network-grid">';
keys.forEach(function(cid){
var fc=factionColor(npcFaction[cid]);
var name=nameMap[cid]||cid;
var rels=relationshipNetwork[cid];
var isHL=highlightedNPC===cid;
var entries=Object.entries(rels).sort(function(a,b){return b[1]-a[1]});
var connHtml='';
entries.slice(0,8).forEach(function(e){
var otherId=e[0],affinity=e[1];
var cls=affinity>=70?'ally':affinity<=30?'rival':'neutral';
var otherName=nameMap[otherId]||otherId;
connHtml+='<span class="nn-link '+cls+'" title="'+otherName+': '+Math.round(affinity)+'">'+esc(otherName.replace(/_/g,' '))+'<span class="nn-strength">'+Math.round(affinity)+'</span></span>';
});
var questCount=getQuestCountForNPC(cid);
var badgeHtml=questCount>0?'<div class="nn-quest-badge">'+questCount+'</div>':'';
html+='<div class="network-node'+(isHL?' highlight':'')+'" onclick="highlightNPC(\''+esc(cid)+'\')">';
html+=badgeHtml;
html+='<div class="nn-name" style="color:'+fc+'">'+esc(name)+'</div>';
html+='<div class="nn-faction" style="color:'+fc+'">'+esc(factionName(npcFaction[cid]))+'</div>';
html+='<div class="nn-connections">'+connHtml+'</div>';
html+='</div>';
});
html+='</div>';
panel.innerHTML=html;
}

function highlightNPC(cid){
highlightedNPC=highlightedNPC===cid?null:cid;
renderNetwork();
}

// ── Tab: Stances ────────────────────────────────────────────
function renderStances(){
var panel=document.getElementById('panel-stances');
if(!factions||!Object.keys(factions).length){panel.innerHTML='<div style="color:var(--dim)">No faction stance data available</div>';return}
var fids=Object.keys(FC);
var html='<div style="margin-bottom:10px;color:var(--dim);font-size:14px">8\u00d78 faction stance matrix — rows show how each faction views the column faction</div>';
html+='<table class="stances-matrix"><thead><tr><th></th>';
fids.forEach(function(fid){
html+='<th class="col-header" style="color:'+factionColor(fid)+'">'+esc(factionName(fid).substring(0,12))+'</th>';
});
html+='</tr></thead><tbody>';
fids.forEach(function(rowFid){
var rowData=factions[rowFid];
var stances=rowData&&rowData.stances?rowData.stances:{};
html+='<tr><th style="color:'+factionColor(rowFid)+';text-align:right;padding-right:8px">'+esc(factionName(rowFid))+'</th>';
fids.forEach(function(colFid){
if(rowFid===colFid){
html+='<td class="self"><span class="stances-cell-val">&mdash;</span><span class="stances-cell-label">self</span></td>';
}else{
var s=stances[colFid];
var val=s&&(s.value!=null)?s.value:null;
var label=s?s.label||'':'';
var trend=s?s.trend:0;
var cellClass='neutral-cell';
if(val!==null){
if(val>=0.8)cellClass='ally';
else if(val>=0.6)cellClass='cordial';
else if(val>=0.4)cellClass='neutral-cell';
else if(val>=0.2)cellClass='tense';
else cellClass='hostile';
}
var trendArrow=trend>0.01?' \u2191':trend<-0.01?' \u2193':'';
html+='<td class="'+cellClass+'">';
html+='<span class="stances-cell-val">'+(val!==null?val.toFixed(2):'?')+'</span>';
html+='<span class="stances-cell-label">'+esc(label)+trendArrow+'</span>';
html+='</td>';
}
});
html+='</tr>';
});
html+='</tbody></table>';

html+='<div class="stances-legend">';
html+='<div class="legend-item"><span class="legend-dot" style="background:rgba(76,175,80,0.18)"></span>Ally (0.80+)</div>';
html+='<div class="legend-item"><span class="legend-dot" style="background:rgba(76,175,80,0.10)"></span>Cordial (0.60-0.79)</div>';
html+='<div class="legend-item"><span class="legend-dot" style="background:rgba(255,193,7,0.10)"></span>Neutral (0.40-0.59)</div>';
html+='<div class="legend-item"><span class="legend-dot" style="background:rgba(255,152,0,0.12)"></span>Tense (0.20-0.39)</div>';
html+='<div class="legend-item"><span class="legend-dot" style="background:rgba(244,67,54,0.14)"></span>Hostile (<0.20)</div>';
html+='<div class="legend-item"><span style="font-size:13px;color:var(--dim)">\u2191 improving &nbsp; \u2193 worsening</span></div>';
html+='</div>';

html+='<div class="recent-decisions">';
html+='<div class="rd-title">Recent Decisions</div>';
if(choiceResolutions&&choiceResolutions.length){
choiceResolutions.slice(0,5).forEach(function(r){
var title=r.event_title||r.event_id||'Unknown Event';
var chosen=r.chosen_choice_text||r.chosen_choice_id||'';
var fv=r.faction_votes||{};
html+='<div class="rd-item">';
html+='<div class="rd-event">'+esc(title)+'</div>';
html+='<div class="rd-choice">Chose: '+esc(chosen.replace(/_/g,' '))+'</div>';
var votesHtml='';
Object.keys(fv).forEach(function(fid){
var vote=fv[fid];
var fc=factionColor(fid);
var choiceLabel=vote.choice_id?vote.choice_id.replace(/_/g,' '):'?';
var score=vote.score!=null?vote.score.toFixed(3):'\u2014';
var vCls=chosen&&vote.choice_id&&vote.choice_id===r.chosen_choice_id?'for':'against';
if(vote.choice_id===chosen)vCls='for';
else if(score<0.3)vCls='abstain';
votesHtml+='<span class="rd-vote-badge '+vCls+'" style="border-left:2px solid '+fc+'">'+esc(factionName(fid))+': '+esc(choiceLabel)+' ('+score+')</span>';
});
html+='<div class="rd-votes">'+votesHtml+'</div>';
html+='</div>';
});
}else{
html+='<div style="color:var(--dim);font-size:14px">No faction decisions recorded yet</div>';
}
html+='</div>';

panel.innerHTML=html;
}

// ── Tab: Brain ──────────────────────────────────────────────
function renderBrain(){
var panel=document.getElementById('panel-brain');
var fids=Object.keys(factionBrains);
if(!fids.length){panel.innerHTML='<div style="color:var(--dim)">No faction brain state data — brains update every 5 minutes during simulation ticks</div>';return}
var html='<div style="margin-bottom:10px;color:var(--dim);font-size:14px">Faction decision-making priorities — higher weight = higher priority</div>';
fids.forEach(function(fid){
var brain=factionBrains[fid];
var fc=factionColor(fid);
var priorities=brain.priorities||[];
if(!priorities.length)return;
var maxW=0;
priorities.forEach(function(p){if(p.weight>maxW)maxW=p.weight});
if(maxW===0)maxW=1;
html+='<div class="brain-faction-card" style="border-left-color:'+fc+'">';
html+='<div class="brain-faction-name" style="color:'+fc+'">'+esc(factionName(fid))+'</div>';
priorities.forEach(function(p){
var pct=Math.round((p.weight/maxW)*100);
var label=(p.action||'').replace(/_/g,' ');
var isTop=p.weight===maxW;
html+='<div class="brain-priority">';
html+='<span class="bp-label">'+esc(label)+'</span>';
html+='<div class="bp-bar"><div class="bp-fill'+(isTop?' top-priority':'')+'" style="width:'+pct+'%;background:'+fc+'"></div></div>';
html+='<span class="bp-weight" style="color:'+fc+'">'+p.weight.toFixed(1)+'</span>';
html+='</div>';
});
html+='</div>';
});

html+='<div class="recent-events">';
html+='<div class="re-title">Recent Events</div>';
if(eventLog&&eventLog.length){
html+='<div class="re-timeline">';
eventLog.slice(0,5).forEach(function(ev){
var evType=(ev.type||ev.event_type||'').toLowerCase();
var evSource=(ev.source||ev.source_type||'').toLowerCase();
var srcClass='world';
var srcLabel='SYSTEM';
if(evType==='cascade'||ev.cascade){srcClass='cascade';srcLabel='CASCADE'}
else if(evSource==='faction'||evType==='faction_action'||ev.faction_id){srcClass='faction';srcLabel='FACTION'}
else if(evSource==='quest'){srcClass='quest';srcLabel='QUEST'}
else if(evSource==='tech'){srcClass='tech';srcLabel='TECH'}
var desc=ev.description||ev.message||ev.text||ev.event||'';
var ts=ev.timestamp||ev.time||'';
html+='<div class="re-entry">';
html+='<span class="re-time">'+esc(String(ts))+'</span>';
html+='<span class="re-source '+srcClass+'">'+srcLabel+'</span>';
html+='<span class="re-body">'+esc(desc)+'</span>';
html+='</div>';
});
html+='</div>';
}else{
html+='<div style="color:var(--dim);font-size:14px">No events recorded yet</div>';
}
html+='</div>';

panel.innerHTML=html;
}

function renderActiveTab(){
switch(activeTab){
case'thoughts':renderThoughts(npcActivity);break;
case'network':renderNetwork();break;
case'stances':renderStances();break;
case'brain':renderBrain();break;
}
}

// ── WebSocket ────────────────────────────────────────────────
function connectWS(){
try{
var proto=location.protocol==='https:'?'wss:':'ws:';
ws=new WebSocket(proto+'//'+location.host+'/ws');
ws.onopen=function(){wsReconnects=0;console.log('WS connected')};
ws.onmessage=function(e){
try{
var d=JSON.parse(e.data);
if(d.type==='world_state'||d.type==='world_state_update'){
worldState=d.data||d;
updateHeaderMetrics(worldState);
}
if(d.type==='narration')renderNarration(d.data);
if(d.type==='event')eventLog.unshift(d.data);
}catch(err){}
};
ws.onclose=function(){
wsReconnects++;
var delay=Math.min(5000,1000*wsReconnects);
setTimeout(connectWS,delay);
};
ws.onerror=function(){ws.close()};
}catch(e){setTimeout(connectWS,5000)}
}

// ── Data Fetching ────────────────────────────────────────────
async function fetchWorldState(){
var d=await api('/world/state',8000);
if(d){
var ws=d.state||d;
worldState=ws;
updateHeaderMetrics(ws);
}
}

async function fetchStatus(){
var d=await api('/simulation/status',10000);
if(d){
if(d.world_state||d.worldState)updateHeaderMetrics(d.world_state||d.worldState);
updateEra(d);
}
var es=await api('/engine-status',8000);
if(es){
updateEra(es.turn_progression||es);
}
}

async function fetchNarration(){
var d=await api('/narrator/history',8000);
var narrs=d&&d.narrations?d.narrations:(Array.isArray(d)?d:[]);
if(narrs.length){
narrationHistory=narrs;
renderNarration(narrs[0]);
}
}

async function fetchFactions(){
var d=await api('/simulation/factions',10000);
if(d)factions=d;
}

async function fetchNPCs(){
var d=await api('/simulation/npcs/activity',15000);
if(d){
var arr=d.npcs||d;
npcActivity=Array.isArray(arr)?arr:Object.values(arr);
}
}

async function fetchQuests(){
var d=await api('/simulation/npc-quests',10000);
if(d)questLog=d;
}

async function fetchTech(){
var d=await api('/simulation/faction-tech',10000);
if(d)techData=d;
}

async function fetchChoices(){
var d=await api('/simulation/choice-resolutions',8000);
if(d)choiceStats=d;
}

async function fetchEvents(){
var d=await api('/simulation/events',10000);
if(d){
var all=[];
if(d.world_events&&Array.isArray(d.world_events))all=all.concat(d.world_events);
if(d.cascade_events&&Array.isArray(d.cascade_events))all=all.concat(d.cascade_events);
if(d.broadcast_events&&Array.isArray(d.broadcast_events))all=all.concat(d.broadcast_events);
eventLog=all;
}
}

async function fetchRelationshipNetwork(){
var d=await api('/npcs/relationship-network',15000);
if(d&&d.network)relationshipNetwork=d.network;
}

async function fetchCascadeChains(){
var d=await api('/simulation/cascade-chains',10000);
if(d&&d.chains)cascadeChains=d.chains;
}

async function fetchFactionBrains(){
var d=await api('/simulation/faction-brains',10000);
if(d&&d.factions)factionBrains=d.factions;
}

async function fetchChoiceResolutionsDetail(){
var d=await api('/simulation/choice-resolutions/detail',10000);
if(d&&d.resolutions)choiceResolutions=d.resolutions;
}

// ── Main Refresh ─────────────────────────────────────────────
async function refreshLight(){
await Promise.all([fetchWorldState(),fetchStatus(),fetchNarration(),fetchFactions()]);
renderFactions(factions,techData,questLog);
}

async function refreshHeavy(){
await Promise.all([fetchNPCs(),fetchQuests(),fetchTech(),fetchChoices(),fetchEvents(),fetchRelationshipNetwork(),fetchCascadeChains(),fetchFactionBrains(),fetchChoiceResolutionsDetail()]);
renderActiveTab();
renderFactions(factions,techData,questLog);
}

async function init(){
makeStars();
buildHeaderMetrics();
connectWS();
await refreshLight();
await refreshHeavy();
setInterval(refreshLight,10000);
setInterval(refreshHeavy,30000);
}

document.addEventListener('DOMContentLoaded',init);
