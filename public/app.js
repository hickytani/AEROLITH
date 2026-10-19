import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';

const api = '/api/v1';
const byId = (id) => document.getElementById(id);
let project;
let scene;
let camera;
let renderer;
let controls;
let meshes = {};
let selectedId = null;
let buildSequence = 0;
let applying = false;

function required(id) {
  const element = byId(id);
  if (!element) throw new Error(`Studio interface is missing required element #${id}.`);
  return element;
}

async function request(path, options) {
  const result = await fetch(`${api}${path}`, options);
  const text = await result.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text || 'Empty server response.' }; }
  if (!result.ok) {
    const detail = data.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg || JSON.stringify(item)).join('; ')
      : (typeof detail === 'string' ? detail : data.error || `Request failed (${result.status}).`);
    throw new Error(message);
  }
  return data;
}

function setLoading(message, isError = false) {
  const loading = required('loading');
  loading.hidden = !message;
  loading.textContent = message || '';
  loading.classList.toggle('loading-error', isError);
}

function init() {
  const element = required('viewport');
  scene = new THREE.Scene();
  scene.background = new THREE.Color('#f9fbfc');
  camera = new THREE.PerspectiveCamera(36, element.clientWidth / Math.max(1, element.clientHeight), 0.1, 5000);
  camera.up.set(0, 0, 1);
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(element.clientWidth, element.clientHeight);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  element.appendChild(renderer.domElement);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.target.set(0, 0, 0);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x647384, 2.2));
  const light = new THREE.DirectionalLight(0xffffff, 3);
  light.position.set(-70, -80, 130);
  scene.add(light);
  const grid = new THREE.GridHelper(240, 24, 0xcbd6dc, 0xe6ecef);
  grid.rotation.x = Math.PI / 2;
  grid.position.z = -10;
  scene.add(grid);
  const axes = new THREE.AxesHelper(20);
  axes.position.set(-90, -65, -7);
  scene.add(axes);
  const resize = new ResizeObserver(() => {
    if (!element.clientWidth || !element.clientHeight) return;
    camera.aspect = element.clientWidth / element.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(element.clientWidth, element.clientHeight);
  });
  resize.observe(element);
  renderer.domElement.addEventListener('pointerdown', pick);
  renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
}

function fitView(view = 'iso') {
  if (!project || !camera) return;
  const derived = project.derived;
  const largestDiameter = Math.max(...derived.components.map((component) => component.outer_diameter_mm));
  const span = Math.max(derived.center_distance_mm + largestDiameter / 2, largestDiameter) * 1.45;
  const target = new THREE.Vector3(derived.center_distance_mm / 2, 0, 0);
  const vectors = {
    iso: new THREE.Vector3(0.9, -1.05, 1.2),
    top: new THREE.Vector3(0.001, 0.001, 1.9),
    front: new THREE.Vector3(0.001, -1.9, 0.25),
  };
  camera.position.copy(target).addScaledVector(vectors[view] || vectors.iso, span);
  camera.far = Math.max(5000, span * 8);
  camera.updateProjectionMatrix();
  controls.target.copy(target);
  controls.update();
}

function setSelected(id) {
  selectedId = id;
  for (const button of document.querySelectorAll('.component')) {
    button.setAttribute('aria-pressed', String(button.dataset.id === id));
  }
  for (const [meshId, mesh] of Object.entries(meshes)) {
    const color = meshId === 'pinion' ? 0x00a8c7 : 0x9cabb5;
    mesh.material.color.setHex(meshId === id ? 0x14c2dc : color);
    mesh.material.emissive.setHex(meshId === id ? 0x05323b : 0x000000);
  }
}

function disposeMeshes() {
  for (const mesh of Object.values(meshes)) {
    scene.remove(mesh);
    mesh.geometry.dispose();
    mesh.material.dispose();
  }
  meshes = {};
}

