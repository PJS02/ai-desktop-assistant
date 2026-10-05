/* A sleeve-attached cuff section follows the reviewed painted hand. */
(function (root, factory) {
  'use strict';
  const attachment = typeof module === 'object' && module.exports
    ? require('./side-cuff-attachment.js') : root.CloudySideCuffAttachment;
  const api = factory(attachment);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.CloudySideCuffMotion = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (Attachment) {
  'use strict';
  const TAU = 2 * Math.PI;
  const clamp = value => Math.max(0, Math.min(1, value));
  const smooth = value => { const x = clamp(value); return x * x * (3 - 2 * x); };
  const mix = (a, b, t) => ({x:a.x+(b.x-a.x)*t, y:a.y+(b.y-a.y)*t});
  const finite = point => point && Number.isFinite(point.x) && Number.isFinite(point.y);

  function ranges(angle, front, width) {
    const start = front ? -Math.PI / 2 : Math.PI / 2, result = [];
    for (let turn=-2; turn<=2; turn++) {
      const low = Math.max(0, (start + turn * TAU - angle) / TAU + .25);
      const high = Math.min(1, (start + Math.PI + turn * TAU - angle) / TAU + .25);
      if (high > low + 1e-10) result.push({min:low*width,max:high*width});
    }
    return result.sort((a,b)=>a.min-b.min);
  }

  /**
   * cuff is the original rest-profile cuff (progress zero). boundary is its
   * opaque sleeve mouth mapped through forearmMap, in canvas coordinates.
   * sourceAnchor/sourceAxis are ATLAS coordinates; handMap and forearmMap both
   * take atlas points and return canvas points. Neither callback is modified.
   * progress is CloudyMotion.sideWaveRoll(gesture), the actual bend-plane phase,
   * not the earlier arm-lift amount and not a body-dot-selected paint phase.
   *
   * The section rolls once in a fixed anatomical direction. Its projected
   * width, depth and lip tilt change, so the opening moves as a physical shape,
   * rather than merely relabelling a rotationally symmetric UV cylinder. Carry
   * that section into the existing hand map. Only the distal band changes; its
   * entire proximal perimeter remains inside the original opaque sleeve mouth.
   */
  function create(options) {
    const cuff=options.cuff,forearmMap=options.forearmMap,handMap=options.handMap;
    const sourceAnchor=options.sourceAnchor,sourceAxis=options.sourceAxis;
    if (!Attachment || !cuff || !finite(sourceAnchor) || !finite(sourceAxis)
      || typeof forearmMap!=='function' || typeof handMap!=='function') {
      throw new TypeError('A rest cuff, atlas wrist frame, and the existing forearm/hand maps are required');
    }
    const length=Math.hypot(sourceAxis.x,sourceAxis.y);
    if (!(length>1e-8)) throw new RangeError('The source forearm axis must have positive length');
    const axis={x:sourceAxis.x/length,y:sourceAxis.y/length};
    const normal={x:-axis.y,y:axis.x};
    const source=(along,across)=>({x:sourceAnchor.x+axis.x*along+normal.x*across,
      y:sourceAnchor.y+axis.y*along+normal.y*across});
    const attached=Attachment.create({cuff,boundary:options.boundary,overlap:options.overlap});
    const progress=clamp(options.progress||0),gesture=clamp(options.gesture===undefined?progress:options.gesture);
    const sign=options.side==='left'?-1:1;
    const angle=sign*Math.PI*progress;
    const radialDepth=.92;
    // The ellipse's material orientation is transported continuously through
    // its actual projection. It never changes sign at a torso-dot crossing.
    const projectedAngle=Math.atan2(radialDepth*Math.sin(angle),Math.cos(angle));
    const projection=Math.hypot(Math.cos(angle),radialDepth*Math.sin(angle));
    const fold=smooth(progress),widthScale=Math.max(.90,projection*(1-.06*fold));
    const depthScale=1+.18*fold,lipTilt=sign*cuff.depth*.35*fold;
    const handAmount=smooth(gesture/.18);
    const anchor=forearmMap(sourceAnchor),a=forearmMap(source(8,0)),n=forearmMap(source(0,8));
    const ax={x:(a.x-anchor.x)/8,y:(a.y-anchor.y)/8},nx={x:(n.x-anchor.x)/8,y:(n.y-anchor.y)/8};
    const determinant=ax.x*nx.y-ax.y*nx.x;
    if (!finite(anchor)||!Number.isFinite(determinant)||Math.abs(determinant)<1e-9) {
      throw new RangeError('The approved forearm wrist map must be finite and invertible');
    }
    const inverse=point=>{
      const dx=point.x-anchor.x,dy=point.y-anchor.y;
      let along=(dx*nx.y-dy*nx.x)/determinant,across=(ax.x*dy-ax.y*dx)/determinant;
      // Girth varies with axial position. Invert that existing map locally,
      // instead of applying its wrist/palm gradient a second time to the cuff.
      for(let i=0;i<6;i++) {
        const p=forearmMap(source(along,across)),ex=point.x-p.x,ey=point.y-p.y;
        if(Math.hypot(ex,ey)<1e-7)break;
        const h=.1,pa=forearmMap(source(along+h,across)),pn=forearmMap(source(along,across+h));
        const ux=(pa.x-p.x)/h,uy=(pa.y-p.y)/h,vx=(pn.x-p.x)/h,vy=(pn.y-p.y)/h,d=ux*vy-uy*vx;
        if(!Number.isFinite(d)||Math.abs(d)<1e-9)throw new RangeError('The forearm map becomes singular at the cuff');
        along+=(ex*vy-ey*vx)/d;across+=(ux*ey-uy*ex)/d;
      }
      return source(along,across);
    };
    const carry=point=>handAmount===0?point:mix(point,handMap(inverse(point)),handAmount);
    const center={x:cuff.openingCenter.x,y:cuff.openingCenter.y};
    const openingCenter=carry(center),openingCache=new Map();
    const theta=u=>TAU*(u-.25)+projectedAngle;
    const opening=u=>{
      // Identical periodic endpoints also eliminate subpixel mesh seam drift.
      const periodic=((u%1)+1)%1,key=Math.round(periodic*1e12)/1e12;
      if(openingCache.has(key))return openingCache.get(key);
      const t=theta(periodic),across=cuff.radius*widthScale*Math.sin(t);
      const along=-cuff.depth*depthScale*Math.cos(t)+lipTilt*Math.sin(t);
      const point=carry({x:center.x+cuff.normal.x*across+cuff.axis.x*along,
        y:center.y+cuff.normal.y*across+cuff.axis.y*along});
      openingCache.set(key,point);return point;
    };
    const proximal=u=>attached.proximal(u+projectedAngle/TAU);
    const bandMap=point=>{
      const u=point.x/256,v=clamp(point.y/96),shifted={x:point.x+projectedAngle/TAU*256,y:point.y};
      if(v===0)return proximal(u);
      if(v===1)return opening(u);
      const base=attached.bandMap(shifted),oldOpening=cuff.opening(u+projectedAngle/TAU);
      const target=opening(u),amount=smooth(v);
      return {x:base.x+(target.x-oldOpening.x)*amount,y:base.y+(target.y-oldOpening.y)*amount};
    };
    const rimMap=point=>{
      const edge=opening(point.x/256),fraction=1-.12*clamp(point.y/24);
      return mix(openingCenter,edge,fraction);
    };
    const handFrame={anchor:handMap(sourceAnchor),axisPoint:handMap(source(12,0)),
      negative:handMap(source(6,-24)),positive:handMap(source(6,24))};
    return {...attached,bandMap,rimMap,opening,openingCenter,theta,roll:angle,progress,
      proximal,attachmentTop:t=>proximal((t-projectedAngle)/TAU+.25),
      frontRanges:ranges(projectedAngle,true,256),backRanges:ranges(projectedAngle,false,256),
      rimFrontRanges:ranges(projectedAngle,true,256),rimBackRanges:ranges(projectedAngle,false,256),
      motion:{angle,projectedAngle,progress,gesture,sign,widthScale,depthScale,lipTilt,handAmount,handFrame,
        openingCenter,openingNegative:opening(.0-projectedAngle/TAU),openingPositive:opening(.5-projectedAngle/TAU)} };
  }
  return {create};
});
