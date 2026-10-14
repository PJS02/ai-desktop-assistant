/* Carry the cuff's inward material turn through the posed forearm frame. */
(function(root,factory){
 'use strict';const api=factory();
 if(typeof module==='object'&&module.exports)module.exports=api;
 if(root)root.CloudySideCuffRoll=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
 'use strict';
 const clamp=x=>Math.max(0,Math.min(1,x));
 const ease=x=>{x=clamp(x);return x*x*x*(10+x*(-15+6*x));};
 function sample(progress,normal,towardBody){
  const dot=normal.x*towardBody.x+normal.y*towardBody.y;
  // At the edge-on crossing neither normal side faces the body. Transport
  // the material through that interval continuously, rather than flipping a
  // rest-view sign after the forearm has turned over.
  const direction=2*ease((dot+12)/24)-1;
  // Stop with a small inward lip still visible. An exact half turn puts the
  // asymmetric painted highlight across the silhouette and hides the inward
  // cue while the wrist is still finishing its rise.
  const angle=Math.PI*.94*clamp(progress)*direction;
  return {angle,progress:Math.abs(angle)/Math.PI,sign:angle<0?-1:1,bodyDot:dot,direction};
 }
 return {sample};
});
