"use strict";
// Freddie's Road Receipts: page logic. All data lives on the Pi. This page can run from the Pi or from GitHub Pages.
const API=window.FRR_API!==undefined?window.FRR_API:(/github\.io$/.test(location.hostname)?"https://acars-pi2.tail5b21f4.ts.net:8443":"");
let CODE="";try{CODE=localStorage.getItem("frr-code")||""}catch(e){}
const U=p=>API+p+(CODE?(p.includes("?")?"&":"?")+"k="+encodeURIComponent(CODE):"");
const $=(s,r=document)=>r.querySelector(s);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function toast(t){const d=document.createElement("div");d.className="toast";d.textContent=t;document.body.appendChild(d);setTimeout(()=>d.remove(),2600)}
async function api(path,body,method){
  try{
    const h=CODE?{"X-Code":CODE}:{};
    const r=await fetch(API+path,body===undefined?{headers:h}:{method:method||"POST",...(body instanceof FormData?{body,headers:h}:{headers:{"Content-Type":"application/json",...h},body:JSON.stringify(body)})});
    const j=await r.json().catch(()=>({ok:false,error:"The server sent something unexpected."}));
    if(!r.ok&&j.ok===undefined)j.ok=false;
    return j;
  }catch(e){return {ok:false,error:"Could not reach the Pi. Check your signal, then try again. If it keeps failing the Pi may be off."}}
}
function loginScreen(msg){
  setHead("Freddie's Road Receipts",null);
  app.innerHTML=`<div class="card"><h2>Passcode</h2><div class="mut">${esc(msg||"Type the passcode once. This phone remembers it.")}</div><input type="password" id="pc" autocomplete="off" autocapitalize="off" placeholder="Passcode"><button class="btn pri" id="pcb">Open</button></div>`;
  const go2=()=>{CODE=$("#pc").value.trim();try{localStorage.setItem("frr-code",CODE)}catch(e){}nav()};
  $("#pcb").onclick=go2;$("#pc").onkeydown=e=>{if(e.key==="Enter")go2()};
}
let S={roster:[],tags:[],trips:[]},busy=0,selTag=null,shrinkOn=true;
const P=id=>S.roster.find(p=>p.id===id)||{id,name:"?"};
const last=p=>p.name.split(" ").slice(-1)[0];
const HOTEL="Hotel",NONA="NONA";
const TL=g=>g===NONA?"Non Availability":g;
const TORD=["Hotel","Taxi",NONA,"CNA"];
const tagsSorted=()=>[...S.tags].sort((a,b)=>{const x=TORD.indexOf(a),y=TORD.indexOf(b);return (x<0?99:x)-(y<0?99:y)});
const TRIP=id=>S.trips.find(t=>t.id==id);
function findBatch(id){for(const t of S.trips){const b=t.batches.find(x=>x.id==id);if(b)return{t,b}}return{}}
const counts=r=>(r.status==="matched"||r.status==="confirmed")&&r.pid&&r.tag===HOTEL;
const present=b=>new Set(b.receipts.filter(counts).map(r=>r.pid));
const missing=(t,b)=>t.members.filter(id=>!present(b).has(id));
const queue=t=>t.batches.flatMap(b=>b.receipts.filter(r=>r.status==="needs_review").map(r=>({r,b})));
const hotel=b=>b.hotelFinal||b.hotelGuess||b.label;
const dateTxt=b=>{const d=b.dateFinal||b.dateGuess;if(!d)return"";return new Date(d+"T12:00").toLocaleDateString(undefined,{month:"short",day:"numeric"})};
const bLabel=b=>hotel(b)+(dateTxt(b)?` (${dateTxt(b)})`:"");
const live=t=>t.batches.filter(b=>b.receipts.length);
function report(t){return t.members.map(id=>({p:P(id),miss:live(t).filter(b=>missing(t,b).includes(id))})).sort((a,b)=>b.miss.length-a.miss.length)}
function stats(t){let miss=0,bats=0;live(t).forEach(b=>{bats++;miss+=missing(t,b).length});return{miss,bats,q:queue(t).length}}
const kb=n=>n>=1048576?(n/1048576).toFixed(1)+" MB":Math.max(1,Math.round(n/1024))+" KB";
function fname(t,r){
  const who=r.pid?last(P(r.pid)):"Unsorted";
  const same=t.batches.flatMap(b=>b.receipts).filter(x=>x.pid===r.pid&&x.tag===r.tag&&x.date===r.date&&x.status!=="needs_review"&&x.status!=="processing");
  const n=Math.max(1,same.findIndex(x=>x.id===r.id)+1);
  return `${who}_${r.date}_${r.tag}${n>1?"_"+n:""}.pdf`;
}
let needLogin=false;
async function refresh(){const s=await api("/api/state");if(s&&s.trips){S=s;needLogin=false}else if(s&&s.auth){needLogin=true}}

