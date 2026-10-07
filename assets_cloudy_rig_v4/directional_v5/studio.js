'use strict';
const $=s=>document.querySelector(s), M=CloudyMotion;
const names={idle:'대기',walk:'걷기',run:'달리기',wave:'인사',thinking:'생각',sleep:'수면',hovering:'들기',jump:'점프',fall:'낙하',land:'착지',sequence:'연속 동작'};
const emotions={auto:'자동',...Object.fromEntries(Object.entries(M.emotions).map(([id,entry])=>[id,entry.label]))};
let emotion='auto',speaking=false,speechTime=0;
let state='idle',time=0,gaitTime=0,runGaitTime=0,last=0,paused=false,yaw=0,yawTarget=0,yawStart=0,turnElapsed=1,walk=0,walkTarget=0,run=0,runTarget=0,x=0,travelDir=-1,travelMode='move',travelGait='walk',travelSpeed=0,frameCount=0,fpsTime=0;
let transition=new M.PoseTransition(M.pose(state,0)),renderer,draw=M.pose(state,0),trip=null,tripTime=0;
let actionTime=0;
const mix=(a,b,t)=>a+(b-a)*t;
function updateEmotionControls(){document.querySelectorAll('#emotions button').forEach(b=>{const active=b.dataset.emotion===emotion;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));b.disabled=state==='sleep';});$('#speaking').checked=speaking;$('#speaking').disabled=state==='sleep';$('#speechNote').textContent=state==='sleep'?'자는 동안은 대화를 쉬고, 깨어나면 선택한 설정으로 이어갑니다.':'어떤 동작에서도 선택한 감정으로 말합니다.';updateGallerySelection();}
function chooseEmotion(value){emotion=value;updateEmotionControls();transition.retarget(sample());if(paused)draw=sample();paint();}
function updateActionControls(){document.querySelectorAll('#states button').forEach(b=>{const active=b.dataset.state===state;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});document.querySelectorAll('#directions button').forEach(b=>b.disabled=state==='run'&&+b.dataset.yaw===0);$('#playSequence').classList.toggle('active',state==='sequence');$('#playSequence').setAttribute('aria-pressed',String(state==='sequence'));$('#travelLabel').textContent=state==='run'?'좌우 왕복 달리기':'좌우 왕복 걷기';}
function choose(s){if(s!==state||s==='sequence')actionTime=0;state=s;walkTarget=s==='walk'?1:0;runTarget=s==='run'?1:0;if(s==='run'&&Math.abs(yawTarget)<1)setYaw(-65);transition.retarget(sample());updateActionControls();updateEmotionControls();if(s==='walk'&&Math.abs(yawTarget)<1)setYaw(-65);if(paused){walk=walkTarget;run=runTarget;draw=sample();paint();}}
function setYaw(value){let direction=value<-21?-65:value>21?65:0;if(state==='run'&&direction===0)direction=yaw>0?65:-65;yaw=direction;yawTarget=yaw;yawStart=yaw;turnElapsed=1;document.querySelectorAll('#directions button').forEach(b=>b.classList.toggle('active',+b.dataset.yaw===yaw));updateGalleryDirection();paint();}
function sample(){
 const p=state==='sequence'?CloudySequence.sample(actionTime).pose:M.pose(state,actionTime,{walkAmount:0,runAmount:0});
 // Keep optional running channels present so leaving a run can fade them out.
 p.runGesture=0;p.runLean=0;
 if(state!=='sequence'){
  const gait=M.pose('walk',gaitTime,{walkAmount:1});
  if(run>0){
   const running=M.pose('run',runGaitTime,{runAmount:1}),amount=walk+run,weight=Math.min(1,amount);
   for(const k of new Set([...Object.keys(p),...Object.keys(gait),...Object.keys(running)]))if(k!=='blink'){
    const locomotion=((gait[k]??0)*walk+(running[k]??0)*run)/amount;
    p[k]=mix(p[k]??0,locomotion,weight);
   }
  }else{
   for(const k of Object.keys(p))if(k!=='blink'&&k!=='runGesture'&&k!=='runLean')p[k]=mix(p[k],gait[k],walk);
  }
 }
 // Apply the selected face AFTER locomotion blending, so a full walk cannot
 // erase emotion. Speech and the chin gesture remain independent channels.
 return M.applySpeech(M.applyEmotion(p,emotion),speaking,speechTime);
}
function paint(){
 if(!renderer)return;
 const p={...draw};
 if(+$('#blink').value>=0)p.blink=+$('#blink').value;
 if(+$('#elbow').value>=0){p.elbowNear=+$('#elbow').value;p.waveElbowOffset=0;p.waveForearmShorten=0;p.idleGesture=0;}
 renderer.render(p,yaw,time,{action:state});
 $('#actor').style.transform='translateX(calc(-50% + '+x.toFixed(2)+'px))';
 const sequence=state==='sequence'?CloudySequence.sample(actionTime):null;
 $('#time').textContent=actionTime.toFixed(2)+' s';$('#badge').textContent=(sequence?'연속 · '+names[sequence.stage]:names[state])+(state==='sleep'?'':' · '+emotions[emotion]+(speaking?' · 대화 중':''))+' · '+(yaw<-3?'왼쪽':yaw>3?'오른쪽':'정면');
 $('#sequenceStatus').textContent=sequence?names[sequence.stage]+' · '+Math.min(actionTime,CloudySequence.duration).toFixed(2)+' / '+CloudySequence.duration.toFixed(1)+' s':'한 번 이어서 재생한 뒤 대기 자세로 돌아옵니다.';
 const clock=sequence?Math.min(actionTime,CloudySequence.duration):state==='run'?runGaitTime%M.runProfile.duration:actionTime%4.6;
 $('#scrub').max=sequence?CloudySequence.duration:state==='run'?M.runProfile.duration:4.6;$('#scrub').value=clock;$('#scrubLabel').textContent=clock.toFixed(2)+' s';
 $('#angle').value=yaw;$('#angleLabel').textContent=Math.round(yaw)+'°';
}
for(const [id,label]of Object.entries(names)){if(id==='sequence')continue;const b=document.createElement('button');b.textContent=label;b.dataset.state=id;b.onclick=()=>{if(safelyStopTravel())travelMode='stop';choose(id);};$('#states').append(b);}
$('#playSequence').onclick=()=>{if(safelyStopTravel())travelMode='stop';paused=false;$('#pause').textContent='일시정지';choose('sequence');};
for(const [id,label]of Object.entries(emotions)){const b=document.createElement('button');b.textContent=label;b.dataset.emotion=id;b.onclick=()=>chooseEmotion(id);$('#emotions').append(b);}
$('#speaking').onchange=e=>{speaking=e.target.checked;transition.retarget(sample());if(paused)draw=sample();paint();};
function safelyStopTravel(){const active=$('#travel').checked;$('#travel').checked=false;return active;}
document.querySelectorAll('#directions button').forEach(b=>b.onclick=()=>{safelyStopTravel();setYaw(+b.dataset.yaw);});
$('#travel').onchange=e=>{if(e.target.checked){travelGait=state==='run'?'run':'walk';choose(travelGait);travelDir=yaw>0?1:-1;setYaw(travelDir*65);travelMode='turn';}else{travelMode='stop';choose('idle');}};
$('#pause').onclick=e=>{paused=!paused;e.target.textContent=paused?'계속 재생':'일시정지';};
$('#reset').onclick=()=>{safelyStopTravel();emotion='auto';speaking=false;speechTime=0;$('#blink').value=-1;$('#elbow').value=-1;$('#blinkLabel').textContent='자동';$('#elbowLabel').textContent='자동';time=0;actionTime=0;gaitTime=0;runGaitTime=0;travelGait='walk';travelSpeed=0;walk=0;run=0;x=0;choose('idle');setYaw(0,true);draw=M.pose('idle',0);transition=new M.PoseTransition(draw);paint();};
$('#speed').oninput=e=>$('#speedLabel').textContent=e.target.value+'×';
$('#blink').oninput=e=>{$('#blinkLabel').textContent=+e.target.value<0?'자동':Math.round(e.target.value*100)+'%';paint();};
$('#elbow').oninput=e=>{$('#elbowLabel').textContent=+e.target.value<0?'자동':e.target.value+'°';paint();};
$('#angle').oninput=e=>{safelyStopTravel();setYaw(+e.target.value,true);};
$('#scrub').oninput=e=>{paused=true;$('#pause').textContent='계속 재생';time=+e.target.value;actionTime=time;gaitTime=time;runGaitTime=time;speechTime=time;walk=walkTarget;run=runTarget;draw=sample();transition=new M.PoseTransition(draw);paint();};
function exportCanvas(canvas,name){const url=canvas.toDataURL('image/png'),link=$('#downloadAsset');link.href=url;link.download=name;link.textContent=name+' 다운로드';$('#exportImage').src=url;$('#exportResult').hidden=false;$('#exportStatus').textContent='PNG 생성 완료';canvas.toBlob(async blob=>{try{const response=await fetch('export-png?name='+encodeURIComponent(name),{method:'POST',headers:{'Content-Type':'image/png'},body:blob});if(!response.ok)throw Error('export server unavailable');const result=await response.json();$('#exportStatus').textContent='저장 완료 · '+result.file;}catch{$('#exportStatus').textContent='PNG 생성 완료 · 다운로드 링크로 저장하세요';}},'image/png');}
const emotionSuffix=()=>emotion==='auto'||state==='sleep'?'':'-'+emotion;
$('#export').onclick=()=>exportCanvas($('#canvas'),'cloudy-'+state+emotionSuffix()+(speaking&&state!=='sleep'?'-speaking':'')+'-'+Math.round(yaw)+'.png');
$('#exportWalk').onclick=()=>{
 const sheet=document.createElement('canvas');sheet.width=4320;sheet.height=3240;const ctx=sheet.getContext('2d'),direction=yaw>0?65:-65;
 for(let i=0;i<72;i++){const t=i/60,p=M.pose('walk',t,{emotion,speaking,speechTime:t*2.8/1.2});p.blink=0;p.headAngle=.55*Math.sin(Math.PI*2*t/1.2-.4);renderer.render(p,direction,t,{companion:false});ctx.drawImage($('#canvas'),(i%12)*360,Math.floor(i/12)*540,360,540);}
 paint();exportCanvas(sheet,'cloudy-walk-'+(direction>0?'right':'left')+(emotion==='auto'?'':'-'+emotion)+(speaking?'-speaking':'')+'-60fps.png');
};
$('#exportRun').onclick=()=>{
 const sheet=document.createElement('canvas');sheet.width=4320;sheet.height=2160;const ctx=sheet.getContext('2d'),direction=yaw>0?65:-65,{duration,fps,frameCount}=M.runProfile;
 for(let i=0;i<frameCount;i++){const t=i/fps,p=M.pose('run',t,{runAmount:1,emotion,speaking,speechTime:t*2.8/duration});p.blink=0;renderer.render(p,direction,t,{companion:false,action:'run'});ctx.drawImage($('#canvas'),(i%12)*360,Math.floor(i/12)*540,360,540);}
 paint();exportCanvas(sheet,'cloudy-run-'+(direction<0?'left':'right')+(emotion==='auto'?'':'-'+emotion)+(speaking?'-speaking':'')+'-60fps.png');
};
$('#background').onchange=e=>$('#stage').className='stage '+e.target.value;
$('#size').onchange=e=>{let a=$('#actor');a.style.width=e.target.value==='actual'?'133.33px':'';a.style.height=e.target.value==='actual'?'200px':'';};
// Static, lazy-loaded thumbnails do not add another renderer or animation loop.
function updateGallerySelection(){document.querySelectorAll('#emotionGrid button').forEach(b=>{const active=b.dataset.emotion===emotion;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));b.disabled=state==='sleep';});}
function updateGalleryDirection(){
 const gallery=$('#emotionGallery');if(!gallery)return;
 const direction=yaw<0?'left':yaw>0?'right':'front',label=yaw<0?'왼쪽':yaw>0?'오른쪽':'정면';
 $('#galleryDirection').textContent=label+' 표정 15가지';
 if(!gallery.open)return;
 const grid=$('#emotionGrid');
 if(!grid.children.length)for(const [id,entry] of Object.entries(M.emotions)){
  const b=document.createElement('button'),img=document.createElement('img'),text=document.createElement('span');
  b.className='emotion-card';b.dataset.emotion=id;b.onclick=()=>chooseEmotion(id);
  img.width=180;img.height=241;img.loading='lazy';img.decoding='async';img.alt=entry.label+' 표정';
  text.textContent=entry.label;b.append(img,text);grid.append(b);
 }
 grid.querySelectorAll('button').forEach(b=>{const img=b.querySelector('img'),src='exports/previews-v35/'+direction+'-'+b.dataset.emotion+'.webp?v=face-gallery-v35-20261004';if(img.getAttribute('src')!==src)img.src=src;});
 updateGallerySelection();
}
if($('#emotionGallery'))$('#emotionGallery').ontoggle=updateGalleryDirection;
const previewPresets={happy:{action:'idle',emotion:'happy',speaking:true},sad:{action:'idle',emotion:'sad'},anxious:{action:'idle',emotion:'anxious'},tired:{action:'idle',emotion:'tired'},scared:{action:'idle',emotion:'scared'},wave:{action:'wave',emotion:'happy'},run:{action:'run',emotion:'happy'}};
document.querySelectorAll('[data-preview]').forEach(b=>b.onclick=()=>{
 const preset=previewPresets[b.dataset.preview];if(!preset)return;
 safelyStopTravel();emotion=preset.emotion;speaking=Boolean(preset.speaking);
 $('#blink').value=-1;$('#elbow').value=-1;$('#blinkLabel').textContent='자동';$('#elbowLabel').textContent='자동';
 paused=false;actionTime=0;$('#pause').textContent='일시정지';choose(preset.action);updateGallerySelection();
});
function advance(dt){
 time+=dt;actionTime+=dt;speechTime+=dt;turnElapsed+=dt;
 const travel=$('#travel').checked;
 const cssScale=$('#actor').clientHeight/540, maxSpeed=(travelGait==='run'?M.runProfile.speed:55.5556)*cssScale;
 const range=Math.max(12,($('#stage').clientWidth-$('#actor').clientWidth)/2-18);
 if(travel){
  if(travelMode==='turn'&&turnElapsed>=.72){travelMode='move';trip=CloudyTravel.create(x,travelDir*range,maxSpeed,.55);tripTime=0;}
  if(travelMode==='move'){
   tripTime+=dt;const sample=trip.sample(tripTime);x=sample.x;travelSpeed=Math.abs(sample.speed);
   if(sample.done){travelMode='turn';travelDir*=-1;setYaw(travelDir*65);}
  }
 }else{
  const oldSpeed=travelSpeed;travelSpeed*=Math.exp(-10*dt);
  x+=travelDir*(oldSpeed+travelSpeed)*.5*dt;
 }
 const turnWeight=M.smoothstep(turnElapsed/.72);
 const walkGoal=travel?(travelGait==='walk'?travelSpeed/maxSpeed:0):walkTarget*turnWeight;
 const runGoal=travel?(travelGait==='run'?travelSpeed/maxSpeed:0):runTarget*turnWeight;
 walk+=(walkGoal-walk)*(1-Math.exp(-10*dt));
 run+=(runGoal-run)*(1-Math.exp(-10*dt));if(run<1e-8&&runGoal===0)run=0;
 // Cruise stance cancels root travel: 40 pixels / 0.72 seconds.
 gaitTime+=dt*(travel&&travelGait==='walk'?Math.min(1,travelSpeed/Math.max(1,maxSpeed*walk)):1);
 // Run stance uses its own continuous clock and the matching profile speed.
 runGaitTime+=dt*(travel&&travelGait==='run'?Math.min(1,travelSpeed/Math.max(1,maxSpeed*run)):1);
 if(state==='sequence'&&actionTime>=CloudySequence.duration){
  // Keep the same breathing/action clock: the final sequence sample is already
  // exactly this idle pose, so recovery cannot jump or replay on completion.
  state='idle';walk=0;walkTarget=0;run=0;runTarget=0;updateActionControls();updateEmotionControls();
 }
 const p=sample();draw=transition.step(p,dt);
 if(state==='sequence'&&actionTime>=CloudySequence.takeoff)for(const k of Object.keys(p))if(k.startsWith('foot'))draw[k]=p[k];
 if(walk+run>.98)for(const k of Object.keys(p))if(k.startsWith('foot'))draw[k]=p[k];
}
function tick(now){
 let dt=last?Math.min(.12,(now-last)/1000):0;last=now;
 if(!paused){dt*=+$('#speed').value;const steps=Math.max(1,Math.ceil(dt/(1/90)));for(let i=0;i<steps;i++)advance(dt/steps);paint();}
 frameCount++;if(now-fpsTime>1000){$('#fps').textContent=Math.round(frameCount*1000/(now-fpsTime))+' fps';frameCount=0;fpsTime=now;}
 requestAnimationFrame(tick);
}
(async()=>{try{
 renderer=await new CloudyRenderer($('#canvas')).load();
 const params=new URLSearchParams(location.search),initial=params.get('action'),direction=params.get('direction'),directions={left:-65,front:0,right:65};
 choose(Object.prototype.hasOwnProperty.call(names,initial)?initial:'idle');
 if(Object.prototype.hasOwnProperty.call(directions,direction))setYaw(directions[direction]);
 requestAnimationFrame(tick);
}catch(e){$('#badge').textContent='불러오기 실패: '+e.message;console.error(e);}})();
