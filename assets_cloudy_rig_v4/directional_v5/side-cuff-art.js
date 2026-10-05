/* Keep the painted .63 cuff profile; tuck its mouth inward without a half-turn. */
(function(root,factory){
 'use strict';
 const attachment=typeof module==='object'&&module.exports?require('./side-cuff-attachment.js'):root.CloudySideCuffAttachment;
 const api=factory(attachment);
 if(typeof module==='object'&&module.exports)module.exports=api;
 if(root)root.CloudySideCuffArt=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(Attachment){
 'use strict';
 const TAU=2*Math.PI,clamp=x=>Math.max(0,Math.min(1,x));
 const smooth=x=>{x=clamp(x);return x*x*(3-2*x);};
 const mix=(a,b,t)=>({x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t});
 const finite=p=>p&&Number.isFinite(p.x)&&Number.isFinite(p.y);

 /**
  * cuff is the painted REST section, with material progress zero. The mapped
  * opaque sleeve boundary anchors its entire proximal edge. sourceAnchor and
  * sourceAxis use atlas coordinates; forearmMap/handMap are the existing maps.
  * Sample one hand orientation around the wrist, then carry the whole cuff
  * opening rigidly. Do not apply the hand's distal growth/flex gradient to each
  * rim vertex. Hand artwork and all approved motion are rendered independently.
  *
  * gesture .278156 -> .803086 is the .63 -> .91 preparation interval. It closes
  * the mouth's depth with a small inward tuck; its material theta is always 0.
  * New front/inner-lip art and the short rear arc are supplied by the renderer.
  */
 function create(options){
  const cuff=options.cuff,forearmMap=options.forearmMap,handMap=options.handMap;
  const sourceAnchor=options.sourceAnchor,sourceAxis=options.sourceAxis;
  if(!Attachment||!cuff||!finite(sourceAnchor)||!finite(sourceAxis)
   ||typeof forearmMap!=='function'||typeof handMap!=='function')throw new TypeError('A rest cuff and its unchanged sleeve/hand maps are required');
  const length=Math.hypot(sourceAxis.x,sourceAxis.y);
  if(!(length>1e-8))throw new RangeError('The source wrist axis must have positive length');
  const axis={x:sourceAxis.x/length,y:sourceAxis.y/length},normal={x:-axis.y,y:axis.x};
  const source=(along,across)=>({x:sourceAnchor.x+axis.x*along+normal.x*across,
   y:sourceAnchor.y+axis.y*along+normal.y*across});
  const gesture=clamp(options.gesture===undefined?(options.progress||0):options.gesture);
  const tuck=smooth((gesture-.2781560742741126)/(.8030863482901613-.2781560742741126));
  const attached=Attachment.create({cuff,boundary:options.boundary,overlap:options.overlap});
  const anchor=forearmMap(sourceAnchor),handAnchor=handMap(sourceAnchor);
  const foreAxis=forearmMap(source(8,0)),handAxis=handMap(source(8,0));
  if(!finite(anchor)||!finite(handAnchor)||!finite(foreAxis)||!finite(handAxis))throw new RangeError('The sampled wrist frame must be finite');
  const fx=foreAxis.x-anchor.x,fy=foreAxis.y-anchor.y,hx=handAxis.x-handAnchor.x,hy=handAxis.y-handAnchor.y;
  if(!(Math.hypot(fx,fy)>1e-8)||!(Math.hypot(hx,hy)>1e-8))throw new RangeError('The sampled wrist frame must have positive length');
  const slant=Math.atan2(hy,hx)-Math.atan2(fy,fx),handAmount=smooth(gesture/.18);
  const c=Math.cos(slant*handAmount),s=Math.sin(slant*handAmount);
  const carriedAnchor=mix(anchor,handAnchor,handAmount);
  const carry=p=>{const x=p.x-anchor.x,y=p.y-anchor.y;return{x:carriedAnchor.x+c*x-s*y,y:carriedAnchor.y+s*x+c*y};};
  const center=carry(cuff.openingCenter),sectionAxis={x:c*cuff.axis.x-s*cuff.axis.y,y:s*cuff.axis.x+c*cuff.axis.y};
  const sectionNormal={x:-sectionAxis.y,y:sectionAxis.x};
  const sideSign=options.side==='left'?-1:1;
  const depthScale=1-.55*tuck,widthScale=1-.025*tuck;
  const inwardShift=.65*tuck*sideSign;
  const openingCenter={x:center.x+sectionNormal.x*inwardShift,y:center.y+sectionNormal.y*inwardShift};
  const theta=u=>TAU*(u-.25);
  const opening=u=>{
   const t=theta(u),n=cuff.radius*widthScale*Math.sin(t),q=-cuff.depth*depthScale*Math.cos(t);
   return{x:openingCenter.x+sectionNormal.x*n+sectionAxis.x*q,y:openingCenter.y+sectionNormal.y*n+sectionAxis.y*q};
  };
  const bandMap=p=>{
   const u=p.x/256,v=clamp(p.y/96);
   if(v===0)return attached.proximal(u);
   if(v===1)return opening(u);
   const base=attached.bandMap(p),old=cuff.opening(u),target=opening(u),amount=smooth(v);
   return{x:base.x+(target.x-old.x)*amount,y:base.y+(target.y-old.y)*amount};
  };
  const rimMap=p=>mix(openingCenter,opening(p.x/256),1-.12*clamp(p.y/24));
  return{...attached,bandMap,rimMap,opening,openingCenter,theta,roll:0,progress:0,
   frontRanges:[{min:0,max:128}],backRanges:[{min:128,max:256}],
   rimFrontRanges:[{min:0,max:128}],rimBackRanges:[{min:128,max:146},{min:238,max:256}],
   art:{tuck,gesture,materialPhase:0,depthScale,widthScale,inwardShift,handSlant:slant,
    handAmount,openingCenter,axis:sectionAxis,normal:sectionNormal,
    openingNegative:opening(0),openingPositive:opening(.5),
    handFrame:{anchor:handAnchor,axisPoint:handAxis}}};
 }
 return{create};
});
