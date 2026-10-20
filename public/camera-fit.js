export function unionBounds(boundsList) {
  if (boundsList.length === 0) return null;
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (const bounds of boundsList) {
    for (let axis = 0; axis < 3; axis += 1) {
      min[axis] = Math.min(min[axis], bounds.min[axis]);
      max[axis] = Math.max(max[axis], bounds.max[axis]);
    }
  }
  return { min, max };
}

export function cameraFitPose(min, max, aspect, fovDegrees, view = 'iso') {
  const size = max.map((value, axis) => value - min[axis]);
  const target = min.map((value, axis) => (value + max[axis]) / 2);
  const directionByView = {
    iso: [0.9, -1.05, 1.2],
    top: [0, 0, 1],
    front: [0, -1, 0.12],
    'vehicle-front': [1, 0, 0],
  };
  const direction = directionByView[view] || directionByView.iso;
  const length = Math.hypot(...direction);
  const unitDirection = direction.map((value) => value / length);
  const safeAspect = Math.max(0.2, aspect || 1);
  const halfHeight = Math.max(size[2], size[1], size[0] / safeAspect) / 2;
  const distance = Math.max(halfHeight / Math.tan((fovDegrees * Math.PI) / 360), 1) * 1.3;
  const position = target.map((value, axis) => value + unitDirection[axis] * distance);
  return {
    target,
    position,
    up: view === 'top' ? [0, 1, 0] : [0, 0, 1],
    near: Math.max(0.01, distance / 1000),
    far: Math.max(5000, distance * 12),
    distance,
  };
}
