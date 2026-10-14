/* One painted cuff mouth, fitted to its sleeve and hinged toward the actual thumb. */
(function(root,factory){
 'use strict';
 const api=factory();
 if(typeof module==='object'&&module.exports)module.exports=api;
 if(root)root.CloudySideCuffFit=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';
 const TAU=2*Math.PI,clamp=x=>Math.max(0,Math.min(1,x));
 const smooth=x=>{x=clamp(x);return x*x*(3-2*x);};
 const finite=p=>p&&Number.isFinite(p.x)&&Number.isFinite(p.y);
 const mix=(a,b,t)=>({x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t});

 /**
  * cuff is the rest-profile cuff with its material phase zero. boundary is the
  * canonical opaque sleeve-mouth polyline in canvas coordinates, ordered along
  * the forearm normal. Unlike the earlier overlapping bow, every proximal cuff
  * vertex follows THIS painted mouth, with only a small filtering overlap.
  *
  * sourceAnchor, sourceAxis and thumbSource use ATLAS coordinates. thumbSource
  * must be an actual anatomical thumb landmark for the active painted hand.
  * It is mandatory: there is no inferred left/right direction fallback.
  * forearmMap and handMap are the existing immutable renderer callbacks.
  *
  * A rigid wrist frame carries one shared opening and rim. During .63 -> .91,
  * the front radial depth hinges toward the mapped thumb by about 1.2 radians.
  * The texture coordinates stay fixed. The surface and its contour themselves
  * move toward the thumb; neither color replacement nor a UV half-turn stands
  * in for that motion. The entire sleeve seam remains fixed during this hinge.
  */
 function create(options){
  const cuff=options.cuff,forearmMap=options.forearmMap,handMap=options.handMap;
  const sourceAnchor=options.sourceAnchor,sourceAxis=options.sourceAxis,thumbSource=options.thumbSource;
  const boundary=options.boundary,overlap=options.overlap===undefined?1:options.overlap;
  if(!cuff||!finite(sourceAnchor)||!finite(sourceAxis)||!finite(thumbSource)
   ||typeof forearmMap!=='function'||typeof handMap!=='function') {
   throw new TypeError('The cuff requires unchanged wrist maps and an actual thumbSource atlas landmark');
  }
  if(!Array.isArray(boundary)||boundary.length<2||!Number.isFinite(overlap)||overlap<0) {
   throw new RangeError('The canonical opaque sleeve mouth and a nonnegative overlap are required');
  }
  const sourceLength=Math.hypot(sourceAxis.x,sourceAxis.y);
  if(!(sourceLength>1e-8))throw new RangeError('The source wrist axis must have positive length');
  const sourceDirection={x:sourceAxis.x/sourceLength,y:sourceAxis.y/sourceLength};
  const source=(along)=>({x:sourceAnchor.x+sourceDirection.x*along,y:sourceAnchor.y+sourceDirection.y*along});
  const gesture=clamp(options.gesture===undefined?(options.progress||0):options.gesture);
  const tuck=smooth((gesture-.2781560742741126)/(.8030863482901613-.2781560742741126));
  const anchor=forearmMap(sourceAnchor),handAnchor=handMap(sourceAnchor);
  const foreAxis=forearmMap(source(8)),handAxis=handMap(source(8)),thumbPoint=handMap(thumbSource);
  if(![anchor,handAnchor,foreAxis,handAxis,thumbPoint].every(finite))throw new RangeError('The mapped wrist and thumb landmarks must be finite');
  const fx=foreAxis.x-anchor.x,fy=foreAxis.y-anchor.y,hx=handAxis.x-handAnchor.x,hy=handAxis.y-handAnchor.y;
  if(!(Math.hypot(fx,fy)>1e-8)||!(Math.hypot(hx,hy)>1e-8))throw new RangeError('The sampled wrist frame must have positive length');
  // One rigid frame for the whole cuff: the hand's local palm-growth gradient
  // must not stretch the front and back lip by different amounts.
  const rawSlant=Math.atan2(hy,hx)-Math.atan2(fy,fx);
  const slant=Math.atan2(Math.sin(rawSlant),Math.cos(rawSlant));
  const handAmount=smooth(gesture/.18),c=Math.cos(slant*handAmount),s=Math.sin(slant*handAmount);
  const carriedAnchor=mix(anchor,handAnchor,handAmount);
  const carry=p=>{const x=p.x-anchor.x,y=p.y-anchor.y;return{x:carriedAnchor.x+c*x-s*y,y:carriedAnchor.y+s*x+c*y};};
  const sectionAxis={x:c*cuff.axis.x-s*cuff.axis.y,y:s*cuff.axis.x+c*cuff.axis.y};
  const sectionNormal={x:-sectionAxis.y,y:sectionAxis.x};
  const center=carry(cuff.openingCenter);
  const thumbVector={x:thumbPoint.x-handAnchor.x,y:thumbPoint.y-handAnchor.y};
  const thumbLength=Math.hypot(thumbVector.x,thumbVector.y);
  if(!(thumbLength>1e-6))throw new RangeError('The anatomical thumb landmark must differ from the wrist anchor');
  const thumbDirection={x:thumbVector.x/thumbLength,y:thumbVector.y/thumbLength};
  const thumbNormalDot=thumbVector.x*sectionNormal.x+thumbVector.y*sectionNormal.y;
  // Continuous, measured radial influence. An edge-on landmark contributes
  // no directional hinge instead of causing an arbitrary side-sign flip.
  const thumbInfluence=thumbNormalDot/Math.hypot(thumbNormalDot,.5);
  const hingeAngle=1.2*tuck*thumbInfluence;
  const cosine=Math.cos(hingeAngle),sine=Math.sin(hingeAngle);
  const theta=u=>TAU*(u-.25);
  const points=boundary.map(p=>{
   if(!finite(p))throw new RangeError('Sleeve-mouth points must be finite');
   return{x:p.x,y:p.y,n:(p.x-cuff.anchor.x)*cuff.normal.x+(p.y-cuff.anchor.y)*cuff.normal.y};
  });
  for(let i=1;i<points.length;i++)if(!(points[i].n>points[i-1].n+1e-8))throw new RangeError('Sleeve-mouth points must increase along the forearm normal');
  const mouth=fraction=>{
   const n=points[0].n+(points.at(-1).n-points[0].n)*clamp(fraction);
   let i=0;while(i<points.length-2&&n>points[i+1].n)i++;
   return mix(points[i],points[i+1],(n-points[i].n)/(points[i+1].n-points[i].n));
  };
  const proximal=u=>{
   const p=mouth((Math.sin(theta(u))+1)/2);
   return{x:p.x-cuff.axis.x*overlap,y:p.y-cuff.axis.y*overlap};
  };
  const section=(u,angle)=>{
   const t=theta(u),radial=Math.sin(t),front=Math.cos(t);
   const n=cuff.radius*radial+cuff.depth*Math.sin(angle)*front;
   const q=-cuff.depth*Math.cos(angle)*front;
   return{x:center.x+sectionNormal.x*n+sectionAxis.x*q,y:center.y+sectionNormal.y*n+sectionAxis.y*q};
  };
  const opening=u=>section(u,hingeAngle);
  const bandMap=p=>{
   const u=p.x/256,v=clamp(p.y/96),top=proximal(u),bottom=opening(u);
   // A coherent ruled cloth surface shares its entire mouth and wrist edge.
   // Both front and back are the same surface; the hand supplies occlusion.
   return mix(top,bottom,v);
  };
  const rimMap=p=>mix(center,opening(p.x/256),1-.12*clamp(p.y/24));
  const hingeWitnessRest=section(.25,0),hingeWitnessCurrent=opening(.25);
  const thumbwardDisplacement=(hingeWitnessCurrent.x-hingeWitnessRest.x)*thumbDirection.x
   +(hingeWitnessCurrent.y-hingeWitnessRest.y)*thumbDirection.y;
  return{...cuff,bandMap,rimMap,opening,openingCenter:center,theta,roll:0,progress:0,proximal,mouth,
   attachmentTop:angle=>proximal(angle/TAU+.25),
   frontRanges:[{min:0,max:128}],backRanges:[{min:128,max:256}],
   rimFrontRanges:[{min:0,max:128}],rimBackRanges:[{min:128,max:256}],
   attachment:{boundary:points.map(({x,y})=>({x,y})),overlap,
    acrossMinimum:points[0].n,acrossMaximum:points.at(-1).n},
   fit:{gesture,tuck,materialPhase:0,hingeAngle,thumbInfluence,thumbNormalDot,thumbPoint,thumbSource,
    thumbDirection,thumbwardDisplacement,hingeWitnessRest,hingeWitnessCurrent,
    openingCenter:center,axis:sectionAxis,normal:sectionNormal,handSlant:slant,handAmount,
    projectedDepthScale:cosine,radialHinge:sine,
    handFrame:{anchor:handAnchor,axisPoint:handAxis},
    openingNegative:opening(0),openingPositive:opening(.5)}};
 }
 return{create};
});
