import Link from 'next/link';

export default function ProductHeader({ active }: { active: 'studio' | 'learn' | 'platform' | 'new' }) {
  const items = [
    ['studio', 'Studio', '/'],
    ['learn', 'Learn', '/learn'],
    ['platform', 'Platform', '/platform'],
    ['new', 'New design', '/designs/new'],
  ] as const;
  return (
    <header className="top">
      <Link className="brand" href="/"><span className="mark">A</span><span>AeroPKmech<small>ENGINEERING STUDIO</small></span></Link>
      <nav aria-label="Product navigation">{items.map(([key, label, href]) => <Link key={key} className={active === key ? 'active' : ''} href={href}>{label}</Link>)}</nav>
      <div className="rev">LOCAL ENGINEERING</div>
    </header>
  );
}
