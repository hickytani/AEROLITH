import { STLLoader } from 'three/addons/loaders/STLLoader.js';

export class MeshLoadError extends Error {
  constructor(message, { componentId, status = null, currentRevision = null, stale = false } = {}) {
    super(message);
    this.name = 'MeshLoadError';
    this.componentId = componentId;
    this.status = status;
    this.currentRevision = currentRevision;
    this.stale = stale;
  }
}

function responseDetail(text) {
  if (!text) return '';
  try {
    const payload = JSON.parse(text);
    const detail = payload.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map((item) => item.msg || JSON.stringify(item)).join('; ');
  } catch {
    return '';
  }
  return '';
}

export function validateMeshGeometry(geometry, componentId) {
  const positions = geometry?.getAttribute?.('position');
  if (!positions || positions.itemSize !== 3 || positions.count < 3 || positions.count % 3 !== 0) {
    throw new MeshLoadError(`${componentId} mesh has no complete triangle vertex data.`, { componentId });
  }
  for (let i = 0; i < positions.array.length; i += 1) {
    if (!Number.isFinite(positions.array[i])) {
      throw new MeshLoadError(`${componentId} mesh contains a non-finite vertex.`, { componentId });
    }
  }
  const normals = geometry.getAttribute('normal');
  if (normals && (normals.itemSize !== 3 || normals.count !== positions.count)) {
    throw new MeshLoadError(`${componentId} mesh normal data does not match its vertices.`, { componentId });
  }
  if (normals) {
    for (let i = 0; i < normals.array.length; i += 1) {
      if (!Number.isFinite(normals.array[i])) {
        throw new MeshLoadError(`${componentId} mesh contains a non-finite normal.`, { componentId });
      }
    }
  }
  const indices = geometry.getIndex?.();
  if (indices) {
    for (let i = 0; i < indices.count; i += 1) {
      const index = indices.getX(i);
      if (!Number.isInteger(index) || index < 0 || index >= positions.count) {
        throw new MeshLoadError(`${componentId} mesh contains an out-of-range triangle index.`, { componentId });
      }
    }
  }
  geometry.computeBoundingBox();
  const bounds = geometry.boundingBox;
  if (!bounds || ![bounds.min.x, bounds.min.y, bounds.min.z, bounds.max.x, bounds.max.y, bounds.max.z].every(Number.isFinite)) {
    throw new MeshLoadError(`${componentId} mesh has invalid bounds.`, { componentId });
  }
  if (bounds.max.x <= bounds.min.x || bounds.max.y <= bounds.min.y || bounds.max.z <= bounds.min.z) {
    throw new MeshLoadError(`${componentId} mesh has zero extent on one or more axes.`, { componentId });
  }
  return geometry;
}

export async function loadComponentMesh({ componentId, revision, fetchImpl = fetch, api = '/api/v1' }) {
  let response;
  try {
    response = await fetchImpl(`${api}/geometry/${encodeURIComponent(componentId)}.stl?revision=${revision}`, { cache: 'no-store' });
  } catch (error) {
    throw new MeshLoadError(`${componentId} mesh request could not reach the API: ${error.message}`, { componentId });
  }

  const currentRevision = Number(response.headers.get('x-design-revision')) || null;
  if (!response.ok) {
    const detail = responseDetail(await response.text());
    const stale = response.status === 409 && currentRevision !== null && currentRevision !== revision;
    const message = stale
      ? `${componentId} mesh is for revision ${revision}; the API now has revision ${currentRevision}. Refreshing the committed design.`
      : `${componentId} mesh request failed (HTTP ${response.status})${detail ? `: ${detail}` : '.'}`;
    throw new MeshLoadError(message, { componentId, status: response.status, currentRevision, stale });
  }

  const responseComponent = response.headers.get('x-geometry-component-id');
  const designRevision = Number(response.headers.get('x-design-revision'));
  const responseRevision = Number(response.headers.get('x-geometry-revision'));
  const units = response.headers.get('x-geometry-units');
  const format = response.headers.get('x-geometry-format');
  const artifactId = response.headers.get('x-artifact-id') || '';
  const artifactSha256 = response.headers.get('x-artifact-sha256') || '';
  const contentType = response.headers.get('content-type') || '';
  if (responseComponent !== componentId) {
    throw new MeshLoadError(`${componentId} request returned geometry for ${responseComponent || 'an unknown component'}.`, { componentId, status: response.status, currentRevision });
  }
  if (designRevision !== revision || responseRevision !== revision) {
    throw new MeshLoadError(`${componentId} response revision ${responseRevision || 'unknown'} does not match committed revision ${revision}.`, { componentId, status: response.status, currentRevision, stale: currentRevision !== revision });
  }
  if (units !== 'mm' || format !== 'stl') {
    throw new MeshLoadError(`${componentId} geometry contract expected STL in millimetres; received ${format || 'unknown'} in ${units || 'unknown'}.`, { componentId, status: response.status, currentRevision });
  }
  if (!contentType.toLowerCase().startsWith('model/stl')) {
    throw new MeshLoadError(`${componentId} response is ${contentType || 'missing a content type'}, not an STL mesh.`, { componentId, status: response.status, currentRevision });
  }

  const bytes = await response.arrayBuffer();
  if (bytes.byteLength < 84) {
    throw new MeshLoadError(`${componentId} STL payload is too short to contain a triangle mesh.`, { componentId, status: response.status, currentRevision });
  }
  if (!artifactId.startsWith(`${componentId}:r${revision}:`) || !/^[0-9a-f]{64}$/.test(artifactSha256)) {
    throw new MeshLoadError(`${componentId} response has missing or mismatched artifact provenance.`, { componentId, status: response.status, currentRevision });
  }
  if (!globalThis.crypto?.subtle) {
    throw new MeshLoadError('This browser cannot verify the mesh SHA-256 checksum.', { componentId, status: response.status, currentRevision });
  }
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  const actualSha256 = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  if (actualSha256 !== artifactSha256) {
    throw new MeshLoadError(`${componentId} STL bytes do not match their SHA-256 artifact checksum.`, { componentId, status: response.status, currentRevision });
  }
  let geometry;
  try {
    geometry = new STLLoader().parse(bytes);
    validateMeshGeometry(geometry, componentId);
  } catch (error) {
    geometry?.dispose();
    if (error instanceof MeshLoadError) throw error;
    throw new MeshLoadError(`${componentId} STL could not be parsed: ${error.message}`, { componentId, status: response.status, currentRevision });
  }
  geometry.computeVertexNormals();
  validateMeshGeometry(geometry, componentId);
  return geometry;
}

export async function loadComponentSet(components, revision, { api = '/api/v1', fetchImpl = fetch, onGeometry, onError } = {}) {
  const outcomes = new Array(components.length);
  let cursor = 0;
  async function worker() {
    while (cursor < components.length) {
      const index = cursor++;
      const component = components[index];
    let geometry;
    try {
      geometry = await loadComponentMesh({ componentId: component.id, revision, fetchImpl, api });
    } catch (error) {
      onError?.(component, error);
        outcomes[index] = false;
        continue;
    }
    try {
      onGeometry?.(component, geometry);
        outcomes[index] = true;
    } catch (error) {
      geometry.dispose();
      onError?.(component, error);
        outcomes[index] = false;
      }
    }
  }
  await Promise.all(Array.from({length:Math.min(3,components.length)},worker));
  return outcomes;
}