// a file dropped outside the box must not make the browser open it and leave the page
window.addEventListener("dragover",e=>e.preventDefault());
window.addEventListener("drop",e=>e.preventDefault());
// ---- router
const app=$("#app"),titleEl=$("#title"),backBtn=$("#back");let backTo=null;
const go=h=>{location.hash=h};
backBtn.onclick=()=>backTo&&go(backTo);
function setHead(title,back){titleEl.textContent=title;backTo=back;backBtn.style.display=back?"":"none"}
async function render(){
  const [,page,id]=(location.hash||"#/").split("/");
  const t=TRIP(id);
  const pages={"":home,roster:rosterPage,newtrip:()=>newTrip(),trip:()=>t?tripPage(t):home(),batch:()=>batchPage(id),review:()=>t?reviewPage(t):home(),ac:()=>t?acPage(t):home()};
  (pages[page||""]||home)();
}
async function nav(){await refresh();if(needLogin){loginScreen(CODE?"That passcode did not work. Try again.":"");return}await render();window.scrollTo(0,0)}
window.addEventListener("hashchange",nav);
// pages that other people can change refresh themselves every few seconds
setInterval(async()=>{
  if(busy||$("#layer").innerHTML||/INPUT|TEXTAREA/.test(document.activeElement.tagName))return;
  const pg=(location.hash||"#/").split("/")[1]||"";
  if(!["","trip","batch","review"].includes(pg))return;
  if(needLogin)return;const y=window.scrollY;const op=[...document.querySelectorAll("details[open]")].map(d=>(d.querySelector("b")||{}).textContent);await refresh();if(needLogin)return;await render();document.querySelectorAll("details").forEach(d=>{if(op.includes((d.querySelector("b")||{}).textContent))d.open=true});window.scrollTo(0,y);
},6000);

