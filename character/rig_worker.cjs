'use strict';
// Local math-only V8 worker. No DOM, network, image decoding or browser engine.
const fs = require('fs'), path = require('path'), vm = require('vm');
const crypto = require('crypto'), readline = require('readline');
const rigRoot = path.resolve(process.argv[2]);
const files = ['textures/parts.js', 'motion.js', 'limb-girth.js', 'emotion-fx.js',
  'side-wave-skinning.js', 'side-cuff.js', 'side-cuff-roll.js',
  'side-cuff-attachment.js', 'side-cuff-motion.js', 'side-cuff-art.js',
  'side-cuff-fit.js', 'renderer.js'];
const context = {CLOUDY_BINARY_MESHES: true};
context.window = context;
context.globalThis = context;
vm.createContext(context);
const hashes = {};
for (const relative of files) {
  const raw = fs.readFileSync(path.join(rigRoot, relative));
  hashes[relative] = crypto.createHash('sha256').update(raw).digest('hex');
  vm.runInContext(raw.toString('utf8').replace(/^\uFEFF/, ''), context, {filename: relative});
}
vm.runInContext(fs.readFileSync(path.join(__dirname, 'rig_bridge.js'), 'utf8'), context,
  {filename: 'rig_bridge.js'});
const bridge = context.CloudyRigBridge;
function send(result) {
  const chunks = [];
  let length = 0;
  if (result && result.commands) {
    result.commands = result.commands.map(command => {
      const data = command.vertices;
      const bytes = Buffer.from(data.buffer, data.byteOffset, data.byteLength);
      const out = {...command, vertexOffset: length, vertexByteLength: bytes.length};
      delete out.vertices;
      chunks.push(bytes);
      length += bytes.length;
      return out;
    });
  }
  const header = Buffer.from(JSON.stringify({result, binaryLength: length}), 'utf8');
  const prefix = Buffer.alloc(4);
  prefix.writeUInt32LE(header.length);
  process.stdout.write(prefix);
  process.stdout.write(header);
  for (const chunk of chunks) process.stdout.write(chunk);
}
const input = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
input.on('line', line => {
  try {
    const request = JSON.parse(line);
    let result;
    switch (request.op) {
      case 'init': result = {parts: context.CLOUDY_PARTS, hashes,
        effects: bridge.effectMetadata(), recipes: bridge.effectRecipes()}; break;
      case 'plan': result = bridge.plan(request.state || {}); break;
      case 'sample': result = bridge.sample(request.state || {}); break;
      case 'metadata': result = bridge.textureMetadata(request.name); break;
      case 'stats': result = {rss: process.memoryUsage().rss,
        heapUsed: process.memoryUsage().heapUsed}; break;
      default: throw new Error('Unknown rig operation');
    }
    send(result);
  } catch (error) {
    send({workerError: String(error.stack || error)});
  }
});
input.on('close', () => process.exit(0));
