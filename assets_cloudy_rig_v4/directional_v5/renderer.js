/* Standalone WebGL skinned-art renderer; no host application imports. */
(function(root){
'use strict';
const M=root.CloudyMotion, P=root.CLOUDY_PARTS;
const mix=(a,b,t)=>a+(b-a)*t, point=(x,y)=>({x,y});
// The round elbow bridge enters as the sleeve folds at .67 s. Both lift and
// lowering use the same pose progress. A fixed-size patch is revealed beneath
// the forearm sleeve, keeping its anatomy while the visible fold changes.
const elbowCapStart=M&&M.sideWavePreparation(.67).lift,elbowCapFull=M&&M.sideWavePreparation(.82).lift;
const rotate=(p,a,o={x:0,y:0})=>{a*=Math.PI/180;let c=Math.cos(a),s=Math.sin(a),x=p.x-o.x,y=p.y-o.y;return{x:o.x+x*c-y*s,y:o.y+x*s+y*c}};
const end=(p,l,a)=>({x:p.x-l*Math.sin(a*Math.PI/180),y:p.y+l*Math.cos(a*Math.PI/180)});
const configs={
 front:{head:[0,171,298,.79],body:[1,493,65,.50],hips:[[204,357],[154,357]],ankles:[[207,488],[150,488]],shoulders:[[232,269],[128,269]],
 legs:[{i:5,j:[[484,340],[485,443],[478,524],[478,596]]},{i:4,j:[[170,341],[166,446],[156,524],[156,596]]}],
 arms:[{i:3,j:[[1051,64],[1091,171],[1136,281]],hand:7,hp:[1092,429],cuff:[1142,293]},{i:2,j:[[817,63],[779,172],[747,280]],hand:6,hp:[785,429],cuff:[741,294]}]},
 left:{head:[0,149,298,.76],body:[1,474,77,.52],hips:[[190,357],[169,357]],ankles:[[190,488],[169,488]],shoulders:[[202,268],[163,268]],
 legs:[{i:4,j:[[174,340],[172,432],[192,533],[121,581]]},{i:5,j:[[502,342],[496,436],[511,533],[445,582]]}],
 arms:[{i:2,j:[[810,89],[791,178],[754,281]],hand:6,hp:[777,479],cuff:[751,286]},{i:3,j:[[1080,87],[1111,178],[1157,283]],hand:7,hp:[1090,479],cuff:[1159,289]}]},
 right:{head:[0,210,298,.76],body:[1,499,86,.55],hips:[[170,357],[191,357]],ankles:[[170,488],[191,488]],shoulders:[[158,268],[198,268]],
 legs:[{i:5,j:[[496,339],[483,435],[463,517],[538,567]]},{i:4,j:[[174,337],[164,434],[146,517],[225,567]]}],
 arms:[{i:2,j:[[765,102],[803,177],[834,271]],hand:6,hp:[790,480],cuff:[833,277]},{i:3,j:[[1040,101],[1090,179],[1135,271]],hand:7,hp:[1100,480],cuff:[1137,281]}]}
};
function variant(direction,angle){
 const cfg=configs[direction]; if(direction==='front')return{...cfg,key:'front',prefix:'front'};
 const out={...cfg,key:direction+angle,prefix:direction};
 if(angle===15){out.head=direction==='left'?[12,147,1223,.75]:[12,196,1210,.77];out.body=direction==='left'?[13,473,1001,.53]:[13,493,992,.54];}
 if(angle===35){out.head=direction==='left'?[10,773,920,.75]:[10,818,908,.76];out.body=direction==='left'?[11,1085,697,.52]:[11,1111,691,.55];}
 if(angle<65){const t=angle/65;for(let k of ['hips','ankles','shoulders'])out[k]=configs.front[k].map((v,i)=>v.map((x,j)=>mix(x,cfg[k][i][j],t)));}
 return out;
}
const views=[[-65,variant('left',65)],[-35,variant('left',35)],[-15,variant('left',15)],[0,variant('front',0)],[15,variant('right',15)],[35,variant('right',35)],[65,variant('right',65)]];
const key=(prefix,i)=>prefix+'_'+String(i).padStart(2,'0');
const eyeAnchors={front_00:[130,210,226,282],left_00:[89,149,212,278],right_00:[219,277,208,278],left_10:[711,770,833,899],left_12:[100,180,1134,1197],right_10:[809,865,831,889],right_12:[186,260,1119,1184]};
function knots(cfg){const [i,px,py,s]=cfg.head,name=key(cfg.prefix,i),[x,y,w,h]=P[name].bbox,[a,b,eye,chin]=eyeAnchors[name];return{x:[x,a,b,x+w].map(v=>(v-px)*s),y:[y,eye,chin,y+h].map(v=>(v-py)*s)};}
function remap(value,a,b){let i=0;while(i<a.length-2&&value>a[i+1])i++;return mix(b[i],b[i+1],(value-a[i])/(a[i+1]-a[i]));}
function flowAt(flow,x,y){x=Math.max(0,Math.min(48,x/239*48));y=Math.max(0,Math.min(56,y/279*56));const ix=Math.min(47,Math.floor(x)),iy=Math.min(55,Math.floor(y)),tx=x-ix,ty=y-iy;const a=flow[iy*49+ix],b=flow[iy*49+ix+1],c=flow[(iy+1)*49+ix],d=flow[(iy+1)*49+ix+1];return a.map((v,i)=>mix(mix(v,b[i],tx),mix(c[i],d[i],tx),ty));}

class Renderer{
 constructor(canvas){
  this.canvas=canvas;this.gl=canvas.getContext('webgl',{alpha:true,antialias:true,premultipliedAlpha:true,preserveDrawingBuffer:true});
  if(!this.gl)throw Error('WebGL을 사용할 수 없습니다.');
  const gl=this.gl;
  const compile=(type,source)=>{let s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s};
  this.program=gl.createProgram();
  gl.attachShader(this.program,compile(gl.VERTEX_SHADER,'attribute vec2 pos;attribute vec2 uv;uniform vec2 viewport;varying vec2 tex;void main(){gl_Position=vec4(pos.x/viewport.x*2.0-1.0,1.0-pos.y/viewport.y*2.0,0.0,1.0);tex=uv;}'));
  gl.attachShader(this.program,compile(gl.FRAGMENT_SHADER,'precision mediump float;uniform sampler2D image;uniform sampler2D replacement;uniform sampler2D bodyNegativeLower;uniform sampler2D bodyNegativeUpper;uniform float replacementAmount;uniform float bodyBlendEnabled;uniform float bodyPositiveWeight;uniform float sourceClipEnabled;uniform vec3 sourceClipAxis;uniform vec2 sourceClipBounds;uniform float opacity;varying vec2 tex;void main(){if(sourceClipEnabled>0.5){float axial=dot(tex,sourceClipAxis.xy)+sourceClipAxis.z;if(axial<sourceClipBounds.x||axial>sourceClipBounds.y)discard;}vec4 base=texture2D(image,tex);if(bodyBlendEnabled>0.5){vec4 positive=base+(texture2D(replacement,tex)-base)*replacementAmount;vec4 negativeBase=texture2D(bodyNegativeLower,tex);vec4 negative=negativeBase+(texture2D(bodyNegativeUpper,tex)-negativeBase)*replacementAmount;gl_FragColor=(negative+(positive-negative)*bodyPositiveWeight)*opacity;}else{gl_FragColor=(base+(texture2D(replacement,tex)-base)*replacementAmount)*opacity;}}'));
  gl.linkProgram(this.program);if(!gl.getProgramParameter(this.program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(this.program));
  gl.useProgram(this.program);this.pos=gl.getAttribLocation(this.program,'pos');this.uv=gl.getAttribLocation(this.program,'uv');this.opacity=gl.getUniformLocation(this.program,'opacity');
  gl.uniform2f(gl.getUniformLocation(this.program,'viewport'),360,540);gl.uniform1i(gl.getUniformLocation(this.program,'image'),0);
  gl.uniform1i(gl.getUniformLocation(this.program,'replacement'),1);this.replacementAmount=gl.getUniformLocation(this.program,'replacementAmount');
  gl.uniform1i(gl.getUniformLocation(this.program,'bodyNegativeLower'),2);gl.uniform1i(gl.getUniformLocation(this.program,'bodyNegativeUpper'),3);
  this.bodyBlendEnabled=gl.getUniformLocation(this.program,'bodyBlendEnabled');this.bodyPositiveWeight=gl.getUniformLocation(this.program,'bodyPositiveWeight');
  this.sourceClipEnabled=gl.getUniformLocation(this.program,'sourceClipEnabled');this.sourceClipAxis=gl.getUniformLocation(this.program,'sourceClipAxis');this.sourceClipBounds=gl.getUniformLocation(this.program,'sourceClipBounds');
  this.buffer=gl.createBuffer();this.images={};this.textures={};this.grids={};this.parts={...P};this.viewZoom=1;
  gl.enable(gl.BLEND);gl.blendFunc(gl.ONE,gl.ONE_MINUS_SRC_ALPHA);gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,true);

 }
 async load(){await Promise.all(Object.entries(P).map(async([name,part])=>{
   let im;
   for(let attempt=0;attempt<3;attempt++){
    im=new Image();im.src=part.file+(attempt?(part.file.includes('?')?'&':'?')+'cloudy_retry='+attempt:'');
    try{await im.decode();break;}
    catch(error){
     if(attempt===2)throw new Error('이미지를 불러오지 못했습니다: '+part.file,{cause:error});
     await new Promise(resolve=>setTimeout(resolve,150*(attempt+1)));
    }
   }
   this.images[name]=im;const gl=this.gl,tex=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,tex);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,im);this.textures[name]=tex;
  }));
  const emotionSprites=root.CloudyEmotionFX?root.CloudyEmotionFX.createSprites(this.images,this.parts):{};
  for(const [name,im] of Object.entries(emotionSprites)){
   this.parts[name]={bbox:[0,0,im.width,im.height]};const gl=this.gl,tex=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,tex);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,im);this.textures[name]=tex;
  }
  for(const [name,glyph] of [['fx_question','?'],['fx_Z','Z'],['fx_z','z']]){
   const im=document.createElement('canvas');im.width=128;im.height=128;
   const c=im.getContext('2d');c.font='bold 96px "Trebuchet MS", sans-serif';c.textAlign='center';c.textBaseline='middle';c.lineJoin='round';c.lineWidth=9;c.strokeStyle='#f8fffd';c.fillStyle='#65b7ad';c.strokeText(glyph,64,67);c.fillText(glyph,64,67);
   this.parts[name]={bbox:[0,0,128,128]};const gl=this.gl,tex=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,tex);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,im);this.textures[name]=tex;
  }
  return this;}
 mesh(name,map,opacity=1,cols=1,rows=1,blendName=null,blendAmount=0,baseTextureName=null,bodyBlend=null,sourceClip=null){
  if(!this.textures[name]||opacity<.001)return;
  const gl=this.gl,part=this.parts[name],[bx,by,w,h]=part.bbox,data=[];
  const grid=[];for(let y=0;y<=rows;y++)for(let x=0;x<=cols;x++){let u=x/cols,v=y/rows,p=map({x:bx+w*u,y:by+h*v});grid.push([180+(p.x-180)*this.viewZoom,535+(p.y-535)*this.viewZoom,u,v]);}
  for(let y=0;y<rows;y++)for(let x=0;x<cols;x++){let a=y*(cols+1)+x,b=a+1,c=a+cols+1,d=c+1;for(let i of [a,b,c,b,d,c])data.push(...grid[i]);}
  const baseTexture=this.textures[baseTextureName]||this.textures[name];
  // A folded sleeve is two painted surfaces meeting at an opaque overlap.
  // Clipping in atlas space keeps the original ink; no elbow crossfade can
  // cancel opposing bone transforms or turn the strap into a stretched smear.
  gl.uniform1f(this.sourceClipEnabled,sourceClip?1:0);
  if(sourceClip){
   const {axis,origin,scale,min,max}=sourceClip;
   gl.uniform3f(this.sourceClipAxis,w*scale*axis.x,h*scale*axis.y,
    (bx*scale-origin.x)*axis.x+(by*scale-origin.y)*axis.y);
   gl.uniform2f(this.sourceClipBounds,min,max);
  }
  // Side greetings have two painted cuff rolls. Their progress is shared, but
  // which roll faces the torso follows the current mapped forearm orientation.
  // All other meshes retain the original two-texture fragment calculation.
  const bodyBlendReady=bodyBlend&&this.textures[bodyBlend.negativeLower]&&this.textures[bodyBlend.negativeUpper];
  gl.uniform1f(this.bodyBlendEnabled,bodyBlendReady?1:0);
  gl.activeTexture(gl.TEXTURE2);gl.bindTexture(gl.TEXTURE_2D,bodyBlendReady?this.textures[bodyBlend.negativeLower]:baseTexture);
  gl.activeTexture(gl.TEXTURE3);gl.bindTexture(gl.TEXTURE_2D,bodyBlendReady?this.textures[bodyBlend.negativeUpper]:baseTexture);
  if(bodyBlendReady)gl.uniform1f(this.bodyPositiveWeight,bodyBlend.weight);
  gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,this.textures[blendName]||baseTexture);gl.uniform1f(this.replacementAmount,blendName?blendAmount:0);gl.activeTexture(gl.TEXTURE0);
  gl.bindTexture(gl.TEXTURE_2D,baseTexture);gl.uniform1f(this.opacity,opacity);gl.bindBuffer(gl.ARRAY_BUFFER,this.buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(data),gl.DYNAMIC_DRAW);gl.enableVertexAttribArray(this.pos);gl.vertexAttribPointer(this.pos,2,gl.FLOAT,false,16,0);gl.enableVertexAttribArray(this.uv);gl.vertexAttribPointer(this.uv,2,gl.FLOAT,false,16,8);gl.drawArrays(gl.TRIANGLES,0,data.length/4);
 }
 drawSprite(name,pivot,location,scale,angle,opacity=1){this.mesh(name,p=>rotate({x:location.x+(p.x-pivot.x)*scale,y:location.y+(p.y-pivot.y)*scale},angle,location),opacity);}
 bodyPoint(p,pose){return rotate({x:p.x+pose.bodyX,y:p.y+pose.bodyY},pose.lean,{x:180+pose.bodyX,y:357+pose.bodyY});}
 limb(cfg,index,type,pose,opacity,surface='all'){
  const part=(type==='leg'?cfg.legs:cfg.arms)[index],name=key(cfg.prefix,part.i),near=index===0,suffix=near?'Near':'Far',scale=type==='leg'?.48:.34;
  const src=part.j.map(([x,y])=>({x:x*scale,y:y*scale}));
  let dest,hand;
  if(type==='leg'){
   const hip=this.bodyPoint(point(...cfg.hips[index]),pose),base=cfg.ankles[index],sign=cfg.prefix==='right'?-1:1;
   const bounds=P[name].bbox,sole=bounds[1]+bounds[3]-3;
   const floorCorrection=535-(base[1]+(sole-part.j[2][1])*scale);
   hip.y+=floorCorrection;
   const foot={x:base[0]+sign*pose['foot'+suffix+'X'],y:base[1]+floorCorrection+Math.min(0,pose['foot'+suffix+'Y'])};
   // Concealed hip correction keeps both planted soles on a single ground plane.
   const reach=Math.hypot(foot.x-hip.x,foot.y-hip.y);
   if(reach>134.6)hip.y+=reach-134.6;
   const bend=cfg.prefix==='front'?(near?-1:1):(cfg.prefix==='right'?-1:1);
   const ik=M.solveIK(hip,foot,68,67,bend);
   if(cfg.prefix==='front')ik.knee.x=mix((hip.x+foot.x)*.5,ik.knee.x,.32);
   const rest=src[3],ankle=src[2],delta={x:rest.x-ankle.x,y:rest.y-ankle.y};
   const toe=rotate({x:ik.ankle.x+delta.x,y:ik.ankle.y+delta.y},sign*pose['foot'+suffix+'Angle'],ik.ankle);
   dest=[hip,ik.knee,ik.ankle,toe];
  }else{
   const shoulder=this.bodyPoint(point(...cfg.shoulders[index]),pose);
   const orientation=cfg.prefix==='right'?-1:1;
   let arm=pose['arm'+suffix],bend=pose['elbow'+suffix];
   const sideWave=near&&cfg.prefix!=='front';
   if(sideWave){arm+=pose.waveArmOffset||0;bend+=pose.waveElbowOffset||0;}
   if(cfg.prefix==='front'){
    // Both arms rest diagonally out from the body with a soft elbow bend.
    // The far arm is mirrored below; both input angles therefore move negative.
    const rest=Math.max(0,Math.min(1,pose.exprSleep||0),near?0:Math.min(1,pose.thinkGesture||0));
    // Sleep uses both relaxed arms; thinking keeps only the unraised arm here.
    const gesture=Math.max(rest*.95,Math.max(0,Math.min(1,pose.idleGesture||0)))*(near?1-Math.max(0,Math.min(1,pose.waveGesture||0)):1);
    arm-=(near?29:33)*gesture;bend+=(near?5:7)*gesture;
   }
   let a=orientation*arm+pose.lean;
   if(cfg.prefix==='front'&&!near)a=mix(-arm,arm,pose.airArms||0)+pose.lean;
   let b=a+orientation*bend*(cfg.prefix==='front'&&!near?-1:1);
   const forearmScale=sideWave?1-Math.max(0,Math.min(.2,pose.waveForearmShorten||0)):1;
   let elbow=end(shoulder,38,a),wrist=end(elbow,46*forearmScale,b);
   if(near&&pose.thinkGesture>0){
    const chinSource={front:[171,282],left:[117,277],right:[253,270]}[cfg.prefix];
    const [,hx,hy,hs]=cfg.head,head=this.bodyPoint({x:180,y:250},pose);
    const chin=rotate({x:head.x+(chinSource[0]-hx)*hs,y:head.y+(chinSource[1]-hy)*hs},pose.lean+pose.headAngle,head);
    const target={x:chin.x+(cfg.prefix==='right'?-18:18),y:chin.y+24};
    const ik=M.solveIK(shoulder,target,38,46,cfg.prefix==='right'?1:-1),t=M.smoothstep(pose.thinkGesture);
    elbow={x:mix(elbow.x,ik.knee.x,t),y:mix(elbow.y,ik.knee.y,t)};wrist={x:mix(wrist.x,ik.ankle.x,t),y:mix(wrist.y,ik.ankle.y,t)};
    b=Math.atan2(-(wrist.x-elbow.x),wrist.y-elbow.y)*180/Math.PI;
   }
   dest=[shoulder,elbow,wrist];
   const handName=key(cfg.prefix,part.hand),handPivot=point(...part.hp);
   const flex=orientation*(pose['wrist'+suffix]+(sideWave?(pose.waveWristOffset||0):0));
   hand={name:handName,pivot:handPivot,angle:b+flex,forearmAngle:b,flex,projectionScale:forearmScale};
  }
  const normalScale=root.CloudyGirth?root.CloudyGirth.scale(cfg.prefix,type,near):undefined;
  const splitMaterials=this.textures[name+'_connected_wave_cloth']&&this.textures[name+'_connected_wave_hardware']
   &&this.textures[name+'_connected_wave_tag']&&this.textures[name+'_wave_elbow_cloth_cap_v16'];
  const waveLayers=type==='arm'&&near&&cfg.prefix!=='front'&&(pose.waveSideGesture||0)>0&&root.CloudySideWaveSkinning&&splitMaterials
   ?root.CloudySideWaveSkinning.createLayers(src,dest,{activation:pose.waveSideGesture,normalScale,
      fallback:p=>M.deformPoint(p,src,dest,normalScale),overlap:1.2,
      capStatic:true,capScale:{along:.72,across:.82},capOffset:cfg.prefix==='left'?{along:0,across:0}:{along:-2,across:2},
      capActivation:M.smoothstep((pose.waveSideGesture-elbowCapStart)/(elbowCapFull-elbowCapStart))}):null;
  if(waveLayers&&cfg.prefix==='left'){
   // Fit the existing disk to the painted forearm cut, whose center is offset
   // from the bone. These alpha-edge endpoints are stable in both cloth banks.
   const edgeA=waveLayers.forearmMap(point(288.319502,64.794503)),
    edgeB=waveLayers.forearmMap(point(256.360692,55.687704)),
    dx=edgeB.x-edgeA.x,dy=edgeB.y-edgeA.y,length=Math.hypot(dx,dy),ex=dx/length,ey=dy/length;
   let vx=-ey,vy=ex;
   if(vx*(dest[2].x-dest[1].x)+vy*(dest[2].y-dest[1].y)<0){vx=-vx;vy=-vy;}
   // A shallow dome with the same hidden-overlap proportion as the natural
   // right elbow. Its rim meets both painted endpoints rather than hanging
   // below the sleeve as an independently positioned circle.
   const insetRatio=.23,width=length*.5/Math.sqrt(1-insetRatio*insetRatio),depth=length*.5*1.03,
    cx=(edgeA.x+edgeB.x)*.5+vx*depth*insetRatio,
    cy=(edgeA.y+edgeB.y)*.5+vy*depth*insetRatio,
    {origin,axis,normalAxis}=waveLayers.clip,radius=P[name+'_wave_elbow_cloth_cap_v16'].radius*scale;
   waveLayers.capMap=p=>{
    const dx=p.x-origin.x,dy=p.y-origin.y,
     across=(dx*normalAxis.x+dy*normalAxis.y)*width/radius,
     along=(dx*axis.x+dy*axis.y)*depth/radius;
    return{x:cx+ex*across+vx*along,y:cy+ey*across+vy*along};
   };
  }
  const mapping=p=>{
   const source={x:p.x*scale,y:p.y*scale},mapped=waveLayers?waveLayers.map(source):M.deformPoint(source,src,dest,normalScale);
   if(type!=='leg')return mapped;
   // The painted overlap above the hip belongs inside the skirt. Letting it
   // rotate backwards with the thigh makes a skin spike appear at the waist.
   // Anchor only this concealed extension to the pelvis, with a smooth blend
   // ending before the visible thigh. Knee, ankle, shoe and gait stay intact.
   const dx=src[1].x-src[0].x,dy=src[1].y-src[0].y,length=Math.hypot(dx,dy);
   const px=source.x-src[0].x,py=source.y-src[0].y;
   const axial=(px*dx+py*dy)/length,q=axial/length;
   const weight=1-M.smoothstep(q/.22);
   if(weight===0)return mapped;
   const normal=(-px*dy+py*dx)/length*(normalScale?normalScale(0,q):1);
   const anchor=rotate({x:dest[0].x-normal,y:dest[0].y+axial},pose.lean,dest[0]);
   return {x:mix(mapped.x,anchor.x,weight),y:mix(mapped.y,anchor.y,weight)};
  };
  const segmentMap=segment=>p=>waveLayers[segment]({x:p.x*scale,y:p.y*scale});
  const forearmMapping=waveLayers?segmentMap('forearmMap'):mapping;
  if(hand&&this.textures[name+'_connected']){
   // The forearm, cuff and hand retain a continuous painted attachment. Wrist
   // flex fades in below the cuff; the side elbow uses separate cloth surfaces.
   const opening=forearmMapping(point(...part.cuff));
   const dx=part.j[2][0]-part.j[1][0],dy=part.j[2][1]-part.j[1][1],length=Math.hypot(dx,dy);
   // Open the palm while the arm is still low. Its silhouette is fully painted
   // before it reaches the face, rather than fading throughout the whole lift.
   const waveProgress=cfg.prefix!=='front'&&pose.waveSideGesture!==undefined?pose.waveSideGesture:pose.waveGesture;
   const waveHand=near?M.smoothstep(Math.max(0,Math.min(1,waveProgress||0))/.18):0;
   const palmProgress=Math.max(0,Math.min(1,waveProgress||0));
   const rightPalmGrowth=near&&cfg.prefix==='right'
    ?palmProgress<.4?.36*M.smoothstep(palmProgress/.4)
      :.36+.164*M.smoothstep((palmProgress-.4)/.6):0;
   const clothTexture=name+'_connected_wave_cloth',hardwareTexture=name+'_connected_wave_hardware',tagTexture=name+'_connected_wave_tag';
   const elbowTexture=name+'_wave_elbow_cloth_cap_v16';
   const segmented=waveLayers&&waveLayers.amount>0&&this.textures[clothTexture]
    &&this.textures[hardwareTexture]&&this.textures[tagTexture]&&this.textures[elbowTexture];
   const fitCuff=root.CloudySideCuffFit&&this.textures[name+'_wave_cuff_band_v22'];
   const artCuff=root.CloudySideCuffArt&&this.textures[name+'_wave_cuff_band_v21'];
   const cuffBand=name+(fitCuff?'_wave_cuff_band_v22':artCuff?'_wave_cuff_band_v21':'_wave_cuff_band_v18'),cuffRim=name+'_wave_cuff_backrim_v18';
   const wholeCuff=near&&cfg.prefix!=='front'&&(segmented||this.action==='wave')
    &&root.CloudySideCuff&&this.textures[cuffBand]&&this.textures[cuffRim];
   const cuffElbow=forearmMapping(point(...part.j[1])),cuffAxis={x:opening.x-cuffElbow.x,y:opening.y-cuffElbow.y};
   const cuffLength=Math.hypot(cuffAxis.x,cuffAxis.y),cuffNormal={x:-cuffAxis.y/cuffLength,y:cuffAxis.x/cuffLength};
   const cuffBody=this.bodyPoint({x:180,y:315},pose);
   const cuffRoll=wholeCuff&&root.CloudySideCuffRoll?root.CloudySideCuffRoll.sample(palmProgress,cuffNormal,
    {x:cuffBody.x-opening.x,y:cuffBody.y-opening.y}):null;
   // Construct the cuff after the existing connected hand map is available.
   // Its front and back drawing closures share exactly one wrist opening.
   let cuff=null;
   const drawCuff=front=>{
    if(!cuff)return;
    const tuckFrames=!fitCuff&&artCuff&&P[cuffBand].cuffTuckFrames;
    const position=tuckFrames?cuff.art.tuck*(tuckFrames.length-1):0;
    const lower=Math.floor(position),higher=tuckFrames?Math.min(lower+1,tuckFrames.length-1):0;
    for(const [texture,map,ranges]of [[cuffBand,cuff.bandMap,front?cuff.frontRanges:cuff.backRanges],
     [cuffRim,cuff.rimMap,front?cuff.rimFrontRanges:cuff.rimBackRanges]])
     for(const {min,max}of ranges)this.mesh(texture,map,opacity,64,4,
      texture===cuffBand&&tuckFrames&&higher!==lower?tuckFrames[higher]:null,
      texture===cuffBand&&tuckFrames?position-lower:0,
      texture===cuffBand&&tuckFrames?tuckFrames[lower]:null,null,
      {origin:{x:0,y:0},axis:{x:1,y:0},scale:1,min,max});
   };
   const waveTexture=segmented?clothTexture:wholeCuff?name+'_connected_wave_cuff_fallback_v18':name+'_connected_wave';
   let material=null,replacement=waveHand>0&&this.textures[waveTexture]?waveTexture:null,amount=waveHand,bodyBlend=null;
   const rollFrames=near&&cfg.prefix!=='front'&&P[waveTexture]&&P[waveTexture].rollFrames;
   if(rollFrames&&rollFrames.every(frame=>this.textures[frame])){
    // Material progress follows the eased lift without changing the reviewed
    // elbow, forearm and wrist maps. Direction is selected separately below.
    const frame=Math.max(0,Math.min(1,waveProgress||0))*(rollFrames.length-1);
    const lower=Math.floor(frame),upper=Math.min(lower+1,rollFrames.length-1);
    material=wholeCuff||frame>0?(frame===0&&P[waveTexture].baseRestClean?P[waveTexture].baseRestClean:rollFrames[lower]):null;
    replacement=frame>0&&upper!==lower?rollFrames[upper]:null;amount=frame-lower;
    const positive=P[waveTexture].bodyRollFramesPositive,negative=P[waveTexture].bodyRollFramesNegative;
    if(frame>0&&positive&&negative&&positive.length===rollFrames.length&&negative.length===rollFrames.length
     &&positive.every(texture=>this.textures[texture])&&negative.every(texture=>this.textures[texture])){
     const sourceNormal={x:-dy/length,y:dx/length};
     const across=forearmMapping({x:part.cuff[0]+10*sourceNormal.x,y:part.cuff[1]+10*sourceNormal.y});
     const nx=across.x-opening.x,ny=across.y-opening.y,nLength=Math.hypot(nx,ny);
     const normal={x:nx/nLength,y:ny/nLength};
     const body=this.bodyPoint({x:180,y:315},pose),bodyOffset={x:body.x-opening.x,y:body.y-opening.y};
     const directionDot=normal.x*bodyOffset.x+normal.y*bodyOffset.y;
     // At a zero crossing both rolls stay fully lifted. Only their direction
     // blends, so the broad resting cuff does not flash back into the gesture.
     // Reserve a narrow two-pixel crossover for nearly edge-on cuffs. A wider
     // blend leaves the opposing broad lip visible after the forearm turns.
     const weight=.5+.5*directionDot/Math.sqrt(directionDot*directionDot+4);
     material=positive[lower];replacement=upper!==lower?positive[upper]:null;
     bodyBlend={negativeLower:negative[lower],negativeUpper:negative[upper],weight,normal,bodyOffset,directionDot};
    }
   }
   const connectedMap=baseMap=>p=>{
    const axial=((p.x-part.cuff[0])*dx+(p.y-part.cuff[1])*dy)/length;
    let mapped=baseMap(p);
    if(near&&cfg.prefix!=='front'&&waveHand>0){
     const distal=M.smoothstep((axial+3)/12);
     let vx=mapped.x-opening.x,vy=mapped.y-opening.y;
     // Depth may shorten the sleeve projection, never the painted fingers.
     const angle=hand.forearmAngle*Math.PI/180,ux=-Math.sin(angle),uy=Math.cos(angle);
     const along=vx*ux+vy*uy,correction=along*(1/(hand.projectionScale||1)-1)*distal;
     vx+=ux*correction;vy+=uy*correction;
     // The right source palm was fitted to .6561 of its original size. Undo
     // that fit locally around the cuff; keep the attachment and cloth fixed.
     const palmScale=1+rightPalmGrowth*distal;
     mapped={x:opening.x+vx*palmScale,y:opening.y+vy*palmScale};
    }
    // The left painted hands were tilted against the forearm axis. Correct
    // their resting alignment below the cuff; retain the small wrist sway.
    const alignment=cfg.prefix==='left'?(near?13:-12):0;
   return rotate(mapped,(hand.flex+alignment)*M.smoothstep((axial+3)/28),opening);
   };
   const attachmentBank=P[segmented?clothTexture:name+'_connected_wave_cuff_fallback_v18'];
   const movingCuff=wholeCuff&&root.CloudySideCuffMotion&&attachmentBank&&attachmentBank.cuffAttachmentBoundary;
   cuff=wholeCuff?root.CloudySideCuff.create({anchor:opening,axis:cuffAxis,
    radius:cfg.prefix==='left'?12.6:13.8,height:cfg.prefix==='left'?9.9:12.5,
    depth:cfg.prefix==='left'?3.5:4.2,axialOffset:cfg.prefix==='left'?2:3,
    normalOffset:cfg.prefix==='left'?-.2:2.1,edgeHeightRatio:cfg.prefix==='left'?.50:.62,flare:1.06,
    progress:movingCuff?0:cuffRoll?cuffRoll.progress:palmProgress,
    thumbSign:cuffRoll?cuffRoll.sign:cfg.prefix==='left'?1:-1}):null;
   if(movingCuff){
    let thumbSource;
    if(fitCuff){
     const track=P[cuffBand].thumbTrack;
     let i=0;while(i<track.length-2&&palmProgress>track[i+1].progress)i++;
     const a=track[i],b=track[i+1],t=Math.max(0,Math.min(1,(palmProgress-a.progress)/(b.progress-a.progress)));
     thumbSource={x:mix(a.point[0],b.point[0],t),y:mix(a.point[1],b.point[1],t)};
    }
    cuff=(fitCuff?root.CloudySideCuffFit:artCuff?root.CloudySideCuffArt:root.CloudySideCuffMotion).create({cuff,
     boundary:attachmentBank.cuffAttachmentBoundary.map(forearmMapping),
     forearmMap:forearmMapping,handMap:connectedMap(forearmMapping),
     sourceAnchor:point(...part.cuff),sourceAxis:{x:dx/length,y:dy/length},
     progress:M.sideWaveRoll(palmProgress),gesture:palmProgress,side:cfg.prefix,overlap:1,thumbSource});
   }
   else if(cuff&&root.CloudySideCuffAttachment&&attachmentBank&&attachmentBank.cuffAttachmentBoundary)
    cuff=root.CloudySideCuffAttachment.create({cuff,
     boundary:attachmentBank.cuffAttachmentBoundary.map(forearmMapping),overlap:1});
   if(segmented){
    const {origin,axis,overlap}=waveLayers.clip,clipOverlap=overlap*waveLayers.amount;
    const upper=connectedMap(segmentMap('upperMap')),forearm=connectedMap(forearmMapping);
    if(surface!=='forearm')this.mesh(name+'_connected',upper,opacity,10,40,replacement,amount,material,bodyBlend,
     {origin,axis,scale,min:-10000,max:clipOverlap});
    // Keep the upper mount on its bone and the hanging label on the forearm.
    // Each painted detail is drawn once, rather than copied across the joint.
    const drawDetail=(texture,map,meshName=name+'_connected')=>{
      const bank=P[texture],gesture=Math.max(0,Math.min(1,waveProgress||0));
      // The sleeve label rolls over its upper edge. Keep its route on the
      // same side while the forearm passes the torso-direction crossover;
      // switching with the cloth there sends the label down before it hides.
      const tagRoute=texture===tagTexture&&bank.bodyRollFramesNegative;
      // Finish the occlusion before the lifted sleeve turns past vertical.
      // This Hermite timing joins the original lift with the same speed at
      // .45 and reaches the empty tag frame with zero speed at .83. Lowering
      // samples the same gesture, so the label retraces its upper-edge route.
      const u=Math.max(0,Math.min(1,(gesture-.45)/.38));
      const tagProgress=gesture<=.45?gesture:.45+.55*(u*u*(3-2*u)+(.38/.55)*u*(1-u)*(1-u));
      const position=(tagRoute?tagProgress:gesture)*(bank.rollFrames.length-1);
      const lower=Math.floor(position),higher=Math.min(lower+1,bank.rollFrames.length-1);
      const positive=tagRoute&&cfg.prefix==='right'?bank.bodyRollFramesNegative:
       bank.bodyRollFramesPositive||bank.rollFrames,negative=tagRoute?null:bank.bodyRollFramesNegative;
     const hardwareBlend=bodyBlend&&negative?{...bodyBlend,negativeLower:negative[lower],negativeUpper:negative[higher]}:null;
     this.mesh(meshName,map,opacity,10,40,higher!==lower?positive[higher]:null,position-lower,
      positive[lower],hardwareBlend);
    };
    if(surface!=='forearm')drawDetail(hardwareTexture,upper);
     if(surface!=='upper'&&waveLayers.bridgeWidth>1e-5)this.mesh(name+'_connected',
      p=>waveLayers.bridgeMap({x:p.x*scale,y:p.y*scale}),opacity,32,96,replacement,amount,material,bodyBlend,
      {origin,axis,scale,min:-waveLayers.bridgeWidth,max:waveLayers.bridgeWidth,elbowBridge:true});
    // The cloth joint is already its fitted size when revealed. Put it under
    // the forearm, over the upper cut; the left-view fit follows the cloth end.
    if(surface!=='upper')this.mesh(elbowTexture,p=>waveLayers.capMap({x:p.x*scale,y:p.y*scale}),opacity*waveLayers.capAmount,1,1);
    if(surface!=='upper')drawCuff(false);
    if(surface!=='upper')this.mesh(name+'_connected',forearm,opacity,10,40,replacement,amount,material,bodyBlend,
     {origin,axis,scale,min:-clipOverlap,max:10000});
    if(surface!=='upper')drawDetail(tagTexture,forearm,tagTexture);
    if(surface!=='upper')drawCuff(true);
   }else{
    drawCuff(false);
    this.mesh(name+'_connected',connectedMap(mapping),opacity,10,40,replacement,amount,material,bodyBlend);
    drawCuff(true);
   }
   return;
  }
  this.mesh(name,mapping,opacity,8,26);
  if(hand){
   // The hand starts inside the visible cuff opening. Only its front rim covers
   // the wrist; the dark back wall must not cover the entire attached hand.
   const opening=mapping(point(...part.cuff));
   this.drawSprite(hand.name,hand.pivot,opening,.29,hand.angle,opacity);
   this.mesh(name+'_rim',mapping,opacity,8,26);
  }
 }
 face(cfg,pose,opacity,time=0){
  const [i,px,py,scale]=cfg.head,name=key(cfg.prefix,i),location=this.bodyPoint({x:180,y:250},pose),angle=pose.lean+pose.headAngle;
  const own=knots(cfg),target=cfg.headKnots||own;
  const mapping=p=>{let x=(p.x-px)*scale,y=(p.y-py)*scale;if(cfg.flow){let cx=remap(x,own.x,[0,90,160,239]),cy=remap(y,own.y,[0,210,260,279]);const f=flowAt(cfg.flow,cx,cy);x=remap(cx+f[0]*cfg.flowAmount,[0,90,160,239],target.x);y=remap(cy+f[1]*cfg.flowAmount,[0,210,260,279],target.y);}else{x=remap(x,own.x,target.x);y=remap(y,own.y,target.y);}return rotate({x:location.x+x,y:location.y+y},angle,location);};
  const draw=(texture,alpha)=>this.mesh(texture,mapping,alpha,24,28);
  // Expressions have different eyelid contours. Choose one aligned face so
  // transitioning never leaves two sets of eyes visible on top of each other.
  let expression='',expressionWeight=.5;
  for(const expressionKey of M.expressionKeys||['exprHappy','exprSad','exprAngry','exprScared','exprTalk','exprThinking','exprSleep']){
   const weight=pose[expressionKey]||0;if(weight>expressionWeight){expression=expressionKey.slice(4).toLowerCase();expressionWeight=weight;}
  }
  const speaking=Math.max(0,Math.min(1,pose.speaking===undefined?(expression==='talk'?1:0):pose.speaking));
  const emotionalSpeech=expression&&expression!=='talk'&&expression!=='sleep';
  // Talking uses the emotion's eyes/brows with a clean closed-mouth base.
  // The separate speech channel keeps lip movement alive for every emotion.
  const aligned=name+'_russell_'+(speaking>.001?'talk_':'')+(expression&&expression!=='talk'?expression:'neutral');
  const fallback=speaking>.001?(emotionalSpeech?name+'_talk_'+expression:name+'_talk'):(expression?name+'_'+expression:name);
  const emotion=expression&&expression!=='talk'?expression:'neutral';
  const emotionalMouth=name+'_emouth_'+emotion,cleanSpeech=name+'_espeech_'+emotion;
  // Preserve the five explicitly approved combinations exactly. Other faces
  // return to the original simple speech channel; only smiles get new art.
  const approved=emotion==='displeased'||(cfg.prefix==='front'&&['proud','angry'].includes(emotion));
  const smileFamily=approved?null:({happy:'cheerful',excited:'cheerful',relieved:'gentle',calm:'gentle',proud:'smirk'}[emotion]||null);
  const hasEmotionalMouth=speaking>.001&&(approved||emotion==='hurt')&&this.textures[emotionalMouth]&&this.textures[cleanSpeech];
  const hasSmile=speaking>.001&&smileFamily&&this.textures[name+'_smile_'+smileFamily+'_closed']&&this.textures[cleanSpeech];
  const mouth=Math.max(0,Math.min(1,pose.mouthOpen||0));
  const speechBlend=hasEmotionalMouth?speaking*M.smoothstep(mouth/.28):0;
  const restingFace=name+'_russell_'+emotion;
  let faceTexture=hasEmotionalMouth?restingFace:hasSmile?cleanSpeech:this.textures[aligned]?aligned:(this.textures[fallback]?fallback:name);
  const gaze=emotion==='anxious'&&this.textures[name+'_gaze_rest'];
  const generic=speaking>.001&&!hasEmotionalMouth&&!hasSmile;
  const genericClean=gaze?name+'_gaze_clean':name+'_generic_clean_'+emotion;
  const genericBlend=generic&&this.textures[genericClean]?speaking*M.smoothstep(mouth/.18):0;
  if(gaze)faceTexture=name+'_gaze_'+(speaking>.001?'talk':'rest');
  // A pause is exactly the original expression, including its painted mouth.
  // Mix the two head textures in one premultiplied-alpha draw so the identical
  // eyes, hair and silhouette never fade or gain opacity as speech starts.
  this.mesh(faceTexture,mapping,opacity,24,28,speechBlend>0?cleanSpeech:genericBlend>0?genericClean:null,speechBlend||genericBlend);
  if(gaze){
   // Short eye movements separated by uneven holds: the painted irises move,
   // while the lids, brows and head stay exactly where the expression put them.
   const phase=((time%4.7)+4.7)%4.7;
   const look=M.smoothstep((phase-.58)/.23)*(1-M.smoothstep((phase-2.47)/.28));
   for(let eye=0;eye<2;eye++){
    const iris=name+'_anxious_iris_'+eye,travel=P[iris].travel;
    this.mesh(iris,p=>mapping({x:p.x+travel*look,y:p.y}),opacity,4,6);
   }
  }
  if(hasEmotionalMouth&&speechBlend>0){
   const [mx,my]=P[emotionalMouth].mouthPivot;
   // The opening mouth only becomes visible during a syllable. At the end it
   // gives way to the actual painted resting mouth, never a flattened line.
   const contours={happy:1.6,excited:1.7,proud:.5,relieved:1.1,calm:.1,anxious:-.2,hurt:-1.3,displeased:-.8,distressed:-1.5,sad:-1.7,depressed:-.9,tired:0,angry:-.7,scared:0,neutral:.2,thinking:.1};
   const halfWidth=(P[emotionalMouth].mouthSize||[26,20])[0]/2;
   this.mesh(emotionalMouth,p=>{
    const u=Math.max(-1,Math.min(1,(p.x-mx)/halfWidth));
    let closed=(contours[emotion]||0)*(1-u*u);
    if(emotion==='proud')closed-=u*1.2;
    if(emotion==='hurt')closed+=.25*Math.sin(u*8+time*5);
    const opening=.055+.945*mouth;
    return mapping({x:mx+(p.x-mx)*(.88+.12*mouth),y:my+closed*(1-mouth)+(p.y-my)*opening});
   },opacity*speechBlend,18,16);
  }else if(hasSmile){
   // Drawn closed, half-open and open smiles share UVs and corner anchors.
   // Interpolate their opening and paint together, instead of bending an
   // unrelated mouth into an emotion or bringing back the original large lip.
   const phases=['closed','half','open'],segment=mouth<.5?0:1;
   const amount=M.smoothstep(mouth*2-segment),prefix=name+'_smile_'+smileFamily+'_';
   const first=prefix+phases[segment],second=prefix+phases[segment+1];
   const a=P[first],b=P[second],[mx,my]=a.mouthPivot,inset=a.uvInset||0;
   const strength=emotion==='excited'?1.1:emotion==='calm'?.78:1;
   const width=mix(a.morphSize[0],b.morphSize[0],amount)*strength;
   const height=mix(a.morphSize[1],b.morphSize[1],amount)*strength;
   this.mesh(first,p=>mapping({x:mx+((p.x/128-inset)/(1-2*inset)-.5)*width,
    y:my-3.5+(p.y/128-inset)/(1-2*inset)*height}),opacity*speaking,8,12,amount>0?second:null,amount);
  }else if(speaking>.001&&mouth>.001){
   const [mx,my]=P[name+'_mouth'].mouthPivot;
   this.mesh(name+'_mouth',p=>mapping({x:mx+(p.x-mx)*(.75+.25*mouth),y:my+(p.y-my)*(.16+.84*mouth)}),opacity*speaking*M.smoothstep(mouth/.18),12,20);
  }
  const blink=pose.blink;
  const matchedBlink=name+'_blink_'+emotion;
  if(blink>.001&&this.textures[matchedBlink]){
   if(!['happy','distressed','sleep'].includes(emotion))draw(matchedBlink,opacity*blink);
  }else if(blink>.001){const neutral=expression||speaking>.001?0:opacity,half=name+'_half',closed=name+'_closed';if(this.textures[half]){
    if(blink<.5)draw(half,neutral*blink*2);
    else{draw(half,neutral);draw(closed,neutral*(blink-.5)*2);}
   }else draw(closed,neutral*blink);
   const expressive=(expression&&!['happy','distressed','sleep'].includes(expression))||(!expression&&speaking>.001)?1:0;
   const blinkTexture=this.textures[name+'_russell_expression_blink']?name+'_russell_expression_blink':name+'_expression_blink';
   draw(blinkTexture,opacity*expressive*blink);
  }
  if(root.CloudyEmotionFX&&this.emotionEffects!==false)root.CloudyEmotionFX.draw(this,cfg,pose,time,mapping,opacity);
 }
 renderView(cfg,pose,opacity,time=0){
  // Air poses keep the near arm fully in front of the head, including its hair.
  // Both frontal arms share this depth. Switch draw order without alpha mixing
  // so a moving hand never becomes translucent as it crosses the face.
  const airInFront=(pose.airArms||0)>.001;
  // A frontal view has two arms at the same depth. Only side views place the
  // far arm behind the torso; otherwise one front sleeve disappears in clothes.
  if(cfg.prefix!=='front')this.limb(cfg,1,'arm',pose,opacity);
  this.limb(cfg,1,'leg',pose,opacity);this.limb(cfg,0,'leg',pose,opacity);
  const [i,x,y,s]=cfg.body,location=this.bodyPoint({x:180,y:250},pose);
  this.drawSprite(key(cfg.prefix,i),{x,y},location,s,pose.lean,opacity);
  if(cfg.prefix==='front'&&!airInFront)this.limb(cfg,1,'arm',pose,opacity);
  // A waving arm is one opaque surface throughout lifting and lowering too.
  // Blending two depth orders made the sleeve and palm translucent over hair.
  const waveInFront=(cfg.prefix!=='front'&&pose.waveSideGesture!==undefined?pose.waveSideGesture:pose.waveGesture||0)>.001;
  // Side greetings turn the forearm toward the viewer. The upper sleeve stays
  // at the shoulder depth, so it cannot paint over the lower edge of the hair.
  const splitWave=cfg.prefix!=='front'&&waveInFront&&root.CloudySideWaveSkinning
   &&(pose.waveSideGesture||0)>.002
   &&this.textures[key(cfg.prefix,cfg.arms[0].i)+'_connected_wave_cloth']
   &&this.textures[key(cfg.prefix,cfg.arms[0].i)+'_connected_wave_tag'];
  const handInFront=airInFront||waveInFront?1:Math.max(0,Math.min(1,pose.thinkGesture||0));
  if(handInFront<1)this.limb(cfg,0,'arm',pose,opacity*(1-handInFront));
  if(splitWave)this.limb(cfg,0,'arm',pose,opacity,'upper');
  this.face(cfg,pose,opacity,time);
  if(cfg.prefix==='front'&&airInFront)this.limb(cfg,1,'arm',pose,opacity);
  if(handInFront>.001)this.limb(cfg,0,'arm',pose,opacity*handInFront,splitWave?'forearm':'all');
 }
 effects(pose,time){
  const thinking=Math.max(0,Math.min(1,pose.thinkGesture||0)),sleep=Math.max(0,Math.min(1,pose.exprSleep||0));
  if(thinking>.001)this.drawSprite('fx_question',{x:64,y:64},this.bodyPoint({x:314,y:83+3*Math.sin(time*2.1)},pose),.42+Math.sin(time*2.1)*.025,5*Math.sin(time*1.6),thinking);
  if(sleep>.001)for(let i=0;i<5;i++){
   const phase=((time/3.6+i/5)%1+1)%1,alpha=Math.sin(Math.PI*phase)**1.2;
   this.drawSprite(i===0?'fx_Z':'fx_z',{x:64,y:64},this.bodyPoint({x:305+19*phase+3*Math.sin(phase*4),y:160-100*phase},pose),.2+.2*phase,-9+12*phase,sleep*alpha);
  }
 }
 render(pose,yaw=0,time=0,options={}){
  // An explicit action keeps the same cuff present before the lift begins and
  // after it ends. Gesture thresholds control bone mapping, never asset swaps.
  this.action=options.action||null;
  const gl=this.gl;gl.useProgram(this.program);gl.activeTexture(gl.TEXTURE0);gl.enable(gl.BLEND);gl.bindFramebuffer(gl.FRAMEBUFFER,null);gl.viewport(0,0,this.canvas.width,this.canvas.height);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);
  const cfg=yaw<-21?views[0][1]:yaw>21?views[6][1]:views[3][1];
  // Keep a fixed framing throughout each air-action cycle: the character must
  // not shrink and grow with jump height. Blend only when entering/leaving it.
  this.viewZoom=Number.isFinite(pose.framingZoom)?Math.max(.86,Math.min(1,pose.framingZoom)):1-.14*Math.max(0,Math.min(1,pose.airArms||0));
  this.emotionEffects=options.emotionEffects!==false;
  this.renderView(cfg,pose,1,time);
  this.effects(pose,time);
  if(options.companion!==false)this.drawSprite('front_14',{x:791,y:1100},{x:303+3*Math.sin(time*.8),y:220+5*Math.sin(time*1.6)},.19,3*Math.sin(time),1);
 }
}
root.CloudyRenderer=Renderer;
root.CloudyRig={canvas:[360,540],groundY:535,views:views.map(([yaw,rig])=>({yaw,...rig})),joints:{arm:['shoulder','elbow','wrist'],leg:['hip','knee','ankle','toe']}};
})(window);
