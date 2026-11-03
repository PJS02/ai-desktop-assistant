/* Dizzy faces: clean painted eyes, rotating drawn spirals in each view. */
(function(root){
'use strict';
const clamp=x=>Math.max(0,Math.min(1,Number.isFinite(x)?x:0));
const plainSpiralScale=1.35;
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
// Separate cover art for the optional spiral-only face. The v3 eye apertures,
// sprites and geometry above remain the saved eye-backed variant.
const plainViews={
 front:{colors:['#fff0e5','#fff2e9','#f8e0d5'],covers:[
  {start:[96,227],curves:[[98,217,106,207,115,203],[125,199.8,138,201,146,206],[151,209,155,219,156,231],[157,241,148,249,134,249],[119,251,106,244,102,236],[99,232,96,230,96,227]]},
  {start:[190,224],curves:[[190,211,198,203,209,199.5],[220,197.5,232,205,238,213],[242,216,247,218,247,220],[244,224,240,230,237,235],[235,245,222,249,209,248],[196,247,190,237,190,224]]}
 ]},
 left:{eyeOffsets:[[2,0],[0,0]],colors:['#fff0e6','#fcefe8','#f9e0d7'],covers:[
  {start:[77,210],curves:[[77,202,82,194,87,193],[93,193,99,200,103,209],[106,220,106,233,99,239],[92,243,86,237,83,228],[80,222,77,217,77,210]]},
  {start:[128,201],curves:[[128,192,138,182,149,181],[163,179,176,189,183,198],[180,207,177,219,168,227],[156,234,139,232,132,219],[129,213,128,208,128,201]]}
 ]},
 right:{eyeOffsets:[[0,0],[-1.5,0]],colors:['#fff0e5','#fcf0e9','#f8e0d6'],cleanup:[
  {start:[198,221],curves:[[203,225,218,226,231,220],[230,232,218,237,205,234],[201,232,198,227,198,221]]}
 ],covers:[
  {start:[182,207],curves:[[187,192,200,181,212,179.5],[225,178,235,187,240,201],[241,219,232,236,215,237],[198,239,187,230,182,213],[180,210,181,208,182,207]]},
  {start:[260,192],curves:[[260,182,266,173,272,171],[277,171,280,182,281,193],[280,203,278,215,273,221],[266,223,260,216,259,207],[258,201,259,196,260,192]]}
 ]}
};
const generatedSkinArt={"front":{"name":"dizzy_eyeless_front","file":"textures/dizzy-v5/eyeless-front.png","size":[1254,1254],"toAtlas":[0.24032749309789936,-5.283161279016087e-05,5.283161279016087e-05,0.24032749309789936,22.792527311315375,14.530086656549335]},"left":{"name":"dizzy_eyeless_left","file":"textures/dizzy-v5/eyeless-left.png","size":[1247,1261],"toAtlas":[0.25076212230589506,0.00019783712971753025,1.6647375526608092e-05,0.2554225100479038,26.14172886699133,8.483471997754364]},"right":{"name":"dizzy_eyeless_right","file":"textures/dizzy-v5/eyeless-right.png","size":[1207,1303],"toAtlas":[0.2387190573575371,-0.00011638645697619922,0.00028950605235447354,0.24238873753196258,28.024047361706664,6.656067270793535]}};
if(root.CLOUDY_PARTS)for(const art of Object.values(generatedSkinArt)){
 root.CLOUDY_PARTS[art.name]={file:art.file,bbox:[0,0,...art.size],size:art.size,dizzySkinSource:true};
}
function coverBounds(paths){
 const points=paths.flatMap(path=>[path.start,...path.curves.flatMap(curve=>[[curve[0],curve[1]],[curve[2],curve[3]],[curve[4],curve[5]]])]);
 const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
 const x=Math.floor(Math.min(...xs))-1,y=Math.floor(Math.min(...ys))-1;
 return[x,y,Math.ceil(Math.max(...xs))-x+1,Math.ceil(Math.max(...ys))-y+1];
}
for(const view of Object.values(plainViews)){
 const [x,y,w,h]=coverBounds(view.covers);
 view.skinBounds=[x-6,y-6,w+12,h+12];
}
for(const view of Object.values(views)){
 const points=view.eyes.flatMap(eye=>[eye.aperture.start,...eye.aperture.curves.flatMap(curve=>[[curve[0],curve[1]],[curve[2],curve[3]],[curve[4],curve[5]]])]);
 const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
 const x=Math.floor(Math.min(...xs))-1,y=Math.floor(Math.min(...ys))-1;
 view.whiteBounds=[x,y,Math.ceil(Math.max(...xs))-x+1,Math.ceil(Math.max(...ys))-y+1];
}
function profileFor(cfg){return cfg&&cfg.head&&cfg.head[0]===0?views[cfg.prefix]||null:null;}
function baseFaceFor(cfg){const view=profileFor(cfg);return view?view.baseFace:null;}

function createSprites(images={},parts={}){
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
 for(const [direction,view] of Object.entries(plainViews)){
  const [x,y,w,h]=view.skinBounds;
  const canvas=document.createElement('canvas');canvas.width=w*4;canvas.height=h*4;
  const c=canvas.getContext('2d');
  function mask(paths,feather=0,expansion=0){
   const out=document.createElement('canvas');out.width=canvas.width;out.height=canvas.height;
   const context=out.getContext('2d');context.scale(4,4);context.translate(-x,-y);
   context.fillStyle='#000';context.strokeStyle='#000';context.lineJoin='round';
   context.lineWidth=expansion*2;context.shadowColor='#000';context.shadowBlur=feather*4;
   for(const path of paths){
    context.beginPath();context.moveTo(...path.start);
    for(const curve of path.curves)context.bezierCurveTo(...curve);
    context.closePath();context.fill();if(expansion)context.stroke();
   }
   return out;
  }
  const core=mask(view.covers),soft=mask(view.covers,3);
  // Include the original lower rim and iris-coloured antialiasing too. They
  // must not survive as an eye-shaped ring around the skin replacement.
  const aperture=mask([...views[direction].eyes.map(eye=>eye.aperture),...(view.cleanup||[])],0,3.5);
  const corePixels=core.getContext('2d').getImageData(0,0,core.width,core.height).data;
  const softPixels=soft.getContext('2d').getImageData(0,0,soft.width,soft.height).data;
  const aperturePixels=aperture.getContext('2d').getImageData(0,0,aperture.width,aperture.height).data;
  const im=images[views[direction].baseFace],part=parts[views[direction].baseFace];
  let source=null,sourceWidth=0,sourceHeight=0,sourceX=0,sourceY=0;
  if(im&&part){
   const original=document.createElement('canvas');original.width=im.width;original.height=im.height;
   const originalContext=original.getContext('2d');originalContext.drawImage(im,0,0);
   source=originalContext.getImageData(0,0,im.width,im.height).data;
   sourceWidth=im.width;sourceHeight=im.height;[sourceX,sourceY]=part.bbox;
  }
  function sourcePixel(ax,ay){
   const sx=Math.floor(ax-sourceX),sy=Math.floor(ay-sourceY);
   if(!source||sx<0||sy<0||sx>=sourceWidth||sy>=sourceHeight)return null;
   const i=(sy*sourceWidth+sx)*4;return[source[i],source[i+1],source[i+2],source[i+3]];
  }
  function warmSkin(p){return p&&p[3]>240&&p[0]>220&&p[1]>202&&p[2]>188&&p[0]-p[1]>3&&p[1]-p[2]>2;}
  // Use registered painted eyeless skin instead of interpolating a flat
  // colour field. The alpha mask below keeps the original hair and skin edge.
  const art=generatedSkinArt[direction],painted=images[art.name];
  if(!painted)throw new Error('Missing eyeless skin artwork: '+art.file);
  const [a,b,ac,d,e,f]=art.toAtlas;
  c.setTransform(4*a,4*b,4*ac,4*d,4*(e-x),4*(f-y));
  c.drawImage(painted,0,0);
  c.setTransform(1,0,0,1,0,0);
  const result=c.getImageData(0,0,canvas.width,canvas.height),pixels=result.data;
  for(let py=0;py<canvas.height;py++)for(let px=0;px<canvas.width;px++){
   const i=(py*canvas.width+px)*4,inside=corePixels[i+3]/255,eye=aperturePixels[i+3]/255;
   let alpha=softPixels[i+3]/255;
   const p=sourcePixel(x+px/4,y+py/4);
   if(p){
    alpha*=p[3]/255;
    const hair=p[1]>135&&p[1]-p[0]>5&&p[2]-p[0]>-4&&p[1]>=p[2]-10;
    if(hair&&eye<.01)alpha=0;
    else{
     // Keep already painted warm skin. The opaque core still replaces all
     // whites and dark lashes; feathering only touches neighbouring skin.
     const skin=clamp((p[0]-p[2]-6)/8)*clamp((p[1]-192)/18)*clamp((p[0]-p[1]-1)/6);
     alpha*=1-skin*(1-eye);
     if(inside<.01&&!warmSkin(p))alpha=0;
    }
   }
   pixels[i+3]=Math.round(255*alpha);
  }
  c.putImageData(result,0,0);
  sprites['fx_dizzy_skin_'+direction]=canvas;
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
 const plain=pose.dizzyPlain>.5;
 const cover=(plain?'fx_dizzy_skin_':'fx_dizzy_whites_')+cfg.prefix,coverPart=renderer.parts[cover];
 if(coverPart){
  const [x,y,w,h]=plain?plainViews[cfg.prefix].skinBounds:view.whiteBounds,[bx,by,bw,bh]=coverPart.bbox;
  renderer.mesh(cover,p=>faceMapping({x:x+(p.x-bx)/bw*w,y:y+(p.y-by)/bh*h}),alpha,24,12);
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
 for(const [index,eye] of view.eyes.entries()){
  const angle=eye.phase+eye.spin*clock*Math.PI*2/view.period;
  const size=plain?eye.size.map(value=>value*plainSpiralScale):eye.size;
  const offset=plain&&(plainViews[cfg.prefix].eyeOffsets||[])[index];
  const center=offset?[eye.center[0]+offset[0],eye.center[1]+offset[1]]:eye.center;
  sprite('fx_dizzy_spiral',center,size,angle,1-blink);
 }
 if(!plain&&blink>.001&&renderer.textures[view.blinkFace]){
  renderer.mesh(view.blinkFace,faceMapping,alpha*blink,24,28);
 }
 // A tiny relaxed opening reads as dazed even while the eyes blink. Speech
 // can open it slightly without restoring the original neutral mouth.
 const open=clamp(pose.speaking)*clamp(pose.mouthOpen);
 sprite('fx_dizzy_mouth',view.mouth.center,
        [view.mouth.size[0]*(1+.12*open),view.mouth.size[1]*(1+.65*open)],0);
}

root.CloudyDizzyFX={baseFace,profile,views,plainViews,plainSpiralScale,generatedSkinArt,profileFor,baseFaceFor,createSprites,draw};
})(typeof window!=='undefined'?window:globalThis);
