/* Comic emotion marks in the head's own coordinate space. */
(function(root){
'use strict';
// Separately painted PNG cels, registered before the original renderer loads.
Object.assign(root.CLOUDY_PARTS,{"fx_tear_front_0_0":{"file":"textures/tears-v34/front-0-0.png","bbox":[108.555806228799,231.5339123275479,24.12565445026178,48.25130890052356],"size":[256,512],"drawnTearFrame":true,"direction":"front","eye":0,"stage":0},"fx_tear_front_0_1":{"file":"textures/tears-v34/front-0-1.png","bbox":[108.5753960772734,231.52738526535757,24.12565445026178,48.25130890052356],"size":[256,512],"drawnTearFrame":true,"direction":"front","eye":0,"stage":1},"fx_tear_front_0_2":{"file":"textures/tears-v34/front-0-2.png","bbox":[108.6583885421222,231.53309512481917,24.12565445026178,48.25130890052356],"size":[256,512],"drawnTearFrame":true,"direction":"front","eye":0,"stage":2},"fx_tear_front_0_3":{"file":"textures/tears-v34/front-0-3.png","bbox":[108.5559473218018,231.52941083687475,24.12565445026178,48.25130890052356],"size":[256,512],"drawnTearFrame":true,"direction":"front","eye":0,"stage":3},"fx_tear_front_0_4":{"file":"textures/tears-v34/front-0-4.png","bbox":[108.60576490102508,231.46472537353932,24.12565445026178,48.25130890052356],"size":[256,512],"drawnTearFrame":true,"direction":"front","eye":0,"stage":4},"fx_tear_front_0_5":{"file":"textures/tears-v34/front-0-5.png","bbox":[108.64782772079555,231.46848379637635,24.12565445026178,48.25130890052356],"size":[256,512],"drawnTearFrame":true,"direction":"front","eye":0,"stage":5},"fx_tear_front_1_0":{"file":"textures/tears-v34/front-1-0.png","bbox":[205.72957902195833,233.863699896226,24.641711229946523,49.283422459893046],"size":[256,512],"drawnTearFrame":true,"direction":"front","eye":1,"stage":0},"fx_tear_front_1_1":{"file":"textures/tears-v34/front-1-1.png","bbox":[205.69757456487847,233.86259037312882,24.641711229946523,49.283422459893046],"size":[256,512],"drawnTearFrame":true,"direction":"front","eye":1,"stage":1},"fx_tear_front_1_2":{"file":"textures/tears-v34/front-1-2.png","bbox":[205.8108957744564,233.86715595981605,24.641711229946523,49.283422459893046],"size":[256,512],"drawnTearFrame":true,"direction":"front","eye":1,"stage":2},"fx_tear_front_1_3":{"file":"textures/tears-v34/front-1-3.png","bbox":[205.7635657469219,233.86348658161342,24.641711229946523,49.283422459893046],"size":[256,512],"drawnTearFrame":true,"direction":"front","eye":1,"stage":3},"fx_tear_front_1_4":{"file":"textures/tears-v34/front-1-4.png","bbox":[205.76671165529166,233.86272259857103,24.641711229946523,49.283422459893046],"size":[256,512],"drawnTearFrame":true,"direction":"front","eye":1,"stage":4},"fx_tear_front_1_5":{"file":"textures/tears-v34/front-1-5.png","bbox":[205.84862734122558,233.86035342765837,24.641711229946523,49.283422459893046],"size":[256,512],"drawnTearFrame":true,"direction":"front","eye":1,"stage":5},"fx_tear_left_0_0":{"file":"textures/tears-v34/left-0-0.png","bbox":[84.14037069186114,230.43184861743174,19.2,38.4],"size":[256,512],"drawnTearFrame":true,"direction":"left","eye":0,"stage":0},"fx_tear_left_0_1":{"file":"textures/tears-v34/left-0-1.png","bbox":[84.29049309214929,230.43475067789637,19.2,38.4],"size":[256,512],"drawnTearFrame":true,"direction":"left","eye":0,"stage":1},"fx_tear_left_0_2":{"file":"textures/tears-v34/left-0-2.png","bbox":[84.42149156508246,230.43525401420774,19.2,38.4],"size":[256,512],"drawnTearFrame":true,"direction":"left","eye":0,"stage":2},"fx_tear_left_0_3":{"file":"textures/tears-v34/left-0-3.png","bbox":[84.39803763056584,230.43582901605487,19.2,38.4],"size":[256,512],"drawnTearFrame":true,"direction":"left","eye":0,"stage":3},"fx_tear_left_0_4":{"file":"textures/tears-v34/left-0-4.png","bbox":[84.4534701193445,230.43579110260063,19.2,38.4],"size":[256,512],"drawnTearFrame":true,"direction":"left","eye":0,"stage":4},"fx_tear_left_0_5":{"file":"textures/tears-v34/left-0-5.png","bbox":[84.52825778125371,230.43473857066488,19.2,38.4],"size":[256,512],"drawnTearFrame":true,"direction":"left","eye":0,"stage":5},"fx_tear_left_1_0":{"file":"textures/tears-v34/left-1-0.png","bbox":[140.5912400942386,225.7141747409049,26.482758620689655,52.96551724137931],"size":[256,512],"drawnTearFrame":true,"direction":"left","eye":1,"stage":0},"fx_tear_left_1_1":{"file":"textures/tears-v34/left-1-1.png","bbox":[140.97465314429127,225.70209802553214,26.482758620689655,52.96551724137931],"size":[256,512],"drawnTearFrame":true,"direction":"left","eye":1,"stage":1},"fx_tear_left_1_2":{"file":"textures/tears-v34/left-1-2.png","bbox":[141.3114264985576,225.63795585971818,26.482758620689655,52.96551724137931],"size":[256,512],"drawnTearFrame":true,"direction":"left","eye":1,"stage":2},"fx_tear_left_1_3":{"file":"textures/tears-v34/left-1-3.png","bbox":[141.31182273670763,225.64030718522915,26.482758620689655,52.96551724137931],"size":[256,512],"drawnTearFrame":true,"direction":"left","eye":1,"stage":3},"fx_tear_left_1_4":{"file":"textures/tears-v34/left-1-4.png","bbox":[141.42002749855567,225.6405546897607,26.482758620689655,52.96551724137931],"size":[256,512],"drawnTearFrame":true,"direction":"left","eye":1,"stage":4},"fx_tear_left_1_5":{"file":"textures/tears-v34/left-1-5.png","bbox":[141.67822350552282,225.64176017642225,26.482758620689655,52.96551724137931],"size":[256,512],"drawnTearFrame":true,"direction":"left","eye":1,"stage":5},"fx_tear_right_0_0":{"file":"textures/tears-v34/right-0-0.png","bbox":[198.99428194110007,216.25442565358333,26.33142857142857,52.66285714285714],"size":[256,512],"drawnTearFrame":true,"direction":"right","eye":0,"stage":0},"fx_tear_right_0_1":{"file":"textures/tears-v34/right-0-1.png","bbox":[199.13124668461361,216.26221154896837,26.33142857142857,52.66285714285714],"size":[256,512],"drawnTearFrame":true,"direction":"right","eye":0,"stage":1},"fx_tear_right_0_2":{"file":"textures/tears-v34/right-0-2.png","bbox":[199.3156963126799,216.26427098924404,26.33142857142857,52.66285714285714],"size":[256,512],"drawnTearFrame":true,"direction":"right","eye":0,"stage":2},"fx_tear_right_0_3":{"file":"textures/tears-v34/right-0-3.png","bbox":[199.15324982263903,216.25670807678566,26.33142857142857,52.66285714285714],"size":[256,512],"drawnTearFrame":true,"direction":"right","eye":0,"stage":3},"fx_tear_right_0_4":{"file":"textures/tears-v34/right-0-4.png","bbox":[199.24634052152783,216.25493942337084,26.33142857142857,52.66285714285714],"size":[256,512],"drawnTearFrame":true,"direction":"right","eye":0,"stage":4},"fx_tear_right_0_5":{"file":"textures/tears-v34/right-0-5.png","bbox":[199.6012807595226,216.35224584765922,26.33142857142857,52.66285714285714],"size":[256,512],"drawnTearFrame":true,"direction":"right","eye":0,"stage":5},"fx_tear_right_1_0":{"file":"textures/tears-v34/right-1-0.png","bbox":[254.2916420010065,208.78246243220744,25.18032786885246,50.36065573770492],"size":[256,512],"drawnTearFrame":true,"direction":"right","eye":1,"stage":0},"fx_tear_right_1_1":{"file":"textures/tears-v34/right-1-1.png","bbox":[254.63639351285798,208.9969678949799,25.18032786885246,50.36065573770492],"size":[256,512],"drawnTearFrame":true,"direction":"right","eye":1,"stage":1},"fx_tear_right_1_2":{"file":"textures/tears-v34/right-1-2.png","bbox":[254.71040295771238,209.2025365284881,25.18032786885246,50.36065573770492],"size":[256,512],"drawnTearFrame":true,"direction":"right","eye":1,"stage":2},"fx_tear_right_1_3":{"file":"textures/tears-v34/right-1-3.png","bbox":[255.4877772465229,209.26339142960686,25.18032786885246,50.36065573770492],"size":[256,512],"drawnTearFrame":true,"direction":"right","eye":1,"stage":3},"fx_tear_right_1_4":{"file":"textures/tears-v34/right-1-4.png","bbox":[254.91332528429996,209.176343451617,25.18032786885246,50.36065573770492],"size":[256,512],"drawnTearFrame":true,"direction":"right","eye":1,"stage":4},"fx_tear_right_1_5":{"file":"textures/tears-v34/right-1-5.png","bbox":[255.62943470646923,209.18609406287138,25.18032786885246,50.36065573770492],"size":[256,512],"drawnTearFrame":true,"direction":"right","eye":1,"stage":5}});
const clamp=x=>Math.max(0,Math.min(1,Number.isFinite(x)?x:0));
const smooth=x=>{x=clamp(x);return x*x*(3-2*x);};
const mix=(a,b,t)=>a+(b-a)*t;
const mod=x=>((x%1)+1)%1;
const anchors={
 front:{tear:[[130,239,32,-2],[210,239,32,2]],mark:[246,109],gloom:[65,60],sweat:[242,216],spark:[284,72],sigh:[270,264],shock:[61,91],tremble:[80,204],shade:[170,202,124,57],stress:[171,191,53,43]},
 left:{tear:[[89,232,27,8],[149,232,29,-3]],mark:[202,101],gloom:[58,59],sweat:[174,213],spark:[58,83],sigh:[61,252],shock:[48,105],tremble:[67,183],shade:[122,198,97,55],stress:[121,187,35,42]},
 right:{tear:[[219,231,27,3],[277,225,24,-8]],mark:[244,100],gloom:[74,62],sweat:[199,207],spark:[70,88],sigh:[310,244],shock:[303,112],tremble:[299,186],shade:[245,195,87,56],stress:[245,182,36,42]}
};

// A continuous band crosses the bangs and upper face. Deriving coverage only
// from position and the head's alpha avoids tiny skin-colour islands or holes
// in lashes, while leaving the transparent silhouette and the chin untouched.
function shadeCoverage(direction,x,y,sourceAlpha=1){
 const a=anchors[direction];if(!a)return 0;
 const [cx,cy,rx,ry]=a.shade;
 const side=1-smooth((Math.abs(x-cx)-rx*.78)/(rx*.22));
 const rise=smooth((y-(cy-ry))/(ry*.72));
 const fall=1-smooth((y-(cy+ry*.3))/(ry*.7));
 return clamp(sourceAlpha)*side*rise*fall*.38;
}

// Each stage is a separately painted PNG. Only opacity changes between cels;
// the artwork's shape, reflections, size and cheek path are never morphed.
const tearPaintStages=[0,.16,.32,.49,.65,.82];
function samplePaintedTear(time,period=4.2,offset=0){
 const phase=mod(time/period+offset);let frame=0;
 while(frame<tearPaintStages.length-1&&phase>=tearPaintStages[frame+1])frame++;
 const nextFrame=(frame+1)%tearPaintStages.length;
 const end=nextFrame===0?1:tearPaintStages[nextFrame];
 const blend=smooth((phase-tearPaintStages[frame])/(end-tearPaintStages[frame]));
 // Every painted cel contains the attached pool; only the smaller drops flow.
 // Refill through the first cel without fading the whole pool out each cycle.
 return{phase,frame,nextFrame,mix:blend,alpha:1};
}
function weights(pose){
 const awake=1-clamp(pose.exprSleep||0),out={};
 for(const name of ['happy','excited','proud','relieved','calm','anxious','hurt','displeased','distressed','sad','depressed','tired','angry','scared']){
  out[name]=clamp(pose['expr'+name[0].toUpperCase()+name.slice(1)]||0)*awake;
 }
 return out;
}
function createSprites(images={},parts={}){
 const sprites={};
 function make(name,paint,w=128,h=128){const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;const c=canvas.getContext('2d');c.lineCap='round';c.lineJoin='round';paint(c,w,h);sprites[name]=canvas;return canvas;}
 function outlined(c,draw,color,width=8){c.strokeStyle='rgba(255,255,255,.88)';c.lineWidth=width+5;draw();c.stroke();c.strokeStyle=color;c.lineWidth=width;draw();c.stroke();}
 make('fx_anger',c=>{
  const path=()=>{c.beginPath();for(let i=0;i<4;i++){
   const angle=i*Math.PI/2,cs=Math.cos(angle),sn=Math.sin(angle),p=(x,y)=>[64+(x-64)*cs-(y-64)*sn,64+(x-64)*sn+(y-64)*cs];
   c.moveTo(...p(47,16));c.lineTo(...p(54,42));c.quadraticCurveTo(...p(57,52),...p(46,55));c.lineTo(...p(18,63));
  }};
  outlined(c,path,'#e36c72',10);
 });
 make('fx_gloom',c=>{
  const lengths=[71,92,58,101,79,55],tops=[16,8,22,12,17,28];
  for(let i=0;i<lengths.length;i++){
   const x=17+i*18,y=tops[i],bottom=lengths[i],g=c.createLinearGradient(0,y,0,bottom);
   g.addColorStop(0,'rgba(139,112,192,.22)');g.addColorStop(.18,'rgba(139,112,192,.84)');g.addColorStop(1,'rgba(139,112,192,0)');
   c.fillStyle=g;c.beginPath();c.moveTo(x-1.8,y);c.quadraticCurveTo(x+.2,(y+bottom)/2,x+.3,bottom);c.quadraticCurveTo(x+2.5,(y+bottom)/2,x+1.5,y);c.closePath();c.fill();
  }
 });
 function droplet(c,sweat=false){
  c.beginPath();c.moveTo(68,9);c.bezierCurveTo(63,36,39,65,39,85);c.bezierCurveTo(39,113,86,122,92,88);c.bezierCurveTo(96,66,76,34,68,9);c.closePath();
  const g=c.createLinearGradient(43,40,84,111);g.addColorStop(0,'rgba(249,255,255,.82)');g.addColorStop(.52,'rgba(193,235,248,.67)');g.addColorStop(1,'rgba(133,204,232,.82)');
  c.fillStyle=g;c.fill();c.strokeStyle=sweat?'rgba(95,168,203,.94)':'rgba(103,183,211,.86)';c.lineWidth=sweat?5:4;c.stroke();
  c.beginPath();c.moveTo(58,57);c.quadraticCurveTo(46,78,52,91);c.strokeStyle='rgba(255,255,255,.95)';c.lineWidth=7;c.stroke();
  c.beginPath();c.ellipse(74,102,6,2.7,-.3,0,Math.PI*2);c.fillStyle='rgba(255,255,255,.76)';c.fill();
 }
 make('fx_sweat',c=>droplet(c,true));
 make('fx_spark',c=>{
  c.beginPath();c.moveTo(64,10);c.quadraticCurveTo(70,53,112,64);c.quadraticCurveTo(70,72,64,118);c.quadraticCurveTo(57,73,16,64);c.quadraticCurveTo(57,53,64,10);c.closePath();c.fillStyle='#fff3b6';c.fill();c.strokeStyle='#d0b976';c.lineWidth=4;c.stroke();
  c.beginPath();c.moveTo(64,29);c.lineTo(64,91);c.strokeStyle='rgba(255,255,255,.95)';c.lineWidth=4;c.stroke();
 });
 make('fx_emphasis',c=>{
  const path=()=>{c.beginPath();c.moveTo(30,23);c.lineTo(42,52);c.moveTo(76,14);c.lineTo(70,48);c.moveTo(111,44);c.lineTo(85,64);};outlined(c,path,'#d3b57e',6);
 });
 make('fx_exclaim',c=>{
  // Drawn punctuation has a full-height silhouette and a separate round dot;
  // its readability no longer depends on a small, platform-dependent font.
  const path=()=>{c.beginPath();c.moveTo(49,13);c.quadraticCurveTo(64,7,80,13);c.lineTo(73,79);c.quadraticCurveTo(64,83,55,79);c.closePath();c.moveTo(76,106);c.arc(64,106,12,0,Math.PI*2);};
  path();c.lineWidth=11;c.strokeStyle='rgba(255,255,255,.98)';c.stroke();
  path();c.fillStyle='#ed8d72';c.fill();c.lineWidth=3;c.strokeStyle='#b86658';c.stroke();
  c.beginPath();c.moveTo(57,21);c.lineTo(60,60);c.strokeStyle='rgba(255,236,207,.83)';c.lineWidth=4;c.stroke();
 });
 make('fx_sigh',c=>{
  const g=c.createRadialGradient(59,61,5,64,64,54);g.addColorStop(0,'rgba(239,249,252,.86)');g.addColorStop(1,'rgba(204,223,237,0)');c.fillStyle=g;c.beginPath();c.ellipse(67,64,52,31,-.08,0,Math.PI*2);c.fill();
  const path=()=>{c.beginPath();c.moveTo(17,70);c.bezierCurveTo(36,78,44,46,61,54);c.bezierCurveTo(78,61,82,40,96,46);};outlined(c,path,'rgba(169,191,211,.63)',3);
 });
 make('fx_tremble',c=>{const path=()=>{c.beginPath();c.moveTo(44,19);c.lineTo(31,39);c.lineTo(46,61);c.lineTo(31,82);c.lineTo(44,105);c.moveTo(84,25);c.lineTo(74,43);c.lineTo(87,62);c.lineTo(75,81);c.lineTo(85,101);};outlined(c,path,'#9b89a5',5);});
 // Both overlays use the original head alpha, so their drawn edges can never
 // make a rectangular patch outside the silhouette.
 for(const direction of Object.keys(anchors)){
  const name=direction+'_00',im=images[name],part=parts[name];if(!im||!part)continue;
  const [bx,by,w,h]=part.bbox;
  make('fx_shade_'+direction,c=>{
   c.drawImage(im,0,0,w,h);const data=c.getImageData(0,0,w,h),p=data.data;
   for(let y=0;y<h;y++)for(let x=0;x<w;x++){
    const i=(y*w+x)*4,a=p[i+3]/255;
    p[i]=78;p[i+1]=71;p[i+2]=108;p[i+3]=Math.round(255*shadeCoverage(direction,x+bx,y+by,a));
   }
   c.putImageData(data,0,0);
  },w,h);
  make('fx_stress_'+direction,c=>{
   const [cx,top,width,height]=anchors[direction].stress;
   for(let i=0;i<11;i++){
    const x=cx-width/2+i*width/10-bx,y=top+[0,5,1,8,4,2,6,0,7,3,5][i]-by;
    const bottom=top+height-Math.abs(i-5)*1.7-by,g=c.createLinearGradient(0,y,0,bottom);
    g.addColorStop(0,'rgba(142,113,192,.15)');g.addColorStop(.18,'rgba(142,113,192,.85)');g.addColorStop(.78,'rgba(142,113,192,.78)');g.addColorStop(1,'rgba(142,113,192,0)');
    c.fillStyle=g;c.beginPath();c.moveTo(x-.9,y);c.lineTo(x+.9,y);c.quadraticCurveTo(x+1.2,(y+bottom)/2,x+.15,bottom);c.quadraticCurveTo(x-.5,(y+bottom)/2,x-.9,y);c.closePath();c.fill();
   }
   c.globalCompositeOperation='destination-in';c.drawImage(im,0,0,w,h);c.globalCompositeOperation='source-over';
  },w,h);
 }
 return sprites;
}

function draw(renderer,cfg,pose,time,faceMapping,opacity=1,selectedEmotion=null){
 const a=anchors[cfg.prefix];if(!a||cfg.head[0]!==0)return;
 const w=weights(pose),base=clamp(opacity);if(!base)return;
 function sprite(name,x,y,width,height,alpha,angle=0){
  if(alpha<.001)return;const part=renderer.parts[name];if(!part)return;
  const [bx,by,sw,sh]=part.bbox,cs=Math.cos(angle),sn=Math.sin(angle);
  renderer.mesh(name,p=>{const dx=((p.x-bx)/sw-.5)*width,dy=((p.y-by)/sh-.5)*height;return faceMapping({x:x+dx*cs-dy*sn,y:y+dx*sn+dy*cs});},base*clamp(alpha),4,8);
 }
 const breath=.5+.5*Math.sin(time*1.4),slowPulse=.78+.22*breath;
 function headOverlay(name,alpha){const part=renderer.parts[cfg.prefix+'_00'];if(alpha>.001&&renderer.parts[name]&&part){const [bx,by]=part.bbox;renderer.mesh(name,p=>faceMapping({x:p.x+bx,y:p.y+by}),base*clamp(alpha),16,20);}}
 headOverlay('fx_shade_'+cfg.prefix,Math.max(w.depressed,w.distressed*.48));
 headOverlay('fx_stress_'+cfg.prefix,Math.max(w.anxious*.74,w.distressed*.9,w.depressed*.55));
 sprite('fx_anger',a.mark[0],a.mark[1],54,54,w.angry*(.92+.08*breath),.04);
 sprite('fx_gloom',a.gloom[0],a.gloom[1]+.8*breath,42,46,Math.max(w.depressed*.86,w.distressed*.36));
 const sweatPhase=mod(time/4.9),sweatAlpha=smooth(sweatPhase/.18)*(1-smooth((sweatPhase-.72)/.24));
 sprite('fx_sweat',a.sweat[0],a.sweat[1]+4*smooth(sweatPhase),27,36,w.anxious*sweatAlpha);
 sprite('fx_sweat',a.sweat[0]-9,a.sweat[1]+23+2*smooth(sweatPhase),12,17,w.anxious*sweatAlpha*.55,-.12);
 const surpriseScale=1+.025*breath;
 sprite('fx_exclaim',a.shock[0],a.shock[1]-2*breath,54*surpriseScale,76*surpriseScale,w.scared*(.94+.06*breath),-.07);
 for(let i=0;i<3;i++){
  const strength=i===0?Math.max(w.happy*.7,w.excited,w.proud*.72):w.excited*.8;
  const phase=mod(time/4.8+i*.27),alpha=smooth(phase/.24)*(1-smooth((phase-.59)/.28));
  const sx=a.spark[0]+(i===1?-22:i===2?13:0),sy=a.spark[1]+(i===1?-26:i===2?28:0)-3*smooth(phase);
  const size=(i===0?23:14)*(1+.1*Math.sin(time*1.2+i));sprite('fx_spark',sx,sy,size,size,strength*alpha,Math.sin(time*.7+i)*.08);
 }
 sprite('fx_emphasis',a.spark[0]-22,a.spark[1]-18,27,27,w.excited*.35*slowPulse);
 const sigh=Math.max(w.relieved*.65,w.tired*.72,w.displeased*.48),sighPhase=mod(time/6.1+.18),sighAlpha=smooth(sighPhase/.2)*(1-smooth((sighPhase-.44)/.29));
 const sign=cfg.prefix==='left'?-1:1;
 sprite('fx_sigh',a.sigh[0]+sign*14*smooth(sighPhase),a.sigh[1]-8*smooth(sighPhase),26+13*smooth(sighPhase),18+5*smooth(sighPhase),sigh*sighAlpha);
 sprite('fx_tremble',a.tremble[0]+.6*Math.sin(time*7),a.tremble[1],13,32,w.distressed*.66*slowPulse);
 for(let i=0;i<2;i++){
  // Hurt sheds only the more visible tear and does so less often. Sadness
  // sheds tears from both eyes at separate times, rather than a mirrored loop.
  const strength=Math.max(w.sad,i===(cfg.prefix==='right'?0:1)?w.hurt*.84:0);if(strength<.001)continue;
  const period=w.hurt>w.sad?6.8:4.3+i*.47,t=samplePaintedTear(time,period,i*.43);
  const name='fx_tear_'+cfg.prefix+'_'+i+'_';
  // Follow the eyelid of the actual painted expression chosen by the head.
  // Hurt's lower lids sit higher than sadness; this is a rigid placement,
  // not a change to the painted water shape or to the original head motion.
  const tearEmotion=selectedEmotion||(pose.exprHurt>.5?'hurt':'sad');
  const hurtShift={front:[1,0],left:[-5,-7],right:[-5,-4]};
  const dy=tearEmotion==='hurt'?hurtShift[cfg.prefix][i]:0;
  const tearMapping=dy?p=>faceMapping({x:p.x,y:p.y+dy}):faceMapping;
  renderer.mesh(name+t.frame,tearMapping,base*strength*t.alpha*(1-t.mix),4,8);
  if(t.nextFrame!==t.frame)renderer.mesh(name+t.nextFrame,tearMapping,base*strength*t.alpha*t.mix,4,8);
 }
}
const api={createSprites,draw,samplePaintedTear,weights,anchors,shadeCoverage};
if(typeof module==='object'&&module.exports)module.exports=api;
if(root)root.CloudyEmotionFX=api;
})(typeof window!=='undefined'?window:globalThis);
