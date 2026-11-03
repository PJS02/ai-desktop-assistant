/* Dizzy faces: clean painted eyes, rotating drawn spirals in each view. */
(function(root){
'use strict';
const clamp=x=>Math.max(0,Math.min(1,Number.isFinite(x)?x:0));
const baseFace='front_00_gaze_clean';
const profile={
 baseFace,blinkFace:'front_00_blink_anxious',
 period:1.6,
 // Atlas coordinates, not screen coordinates. The original eyelids and hair
 // stay in the painted head; only the marks inside the whites rotate.
 eyes:[{center:[131,229],size:[43,35],spin:1,phase:.4,
        aperture:{start:[109,226],curves:[[111,215,120,212,131,213],[142,213,150,218,153,227],[156,237,147,244,134,245],[121,246,109,240,109,226]]}},
       {center:[212,227],size:[42,35],spin:-1,phase:2.1,
        aperture:{start:[192,228],curves:[[190,216,201,209,213,210],[224,210,233,218,234,230],[235,240,224,244,211,244],[199,244,191,239,192,228]]}}],
 mouth:{center:[172.5,262.5],size:[12,11]}
};
const views={
 front:profile,
 left:{
  baseFace:'left_00_gaze_clean',blinkFace:'left_00_blink_anxious',period:1.6,
  // The far eye is narrower in the painted three-quarter view. Each spiral
  // is fitted to that eye's own white rather than mirroring the front face.
  eyes:[{center:[94,221],size:[18,32],spin:1,phase:.4,
         aperture:{start:[86,215],curves:[[86,208,89,204,93,206],[99,206,102,213,102,222],[102,230,99,236,94,237],[89,237,86,229,86,215]]}},
        {center:[151,211],size:[44,34],spin:-1,phase:2.1,
         aperture:{start:[130,202],curves:[[133,194,143,191,151,194],[163,195,172,203,173,213],[174,222,163,228,151,228],[140,228,134,220,133,211],[132,207,131,204,130,202]]}}],
  mouth:{center:[115.87,251.2],size:[10,11]}
 },
 right:{
  baseFace:'right_00_gaze_clean',blinkFace:'right_00_blink_anxious',period:1.6,
  eyes:[{center:[213,208],size:[43,34],spin:1,phase:.4,
         aperture:{start:[192,209],curves:[[193,198,202,191,214,191],[225,190,233,196,236,203],[239,214,228,225,215,226],[201,229,191,221,192,209]]}},
        {center:[268,202.5],size:[15,29],spin:-1,phase:2.1,
         aperture:{start:[262,194],curves:[[262,188,266,185,269,187],[274,189,275,198,274,207],[273,215,269,219,265,216],[261,212,261,202,262,194]]}}],
  mouth:{center:[250.42,240.72],size:[9,10]}
 }
};
for(const view of Object.values(views)){
 const points=view.eyes.flatMap(eye=>[eye.aperture.start,...eye.aperture.curves.flatMap(curve=>[[curve[0],curve[1]],[curve[2],curve[3]],[curve[4],curve[5]]])]);
 const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
 const x=Math.floor(Math.min(...xs))-1,y=Math.floor(Math.min(...ys))-1;
 view.whiteBounds=[x,y,Math.ceil(Math.max(...xs))-x+1,Math.ceil(Math.max(...ys))-y+1];
}
function profileFor(cfg){return cfg&&cfg.head&&cfg.head[0]===0?views[cfg.prefix]||null:null;}
function baseFaceFor(cfg){const view=profileFor(cfg);return view?view.baseFace:null;}

function createSprites(){
 const sprites={};
 // The old gaze paintings retain thin iris contours. Fill only the eye
 // apertures with newly drawn whites; the source lashes and skin stay intact.
 for(const [direction,view] of Object.entries(views)){
  const [x,y,w,h]=view.whiteBounds;
  const canvas=document.createElement('canvas');canvas.width=w*4;canvas.height=h*4;
  const c=canvas.getContext('2d');c.scale(4,4);c.translate(-x,-y);
  for(const eye of view.eyes){
   const path=eye.aperture;
   const gradient=c.createLinearGradient(0,eye.center[1]-eye.size[1]/2,0,eye.center[1]+eye.size[1]/2);
   gradient.addColorStop(0,'#e0dde6');gradient.addColorStop(.28,'#f5f3f7');gradient.addColorStop(.68,'#fdfbfc');gradient.addColorStop(1,'#fff8f7');
   c.beginPath();c.moveTo(...path.start);
   for(const curve of path.curves)c.bezierCurveTo(...curve);
   c.closePath();c.fillStyle=gradient;c.fill();
  }
  sprites['fx_dizzy_whites_'+direction]=canvas;
 }
 function make(name,paint){
  const canvas=document.createElement('canvas');canvas.width=256;canvas.height=256;
  const c=canvas.getContext('2d');c.scale(2,2);c.lineCap='round';c.lineJoin='round';
  paint(c);sprites[name]=canvas;
 }
 make('fx_dizzy_spiral',c=>{
  // A single continuous stroke avoids seams or a stationary outer ring.
  // Its empty margins keep every rotation inside the white of the eye.
  c.beginPath();
  const turns=2.25,steps=320;
  for(let i=0;i<=steps;i++){
   const u=i/steps,a=u*turns*Math.PI*2,r=2.5+47*u;
   const x=64+r*Math.cos(a),y=64+r*Math.sin(a);
   if(i)c.lineTo(x,y);else c.moveTo(x,y);
  }
  c.strokeStyle='#4d393e';c.lineWidth=6.3;c.stroke();
 });
 make('fx_dizzy_mouth',c=>{
  c.beginPath();c.ellipse(64,64,34,39,-.08,0,Math.PI*2);
  const fill=c.createLinearGradient(0,28,0,106);
  fill.addColorStop(0,'#87525d');fill.addColorStop(.58,'#b96e78');fill.addColorStop(1,'#ecacaa');
  c.fillStyle=fill;c.fill();c.strokeStyle='#b7787a';c.lineWidth=7;c.stroke();
  c.beginPath();c.ellipse(64,89,17,7,-.1,0,Math.PI*2);
  c.fillStyle='rgba(250,188,178,.8)';c.fill();
 });
 return sprites;
}

function draw(renderer,cfg,pose,time,faceMapping,opacity=1){
 const view=profileFor(cfg);
 if(!view||!renderer.textures[view.baseFace])return;
 const alpha=clamp(opacity),blink=clamp(pose.blink),clock=Number.isFinite(time)?time:0;
 const whites='fx_dizzy_whites_'+cfg.prefix,whitePart=renderer.parts[whites];
 if(whitePart){
  const [x,y,w,h]=view.whiteBounds,[bx,by,bw,bh]=whitePart.bbox;
  renderer.mesh(whites,p=>faceMapping({x:x+(p.x-bx)/bw*w,y:y+(p.y-by)/bh*h}),alpha,24,12);
 }
 function sprite(name,center,size,angle,strength=1){
  const part=renderer.parts[name];if(!part||strength<.001)return;
  const [bx,by,w,h]=part.bbox,cs=Math.cos(angle),sn=Math.sin(angle);
  renderer.mesh(name,p=>{
   const x=(p.x-bx)/w-.5,y=(p.y-by)/h-.5;
   // Rotate in a circle first, then fit that circle into the fixed eyelid
   // ellipse. An already flattened rotating sprite would cross the lashes.
   return faceMapping({x:center[0]+(x*cs-y*sn)*size[0],
                       y:center[1]+(x*sn+y*cs)*size[1]});
  },alpha*clamp(strength),4,4);
 }
 for(const eye of view.eyes){
  const angle=eye.phase+eye.spin*clock*Math.PI*2/view.period;
  sprite('fx_dizzy_spiral',eye.center,eye.size,angle,1-blink);
 }
 if(blink>.001&&renderer.textures[view.blinkFace]){
  renderer.mesh(view.blinkFace,faceMapping,alpha*blink,24,28);
 }
 // A tiny relaxed opening reads as dazed even while the eyes blink. Speech
 // can open it slightly without restoring the original neutral mouth.
 const open=clamp(pose.speaking)*clamp(pose.mouthOpen);
 sprite('fx_dizzy_mouth',view.mouth.center,
        [view.mouth.size[0]*(1+.12*open),view.mouth.size[1]*(1+.65*open)],0);
}

root.CloudyDizzyFX={baseFace,profile,views,profileFor,baseFaceFor,createSprites,draw};
})(typeof window!=='undefined'?window:globalThis);
