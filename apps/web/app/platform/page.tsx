'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import ProductHeader from '../components/ProductHeader';
import { copyText, listOpenApiOperations } from '../lib/platform.mjs';

type Operation = ReturnType<typeof listOpenApiOperations>[number];
type OpenApiDoc = { info?: { title?: string; version?: string; description?: string }; paths?: Record<string, unknown>; components?: { schemas?: Record<string, { properties?: Record<string, { type?: string; minimum?: number; maximum?: number; exclusiveMinimum?: number; default?: unknown }>; required?: string[] }> } };

const curlExample = `curl http://127.0.0.1:8000/api/v1/project`;
const patchExample = `curl -X PATCH http://127.0.0.1:8000/api/v1/project \\
  -H "Content-Type: application/json" \\
  -d '{"pinion_teeth":12,"gear_teeth":30,"module_mm":2,"face_width_mm":12,"input_torque_Nm":8,"input_speed_rpm":900}'`;
const pythonExample = `import requests

base = "http://127.0.0.1:8000/api/v1"
project = requests.get(f"{base}/project", timeout=10).json()
print(project["revision"], project["derived"]["gear_ratio"])

updated = requests.patch(
    f"{base}/project",
    json={"gear_teeth": 30, "pinion_teeth": 12},
    timeout=10,
)
updated.raise_for_status()
print(updated.json()["derived"]["center_distance_mm"])`;

function resolveSchemaName(reference: string) { return reference.split('/').at(-1) || reference; }
function statusCodes(operation: Operation) { return Object.keys(operation.responses).join(', ') || 'Not described'; }

