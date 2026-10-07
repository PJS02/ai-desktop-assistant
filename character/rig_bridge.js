/* Native-Qt planning adapter. The original art, motion and renderer stay intact. */
(function (root) {
  'use strict';
  if (!root.CloudyRenderer || !root.CloudyMotion || !root.CLOUDY_PARTS) {
    throw new Error('Load the original Cloudy rig sources before rig_bridge.js');
  }
  var P = root.CLOUDY_PARTS;
  var copy = function (value) { return JSON.parse(JSON.stringify(value)); };
  var finite = function (value, fallback) { return Number.isFinite(value) ? value : fallback; };
  var textureToken = function (name) { return {name: name}; };

  function recordingGL() {
    var uniforms = {}, bound = {}, unit = 0, vertices = [], commands = [];
    var gl = {
      VERTEX_SHADER: 1, FRAGMENT_SHADER: 2, COMPILE_STATUS: 3, LINK_STATUS: 4,
      TEXTURE_2D: 5, TEXTURE0: 100, TEXTURE1: 101, TEXTURE2: 102, TEXTURE3: 103,
      ARRAY_BUFFER: 6, DYNAMIC_DRAW: 7, FLOAT: 8, TRIANGLES: 9, BLEND: 10,
      ONE: 11, ONE_MINUS_SRC_ALPHA: 12, UNPACK_PREMULTIPLY_ALPHA_WEBGL: 13,
      COLOR_BUFFER_BIT: 14,
      createShader: function () { return {}; }, shaderSource: function () {},
      compileShader: function () {}, getShaderParameter: function () { return true; },
      getShaderInfoLog: function () { return ''; }, createProgram: function () { return {}; },
      attachShader: function () {}, linkProgram: function () {},
      getProgramParameter: function () { return true; }, getProgramInfoLog: function () { return ''; },
      useProgram: function () {}, getAttribLocation: function (_, name) { return name; },
      getUniformLocation: function (_, name) { return name; },
      uniform1i: function (name, value) { uniforms[name] = value; },
      uniform1f: function (name, value) { uniforms[name] = value; },
      uniform2f: function (name, a, b) { uniforms[name] = [a, b]; },
      uniform3f: function (name, a, b, c) { uniforms[name] = [a, b, c]; },
      createBuffer: function () { return {}; }, bindBuffer: function () {},
      bufferData: function (_, data) {
        vertices = root.CLOUDY_BINARY_MESHES ? data : Array.prototype.slice.call(data);
      },
      enableVertexAttribArray: function () {}, vertexAttribPointer: function () {},
      activeTexture: function (value) { unit = value - gl.TEXTURE0; },
      bindTexture: function (_, value) { bound[unit] = value ? value.name : null; },
      enable: function () {}, blendFunc: function () {}, pixelStorei: function () {},
      bindFramebuffer: function () {}, viewport: function () {}, clearColor: function () {},
      clear: function () { commands = []; },
      drawArrays: function (_, first, count) {
        if (vertices.length !== count * 4) throw new Error('Unexpected original vertex layout');
        commands.push({
          vertices: vertices, vertexCount: count, stride: 4,
          base: bound[0], replacement: bound[1],
          bodyNegativeLower: bound[2], bodyNegativeUpper: bound[3],
          opacity: finite(uniforms.opacity, 1),
          replacementAmount: finite(uniforms.replacementAmount, 0),
          bodyBlendEnabled: finite(uniforms.bodyBlendEnabled, 0),
          bodyPositiveWeight: finite(uniforms.bodyPositiveWeight, 0),
          sourceClipEnabled: finite(uniforms.sourceClipEnabled, 0),
          sourceClipAxis: (uniforms.sourceClipAxis || [0, 0, 0]).slice(),
          sourceClipBounds: (uniforms.sourceClipBounds || [0, 0]).slice()
        });
      },
      result: function () { return commands; }
    };
    return gl;
  }

  // Capture the original Canvas2D recipe. Qt renders these commands once into
  // effect textures; the original renderer still places and animates them.
  function recordingCanvas() {
    var canvas = {width: 300, height: 150, commands: []};
    var state = {lineCap: 'butt', lineJoin: 'miter', lineWidth: 1,
      strokeStyle: '#000000', fillStyle: '#000000', globalAlpha: 1,
      globalCompositeOperation: 'source-over', font: '10px sans-serif',
      textAlign: 'start', textBaseline: 'alphabetic'};
    var currentPath = [], saved = [];
    var context = {};
    Object.keys(state).forEach(function (key) {
      Object.defineProperty(context, key, {get: function () { return state[key]; },
        set: function (value) { state[key] = value; }});
    });
    ['moveTo', 'lineTo', 'quadraticCurveTo', 'bezierCurveTo', 'arc', 'ellipse', 'closePath', 'rect']
      .forEach(function (op) { context[op] = function () {
        currentPath.push({op: op, args: Array.prototype.slice.call(arguments)});
      }; });
    context.beginPath = function () { currentPath = []; };
    ['fill', 'stroke'].forEach(function (op) { context[op] = function () {
      canvas.commands.push({op: op, path: copy(currentPath), state: copy(state)});
    }; });
    ['fillText', 'strokeText', 'fillRect', 'clearRect'].forEach(function (op) {
      context[op] = function () {
        canvas.commands.push({op: op, args: Array.prototype.slice.call(arguments), state: copy(state)});
      };
    });
    context.save = function () { saved.push(copy(state)); };
    context.restore = function () { if (saved.length) state = saved.pop(); };
    context.drawImage = function (image) {
      canvas.commands.push({op: 'drawImage', image: image.name,
        args: Array.prototype.slice.call(arguments, 1), state: copy(state)});
    };
    function gradient(kind, args) {
      return {kind: kind, args: args, stops: [], addColorStop: function (offset, color) {
        this.stops.push([offset, color]);
      }};
    }
    context.createLinearGradient = function () {
      return gradient('linear', Array.prototype.slice.call(arguments));
    };
    context.createRadialGradient = function () {
      return gradient('radial', Array.prototype.slice.call(arguments));
    };
    // Pixel-dependent shade is exported as the exact original formula below.
    // Zero source alpha lets createSprites finish without a DOM or PNG decode.
    context.getImageData = function (_, __, width, height) {
      return {width: width, height: height, data: new Uint8ClampedArray(width * height * 4)};
    };
    context.putImageData = function () { canvas.commands.push({op: 'originalShadePixels'}); };
    canvas.getContext = function () { return context; };
    return canvas;
  }

  var recipes, effectParts;
  function prepareEffects() {
    if (recipes) return;
    recipes = {}; effectParts = {};
    var priorDocument = root.document;
    root.document = {createElement: function (tag) {
      if (tag !== 'canvas') throw new Error('Unexpected effect element: ' + tag);
      return recordingCanvas();
    }};
    try {
      var heads = {};
      ['front', 'left', 'right'].forEach(function (direction) {
        var name = direction + '_00', part = P[name];
        heads[name] = {name: name, width: part.size[0], height: part.size[1]};
      });
      var sprites = root.CloudyEmotionFX ? root.CloudyEmotionFX.createSprites(heads, P) : {};
      Object.keys(sprites).forEach(function (name) {
        var image = sprites[name];
        var recipe = {width: image.width, height: image.height, commands: image.commands};
        if (name.indexOf('fx_shade_') === 0) {
          var direction = name.slice('fx_shade_'.length);
          recipe.commands = [{op: 'originalShade', head: direction + '_00',
            bbox: P[direction + '_00'].bbox.slice(),
            anchor: root.CloudyEmotionFX.anchors[direction].shade.slice()}];
        }
        recipes[name] = recipe;
      });
      [['fx_question', '?'], ['fx_Z', 'Z'], ['fx_z', 'z']].forEach(function (pair) {
        var image = recordingCanvas(); image.width = 128; image.height = 128;
        var ctx = image.getContext('2d');
        ctx.font = 'bold 96px "Trebuchet MS", sans-serif'; ctx.textAlign = 'center';
        ctx.textBaseline = 'middle'; ctx.lineJoin = 'round'; ctx.lineWidth = 9;
        ctx.strokeStyle = '#f8fffd'; ctx.fillStyle = '#65b7ad';
        ctx.strokeText(pair[1], 64, 67); ctx.fillText(pair[1], 64, 67);
        recipes[pair[0]] = {width: 128, height: 128, commands: image.commands};
      });
      Object.keys(recipes).forEach(function (name) {
        effectParts[name] = {bbox: [0, 0, recipes[name].width, recipes[name].height],
          size: [recipes[name].width, recipes[name].height], generated: true};
      });
    } finally {
      if (priorDocument === undefined) delete root.document;
      else root.document = priorDocument;
    }
  }

  var renderer, gl, transition, transitionSignature;
  function prepareRenderer() {
    if (renderer) return;
    prepareEffects();
    gl = recordingGL();
    renderer = new root.CloudyRenderer({width: 720, height: 1080,
      getContext: function () { return gl; }});
    renderer.parts = Object.assign({}, P, effectParts);
    // Availability follows metadata, not native GPU residency. Missing cached
    // images must not alter .every(), fallback selection or hand/cuff geometry.
    renderer.textures = Object.create(null);
    Object.keys(renderer.parts).forEach(function (name) { renderer.textures[name] = textureToken(name); });
  }

  function sample(state) {
    state = state || {};
    var action = typeof state.action === 'string' ? state.action : 'idle';
    var time = finite(state.time, 0), options = {};
    ['emotion', 'speaking', 'speechTime', 'walkAmount'].forEach(function (key) {
      if (state[key] !== undefined) options[key] = state[key];
    });
    var pose = root.CloudyMotion.pose(action, time, options);
    var originalPose = copy(pose), adjustment = 0;
    if (state.externalPhysics === true) {
      if (Number.isFinite(state.externalRootHeight)) adjustment = -state.externalRootHeight;
      else if (action === 'jump') adjustment = 62 * pose.airborne;
      else if (action === 'fall') adjustment = 29;
      else if (action === 'hovering') adjustment = 24;
      pose.bodyY += adjustment;
      var controlledJump = state.jumpActive === true && (action === 'jump' || action === 'fall');
      if (controlledJump || action === 'land') {
        // Host physics moves the whole character. Keep the relaxed arm pose
        // through takeoff, descent and landing instead of the panic fall cycle.
        var rest = root.CloudyMotion.pose('idle', time, options);
        ['armNear', 'armFar', 'elbowNear', 'elbowFar', 'wristNear', 'wristFar',
          'idleGesture', 'airArms', 'framingZoom'].forEach(function (key) { pose[key] = rest[key]; });
        if (controlledJump) {
          ['bodyX', 'bodyY', 'lean', 'headAngle', 'airborne',
            'footNearX', 'footNearY', 'footNearAngle',
            'footFarX', 'footFarY', 'footFarAngle'].forEach(function (key) { pose[key] = rest[key]; });
          adjustment = pose.bodyY - originalPose.bodyY;
        }
      }
      // Air poses already fit the authored stage. Host interactions must keep
      // the same display scale as walking/idle rather than zooming out by 14%.
      pose.framingZoom = 1;
    }
    if (Number.isFinite(state.blink) && state.blink >= 0) pose.blink = Math.max(0, Math.min(1, state.blink));
    if (state.smooth === true) {
      var signature = [action, state.emotion, Boolean(state.speaking)].join('|');
      if (!transition) transition = new root.CloudyMotion.PoseTransition(pose);
      if (signature !== transitionSignature) transition.retarget(pose);
      transitionSignature = signature;
      pose = transition.step(pose, Math.max(0.001, Math.min(0.1, finite(state.dt, 1 / 30))));
    }
    return {action: action, time: time, pose: pose, originalPose: originalPose,
      externalRootHeightAdjustment: adjustment};
  }

  function plan(state) {
    state = state || {}; prepareRenderer();
    var frame = sample(state), yaw = finite(state.yaw, 0);
    renderer.render(frame.pose, yaw, frame.time, {
      action: frame.action, emotionEffects: state.emotionEffects,
      companion: state.companion
    });
    var commands = gl.result(), required = Object.create(null);
    var left = Infinity, top = Infinity, right = -Infinity, bottom = -Infinity;
    commands.forEach(function (command) {
      [command.base, command.replacement, command.bodyNegativeLower, command.bodyNegativeUpper]
        .forEach(function (name) { if (name) required[name] = true; });
      // Character parts only: floating companions and emotion effects do not
      // enlarge the body box. Use the very meshes submitted for this frame.
      command.characterPart = command.opacity > 0 && /^(front|left|right)_(0\d|1[0-3])(?:_|$)/.test(command.base || '');
      if (command.characterPart) {
        for (var i = 0; i < command.vertices.length; i += 4) {
          left = Math.min(left, command.vertices[i]); top = Math.min(top, command.vertices[i + 1]);
          right = Math.max(right, command.vertices[i]); bottom = Math.max(bottom, command.vertices[i + 1]);
        }
      }
    });
    return {pose: frame.pose, originalPose: frame.originalPose,
      externalRootHeightAdjustment: frame.externalRootHeightAdjustment,
      action: frame.action, time: frame.time, yaw: yaw,
      logicalSize: [360, 540], groundY: root.CloudyRig.groundY,
      characterBounds: Number.isFinite(left) ? [left, top, right, bottom] : null,
      commands: commands, requiredTextures: Object.keys(required)};
  }

  root.CloudyRigBridge = {
    plan: plan, sample: sample,
    effectRecipes: function () { prepareEffects(); return recipes; },
    effectMetadata: function () { prepareEffects(); return effectParts; },
    textureMetadata: function (name) {
      prepareEffects(); var part = P[name] || effectParts[name];
      return part ? copy(part) : null;
    },
    availableTextureCount: function () { prepareRenderer(); return Object.keys(renderer.textures).length; }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
