'use client';

import { useEffect } from 'react';

export default function WorkspaceShell({ markup }: { markup: string }) {
  useEffect(() => {
    let disposed = false;
    const instance = Math.random().toString(36).slice(2);
    const disposeInstance = () => window.dispatchEvent(new CustomEvent('aeropkmech:studio-dispose', { detail: { instance } }));
    const script = document.createElement('script');
    script.type = 'module';
    script.src = `/app.js?instance=${instance}`;
    script.onload = () => {
      if (disposed) disposeInstance();
    };
    document.body.appendChild(script);
    return () => {
      disposed = true;
      disposeInstance();
      script.remove();
    };
  }, []);

  return <div dangerouslySetInnerHTML={{ __html: markup }} />;
}