export default function PlatformPage() {
  const [document, setDocument] = useState<OpenApiDoc | null>(null);
  const [operations, setOperations] = useState<Operation[]>([]);
  const [error, setError] = useState('');
  const [copyStatus, setCopyStatus] = useState('');
  useEffect(() => { fetch('/api/v1/platform/openapi').then(async (response) => { const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'OpenAPI contract unavailable.'); setDocument(data); setOperations(listOpenApiOperations(data)); }).catch((reason) => setError(reason instanceof Error ? reason.message : 'OpenAPI contract unavailable.')); }, []);

  async function copy(label: string, value: string) {
    try { await copyText(value); setCopyStatus(`${label} copied.`); }
    catch (reason) { setCopyStatus(reason instanceof Error ? reason.message : 'Could not copy example.'); }
  }

  const groups = new Map<string, Operation[]>();
  for (const operation of operations) {
    const group = operation.path.includes('interpret') ? 'Requirement interpretation'
      : operation.path.includes('geometry') || operation.path.includes('export') ? 'Geometry and exports'
        : operation.path.includes('artifact') ? 'Artifact history'
          : operation.path.includes('report') ? 'Reports'
            : operation.path.includes('design-families') || operation.path.includes('initialize') || operation.path.includes('/demo') ? 'Design families and initialization'
              : operation.path.includes('learn') ? 'Learning calculations' : 'Health and project state';
    groups.set(group, [...(groups.get(group) || []), operation]);
  }

  return <><ProductHeader active="platform"/><main className="product-main platform-page">
    <p className="eyebrow">AEROPKMECH PLATFORM / LOCAL DEVELOPER PORTAL</p><h1>Integrate the engineering core</h1><p className="sub">The local API exposes the implemented gear workflow. This portal reads its endpoint inventory from the running FastAPI OpenAPI contract.</p>
    <div className="platform-boundary"><strong>Local development API</strong><span>Version {document?.info?.version || 'loading'} · No authentication is required for local use. No hosted endpoint or AeroPKmech API keys are issued.</span></div>
    <div className="platform-columns"><section><p className="eyebrow">QUICK START</p><h2>Read the current project</h2><p>Start the local services, then call the loopback API. A project response contains `revision`, `family`, `schema_version`, `requirements`, `components`, `derived`, `calculations`, `verification`, and `validation`.</p>
      <div className="code-block"><div><span>HTTP · curl</span><button onClick={() => copy('GET example', curlExample)}>Copy</button></div><pre><code>{curlExample}</code></pre></div>
      <div className="code-block"><div><span>Python · requests</span><button onClick={() => copy('Python example', pythonExample)}>Copy</button></div><pre><code>{pythonExample}</code></pre></div>
      <div className="code-block"><div><span>Validated edit example</span><button onClick={() => copy('PATCH example', patchExample)}>Copy</button></div><pre><code>{patchExample}</code></pre></div>
      {copyStatus && <p className="inline-status" role="status">{copyStatus}</p>}
    </section><aside className="platform-aside"><h2>Compatibility and security</h2><p>Routes are versioned under `/api/v1`. The local implementation is under active development; no backward-compatibility guarantee or deprecation policy is established.</p><p>Local requests have no API-key authentication. Bind to loopback for development. Do not expose this single-writer JSON store as a public multi-tenant service.</p><p>External model-provider credentials are a separate concern and are not required or used by these examples. No provider secret should be placed in browser code.</p><p>Hosted deployment, accounts, keys, quotas, billing, and webhooks are planned and unavailable.</p><Link href="/learn" className="text-link">See the gear calculation lesson →</Link></aside></div>
    <section className="api-reference"><p className="eyebrow">LIVE CONTRACT</p><h2>{document?.info?.title || 'FastAPI'} reference</h2><p>Endpoint methods and paths below are read from the running OpenAPI schema. Request models, path parameters, and documented response codes are shown when present.</p>
      {error && <p className="inline-error" role="alert">{error} Start the API with <code>npm run api</code> and refresh this page.</p>}{!document && !error && <p>Loading live API schema…</p>}
      {[...groups.entries()].map(([group, items]) => <section key={group} className="endpoint-group"><h3>{group}</h3>{items.map((operation) => <details className="endpoint" key={`${operation.method}:${operation.path}`}><summary><span className={`method method-${operation.method.toLowerCase()}`}>{operation.method}</span><code>{operation.path}</code><span>{operation.summary}</span></summary><div><p>{operation.description || 'No additional description in the API schema.'}</p>
        {operation.parameters.length > 0 && <><strong>Parameters</strong><ul>{operation.parameters.map((parameter: { name: string; in: string; required?: boolean; description?: string; schema?: { type?: string } }) => <li key={`${parameter.in}:${parameter.name}`}><code>{parameter.name}</code> · {parameter.in} · {parameter.schema?.type || 'value'}{parameter.required ? ' · required' : ''}{parameter.description ? ` · ${parameter.description}` : ''}</li>)}</ul></>}
        {operation.requestBody && (() => {
          const requestSchema = operation.requestBody.content?.['application/json']?.schema;
          const schemaName = resolveSchemaName(requestSchema?.$ref || 'inline schema');
          const schema = document?.components?.schemas?.[schemaName];
          return <><p>Request body: JSON schema <code>{schemaName}</code>. Fields below are read from the live OpenAPI schema.</p>{schema?.properties && <ul>{Object.entries(schema.properties).map(([name, property]) => <li key={name}><code>{name}</code> · {property.type || 'value'}{schema.required?.includes(name) ? ' · required' : ' · optional'}{property.minimum !== undefined ? ` · minimum ${property.minimum}` : ''}{property.exclusiveMinimum !== undefined ? ` · greater than ${property.exclusiveMinimum}` : ''}{property.maximum !== undefined ? ` · maximum ${property.maximum}` : ''}{property.default !== undefined ? ` · default ${String(property.default)}` : ''}</li>)}</ul>}</>;
        })()}
        <p>Documented responses: <code>{statusCodes(operation)}</code>. Validation uses HTTP 422; unavailable/corrupt local state can return 503; checksum mismatch on retained artifacts returns 409.</p>
      </div></details>)}</section>)}
      {document && operations.length === 0 && <p>No versioned API operations are listed by the current OpenAPI document.</p>}
    </section>
    <section className="platform-planned"><h2>Platform capabilities not available today</h2><p>This local portal documents current behavior. It does not provide hosted engineering jobs, public API keys, identity, tenant isolation, request quotas, usage billing, webhooks, uptime commitments, or production support.</p></section>
  </main></>;
}
