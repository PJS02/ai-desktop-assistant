/* A one-shot jump, fall, impact and recovery; this never wraps the clock. */
(function(root,factory){
 'use strict';
 const api=factory(typeof module==='object'&&module.exports?require('./motion.js'):root.CloudyMotion);
 if(typeof module==='object'&&module.exports)module.exports=api;
 if(root)root.CloudySequence=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(M){
 'use strict';
 const duration=2.9,apex=.72,contact=1.18,takeoff=.28;
 // Each knot is [seconds, displacement from breathing idle, velocity/second].
 // Sharing the tangent on either side of every knot makes all joints C1.
 function curve(knots,t){
  if(t<=knots[0][0])return knots[0][1];
  for(let i=1;i<knots.length;i++)if(t<knots[i][0]){
   const a=knots[i-1],b=knots[i],d=b[0]-a[0],u=(t-a[0])/d,u2=u*u,u3=u2*u;
   return (2*u3-3*u2+1)*a[1]+(u3-2*u2+u)*d*a[2]+(-2*u3+3*u2)*b[1]+(u3-u2)*d*b[2];
  }
  return knots[knots.length-1][1];
 }
 const tracks={
  bodyY:[[0,0,0],[.18,11,0],[.28,6,-105],[.46,-11,-82],[apex,-22,0],[.98,-11,72],[contact,0,108],[1.37,12,0],[1.73,-2,0],[2.08,0,0]],
  lean:[[0,0,0],[.2,3,0],[.5,-2,0],[.85,-3,0],[contact,1,12],[1.48,3,0],[1.95,-.6,0],[2.25,0,0]],
  headAngle:[[0,0,0],[.24,2,0],[.64,-4,0],[1.05,-2,0],[1.52,3,0],[2.07,-.7,0],[2.45,0,0]],
  armNear:[[0,0,0],[.22,9,0],[.6,-121,0],[.84,-112,30],[1.02,-96,0],[1.18,-108,0],[1.5,-36,200],[1.87,7,0],[2.26,-3,0],[2.72,0,0]],
  armFar:[[0,0,0],[.22,-9,0],[.62,115,0],[.86,103,-30],[1.04,86,0],[1.18,101,0],[1.56,32,-170],[1.94,-6,0],[2.31,3,0],[2.78,0,0]],
  elbowNear:[[0,0,0],[.22,5,0],[.7,33,0],[1.06,46,0],[1.4,28,0],[1.8,17,0],[2.72,0,0]],
  elbowFar:[[0,0,0],[.22,5,0],[.72,29,0],[1.06,40,0],[1.44,26,0],[1.89,14,0],[2.78,0,0]],
  wristNear:[[0,0,0],[.6,-10,0],[.84,6,0],[1.04,-12,0],[1.25,9,0],[1.76,-3,0],[2.6,0,0]],
  wristFar:[[0,0,0],[.63,9,0],[.88,-7,0],[1.08,12,0],[1.31,-8,0],[1.84,3,0],[2.66,0,0]],
  footNearY:[[0,0,0],[takeoff,0,0],[.44,-21,-135],[apex,-49,0],[.98,-19,125],[contact,0,0]],
  footFarY:[[0,0,0],[takeoff,0,0],[.44,-20,-125],[apex,-47,0],[.98,-18,120],[contact,0,0]],
  footNearX:[[0,0,0],[takeoff,0,0],[.72,-9,0],[.94,-13,0],[contact,0,0]],
  footFarX:[[0,0,0],[takeoff,0,0],[.72,8,0],[.94,12,0],[contact,0,0]],
  footNearAngle:[[0,0,0],[takeoff,0,0],[.7,18,0],[.94,-10,0],[contact,0,0]],
  footFarAngle:[[0,0,0],[takeoff,0,0],[.72,-14,0],[.94,8,0],[contact,0,0]]
 };
 const envelope={
  rest:[[0,1,0],[.28,0,0],[1.7,0,0],[duration,1,0]],
  arms:[[0,0,0],[.27,1,0],[1.9,1,0],[duration,0,0]],
  air:[[0,0,0],[takeoff,0,0],[.46,1,0],[.97,1,0],[contact,0,0]]
 };
 function sample(time,options={}){
  const t=Number.isFinite(time)?Math.max(0,time):0;
  let p=M.pose('idle',t);
  // The modest pelvis lift and stronger knee tuck fit the original frame.
  // Preserve idle scale through anticipation, flight and recovery.
  p.framingZoom=1;
  if(t<duration){
   for(const [key,knots]of Object.entries(tracks))p[key]+=curve(knots,t);
   p.idleGesture*=curve(envelope.rest,t);
   p.airArms=curve(envelope.arms,t);
   p.airborne=curve(envelope.air,t);
   // Impact is absorbed with planted soles and a lowered pelvis. Do not add a
   // synthetic blink: the existing breathing clock retains natural blinks.
   if(t>=contact&&t<=1.8)p.blink=0;
  }
  p=M.applySpeech(M.applyEmotion(p,options.emotion),options.speaking,
   options.speechTime===undefined?t:options.speechTime);
  return {pose:p,stage:t<apex?'jump':t<contact?'fall':t<duration?'land':'idle',
   done:t>=duration,idleTime:t};
 }
 return {sample,duration,apex,contact,takeoff};
});
