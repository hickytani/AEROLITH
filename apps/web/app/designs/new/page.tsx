'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import ProductHeader from '../../components/ProductHeader';

type Family = { id: string; display_name: string; category: string; schema_version: string; parameters: Array<{ name: string; unit: string; minimum?: number; maximum?: number; minimum_exclusive?: number }>; capabilities: string[]; limitations: string[]; artifacts: string[]; exporters: Array<{ type: string; implementation: string }>; verification_checks: string[] };
type Registry = { families: Family[]; planned_areas: string[]; persistence: string };

export default function NewDesignPage() {
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { fetch('/api/v1/design-families').then(async (response) => { const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Family registry unavailable.'); setRegistry(data); }).catch((reason) => setError(reason instanceof Error ? reason.message : 'Family registry unavailable.')); }, []);

  async function create(family: Family) {
    setBusy(true); setError('');
    try {
      const response = await fetch('/api/v1/project/initialize', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ family_id: family.id, schema_version: family.schema_version }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Design initialization failed.');
      window.location.assign('/');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Design initialization failed.'); setBusy(false); }
  }

  async function restoreDemo() {
    setBusy(true); setError('');
    try {
      const response = await fetch('/api/v1/project/demo', { method: 'POST' });
      if (!response.ok) throw new Error('Could not restore the demo design.');
      window.location.assign('/');
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Could not restore demo.'); setBusy(false); }
  }

  return <><ProductHeader active="new"/><main className="product-main"><p className="eyebrow">DESIGN WORKSPACE / INITIALIZE</p><h1>New design</h1><p className="sub">Choose an implemented family. Initialization uses validated defaults and opens the existing Studio workspace.</p>
    {error && <p className="inline-error" role="alert">{error}</p>}{!registry && !error && <p>Loading registered design families…</p>}
    <p className="availability-note">{registry?.persistence || 'This local service stores one active project.'} The current flow retains the previous state in revision history; it does not create independent project workspaces.</p>
    <div className="family-grid">{registry?.families.map((family) => <article className="family-card" key={family.id}><p className="eyebrow">{family.category} · SCHEMA {family.schema_version}</p><h2>{family.display_name}</h2><h3>Parameters</h3><ul>{family.parameters.map((item) => <li key={item.name}>{item.name} · {item.unit}{item.minimum !== undefined ? ` · min ${item.minimum}` : ''}{item.maximum !== undefined ? ` · max ${item.maximum}` : ''}{item.minimum_exclusive !== undefined ? ` · above ${item.minimum_exclusive}` : ''}</li>)}</ul><h3>Supported capabilities</h3><ul>{family.capabilities.map((item) => <li key={item}>{item}</li>)}</ul><h3>Verification scope</h3><ul>{family.verification_checks.map((item) => <li key={item}>{item}</li>)}</ul><h3>Limitations</h3><ul>{family.limitations.map((item) => <li key={item}>{item}</li>)}</ul><p>Artifacts: {family.artifacts.join(', ')}</p><ul>{family.exporters.map((item) => <li key={item.type}>{item.type} · {item.implementation}</li>)}</ul><button className="primary" disabled={busy} onClick={() => create(family)}>Initialize with validated defaults</button></article>)}</div>
    <section className="planned-panel"><h2>Planned design areas</h2><p>These are not selectable and do not generate a spur-gear project.</p><ul>{registry?.planned_areas.map((area) => <li key={area}>{area} · unavailable</li>)}</ul></section>
    <button className="secondary-button" disabled={busy} onClick={restoreDemo}>Return to the demo gear design</button> <Link className="text-link" href="/">Back to Studio</Link>
  </main></>;
}