function build() {
  if (!project || !scene) return;
  const revision = project.revision;
  const sequence = ++buildSequence;
  disposeMeshes();
  const parts = project.derived.components;
  let loaded = 0;
  let failed = false;
  required('geometry-rev').textContent = `LOADING COMMITTED REVISION ${revision}`;
  required('geometry-state').textContent = 'LOADING GEOMETRY';
  setLoading(`Loading CAD geometry for committed revision ${revision}…`);
  const loader = new STLLoader();
  for (const component of parts) {
    loader.load(
      `${api}/geometry/${encodeURIComponent(component.id)}.stl?revision=${revision}`,
      (geometry) => {
        if (sequence !== buildSequence || project.revision !== revision) { geometry.dispose(); return; }
        geometry.computeVertexNormals();
        const material = new THREE.MeshStandardMaterial({
          color: component.id === 'pinion' ? '#00a8c7' : '#9cabb5',
          metalness: 0.56,
          roughness: 0.37,
          emissive: 0x000000,
        });
        const mesh = new THREE.Mesh(geometry, material);
        mesh.userData = { id: component.id };
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        scene.add(mesh);
        meshes[component.id] = mesh;
        if (selectedId === component.id) setSelected(selectedId);
        loaded += 1;
        if (loaded + (failed ? 1 : 0) >= parts.length) {
          setLoading(failed ? 'Some component geometry could not be loaded.' : '');
          required('geometry-state').textContent = failed ? 'GEOMETRY LOAD ERROR' : 'GEOMETRY GENERATED';
          required('geometry-rev').textContent = `COMMITTED REVISION ${revision}`;
        }
      },
      undefined,
      () => {
        if (sequence !== buildSequence || project.revision !== revision) return;
        failed = true;
        loaded += 1;
        if (loaded >= parts.length) {
          setLoading('CAD geometry could not be loaded. The committed design values remain available.', true);
          required('geometry-state').textContent = 'GEOMETRY LOAD ERROR';
          required('geometry-rev').textContent = `GEOMETRY UNAVAILABLE · DESIGN R${revision}`;
        }
      },
    );
  }
  fitView();
}

