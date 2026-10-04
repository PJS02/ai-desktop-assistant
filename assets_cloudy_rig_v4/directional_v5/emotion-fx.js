/* Comic emotion marks in the head's own coordinate space. */
(function(root){
'use strict';
const clamp=x=>Math.max(0,Math.min(1,Number.isFinite(x)?x:0));
const smooth=x=>{x=clamp(x);return x*x*(3-2*x);};
const mix=(a,b,t)=>a+(b-a)*t;
const mod=x=>((x%1)+1)%1;
const anchors={
 front:{tear:[[130,239,32,-2],[210,239,32,2]],mark:[246,109],gloom:[65,60],sweat:[242,216],spark:[284,72],sigh:[270,264],shock:[61,91],tremble:[80,204],shade:[170,202,124,57],stress:[171,191,53,43]},
 left:{tear:[[89,232,27,2],[149,232,29,-3]],mark:[202,101],gloom:[58,59],sweat:[174,213],spark:[58,83],sigh:[61,252],shock:[48,105],tremble:[67,183],shade:[122,198,97,55],stress:[121,187,35,42]},
 right:{tear:[[219,231,27,3],[277,225,24,-2]],mark:[244,100],gloom:[74,62],sweat:[199,207],spark:[70,88],sigh:[310,244],shock:[303,112],tremble:[299,186],shade:[245,195,87,56],stress:[245,182,36,42]}
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

// Formation, descent and disappearance all have zero endpoint velocity. The
// loop resets only after the pool and the separate rounded beads are invisible.
function sampleTear(time,period=4.2,offset=0,travel=32){
 const phase=mod(time/period+offset),form=smooth(phase/.14),fade=1-smooth((phase-.77)/.17);
 const descent=smooth((phase-.18)/.56),distance=travel*descent;
 return{phase,distance,poolAlpha:form*fade*(1-.54*smooth((phase-.23)/.4)),
  dropAlpha:smooth((phase-.13)/.13)*fade,trailAlpha:smooth((phase-.19)/.18)*fade,
  trailLength:distance,scale:.7+.3*smooth((phase-.1)/.14)};
}
function tearCurve(progress,drift){
 const q=clamp(progress),sign=drift<0?-1:1;
 // A cheek is rounded: the water first bows outward, then turns in toward the
 // chin. The beads share this path, rather than hanging in a vertical column.
 return drift*smooth(q)+sign*(3.1*Math.sin(Math.PI*q)+1.15*Math.sin(Math.PI*2*q));
}
function sampleTearBeads(time,period=4.2,offset=0,travel=32,drift=2){
 const t=sampleTear(time,period,offset,travel),growth=smooth(t.distance/(travel*.34));
 return [.23,.54,.79].map((fraction,i)=>{
  const distance=t.distance*fraction,q=distance/travel;
  const size=[7.6,9.1,7.3][i]*(.45+.55*growth);
  return {x:tearCurve(q,drift),y:distance,width:size,
   height:size*[.91,1.08,1.02][i],alpha:t.trailAlpha*growth*[.78,.94,.84][i]};
 });
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
 function tearBead(c,tip=false){
  c.beginPath();
  if(tip){
   c.moveTo(62,14);c.bezierCurveTo(57,34,25,49,23,78);c.bezierCurveTo(20,120,101,127,106,82);c.bezierCurveTo(110,55,72,35,62,14);
  }else{
   c.moveTo(59,19);c.bezierCurveTo(26,13,12,41,17,70);c.bezierCurveTo(10,105,48,121,78,111);c.bezierCurveTo(113,108,120,75,107,46);c.bezierCurveTo(100,24,79,15,59,19);
  }
  c.closePath();
  const g=c.createLinearGradient(27,27,87,116);g.addColorStop(0,'rgba(244,255,255,.93)');g.addColorStop(.5,'rgba(180,231,247,.79)');g.addColorStop(1,'rgba(139,209,233,.92)');
  c.fillStyle=g;c.fill();c.strokeStyle='rgba(96,177,207,.91)';c.lineWidth=4.5;c.stroke();
  c.beginPath();c.ellipse(40,51,9,18,.45,0,Math.PI*2);c.fillStyle='rgba(255,255,255,.98)';c.fill();
  c.beginPath();c.ellipse(76,101,13,3.8,-.2,0,Math.PI*2);c.fillStyle='rgba(247,255,255,.88)';c.fill();
 }
 make('fx_teardrop',c=>tearBead(c,true));
 make('fx_tearbead',c=>tearBead(c));
 make('fx_tearpool',c=>{
  // Unequal scallops read as water gathering on the lid, not an eye underline.
  c.beginPath();c.moveTo(12,58);c.bezierCurveTo(25,36,43,39,54,48);c.bezierCurveTo(72,34,101,36,115,53);c.bezierCurveTo(123,72,99,84,85,80);c.bezierCurveTo(68,105,43,97,35,80);c.bezierCurveTo(16,84,5,72,12,58);c.closePath();
  c.fillStyle='rgba(182,232,247,.89)';c.fill();c.strokeStyle='rgba(103,181,210,.88)';c.lineWidth=3.5;c.stroke();
  c.beginPath();c.ellipse(32,55,12,5,-.2,0,Math.PI*2);c.ellipse(86,50,16,4,.05,0,Math.PI*2);c.fillStyle='rgba(255,255,255,.98)';c.fill();
  c.beginPath();c.ellipse(64,84,12,3,.12,0,Math.PI*2);c.fillStyle='rgba(249,255,255,.91)';c.fill();
 });
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

function draw(renderer,cfg,pose,time,faceMapping,opacity=1){
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
  const [x,y,travel,drift]=a.tear[i],period=w.hurt>w.sad?6.8:4.3+i*.47;
  const t=sampleTear(time,period,i*.43,travel);
  sprite('fx_tearpool',x,y,21,12,strength*t.poolAlpha*.95,i===0?.06:-.06);
  for(const bead of sampleTearBeads(time,period,i*.43,travel,drift)){
   sprite('fx_tearbead',x+bead.x,y+bead.y,bead.width,bead.height,strength*bead.alpha,i===0?.12:-.12);
  }
  sprite('fx_teardrop',x+tearCurve(t.distance/travel,drift),y+t.distance,9.6*t.scale,12*t.scale,strength*t.dropAlpha*.94);
 }
}
const api={createSprites,draw,sampleTear,sampleTearBeads,weights,anchors,shadeCoverage};
if(typeof module==='object'&&module.exports)module.exports=api;
if(root)root.CloudyEmotionFX=api;
})(typeof window!=='undefined'?window:globalThis);
