// Cosmetic deformation of a reference atlas, not an anthropometric or outcome model.
export const referenceHeight = 1.704;
export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
export function bmi(heightCm, weightKg) {
  return weightKg / ((heightCm / 100) ** 2);
}
export function ellipsePerimeter(a, b) {
  const h = ((a - b) / (a + b)) ** 2;
  return Math.PI * (a + b) * (1 + (3 * h) / (10 + Math.sqrt(4 - 3 * h)));
}
export function waistReference(positions) {
  const y = referenceHeight * 0.59;
  let xmin = Infinity, xmax = -Infinity, zmin = Infinity, zmax = -Infinity;
  for (let i = 0; i < positions.length; i += 3) {
    const x = positions[i], py = positions[i + 1], z = positions[i + 2];
    // The forearms also intersect this height: exclude them from the torso section.
    if (Math.abs(py - y) < 0.018 && Math.abs(x) < 0.18) {
      xmin = Math.min(xmin, x); xmax = Math.max(xmax, x);
      zmin = Math.min(zmin, z); zmax = Math.max(zmax, z);
    }
  }
  if (![xmin, xmax, zmin, zmax].every(Number.isFinite)) throw Error('Waist reference unavailable');
  return { a: (xmax - xmin) / 2, b: (zmax - zmin) / 2, z: (zmax + zmin) / 2 };
}
export function validMeasures(values) {
  const height = Number(values.height), weight = Number(values.weight);
  const waist = values.waist === '' || values.waist == null ? null : Number(values.waist);
  return Number.isFinite(height) && height >= 140 && height <= 210 &&
    Number.isFinite(weight) && weight >= 40 && weight <= 180 &&
    (waist === null || (Number.isFinite(waist) && waist >= 55 && waist <= 180));
}
export function deformSurface(base, out, measurements, reference) {
  if (!validMeasures(measurements)) throw Error('Invalid measurements');
  const heightScale = (measurements.height / 100) / referenceHeight;
  const bulk = clamp(Math.sqrt(bmi(measurements.height, measurements.weight) / 22), 0.80, 1.38);
  const a = reference.a * bulk, b = reference.b * bulk;
  let waistChange = 0;
  if (measurements.waist !== null && measurements.waist !== '') {
    const desired = measurements.waist / 100 / heightScale;
    let lo = -0.55, hi = 2.7;
    for (let k = 0; k < 35; k++) {
      const mid = (lo + hi) / 2;
      if (ellipsePerimeter(a * (1 + 0.7 * mid), b * (1 + 1.3 * mid)) < desired) lo = mid;
      else hi = mid;
    }
    waistChange = (lo + hi) / 2;
  }
  for (let i = 0; i < base.length; i += 3) {
    const x = base[i], y = base[i + 1], z = base[i + 2];
    const trunk = Math.exp(-(((y - 1.09) / 0.30) ** 4)) * Math.exp(-((Math.abs(x) / 0.235) ** 6));
    const waist = Math.exp(-(((y - referenceHeight * 0.59) / 0.145) ** 2)) * Math.exp(-((Math.abs(x) / 0.175) ** 12));
    let px = x * (1 + (bulk - 1) * trunk);
    let pz = reference.z + (z - reference.z) * (1 + (bulk - 1) * trunk);
    px *= 1 + 0.7 * waistChange * waist;
    pz = reference.z + (pz - reference.z) * (1 + 1.3 * waistChange * waist);
    // Mild anterior shift gives a rounded external profile, without changing bone lengths.
    pz += Math.max(0, waistChange) * 0.025 * waist;
    if (y < 0.78 && Math.abs(x) < 0.245) {
      const leg = Math.exp(-(((y - 0.48) / 0.28) ** 4));
      const center = Math.sign(x) * 0.092;
      px += (x - center) * (bulk - 1) * 0.52 * leg;
      pz += z * (bulk - 1) * 0.52 * leg;
    }
    if (Math.abs(x) > 0.21 && y > 0.86 && y < 1.43) {
      const arm = Math.exp(-(((y - 1.20) / 0.21) ** 4));
      px += (x - Math.sign(x) * 0.26) * (bulk - 1) * 0.38 * arm;
      pz += z * (bulk - 1) * 0.38 * arm;
    }
    out[i] = px * heightScale;
    out[i + 1] = y * heightScale;
    out[i + 2] = pz * heightScale;
  }
  return out;
}