function textElement(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function fill() {
  if (!project) return;
  const requirements = project.requirements;
  const derived = project.derived;
  required('rev').textContent = `REVISION ${String(project.revision).padStart(2, '0')}`;
  required('result-rev').textContent = `REVISION ${String(project.revision).padStart(2, '0')}`;
  required('pinion').value = project.components[0].teeth;
  required('gear').value = project.components[1].teeth;
  required('module').value = requirements.module_mm;
  required('width').value = requirements.face_width_mm;
  required('torque').value = requirements.input_torque_Nm;
  required('speed').value = requirements.input_speed_rpm;
  required('ratio').textContent = `${derived.gear_ratio.toFixed(2)}:1`;
  required('center').textContent = `${derived.center_distance_mm.toFixed(1)} mm`;
  required('out-speed').textContent = `${derived.output_speed_rpm.toFixed(0)} rpm`;
  required('out-torque').textContent = `${derived.ideal_output_torque_Nm.toFixed(1)} N·m`;
  required('bore').textContent = `${derived.bore_diameter_mm.toFixed(1)} mm`;
  required('pinion-name').textContent = derived.components[0].name;
  required('gear-name').textContent = derived.components[1].name;
  required('gear-label').textContent = `OUTPUT · ${derived.gear_ratio.toFixed(2)}:1`;
  required('assumptions').textContent = project.assumptions.join(' ');
  required('error').textContent = '';

  const details = required('calculation-details');
  details.replaceChildren();
  const provenance = project.calculations?.provenance;
  if (provenance) details.append(textElement('p', `Method ${provenance.method_version} · revision ${provenance.design_revision}`));
  for (const item of project.calculations?.results || []) {
    const block = document.createElement('section');
    block.append(textElement('strong', `${item.name}: ${Number(item.value).toPrecision(6)} ${item.unit}`));
    block.append(textElement('p', `${item.formula} = ${item.substitution}`));
    block.append(textElement('p', item.assumptions.join(' ')));
    block.append(textElement('small', `${item.status} · ${item.method_version} · revision ${item.design_revision}`));
    details.append(block);
  }

  const checks = required('checks');
  checks.replaceChildren();
  for (const [name, item] of Object.entries(project.verification || {})) {
    const row = document.createElement('p');
    row.append(textElement('span', '', `status ${String(item.state).toLowerCase()}`));
    row.append(textElement('span', `${name.replaceAll('_', ' ')} · ${item.summary}`));
    row.append(textElement('b', item.state));
    checks.append(row);
  }
  for (const input of document.querySelectorAll('.rail input')) input.disabled = applying;
  required('apply').disabled = applying;
}

async function loadArtifacts(revision) {
  try {
    let data = await request('/artifacts');
    if (data.current_revision !== revision && project?.revision === revision) data = await request('/artifacts');
    if (project?.revision !== revision || data.current_revision !== revision) return;
    const container = required('artifact-list');
    container.replaceChildren();
    required('artifact-revision').textContent = `INDEX REVISION ${data.current_revision}`;
    if (!data.artifacts.length) {
      container.append(textElement('p', 'No exported artifacts yet for this revision.'));
      return;
    }
    for (const artifact of data.artifacts.slice().reverse()) {
      const link = document.createElement('a');
      link.href = `${api}/artifacts/${encodeURIComponent(artifact.filename)}`;
      link.textContent = `${artifact.kind.toUpperCase()} · R${artifact.revision}${artifact.stale ? ' · STALE' : ' · CURRENT'}`;
      link.className = artifact.stale ? 'artifact-stale' : 'artifact-current';
      container.append(link);
    }
  } catch (error) {
    required('artifact-revision').textContent = 'ARTIFACT INDEX UNAVAILABLE';
    required('artifact-list').replaceChildren(textElement('p', error.message, 'error'));
  }
}

async function load() {
  try {
    project = await request('/project');
    if (!scene) init();
    fill();
    build();
    loadArtifacts(project.revision);
    for (const input of document.querySelectorAll('.rail input')) input.disabled = false;
    required('apply').disabled = false;
  } catch (error) {
    setLoading(`Could not load design: ${error.message}`, true);
  }
}

async function applyChanges() {
  if (applying || !project) return;
  applying = true;
  const previousRevision = project.revision;
  required('error').textContent = '';
  for (const input of document.querySelectorAll('.rail input')) input.disabled = true;
  required('apply').disabled = true;
  try {
    const body = {
      pinion_teeth: Number(required('pinion').value),
      gear_teeth: Number(required('gear').value),
      module_mm: Number(required('module').value),
      face_width_mm: Number(required('width').value),
      input_torque_Nm: Number(required('torque').value),
      input_speed_rpm: Number(required('speed').value),
    };
    const committed = await request('/project', {
      method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
    });
    if (committed.revision <= previousRevision) throw new Error('Server response did not advance the committed revision.');
    project = committed;
    fill();
    build();
    loadArtifacts(project.revision);
  } catch (error) {
    const message = error.message;
    // A network failure can happen after the server committed. Read canonical state before showing the last result.
    try {
      project = await request('/project');
      fill();
      if (project.revision !== previousRevision) {
        build();
        loadArtifacts(project.revision);
      }
    } catch {
      // Retain the last successfully loaded client snapshot when the API cannot be read.
    }
    required('error').textContent = message;
  } finally {
    applying = false;
    fill();
  }
}

async function restoreDemo() {
  if (applying) return;
  applying = true;
  for (const input of document.querySelectorAll('.rail input')) input.disabled = true;
  required('apply').disabled = true;
  try {
    project = await request('/project/demo', { method: 'POST' });
    fill();
    build();
    loadArtifacts(project.revision);
  } catch (error) {
    required('error').textContent = error.message;
  } finally {
    applying = false;
    fill();
  }
}

function pick(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  const mouse = new THREE.Vector2(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
  const ray = new THREE.Raycaster();
  ray.setFromCamera(mouse, camera);
  const hit = ray.intersectObjects(Object.values(meshes))[0];
  if (hit) setSelected(hit.object.userData.id);
}

for (const button of document.querySelectorAll('.component')) {
  button.addEventListener('click', (event) => {
    const id = button.dataset.id;
    const mesh = meshes[id];
    if (event.target.closest('.eye')) {
      if (!mesh) return;
      mesh.visible = !mesh.visible;
      button.querySelector('.eye').textContent = mesh.visible ? '◉' : '○';
      return;
    }
    setSelected(id);
  });
}
required('apply').addEventListener('click', applyChanges);
required('restore-demo').addEventListener('click', restoreDemo);
required('reset').addEventListener('click', () => fitView());
for (const button of document.querySelectorAll('[data-view]')) button.addEventListener('click', () => fitView(button.dataset.view));
for (const link of document.querySelectorAll('.exports > a')) {
  link.addEventListener('click', async (event) => {
    if (!project) return;
    event.preventDefault();
    const previousText = link.textContent;
    link.textContent = 'Generating for current revision…';
    try {
      const response = await fetch(link.href);
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || `Export failed (${response.status}).`);
      }
      const artifactRevision = Number(response.headers.get('x-design-revision'));
      if (artifactRevision && artifactRevision !== project.revision) {
        project = await request('/project');
        fill();
        build();
        loadArtifacts(project.revision);
        throw new Error(`The project advanced to revision ${project.revision}. Review the refreshed design and generate the export again.`);
      }
      const blobUrl = URL.createObjectURL(await response.blob());
      const download = document.createElement('a');
      download.href = blobUrl;
      download.download = response.headers.get('content-disposition')?.match(/filename="?([^";]+)"?/i)?.[1] || 'aeropkmech-artifact';
      download.click();
      URL.revokeObjectURL(blobUrl);
      await loadArtifacts(project.revision);
    } catch (error) {
      required('error').textContent = error.message;
    } finally {
      link.textContent = previousText;
    }
  });
}

load();
