// My body · 3D, for movement: the approved smooth mannequin, with the areas the day's movement works in orange.
// The areas come from the server (coach.areas_worked); here they only paint the surface. No future body is drawn:
// the mannequin is a figure, not a forecast.
import * as THREE from '/static/vendor/three/three.module.js';
import { OrbitControls } from '/static/vendor/three/OrbitControls.js';
import { loadMannequin, mannequinGeometry } from './mannequin.js';

const BASE = new THREE.Color('#c2beb3'), WORK = new THREE.Color('#d9672d');

// Where each area sits on the 1.704 m reference figure, facing +z: heights in metres, |x| and z in metres
function area(x, y, z) {
  const ax = Math.abs(x), found = [];
  const arm = ax > 0.19 && y > 0.72 && y < 1.46;
  if (arm) found.push('arms');
  if (!arm && y < 0.80) found.push('legs');
  if (!arm && y > 0.76 && y < 0.98 && z < -0.01) found.push('glutes');
  if (!arm && y > 0.92 && y < 1.18 && ax < 0.17 && z > -0.02) found.push('core');
  if (!arm && y > 1.15 && y < 1.40 && ax < 0.18 && z > 0.0) found.push('chest');
  if (!arm && y > 0.98 && y < 1.42 && ax < 0.19 && z < 0.0) found.push('back');
  if (y > 1.32 && y < 1.49 && ax > 0.11 && ax < 0.25) found.push('shoulders');
  return found;
}

export async function mountBodyMove(host, { areas = [], figure = 'male', label = '' } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.7));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  host.appendChild(renderer.domElement);
  renderer.domElement.tabIndex = 0;
  renderer.domElement.setAttribute('role', 'img');
  renderer.domElement.setAttribute('aria-label', label);
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight('#f0e8da', '#141b1c', 1.0));
  const key = new THREE.DirectionalLight('#fff4e3', 2.6); key.position.set(-3, 4, 3); scene.add(key);
  const fill = new THREE.DirectionalLight('#e3eaf0', 1.25); fill.position.set(3, 2, 3); scene.add(fill);
  const rim = new THREE.DirectionalLight('#f3e6d1', 2.0); rim.position.set(1.5, 3, -3); scene.add(rim);
  const camera = new THREE.PerspectiveCamera(32, 1, 0.05, 20);
  camera.position.set(0, 0.94, 3.55);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0.91, 0); controls.enablePan = false;
  controls.minDistance = 1.7; controls.maxDistance = 5.5; controls.minPolarAngle = Math.PI * 0.2; controls.maxPolarAngle = Math.PI * 0.78;
  controls.update();  // aim at the figure's middle, not at the floor
  const material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.69, metalness: 0.035 });
  let mesh = null;

  async function show(kind) {
    const data = await loadMannequin(kind);
    const geometry = mannequinGeometry(data), p = geometry.attributes.position, colors = new Float32Array(p.count * 3);
    for (let i = 0; i < p.count; i++) {
      const hit = area(p.getX(i), p.getY(i), p.getZ(i)).some(a => areas.includes(a));
      (hit ? WORK : BASE).toArray(colors, i * 3);
    }
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    if (mesh) { scene.remove(mesh); mesh.geometry.dispose(); }
    mesh = new THREE.Mesh(geometry, material); scene.add(mesh); draw();
  }
  function resize() {
    const w = host.clientWidth || 320, h = host.clientHeight || 460;
    renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); draw();
  }
  function draw() { renderer.render(scene, camera); }
  controls.addEventListener('change', draw);
  new ResizeObserver(resize).observe(host);
  resize();
  await show(figure);
  return { show };
}
