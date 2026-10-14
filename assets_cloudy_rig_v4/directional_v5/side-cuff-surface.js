/* A sewn cuff surface: transported material, shared sleeve seam and wrist rim. */
(function(root,factory){
 'use strict'; const api=factory();
 if(typeof module==='object'&&module.exports)module.exports=api;
 if(root)root.CloudySideCuffSurface=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';
 const TAU=2*Math.PI,clamp=x=>Math.max(0,Math.min(1,x));
 const smooth=x=>{x=clamp(x);return x*x*(3-2*x);};
 const mix=(a,b,t)=>({x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t});
 function create(o){
  const c=o.cuff,anchor=o.forearmMap(o.sourceAnchor),ha=o.handMap(o.sourceAnchor);
  const l=Math.hypot(o.sourceAxis.x,o.sourceAxis.y),sa={x:o.sourceAxis.x/l,y:o.sourceAxis.y/l};
  const sn={x:-sa.y,y:sa.x},sample={x:o.sourceAnchor.x+8*sa.x,y:o.sourceAnchor.y+8*sa.y};
  const fa=o.forearmMap(sample),h=o.handMap(sample);
  const raw=Math.atan2(h.y-ha.y,h.x-ha.x)-Math.atan2(fa.y-anchor.y,fa.x-anchor.x);
  const slant=Math.atan2(Math.sin(raw),Math.cos(raw));
  const gesture=clamp(o.gesture||0),carryAmount=smooth(gesture/.18);
  const cs=Math.cos(slant*carryAmount),ss=Math.sin(slant*carryAmount);
  const carried=mix(anchor,ha,carryAmount);
  const carry=p=>({x:carried.x+cs*(p.x-anchor.x)-ss*(p.y-anchor.y),
   y:carried.y+ss*(p.x-anchor.x)+cs*(p.y-anchor.y)});
  const axis={x:cs*c.axis.x-ss*c.axis.y,y:ss*c.axis.x+cs*c.axis.y};
  const normal={x:-axis.y,y:axis.x},center=carry(c.openingCenter);
  // This sign comes from the actual painted thumb in atlas space. It cannot
  // flip when the forearm crosses the torso or the screen vertical.
  const thumbAcross=(o.thumbSource.x-o.sourceAnchor.x)*sn.x+(o.thumbSource.y-o.sourceAnchor.y)*sn.y;
  if(!Number.isFinite(thumbAcross)||Math.abs(thumbAcross)<1e-5)throw Error('A painted thumb side is required');
  const turn=Math.sign(thumbAcross)*1.05*smooth(gesture/.8030863482901613);
  const eccentricity=.88,topPhase=turn*.30;
  const phase=v=>topPhase+(turn-topPhase)*smooth(v);
  const points=o.boundary.map(p=>({...p,n:(p.x-c.anchor.x)*c.normal.x+(p.y-c.anchor.y)*c.normal.y}));
  const mouth=f=>{
   const n=points[0].n+(points.at(-1).n-points[0].n)*clamp(f);
   let i=0;while(i<points.length-2&&n>points[i+1].n)i++;
   return mix(points[i],points[i+1],(n-points[i].n)/(points[i+1].n-points[i].n));
  };
  const theta=u=>TAU*(u-.25);
  const proximal=u=>{
   const p=mouth((Math.sin(theta(u)+topPhase)+1)/2),overlap=o.overlap===undefined?1.6:o.overlap;
   return{x:p.x-c.axis.x*overlap,y:p.y-c.axis.y*overlap};
  };
  // Rotate an elliptic radial section, including both its side silhouette and
  // axial projection. Unlike a hinged mouth, every circumferential vertex and
  // every material row participates; mint paint and ink share the same map.
  const section=(u,a)=>{
   const t=theta(u),s=Math.sin(t),co=Math.cos(t),ca=Math.cos(a),si=Math.sin(a);
   const n=c.radius*(s*ca+eccentricity*co*si);
   const q=-c.depth*(co*ca-s*si/eccentricity);
   return{x:center.x+normal.x*n+axis.x*q,y:center.y+normal.y*n+axis.y*q};
  };
  const sewnCenter=mouth(.5),bend=Math.sign(thumbAcross)*.28*smooth(gesture/.8030863482901613);
  // The sewn row remains in the sleeve. The broad cloth face progressively
  // turns about that row toward the painted thumb; this is a geometric bend,
  // not only material travel around a symmetric cylinder. Carry the side
  // contours and the complete wrist edge through the same deformation.
  const bendPoint=(p,v)=>{
   const angle=bend*smooth(v/.80),co=Math.cos(angle),si=Math.sin(angle);
   const x=p.x-sewnCenter.x,y=p.y-sewnCenter.y;
   return{x:sewnCenter.x+co*x-si*y,y:sewnCenter.y+si*x+co*y};
  };
  const turnedCenter=bendPoint(center,1);
  const opening=u=>bendPoint(section(u,turn),1);
  const bandMap=p=>{
   const u=p.x/256,v=clamp(p.y/96),a=section(u,topPhase),b=section(u,phase(v));
   const base=mix(proximal(u),a,v),amount=smooth(v);
   return bendPoint({x:base.x+(b.x-a.x)*amount,y:base.y+(b.y-a.y)*amount},v);
  };
  const rimMap=p=>mix(turnedCenter,opening(p.x/256),1-.12*clamp(p.y/24));
  // Visibility is evaluated on each material row. This makes the moving side
  // walls pass behind the unchanged hand rather than keeping rest UV halves
  // arbitrarily in front. The mesh samples an unwrapped half circumference.
  const sourceX=(f,v,front,rim=false)=>{
   const a=rim?turn:phase(v),e=rim?eccentricity:1+(eccentricity-1)*smooth(v);
   const offset=Math.atan2(e*Math.sin(a),Math.cos(a));
   return-offset/TAU+(front?0:.5)+f*.5;
  };
  return{...c,bandMap,rimMap,opening,openingCenter:turnedCenter,proximal,mouth,theta,roll:turn,
   sourceX,frontRanges:[{min:0,max:256}],backRanges:[{min:0,max:256}],
   rimFrontRanges:[{min:0,max:256}],rimBackRanges:[{min:0,max:256}],
   surface:{gesture,turn,bend,topPhase,eccentricity,axis,normal,thumbSource:o.thumbSource,
    thumbPoint:o.handMap(o.thumbSource),thumbAcross,center:turnedCenter,boundary:o.boundary}};
 }
 return{create};
});