// ---- pages
function datesTxt(t){
  const f=d=>{if(!d)return"";const [y,m,dd]=d.split("-");return new Date(+y,+m-1,+dd).toLocaleDateString(undefined,{month:"short",day:"numeric",year:"numeric"})};
  const a=f(t.startDate),b=f(t.endDate);return a&&b?a+" to "+b:a?"Starts "+a:b?"Ends "+b:"";
}
function mcard(t){
  const st=stats(t);
  const pill=!st.bats?'<span class="pill warn">No receipts yet</span>':st.miss?`<span class="pill bad">${st.miss} missing</span>`:'<span class="pill ok">Complete</span>';
  return `<a class="mcard" href="#/trip/${t.id}"><div class="row sp"><b>${esc(t.name)}</b>${pill}</div>
  <div class="mut">${datesTxt(t)?datesTxt(t)+" &middot; ":""}${t.members.length} people &middot; ${t.batches.length} hotel batch${t.batches.length===1?"":"es"}${st.q?` &middot; <span style="color:var(--warn);font-weight:700">${st.q} to review</span>`:""}</div></a>`;
}
function home(){
  setHead("Freddie's Road Receipts",null);
  const open=S.trips.filter(t=>t.status!=="sent"),done=S.trips.filter(t=>t.status==="sent");
  app.innerHTML=`<div class="hero"><svg viewBox="0 0 370 130" class="c5" role="img" aria-label="Cartoon C-5 Galaxy"><g stroke="#1b2733" stroke-width="4" stroke-linejoin="round" stroke-linecap="round">
<path d="M14 6h60M30 118h40" stroke="#bcd3ee" stroke-dasharray="2 9"/>
<path d="M300 44L314 10h26l-6 36z" fill="#8f9eb0"/><rect x="298" y="3" width="58" height="11" rx="5" fill="#a9b6c6"/>
<path d="M18 76C14 52 40 42 70 42h180c36 0 56 4 82-14l16 4-8 38c-12 20-50 22-90 22H70c-32 0-48-4-52-16z" fill="#aab6c5"/>
<path d="M20 78c4 8 20 12 50 12h180c40 0 76-2 90-22-10 14-40 16-90 16H70c-26 0-46-2-50-6z" fill="#e3e9f0" stroke="none"/>
<path d="M126 50L190 50 250 22 214 22z" fill="#7f8ea1"/>
<path d="M146 62v12M204 62v12" stroke-width="5"/><rect x="128" y="72" width="44" height="20" rx="10" fill="#5d6c7e"/><rect x="186" y="72" width="44" height="20" rx="10" fill="#5d6c7e"/>
<circle cx="136" cy="102" r="9" fill="#2b3642"/><circle cx="160" cy="102" r="9" fill="#2b3642"/><circle cx="214" cy="102" r="9" fill="#2b3642"/><circle cx="238" cy="102" r="9" fill="#2b3642"/>
<path d="M44 50c8-4 20-6 34-6l4 12c-14 0-28 2-40 6z" fill="#7fc4ff"/>
<circle cx="52" cy="66" r="11" fill="#fff"/><circle cx="55" cy="67" r="5" fill="#1b2733" stroke="none"/><circle cx="57" cy="64" r="1.8" fill="#fff" stroke="none"/>
<path d="M28 80q12 10 28 2" fill="none" stroke-width="3.5"/>
</g><text x="262" y="74" font-family="Arial Black,Impact,sans-serif" font-size="17" fill="#fff" stroke="#1b2733" stroke-width="3" paint-order="stroke" transform="rotate(-2 262 74)">C-5</text></svg><div class="herot">Freddie's Road Receipts</div></div><div class="mut" style="margin:0 0 .5rem">Open missions. Anyone can open one to add receipts or see what is still missing.</div>
  ${open.map(mcard).join("")||'<div class="card mut">No open missions. Start one below.</div>'}
  <a class="btn pri" href="#/newtrip">+ Start a new mission</a>
  ${done.length?`<h2 style="margin-top:1.4rem">Sent</h2>${done.map(mcard).join("")}`:""}
  <a class="btn" href="#/roster" style="margin-top:1rem">People (roster)</a>`;
}
function rosterPage(){
  setHead("People","#/");
  app.innerHTML=`<div class="card"><h2>Roster</h2>${S.roster.map(p=>`<div class="row sp" style="min-height:52px;border-bottom:1px solid var(--line)"><div><b>${esc(p.name)}</b>${p.aliases?`<div class="mut">also: ${esc(p.aliases)}</div>`:""}</div><div class="row"><button class="btn sm" data-e="${p.id}">Edit</button><button class="btn sm" data-t="${p.id}">${p.active?"Active":"Off"}</button></div></div>`).join("")||'<div class="mut">Nobody yet.</div>'}</div>
  <div class="card"><h2>Add a person</h2><input type="text" id="nn" placeholder="Full name, like Mike Johnson"><div style="height:.5rem"></div><input type="text" id="na" placeholder="Other spellings on receipts, separated by commas (optional)"><button class="btn pri" id="add">Add person</button></div>`;
  app.querySelectorAll("[data-t]").forEach(b=>b.onclick=async()=>{const p=P(+b.dataset.t);await api("/api/person/"+p.id,{active:p.active?0:1});await refresh();rosterPage()});
  app.querySelectorAll("[data-e]").forEach(b=>b.onclick=()=>editPerson(P(+b.dataset.e)));
  $("#add").onclick=async()=>{const n=$("#nn").value.trim();if(!n)return toast("Type a name first");const r=await api("/api/person",{name:n,aliases:$("#na").value.trim()});if(!r.ok)return toast(r.error);await refresh();rosterPage();toast("Added "+n)};
}
function editPerson(p){
  const L=$("#layer");L.innerHTML=`<div class="modal"><div class="sheet"><h2>Edit person</h2><input type="text" id="en" value="${esc(p.name)}"><div style="height:.5rem"></div><input type="text" id="ea" value="${esc(p.aliases)}" placeholder="Other spellings, separated by commas"><button class="btn pri" id="es">Save</button><button class="btn danger" id="ed">Remove this person</button><button class="btn" id="ec">Close</button></div></div>`;
  $("#ec").onclick=()=>L.innerHTML="";
  $("#ed").onclick=async()=>{
    const n=S.trips.reduce((a,t)=>a+t.batches.reduce((x,b)=>x+b.receipts.filter(r=>r.pid===p.id).length,0),0);
    if(!confirm("Remove "+p.name+" from the crew? "+(n?n+" receipt"+(n===1?"":"s")+" filed under them will go back to 'Not sure whose these are' (the receipts are kept).":"They have no receipts filed."))) return;
    const r=await api("/api/person/"+p.id+"/delete",{});if(!r.ok)return toast(r.error||"Could not remove.");
    L.innerHTML="";toast(p.name+" removed");await refresh();rosterPage();
  };
  $("#es").onclick=async()=>{const r=await api("/api/person/"+p.id,{name:$("#en").value,aliases:$("#ea").value});if(!r.ok)return toast(r.error);L.innerHTML="";await refresh();rosterPage()};
}
// one-tap crews: adds the people to the roster (if missing) and ticks them for this mission. Always optional.
const CREWS={"Crew 4":["Matthew Allen","Cale Simmons","Samuel Johnson","Katie Ha","Tristian Acosta","Jason Johns","Alicia Grajeda","Sebastian Romero"]};
const nkey=n=>String(n||"").toUpperCase().replace(/[^A-Z'\- ]/g," ").split(/\s+/).filter(Boolean).join(" ");
function newTrip(pre=[],nameVal=""){
  setHead("New mission","#/");
  app.innerHTML=`<div class="card"><h2>Mission name</h2><input type="text" id="tn" placeholder="e.g. Pacific Mission, Apr 2026" value="${esc(nameVal)}"></div>
  <div class="card"><h2>Who is on this mission?</h2><div class="mut" style="margin-bottom:.4rem">Everyone on the crew list is ticked. Untick anyone who is not on this one.</div>
  <div class="row" style="margin-bottom:.4rem">${Object.keys(CREWS).map(k=>`<button class="btn sm" data-crew="${esc(k)}">+ ${esc(k)} (${CREWS[k].length} people)</button>`).join("")}</div>
  ${S.roster.filter(p=>p.active).map(p=>`<label class="chk"><input type="checkbox" value="${p.id}" ${(pre.length?pre.includes(p.id):true)?"checked":""}> ${esc(p.name)}</label>`).join("")}</div>
  <button class="btn pri" id="go">Start mission</button>`;
  app.querySelectorAll("[data-crew]").forEach(b=>b.onclick=async()=>{
    const names=CREWS[b.dataset.crew],keep=[...app.querySelectorAll("input[type=checkbox]:checked")].map(c=>+c.value),nv=$("#tn").value;
    const ids=[];
    for(const n of names){
      let p=S.roster.find(x=>nkey(x.name)===nkey(n));
      if(!p){const r=await api("/api/person",{name:n});if(!r.ok){toast(r.error||"Could not add "+n);return}await refresh();p=S.roster.find(x=>nkey(x.name)===nkey(n))}
      if(p){if(!p.active){await api("/api/person/"+p.id,{active:1});await refresh()}ids.push(p.id)}
    }
    newTrip([...new Set([...keep,...ids])],nv);toast(b.dataset.crew+" added");
  });
  $("#go").onclick=async()=>{const n=$("#tn").value.trim();const m=[...app.querySelectorAll("input[type=checkbox]:checked")].map(c=>+c.value);
    if(!n)return toast("Give the mission a name");
    const r=await api("/api/trip",{name:n,members:m});if(!r.ok)return toast(r.error);await refresh();go("#/trip/"+r.id)};
}
function stayKey(b){return b.dateFinal||b.dateGuess||"9999-99-99"}
function stayCard(t,b){
  const m=missing(t,b),n=t.members.length-m.length,full=t.members.length>0&&!m.length,empty=!b.receipts.length;
  const pc=t.members.length?Math.round(100*n/t.members.length):0;
  const pill=empty?'<span class="pill warn">No receipts yet</span>':`<span class="pill ${full?"ok":"bad"}">${n} of ${t.members.length}${full?" &#10003;":""}</span>`;
  const have=present(b);
  const people=t.members.map(id=>`<span class="pchip ${have.has(id)?"y":"n"}">${have.has(id)?"&#10003;":"&#10007;"} ${esc(last(P(id)))}</span>`).join("");
  return `<details class="stay ${full?"done":""}"><summary><div class="row sp"><div><b>${esc(hotel(b)||b.label)}</b><div class="mut">${esc(dateTxt(b)||"No date yet")} &middot; ${esc(b.label)}</div></div>${pill}</div><div class="prog"><i style="width:${pc}%;background:${full?"var(--ok)":"var(--warn)"}"></i></div></summary>
  <div class="pchips">${people||'<span class="mut">No crew list on this mission.</span>'}</div>
  <div class="row" style="gap:.5rem"><a class="btn sm pri" href="#/batch/${b.id}">${empty?"Add receipts":"Open this stay"}</a>${empty?`<button class="btn sm danger" data-delstay="${b.id}">Remove</button>`:""}</div></details>`;
}
function stayModal(t){
  const L=$("#layer");let rows=[["",""],["",""]];
  const draw=()=>{L.innerHTML=`<div class="modal"><div class="sheet"><h2>Add hotel stays</h2><div class="mut">Name the hotels now and add receipts later. The date is optional.</div>${rows.map((r,i)=>`<div class="row" style="gap:.4rem;margin-top:.5rem"><input type="text" data-hn="${i}" placeholder="Hotel name" value="${esc(r[0])}" style="flex:2"><input type="date" data-hd="${i}" value="${esc(r[1])}" style="flex:1"></div>`).join("")}<button class="btn sm" id="more" style="margin-top:.5rem">+ Another hotel</button><button class="btn pri" id="ssv">Save stays</button><button class="btn" id="sgo">Save and add receipts to the first one</button><button class="btn" id="scl">Cancel</button></div></div>`;
    const keep=()=>{L.querySelectorAll("[data-hn]").forEach(e=>rows[+e.dataset.hn][0]=e.value);L.querySelectorAll("[data-hd]").forEach(e=>rows[+e.dataset.hd][1]=e.value)};
    $("#more").onclick=()=>{keep();rows.push(["",""]);draw()};
    $("#scl").onclick=()=>L.innerHTML="";
    const save=async first=>{keep();const todo=rows.filter(r=>r[0].trim());if(!todo.length)return toast("Type at least one hotel name");let firstId=null;
      for(const r of todo){const b=await api("/api/trip/"+t.id+"/batch",{});if(!b.ok)return toast(b.error||"Could not add.");if(!firstId)firstId=b.id;await api("/api/batch/"+b.id+"/meta",{hotel:r[0].trim(),date:r[1]})}
      L.innerHTML="";await refresh();toast(todo.length+" stay"+(todo.length===1?"":"s")+" saved");if(first)go("#/batch/"+firstId);else tripPage(TRIP(t.id))};
    $("#ssv").onclick=()=>save(false);$("#sgo").onclick=()=>save(true);
  };draw();
}
function tripPage(t){
  setHead(t.name,"#/");
  const q=queue(t).length,st=stats(t);
  const stays=[...t.batches].sort((x,y)=>stayKey(x)<stayKey(y)?-1:stayKey(x)>stayKey(y)?1:x.id-y.id);
  const complete=stays.filter(b=>b.receipts.length&&!missing(t,b).length).length;
  const lv=live(t);
  const CATS=["Taxi",NONA,"CNA"];
  const catSet=g=>new Set(t.batches.flatMap(b=>b.receipts.filter(r=>(r.status==="matched"||r.status==="confirmed")&&r.pid&&r.tag===g).map(r=>r.pid)));
  const cats=t.members.length?`<div class="cats" id="cats">${CATS.map(g=>{const h=catSet(g),n=t.members.filter(id=>h.has(id)).length,ok=n===t.members.length;return `<button class="cat ${ok?"ok":""}" data-cat="${esc(g)}"><span>${esc(TL(g))}</span><b>${n}/${t.members.length}</b></button>`}).join("")}</div>`:"";
  const nona="";
  const grid=lv.length>1?`<details class="card"><summary><b>Full grid (everyone, every stay)</b></summary><div style="overflow-x:auto;margin-top:.5rem"><table class="mx"><tr><th>Person</th>${lv.map(b=>`<th>${esc(hotel(b))}<br>${esc(dateTxt(b))}</th>`).join("")}</tr>${report(t).map(x=>`<tr><td>${esc(x.p.name)}</td>${lv.map(b=>{const m=missing(t,b).includes(x.p.id);return `<td class="${m?"n":"y"}">${m?"MISSING":"&#10003;"}</td>`}).join("")}</tr>`).join("")}</table></div><div class="mut" style="margin-top:.4rem">Counts hotel receipts only.</div></details>`:"";
  app.innerHTML=`${cats}<div class="card"><div class="row sp"><div><b>${stays.length} stay${stays.length===1?"":"s"}</b> &middot; ${complete} complete</div><span class="pill ${t.status==="sent"?"ok":"warn"}">${t.status==="sent"?"Sent":"Open"}</span></div>
  <div class="mut" style="margin:.2rem 0 .5rem">${st.miss?`<span class="miss">${st.miss} receipt${st.miss===1?"":"s"} still missing</span>`:(stays.length?"Nobody is missing anything":"No stays yet")}${datesTxt(t)?" &middot; "+datesTxt(t):""} &middot; ${t.members.length} people</div>
  <div class="row" style="gap:.5rem;flex-wrap:wrap"><a class="btn sm" href="#/review/${t.id}">Not sure whose ${q?`<span class="pill warn">${q}</span>`:""}</a><a class="btn sm" href="#/ac/${t.id}" style="background:#0b6b3a;border-color:#0b6b3a;color:#fff">AC Review</a></div></div>
  <h2 style="margin:.9rem 0 .4rem">Hotel stays</h2>
  ${stays.map(b=>stayCard(t,b)).join("")||'<div class="card mut">No stays yet. Start one for your first hotel.</div>'}
  <button class="btn pri" id="nb">+ Add hotel stays</button>
  ${nona}
  ${grid}
  <details class="card"><summary><b>Mission dates</b></summary><div class="row" style="gap:.6rem;flex-wrap:wrap;align-items:end;margin-top:.5rem"><label class="mut" style="flex:1;min-width:8rem">Start date<br><input type="date" id="sd" value="${esc(t.startDate||"")}" style="width:100%"></label><label class="mut" style="flex:1;min-width:8rem">End date<br><input type="date" id="ed" value="${esc(t.endDate||"")}" style="width:100%"></label></div></details>
  ${t.status==="sent"?'<button class="btn" id="reopen">Reopen mission</button>':""}
  <div style="height:1rem"></div><button class="btn danger" id="delmission">Delete this mission</button>`;
  const saveDates=async()=>{const r=await api("/api/trip/"+t.id+"/dates",{startDate:$("#sd").value,endDate:$("#ed").value});if(!r.ok){toast(r.error||"Could not save dates.");return}await refresh();toast("Dates saved")};
  $("#sd").onchange=saveDates;$("#ed").onchange=saveDates;
  $("#delmission").onclick=async()=>{
    const n=t.batches.reduce((a,b)=>a+b.receipts.length,0);
    if(!confirm('Delete the mission "'+t.name+'" and all '+n+' receipt'+(n===1?"":"s")+' in it? The photos, scans and zips are removed from the Pi.'))return;
    if(!confirm('Are you REALLY sure? "'+t.name+'" will be gone for good. This cannot be undone.'))return;
    const r=await api("/api/trip/"+t.id+"/delete",{});if(!r.ok)return toast(r.error||"Could not delete.");
    toast("Mission deleted");await refresh();go("#/");
  };
  $("#nb").onclick=()=>stayModal(t);
  const ch=$("#cats");if(ch)ch.style.top=(document.querySelector("header.top").offsetHeight)+"px";
  app.querySelectorAll("[data-cat]").forEach(bt=>bt.onclick=()=>{const g=bt.dataset.cat,h=catSet(g),L=$("#layer");
    L.innerHTML=`<div class="modal"><div class="sheet"><h2>${esc(TL(g))}</h2><div class="mut">Upload these inside any hotel stay and pick the <b>${esc(TL(g))}</b> tag. Green means a receipt is filed.</div><div class="pchips">${t.members.map(id=>`<span class="pchip ${h.has(id)?"y":"n"}">${h.has(id)?"&#10003;":"&#10007;"} ${esc(P(id).name)}</span>`).join("")}</div><button class="btn" id="ccl">Close</button></div></div>`;
    $("#ccl").onclick=()=>L.innerHTML=""});
  app.querySelectorAll("[data-delstay]").forEach(bt=>bt.onclick=async()=>{if(!confirm("Remove this empty stay?"))return;const r=await api("/api/batch/"+bt.dataset.delstay+"/delete",{});if(!r.ok)return toast(r.error||"Could not remove.");await refresh();tripPage(TRIP(t.id))});
  const ro=$("#reopen");if(ro)ro.onclick=async()=>{await api("/api/trip/"+t.id+"/status",{status:"open"});await refresh();tripPage(TRIP(t.id));toast("Mission reopened")};
}
function batchPage(id){
  const {t,b}=findBatch(id);if(!b)return home();
  setHead(b.label,"#/trip/"+t.id);
  const m=missing(t,b),n=t.members.length-m.length,aw=b.receipts.filter(r=>r.status==="needs_review").length,pr=b.receipts.filter(r=>r.status==="processing").length;
  const byP={};b.receipts.filter(r=>(r.status==="matched"||r.status==="confirmed")&&r.pid).forEach(r=>(byP[r.pid]??=[]).push(r));
  app.innerHTML=`<div class="counter ${m.length?'warn':'ok'}"><span><span class="big">${n} of ${t.members.length}</span> hotel receipts</span>${aw?`<a class="lnk" href="#/review/${t.id}">${aw} to review</a>`:""}</div>
  ${pr?`<div class="card">Reading ${pr} receipt${pr>1?"s":""}… this page updates by itself.</div>`:""}
  ${m.length&&b.receipts.length?`<div class="card"><b class="miss">Missing:</b> ${m.map(i=>`<span class="miss">${esc(P(i).name)}</span>`).join(", ")}</div>`:""}
  <div class="drop">
   <div class="step"><b>1.</b> Pick a tag</div>
   <div class="chips">${tagsSorted().map(g=>`<button class="chip ${g===selTag?"sel":""}" data-g="${esc(g)}">${esc(TL(g))}</button>`).join("")}<button class="chip" id="newtag">+ New</button></div>
   <div id="newrow" style="display:none" class="row"><input type="text" id="ntn" placeholder="New tag name" style="flex:1"><button class="btn sm pri" id="ntok">Add</button></div>
   <div class="step"><b>2.</b> Add receipts</div><div class="dd mut">On a computer you can also drag photos onto this box.</div>
   <input type="file" id="files" accept="image/*" multiple hidden><input type="file" id="cam" accept="image/*" capture="environment" hidden>
   <button class="btn pri" id="pick">Add receipts with photo library</button><button class="btn" id="shoot">Take photo</button>
   <div class="mut" style="margin:.4rem 0">Files are named: last name, today's date, then the tag.</div>
   <label class="row" style="justify-content:center;gap:.6rem;min-height:44px"><input type="checkbox" id="shr" ${shrinkOn?"checked":""}> <span class="mut">Shrink big photos before sending (faster, saves data)</span></label>
   <div id="prog"></div></div>
  <div class="card"><h2>Hotel and date</h2><div class="mut">${b.hotelGuess?"Our guess, tap to fix:":"Filled in after the first hotel receipt is read."}</div>
   <input type="text" id="hn" value="${esc(b.hotelFinal||b.hotelGuess)}" placeholder="Hotel name"><div style="height:.5rem"></div><input type="date" id="dt" value="${esc(b.dateFinal||b.dateGuess)}">
   <button class="btn" id="sv">Save</button></div>
  ${Object.keys(byP).length?`<div class="card"><h2>Filed receipts</h2>${t.members.filter(i=>byP[i]).map(i=>`<div class="who">${esc(P(i).name)}</div><div class="grid">${byP[i].map(r=>`<div><button class="thumb" data-r="${r.id}" style="width:100%"><img src="${U(r.img)}" alt="">${r.inferred?'<span class="tag">guessed by elimination</span>':""}</button><div class="cap">${esc(fname(t,r))}</div></div>`).join("")}</div>`).join("")}</div>`:""}`;
  $("#sv").onclick=async()=>{await api("/api/batch/"+b.id+"/meta",{hotel:$("#hn").value,date:$("#dt").value});await refresh();toast("Saved");batchPage(id)};
  const needTag=()=>{if(!selTag){toast("Pick a tag first (step 1)");return false}return true};
  app.querySelectorAll("[data-g]").forEach(c=>c.onclick=()=>{selTag=c.dataset.g;batchPage(id)});
  $("#newtag").onclick=()=>{$("#newrow").style.display="flex";$("#ntn").focus()};
  $("#ntok").onclick=async()=>{const r=await api("/api/tag",{name:$("#ntn").value});if(!r.ok)return toast(r.error);selTag=r.name;await refresh();batchPage(id)};
  $("#shr").onchange=e=>shrinkOn=e.target.checked;
  const fromInput=e=>{const fs=[...e.target.files];e.target.value="";if(fs.length)upload(b,fs,selTag)};
  $("#pick").onclick=()=>needTag()&&$("#files").click();
  $("#shoot").onclick=()=>needTag()&&$("#cam").click();
  $("#files").onchange=fromInput;$("#cam").onchange=fromInput;
  // drag and drop (computers)
  const dz=$(".drop");
  ["dragenter","dragover"].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.add("over")}));
  ["dragleave","drop"].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.remove("over")}));
  dz.addEventListener("drop",e=>{
    const fs=[...(e.dataTransfer?e.dataTransfer.files:[])].filter(f=>/^image\//.test(f.type)||/\.(jpe?g|png|heic|heif)$/i.test(f.name));
    if(!fs.length)return toast("Drop photo files (JPEG, PNG or HEIC).");
    if(needTag())upload(b,fs,selTag);
  });
  app.querySelectorAll("button.thumb").forEach(el=>el.onclick=()=>cropModal(findBatch(id).b.receipts.find(r=>r.id==el.dataset.r)));
}
async function shrinkFile(f){
  try{
    const url=URL.createObjectURL(f);const im=new Image();await new Promise((ok,no)=>{im.onload=ok;im.onerror=no;im.src=url});
    const sc=Math.min(1,1600/Math.max(im.width,im.height));
    const c=document.createElement("canvas");c.width=Math.round(im.width*sc);c.height=Math.round(im.height*sc);
    c.getContext("2d").drawImage(im,0,0,c.width,c.height);URL.revokeObjectURL(url);
    const blob=await new Promise(r=>c.toBlob(r,"image/jpeg",.8));
    return blob&&blob.size<f.size?new File([blob],f.name.replace(/\.\w+$/,"")+".jpg",{type:"image/jpeg"}):f;
  }catch(e){return f}   // e.g. HEIC the browser cannot draw: send as is
}
async function upload(b,files,tag){
  busy++;
  const box=$("#prog");box.innerHTML=files.map((f,i)=>`<div style="margin-top:.6rem"><div class="row sp"><span>${esc(f.name)}</span><span class="mut" id="st${i}">Waiting</span></div><div class="prog"><i id="pb${i}"></i></div></div>`).join("");
  try{
    const fd=new FormData();fd.append("tag",tag);const sizes=[];
    for(let i=0;i<files.length;i++){
      $("#st"+i).textContent=shrinkOn?"Shrinking…":"Preparing…";$("#pb"+i).style.width="10%";
      const f=shrinkOn?await shrinkFile(files[i]):files[i];
      sizes.push(kb(files[i].size)+(f.size<files[i].size?" to "+kb(f.size):""));fd.append("files",f);$("#pb"+i).style.width="25%";
    }
    files.forEach((_,i)=>$("#st"+i).textContent="Sending…");
    const r=await api("/api/batch/"+b.id+"/upload",fd);
    if(!r.ok){box.innerHTML=`<div class="err">${esc(r.error||"Upload failed.")}</div>`;return}
    if(r.errors&&r.errors.length)box.insertAdjacentHTML("afterbegin",r.errors.map(e=>`<div class="err">${esc(e)}</div>`).join(""));
    // wait for the Pi to read them
    const ids=r.ids;let done=false,tries=0;
    while(!done&&tries++<400){
      await refresh();const rs=findBatch(b.id).b.receipts.filter(x=>ids.includes(x.id));
      done=rs.every(x=>x.status!=="processing");
      ids.forEach((id,i)=>{const x=rs.find(y=>y.id===id);if(!x)return;const el=$("#st"+i);if(!el)return;
        el.textContent=x.status==="processing"?"Reading…":(x.status==="needs_review"?"Not sure whose":(x.inferred?"Filed (guessed)":"Filed"))+" ("+sizes[i]+")";
        $("#pb"+i).style.width=x.status==="processing"?"60%":"100%"});
      if(!done)await sleep(1500);
    }
    await sleep(1200);
  }finally{busy--}
  await refresh();render();toast("Done");
}
async function delReceipt(r,after){
  if(!confirm("Delete this receipt? The photo and scan are removed from the Pi. This cannot be undone."))return;
  const res=await api("/api/receipt/"+r.id+"/delete",{});
  if(!res.ok)return toast(res.error||"Could not delete.");
  toast("Receipt deleted");await refresh();after();
}
function dlist(id){return `<datalist id="${id}">${S.roster.map(p=>`<option value="${esc(p.name)}">`).join("")}</datalist>`}
function reviewPage(t){
  setHead("Not sure whose these are","#/trip/"+t.id);
  const items=queue(t);
  if(!items.length){app.innerHTML=`<div class="card"><span class="pill ok">All clear</span> Nothing waiting for review.</div>`;return}
  app.innerHTML=items.map(({r,b})=>{
    const have=r.cands.map(c=>P(c).name);
    const names=(r.sugg||[]).filter(n=>!have.includes(n));
    return `<div class="card"><div class="mut">${esc(b.label)}: ${esc(hotel(b))} &middot; tag: <b>${esc(TL(r.tag))}</b></div>
    <div class="q"><img src="${U(r.img)}" alt="" data-c="${r.id}"><div><div class="ocr">${esc(r.text.slice(0,200))}</div><div class="mut" style="margin-top:.3rem">${esc(r.note)} ${r.cands.length?"Best guesses:":"Pick who this is:"}</div></div></div>
    <div class="candbtns">${r.cands.map(c=>`<button class="btn" data-r="${r.id}" data-p="${c}">${esc(P(c).name)}</button>`).join("")}
    <div class="row"><input type="text" list="dl" placeholder="Pick a crew name" data-in="${r.id}" style="flex:1"><button class="btn sm pri" data-go="${r.id}">Add</button></div><button class="btn danger" data-del="${r.id}">Delete this receipt</button></div></div>`}).join("")+dlist("dl");
  const fileAs=async(rid,body,label)=>{const r=await api("/api/receipt/"+rid+"/confirm",body);if(!r.ok)return toast(r.error);toast("Filed under "+label);await refresh();reviewPage(TRIP(t.id))};
  app.querySelectorAll("[data-p]").forEach(bt=>bt.onclick=()=>fileAs(bt.dataset.r,{person_id:+bt.dataset.p},P(+bt.dataset.p).name));
  app.querySelectorAll("[data-n]").forEach(bt=>bt.onclick=()=>fileAs(bt.dataset.r,{name:bt.dataset.n},bt.dataset.n));
  app.querySelectorAll("[data-go]").forEach(bt=>bt.onclick=()=>{const v=app.querySelector(`[data-in="${bt.dataset.go}"]`).value.trim();if(!v)return toast("Type a name first");fileAs(bt.dataset.go,{name:v},v)});
  app.querySelectorAll("img[data-c]").forEach(im=>im.onclick=()=>viewer(items.find(x=>x.r.id==im.dataset.c).r));
  app.querySelectorAll("[data-del]").forEach(bt=>bt.onclick=()=>delReceipt(items.find(x=>x.r.id==bt.dataset.del).r,()=>reviewPage(TRIP(t.id))));
}
function acPage(t){
  setHead("Aircraft Commander Review","#/trip/"+t.id);
  const rep=report(t),bad=rep.filter(x=>x.miss.length),ok=rep.filter(x=>!x.miss.length),q=queue(t).length;
  app.innerHTML=`${q?`<div class="card" style="background:var(--warnbg)"><b>${q} receipt${q>1?"s":""} still not sure whose.</b> <a class="lnk" href="#/review/${t.id}">Review them first</a></div>`:""}
  <div class="card"><h2>Missing receipts</h2>${bad.length?bad.map(x=>`<p class="miss" style="margin:.4rem 0">${esc(last(x.p))} is missing receipts at ${x.miss.map(b=>esc(bLabel(b))).join(" and ")}.</p>`).join(""):`<span class="pill ok">Nobody is missing anything</span>`}</div>
  <div class="card"><h2>Complete</h2>${ok.map(x=>`<span class="pill ok" style="margin:.15rem">${esc(x.p.name)}</span>`).join(" ")||'<span class="mut">No one yet</span>'}</div>
  <a class="btn" href="#/trip/${t.id}">Back to mission</a><button class="btn pri" id="send">Build and send</button><div id="out"></div>`;
  $("#send").onclick=async()=>{
    if(bad.length&&!confirm(bad.length+" "+(bad.length>1?"people are":"person is")+" missing receipts. Send anyway?"))return;
    const out=$("#out");out.innerHTML=`<div class="card"><div>Building the PDFs and zip, then emailing… this can take a minute on the Pi.</div><div class="prog"><i style="width:60%"></i></div></div>`;
    busy++;const r=await api("/api/trip/"+t.id+"/ac-send",{});busy--;
    if(r.mb===undefined){out.innerHTML=`<div class="err">${esc(r.error||"Something went wrong.")}</div>`;return}
    const tree=Object.entries(r.tree||{}).map(([f,fs])=>`${f}/\n`+fs.map(n=>"    "+n).join("\n")).join("\n");
    out.innerHTML=`<div class="card"><span class="pill ${r.ok?"ok":"warn"}">${r.ok?"Sent":"Built, not emailed"}</span>
    <p>${r.receipts} receipts, zip is <b>${r.mb} MB</b>. ${r.ok?(r.attached?"Attached to the email, with a download link too.":"Too big to attach, so the email has a link only."):""}</p>
    ${r.error?`<div class="err">${esc(r.error)}</div>`:""}
    <pre class="tree">SUMMARY.pdf\n${esc(tree)}</pre>
    <a class="btn" href="${esc(r.link)}">Download the zip</a><div class="mut" style="word-break:break-all">${esc(r.link)}</div></div>`;
    await refresh();
  };
}
function viewer(r){
  if(!r)return;
  const L=$("#layer");let z=1,orig=false;
  L.innerHTML=`<div class="modal" style="align-items:stretch"><div class="viewer"><div class="vbar"><button class="btn sm" id="vzm">&minus;</button><button class="btn sm" id="vzp">+</button><button class="btn sm" id="vzf">Fit</button><button class="btn sm" id="vzo">Original</button><button class="btn sm" id="vcr">Fix crop</button><button class="btn sm pri" id="vcl">Close</button></div>
  <div class="vbox" id="vb"><img id="vi" src="${U("/img/"+r.id)}" alt=""></div><div class="mut" style="color:#ccc;text-align:center;font-size:.75rem;padding:.3rem">Use + and &minus;, or double-tap the photo. Drag to move around.</div></div></div>`;
  const vi=$("#vi"),vb=$("#vb");
  const set=n=>{z=Math.min(5,Math.max(1,n));vi.style.width=(z*100)+"%"};
  $("#vzp").onclick=()=>set(z+.5);$("#vzm").onclick=()=>set(z-.5);$("#vzf").onclick=()=>set(1);
  vi.ondblclick=()=>set(z>=2?1:2.5);
  $("#vzo").onclick=e=>{orig=!orig;vi.src=U("/img/"+r.id+(orig?"?orig=1":""));e.target.textContent=orig?"Cleaned":"Original"};
  $("#vcl").onclick=()=>L.innerHTML="";
  $("#vcr").onclick=()=>cropModal(r);
  let d=null;vb.onpointerdown=e=>{if(e.pointerType==="mouse"){d=[e.clientX,e.clientY,vb.scrollLeft,vb.scrollTop];vb.setPointerCapture(e.pointerId)}};
  vb.onpointermove=e=>{if(d){vb.scrollLeft=d[2]-(e.clientX-d[0]);vb.scrollTop=d[3]-(e.clientY-d[1])}};
  vb.onpointerup=()=>{d=null};
}
function cropModal(r){
  if(!r)return;
  const L=$("#layer");L.innerHTML=`<div class="modal"><div class="sheet"><h2>Fix the crop</h2><div class="mut">Drag the four corners to the edges of the paper, then re-scan.</div>
  <div class="cropbox" id="cb"><img src="${U("/img/"+r.id+"?orig=1")}" alt=""><svg><polygon id="pg" fill="rgba(76,141,255,.15)" stroke="#4c8dff" stroke-width="3"/></svg></div>
  <button class="btn pri" id="ap">Re-scan with this crop</button>
  <div class="mut" style="margin-top:.8rem">Filed under (type to change):</div><input type="text" id="mvn" list="dl2" value="${esc(r.pid?P(r.pid).name:"")}">${dlist("dl2")}<button class="btn" id="mv">Save name</button>
  <button class="btn danger" id="rm">Delete this receipt</button>
  <button class="btn" id="cl">Close</button></div></div>`;
  const cb=$("#cb"),img=$("img",cb);let pts=[[.1,.1],[.9,.1],[.9,.9],[.1,.9]],hs=[];
  const draw=()=>{const w=cb.clientWidth,h=cb.clientHeight;$("#pg").setAttribute("points",pts.map(p=>p[0]*w+","+p[1]*h).join(" "));hs.forEach((e,i)=>{e.style.left=pts[i][0]*w+"px";e.style.top=pts[i][1]*h+"px"})};
  pts.forEach((p,i)=>{const e=document.createElement("div");e.className="handle";cb.appendChild(e);hs.push(e);
    e.onpointerdown=ev=>{e.setPointerCapture(ev.pointerId);e.onpointermove=m=>{const R=cb.getBoundingClientRect();pts[i]=[Math.min(1,Math.max(0,(m.clientX-R.left)/R.width)),Math.min(1,Math.max(0,(m.clientY-R.top)/R.height))];draw()};e.onpointerup=()=>{e.onpointermove=null}}});
  img.onload=draw;setTimeout(draw,50);
  $("#cl").onclick=()=>L.innerHTML="";
  $("#rm").onclick=async()=>{await delReceipt(r,()=>{L.innerHTML="";render()})};
  $("#mv").onclick=async()=>{const v=$("#mvn").value.trim();if(!v)return toast("Type a name first");const res=await api("/api/receipt/"+r.id+"/confirm",{name:v});if(!res.ok)return toast(res.error);L.innerHTML="";toast("Saved");await refresh();render()};
  $("#ap").onclick=async()=>{const res=await api("/api/receipt/"+r.id+"/crop",{points:pts});L.innerHTML="";toast(res.ok?"Re-scanning…":res.error);await refresh();render()};
}
nav();
