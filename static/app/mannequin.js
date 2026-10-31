import * as THREE from '/static/vendor/three/three.module.js';
import { waistReference } from './body-shape.js';

const cache = new Map();
export function loadMannequin(kind = 'male') {
  if (!['male', 'female', 'male-fit', 'female-fit'].includes(kind)) throw Error('Unknown mannequin');
  if (!cache.has(kind)) cache.set(kind, fetch(`/static/models/mannequin/${kind}.glb`).then(async response => {
    if (!response.ok) throw Error(`Mannequin ${response.status}`);
    const buffer = await response.arrayBuffer(), view = new DataView(buffer);
    if (view.getUint32(0, true) !== 0x46546c67) throw Error('Invalid mannequin');
    const length = view.getUint32(12, true);
    const g = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 20, length)));
    const start = 20 + length + 8;
    const primitive = g.meshes[0].primitives[0];
    function read(index, Type) {
      const a = g.accessors[index], b = g.bufferViews[a.bufferView];
      const width = a.type === 'VEC3' ? 3 : 1;
      return new Type(buffer, start + (b.byteOffset || 0) + (a.byteOffset || 0), a.count * width).slice();
    }
    const positions = read(primitive.attributes.POSITION, Float32Array);
    return { positions, indices: read(primitive.indices, Uint32Array), reference: waistReference(positions) };
  }).catch(error => { cache.delete(kind); throw error; }));
  return cache.get(kind);
}

export function mannequinGeometry(data) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(data.positions.slice(), 3));
  geometry.setIndex(new THREE.BufferAttribute(data.indices, 1));
  geometry.computeVertexNormals();
  return geometry;
}
export function mannequinMaterial() {
  return new THREE.MeshStandardMaterial({ color: '#c2beb3', roughness: .69, metalness: .035 });
}
