/* The full painted sleeve tag is one ribbon attached to its original eyelet. */
(function(root,factory){
 'use strict';const api=factory();
 if(typeof module==='object'&&module.exports)module.exports=api;
 if(root)root.CloudySideSleeveTag=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';
 const clamp=v=>Math.max(0,Math.min(1,v));
 const smooth=v=>{v=clamp(v);return v*v*(3-2*v);};
 const mix=(a,b,t)=>({x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t});
 const config={
  left:{anchor:{x:771.70,y:163.30},axis:{x:-.46798,y:.88374},length:76.22,
   forearm:{x:-37,y:103},elbow:{x:791,y:178},thumbSign:-1,mountFrontMin:-69},
  right:{anchor:{x:823.23,y:169.73},axis:{x:.37166,y:.92837},length:63.49,
   forearm:{x:31,y:94},elbow:{x:803,y:177},thumbSign:1,mountFrontMin:-54}
 };
 function create(o){
  const c=config[o.side];if(!c)throw Error('A side-specific painted tag is required');
  const g=clamp(o.gesture||0),activation=smooth(g/.005);
  const fl=Math.hypot(c.forearm.x,c.forearm.y),fa={x:c.forearm.x/fl,y:c.forearm.y/fl};
  const fn={x:-fa.y,y:fa.x},cross={x:c.axis.y,y:-c.axis.x};
  const turn=smooth((g-.04)/.65),roll=1.0*turn,swing=c.thumbSign*.82*turn;
  const sourceAt=l=>({x:c.anchor.x+c.axis.x*l,y:c.anchor.y+c.axis.y*l});
  const mount=o.upperMap(c.anchor),f=o.forearmMap(c.anchor);
  const f1=o.forearmMap(sourceAt(1)),fw=o.forearmMap({x:c.anchor.x+cross.x,y:c.anchor.y+cross.y});
  const lengthScale=Math.hypot(f1.x-f.x,f1.y-f.y),widthScale=Math.hypot(fw.x-f.x,fw.y-f.y);
  const baseAngle=Math.atan2(f1.y-f.y,f1.x-f.x),angle=baseAngle+swing;
  const along={x:Math.cos(angle),y:Math.sin(angle)},across={x:along.y,y:-along.x};
  const projectedWidth=Math.cos(roll),shear=c.thumbSign*.18*Math.sin(roll);
  const plane=(l,w)=>({x:mount.x+along.x*lengthScale*(l+shear*w)+across.x*widthScale*w*projectedWidth,
   y:mount.y+along.y*lengthScale*(l+shear*w)+across.y*widthScale*w*projectedWidth});
  const center=l=>plane(l,0);
  const tagMap=p=>{
   const x=p.x-c.anchor.x,y=p.y-c.anchor.y,l=x*c.axis.x+y*c.axis.y,w=x*cross.x+y*cross.y;
   // The eyelet is the pivot of one complete painted plane. Holding a strip
   // of pixels to a different bone would curl and invert the tag's neck.
   const projected=plane(l,w);
   return mix(o.forearmMap(p),projected,activation);
  };
  return{tagMap,map:tagMap,anchor:c.anchor,mappedAnchor:o.upperMap(c.anchor),
   centerline:Array.from({length:17},(_,i)=>center(c.length*i/16)),
   source:{...c,cross,forearmAxis:fa,forearmNormal:fn},
   surface:{gesture:g,activation,roll,swing,projectedWidth,thumbSign:c.thumbSign,
    joining:'full tag plane pivots at the unchanged upper-hardware eyelet',
    material:'native full frame-zero mint tag, ink, cloud mark and black backing'}};
 }
 return{create,config};
});
